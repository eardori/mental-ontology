#!/usr/bin/env python3
"""Ontology hygiene: near-duplicate detection, confidence recalibration, staleness/orphan flags.

As the corpus grows, models accumulate that overlap, drift, or stay under-evidenced.
This script does NOT auto-delete — it produces a REVIEW REPORT (and, with --apply-recalib,
applies the deterministic confidence rules). Semantic merges stay human/LLM-judged: the
report gives candidate pairs; a reviewer decides and merges with merge_models().

Usage:
  python3 consolidate.py <corpus_path>                 # report only (dupes + recalib + flags)
  python3 consolidate.py <corpus_path> --apply-recalib # also write recalibrated evidence grades
  python3 consolidate.py <corpus_path> --threshold 0.45

Report sections:
  1) NEAR-DUPLICATES — same category, high content-word Jaccard → candidate merges
  2) RECALIBRATION   — evidence grade vs deterministic rule (count/evidence_type/quote)
  3) FLAGS           — orphans (no related, count 1), stale (last_seen old), hearsay-high
"""
import argparse, json, os, re, sys

STOP = set("은 는 이 가 을 를 에 의 도 로 으로 과 와 및 그 저 것 수 등 더 좀 안 못 잘 이런 저런 그런 하는 되는 하고 있는 없는 대해 위해 통해 라는 라고 것이 것을 게 걸 거 저희 우리 내가 나는 사람 사람이 사람을 회사 때 때문 대한 한다 된다 이다 아니라 있다 없다 해야 한다는".split())

# common Korean particles/endings, longest-first, stripped to normalize 마크업을→마크업
_JOSA = sorted(["으로서","으로써","에서는","에게서","으로","에서","에게","한테","보다","처럼","마다","까지","부터",
                "이라는","라는","이라고","라고","이나","나마","조차","마저","밖에","이든","든지","이란","이야",
                "은","는","이","가","을","를","에","의","도","로","와","과","만","랑","이랑","께","께서"], key=len, reverse=True)
def _stem(w):
    for j in _JOSA:
        if len(w)>len(j)+1 and w.endswith(j): return w[:-len(j)]
    return w
def words(*txts):
    toks=[]
    for t in txts:
        if not t: continue
        for w in re.findall(r"[A-Za-z가-힣]{2,}", t):
            w=_stem(w)
            if len(w)>=2 and w not in STOP: toks.append(w)
    return set(toks)

def jaccard(a,b):
    if not a or not b: return 0.0
    return len(a&b)/len(a|b)

def load(corpus):
    p=os.path.join(corpus,"_ontology","objects.json")
    return p, json.load(open(p,encoding="utf-8"))

# ---- 1) near-duplicate detection ----
def find_dupes(models, thr):
    by_cat={}
    for m in models:
        by_cat.setdefault(m.get("category","?"),[]).append(m)
    pairs=[]
    for cat, ms in by_cat.items():
        for i in range(len(ms)):
            wi=words(ms[i].get("title"),ms[i].get("desc"))
            for j in range(i+1,len(ms)):
                s=jaccard(wi, words(ms[j].get("title"),ms[j].get("desc")))
                if s>=thr:
                    pairs.append((round(s,2),cat,ms[i]["id"],ms[j]["id"],ms[i].get("title","")[:40],ms[j].get("title","")[:40]))
    return sorted(pairs,reverse=True)

# ---- 2) confidence recalibration rule ----
def recalib_grade(m):
    """Deterministic target grade. high needs direct evidence + verbatim quote + count>=2.
       hearsay/reference cap at mid. count 1 + no quote caps at low/mid."""
    et=m.get("evidence_type","direct")
    cnt=m.get("count",1)
    has_q=bool((m.get("quote") or "").strip())
    if et in ("hearsay","reference"):
        return "mid" if (cnt>=2 or has_q) else "low"
    # direct
    if cnt>=3 and has_q: return "high"   # high = a real repeated pattern
    if cnt>=2 or has_q:  return "mid"
    return "low"

def find_recalib(models):
    out=[]
    for m in models:
        tgt=recalib_grade(m); cur=m.get("evidence","mid")
        if tgt!=cur: out.append((m["id"],cur,tgt,m.get("count",1),m.get("evidence_type","direct"),bool(m.get("quote"))))
    return out

# ---- 3) flags ----
def find_flags(models):
    orphans=[m["id"] for m in models if not m.get("related") and m.get("count",1)<=1]
    stale=[(m["id"],m.get("last_seen")) for m in models if (m.get("last_seen") or "9999")<"2026-01-01"]
    hearsay_high=[m["id"] for m in models if m.get("evidence")=="high" and m.get("evidence_type") in ("hearsay","reference")]
    return orphans, stale, hearsay_high

# ---- merge helper (called by reviewer, not auto) ----
def merge_models(objpath, keep_id, drop_id):
    d=json.load(open(objpath,encoding="utf-8")); M={m["id"]:m for m in d["models"]}
    k,dr=M.get(keep_id),M.get(drop_id)
    assert k and dr, "id not found"
    k["holders"]=sorted(set(k.get("holders",[])+dr.get("holders",[])))
    k["related"]=sorted(set([r for r in k.get("related",[])+dr.get("related",[]) if r not in (keep_id,drop_id)]))
    k["count"]=k.get("count",1)+dr.get("count",1)
    k["first_seen"]=min(k.get("first_seen","9999"),dr.get("first_seen","9999"))
    k["last_seen"]=max(k.get("last_seen",""),dr.get("last_seen",""))
    if not k.get("quote") and dr.get("quote"): k["quote"]=dr["quote"]
    k.setdefault("merged_from",[]).append(drop_id)
    # repoint references
    for m in d["models"]:
        if drop_id in m.get("related",[]):
            m["related"]=[keep_id if r==drop_id else r for r in m["related"]]
    d["models"]=[m for m in d["models"] if m["id"]!=drop_id]
    json.dump(d,open(objpath,"w",encoding="utf-8"),ensure_ascii=False,indent=1)
    return len(d["models"])

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("corpus"); ap.add_argument("--threshold",type=float,default=0.42)
    ap.add_argument("--apply-recalib",action="store_true")
    a=ap.parse_args()
    objpath,d=load(a.corpus); models=d["models"]
    print(f"models: {len(models)}\n")

    dupes=find_dupes(models,a.threshold)
    print(f"=== 1) NEAR-DUPLICATES (Jaccard ≥ {a.threshold}, same category) — {len(dupes)} pairs ===")
    for s,cat,i1,i2,t1,t2 in dupes[:40]:
        print(f"  {s}  [{cat}]  {i1}  ⇄  {i2}\n         {t1!r}  ⇄  {t2!r}")

    rec=find_recalib(models)
    print(f"\n=== 2) RECALIBRATION (grade ≠ rule target) — {len(rec)} models ===")
    for mid,cur,tgt,cnt,et,q in rec[:40]:
        print(f"  {cur}→{tgt}  {mid}  (count={cnt}, {et}, quote={'Y' if q else 'N'})")
    if a.apply_recalib and rec:
        for m in models:
            m["evidence"]=recalib_grade(m)
        json.dump(d,open(objpath,"w",encoding="utf-8"),ensure_ascii=False,indent=1)
        print(f"  → applied recalibration to {len(rec)} models")

    orphans,stale,hh=find_flags(models)
    print(f"\n=== 3) FLAGS ===")
    print(f"  orphans (no related, count≤1): {len(orphans)}")
    print(f"  stale (last_seen < 2026-01-01): {len(stale)}")
    print(f"  hearsay/reference graded high (should cap mid): {hh}")

if __name__=="__main__":
    main()
