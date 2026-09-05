#!/usr/bin/env python3
"""External enrichment — what the web knows about the names and terms in the corpus.

A recording says "넥스토라 쪽에 물어보죠" and the corpus has no idea whether that is a
company, how it is actually spelled, or what it does. The web does. This script is the
deterministic half of that loop: it decides WHAT is worth looking up, WRITES THE QUERY
STRINGS ITSELF, and later folds the answers back into the lexicon and the person
registry — with a URL and a fetch date on every single claim.

Scripts cannot call web tools, so the flow mirrors the calendar one (Stage 1b):

    enrich.py plan   →  the skill runs WebSearch/WebFetch on the printed queries
                     →  writes results.json
    enrich.py save   →  cache at _meta/enrichment.json  (the only thing 'apply' reads)
    enrich.py apply  →  lexicon.json desc/spelling · speakers.json role/org  (dry run first)

Cache-first is what makes this re-runnable, inspectable and testable: the same cache
always produces the same corpus edits, and every edit can be traced to a URL.

Three rules are enforced in code, not just documented:

  1. **Queries never carry corpus text.** A query is built from the entity name plus, at
     most, an org name already in the registry. What was said in a meeting — numbers,
     deals, complaints — is never sent to a search engine. `plan` composes the strings so
     no reader is tempted to "add a little context".
  2. **Private people are not searchable.** A person is proposed only when the registry
     marks them `public: true`, or their role reads public (대표/CEO/창업자/연사 …) AND an
     org is known. 팀원·가족·지인 are excluded by relationship, with the reason printed.
  3. **A web fact is never evidence.** Everything saved here carries source=web with a URL
     and a date, lands in its own DB table, and may not raise any model's evidence grade.
     The web can tell you how a company spells its name; it cannot tell you what someone
     believes. Corrections it suggests enter the lexicon as 후보 (사람 확인) unless the
     corpus itself already spells it that way.

Store: <corpus>/_meta/enrichment.json
No external dependencies (python3 stdlib only).
"""
import argparse, json, os, re, sys, unicodedata
from collections import Counter
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lexicon as lx  # noqa: E402  (shared tokenizer, jamo distance, registry helpers)

STORE_REL = "_meta/enrichment.json"
KINDS = ["인물", "조직", "제품", "용어"]
STATUS = ["확인됨", "불확실", "기각"]

# A role that reads "this person has a public profile". Conservative on purpose: the
# cost of a false positive is searching the web for a private individual.
PUBLIC_ROLE = re.compile(
    r'(대표|CEO|CTO|CFO|COO|창업자|파운더|founder|사장|부사장|의장|회장|이사|파트너|'
    r'교수|연사|저자|투자자|심사역|대표이사|본부장|VC|GP)', re.I)
PRIVATE_REL = {"팀원", "가족", "지인", "친구", "동료"}


def norm(s):
    return unicodedata.normalize("NFC", (s or "").strip())


def load_store(corpus):
    p = os.path.join(corpus, STORE_REL)
    if os.path.exists(p):
        try:
            d = json.load(open(p, encoding="utf-8"))
            d.setdefault("entities", {})
            return d
        except Exception as ex:
            sys.exit(f"ERROR: {STORE_REL} 파싱 실패 — {ex}")
    return {"version": 1, "updated": "", "entities": {}}


def save_store(corpus, store):
    store["updated"] = datetime.now().strftime("%Y-%m-%d")
    p = os.path.join(corpus, STORE_REL)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    json.dump(store, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


# ------------------------------------------------------------------- planning

def person_gate(e):
    """(searchable, reason) — the privacy gate for one registry entry."""
    name = norm(e.get("name", ""))
    rel = norm(e.get("relationship", ""))
    role, org = norm(e.get("role", "")), norm(e.get("org", ""))
    if e.get("public") is True:
        return True, "registry public:true"
    if e.get("public") is False:
        return False, "registry public:false (사용자가 검색 제외로 표시)"
    if rel in PRIVATE_REL:
        return False, f"사적 관계({rel}) — 검색하지 않음"
    if PUBLIC_ROLE.search(role) and org:
        return True, f"공개 직함 추정: {role} @ {org}"
    return False, "공개 프로필 근거 없음 (직함+소속 미확인)" if name else "이름 없음"


def queries_for(kind, name, org=""):
    """The ONLY place query strings are built. Entity + registry org, nothing else."""
    name = norm(name)
    if kind == "인물":
        return [f"{name} {org}".strip(), f"{name} {org} 프로필".strip()]
    if kind == "조직":
        return [f"{name} 회사", f"{name} 공식 홈페이지"]
    if kind == "제품":
        return [f"{name} 제품", f"{name} 서비스 소개"]
    return [f"{name} 뜻", f"{name} 용어"]


def cmd_plan(a, corpus, store):
    lex = lx.load_store(corpus)
    registry = lx.load_registry(corpus)
    counts, docs, first, last, n_docs = lx.count_tokens(corpus, a.since)
    known_canon, known_miss = lx.lexicon_index(lex)
    names = lx.name_tokens(registry)
    done = {norm(k) for k, v in store["entities"].items()
            if v.get("status") == "확인됨" and not a.refresh}

    tasks, excluded = [], []

    # 1) lexicon entries that still have no description, or an unconfirmed spelling
    for e in lex["terms"]:
        t = norm(e["term"])
        if t in done or e.get("kind") == "인물":
            continue
        why = None
        if not e.get("desc"):
            why = "사전에 있으나 설명이 없음"
        elif e.get("status") == "추론":
            why = "추론으로 학습된 용어 — 표기 확인 필요"
        if why:
            tasks.append({"entity": t, "kind": e.get("kind") or "용어", "why": why,
                          "count": counts.get(t, e.get("count", 0)),
                          "queries": queries_for(e.get("kind") or "용어", t)})

    # 2) frequent tokens the corpus keeps using but nothing explains
    for t, c in counts.most_common():
        if len(tasks) >= a.limit:
            break
        if (c < a.min_count or t in lx.STOPWORDS or t in names or t in done
                or t.lower() in known_canon or t.lower() in known_miss
                or not lx.term_like(t, len(docs[t]), n_docs)):
            continue
        tasks.append({"entity": t, "kind": "용어", "why": f"{c}회 등장하는데 사전에 없음",
                      "count": c, "first_seen": first.get(t, ""), "last_seen": last.get(t, ""),
                      "queries": queries_for("용어", t)})

    # 3) people — gated
    for e in registry:
        name = norm(e.get("name", ""))
        if not name or name in done:
            continue
        ok, reason = person_gate(e)
        if not ok:
            excluded.append({"entity": name, "reason": reason})
            continue
        if not a.include_people:
            excluded.append({"entity": name, "reason": f"{reason} — --include-people 필요"})
            continue
        missing = [k for k in ("role", "org") if not norm(e.get(k, ""))]
        tasks.append({"entity": name, "kind": "인물",
                      "why": reason + (f" · 비어있는 항목: {', '.join(missing)}" if missing else ""),
                      "count": len(e.get("meetings") or []),
                      "queries": queries_for("인물", name, norm(e.get("org", "")))})

    tasks = tasks[:a.limit]
    print(f"검색 후보 {len(tasks)}건 · 제외 {len(excluded)}건 · 캐시 {len(store['entities'])}건"
          f" (전사 {n_docs}개 스캔)")
    print("질의문은 이 스크립트가 만듭니다 — 회의 본문은 검색어에 절대 들어가지 않습니다.")
    for t in tasks:
        print(f"\n  [{t['kind']}] {t['entity']}  ({t.get('count', 0)}회) — {t['why']}")
        for q in t["queries"]:
            print(f"      검색: {q}")
    if excluded:
        print(f"\n검색 제외 ({len(excluded)}) — 프라이버시 게이트")
        for x in excluded[:20]:
            print(f"  {x['entity']}: {x['reason']}")
    if a.json:
        os.makedirs(os.path.dirname(os.path.abspath(a.json)) or ".", exist_ok=True)
        json.dump({"generated": datetime.now().strftime("%Y-%m-%d"),
                   "tasks": tasks, "excluded": excluded},
                  open(a.json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"\n→ {a.json}")
    print("\n다음: 이 질의문으로 웹 검색 → results.json 작성 → `enrich.py <corpus> save --file results.json`")
    print("  results.json: {\"results\":[{\"entity\",\"kind\",\"canonical\",\"summary\","
          "\"facts\":[{\"text\",\"url\"}],\"spelling_variants\":[],\"role\",\"org\","
          "\"status\":\"확인됨|불확실|기각\"}]}")


# --------------------------------------------------------------------- saving

def cmd_save(a, corpus, store):
    try:
        raw = json.load(open(a.file, encoding="utf-8"))
    except Exception as ex:
        sys.exit(f"ERROR: {a.file} 읽기 실패 — {ex}")
    results = raw["results"] if isinstance(raw, dict) else raw
    today = datetime.now().strftime("%Y-%m-%d")
    saved, skipped = 0, 0
    for r in results:
        ent = norm(r.get("entity", ""))
        if not ent:
            print(f"SKIP: entity 없음 — {r}")
            skipped += 1
            continue
        status = r.get("status") or "불확실"
        if status not in STATUS:
            print(f"SKIP({ent}): status '{status}' 는 {STATUS} 중 하나여야 합니다")
            skipped += 1
            continue
        facts = []
        for f in r.get("facts") or []:
            text, url = norm(f.get("text", "")), norm(f.get("url", ""))
            if not text or not url:
                print(f"SKIP(fact/{ent}): 출처 URL 없는 주장은 저장하지 않습니다 — {text[:40]}")
                continue
            facts.append({"text": text, "url": url, "fetched": f.get("fetched") or today})
        if status == "확인됨" and not facts:
            print(f"DOWNGRADE({ent}): 근거 URL이 하나도 없어 '불확실'로 저장합니다")
            status = "불확실"
        prev = store["entities"].get(ent, {})
        store["entities"][ent] = {
            "kind": r.get("kind") or prev.get("kind") or "용어",
            "canonical": norm(r.get("canonical", "")) or prev.get("canonical", ""),
            "summary": norm(r.get("summary", "")) or prev.get("summary", ""),
            "role": norm(r.get("role", "")) or prev.get("role", ""),
            "org": norm(r.get("org", "")) or prev.get("org", ""),
            "spelling_variants": sorted({norm(x) for x in (r.get("spelling_variants") or [])
                                         if norm(x)} | set(prev.get("spelling_variants") or [])),
            "facts": facts or prev.get("facts", []),
            "status": status, "note": norm(r.get("note", "")),
            "queries": r.get("queries") or prev.get("queries", []),
            "fetched": today, "source": "web",
        }
        saved += 1
    save_store(corpus, store)
    print(f"저장 {saved}건 · 건너뜀 {skipped}건 → {STORE_REL} (총 {len(store['entities'])}건)")
    print("반영은 `enrich.py <corpus> apply` (dry run) → `--apply`.")


# -------------------------------------------------------------------- applying

def cmd_apply(a, corpus, store):
    lex = lx.load_store(corpus)
    registry = lx.load_registry(corpus)
    counts, _docs, _f, _l, _n = lx.count_tokens(corpus)
    reg_path = os.path.join(corpus, "_meta", "speakers.json")
    reg_names = lx.name_tokens(registry)
    lex_changes, reg_changes, spell = [], [], []

    for ent, d in sorted(store["entities"].items()):
        if d.get("status") == "기각":
            continue
        if d.get("kind") == "인물":
            e = next((x for x in registry if norm(x.get("name", "")) == ent), None)
            if not e:
                continue
            for field in ("role", "org"):
                if d.get(field) and not norm(e.get(field, "")):
                    reg_changes.append((e, field, d[field]))
            note = d.get("summary", "")
            if note and norm((e.get("web") or {}).get("summary", "")) != note:
                reg_changes.append((e, "_web", note))
            continue

        entry = lx.find_term(lex, ent)
        if not entry:
            entry = {"term": ent, "kind": d.get("kind") or "용어", "desc": "",
                     "aliases": [], "misspellings": [], "status": "후보",
                     "source": "web", "count": counts.get(ent, 0),
                     "first_seen": "", "last_seen": "", "protect": False}
            lex["terms"].append(entry)
            lex_changes.append((ent, "신규 등록", d.get("kind") or "용어"))
        if d.get("summary") and not entry.get("desc"):
            lex_changes.append((ent, "설명", d["summary"][:60]))
            entry["desc"] = d["summary"]
        if d.get("facts"):
            entry["web"] = {"url": d["facts"][0]["url"], "fetched": d.get("fetched", ""),
                            "status": d.get("status", ""), "note": d.get("summary", "")[:200]}
        # A web-sourced spelling correction targets the term as the CORPUS spells it —
        # the formal name ("넥스트라(Nextra Inc.)") is recorded as an alias, never
        # substituted into what someone said out loud.
        target = norm(entry["term"])
        formal = norm(d.get("canonical", ""))
        for var in d.get("spelling_variants") or []:
            var = norm(var)
            if not var or var == target or var in reg_names:
                continue
            if var in {norm(m["form"]) for m in entry.get("misspellings") or []}:
                continue
            # the corpus itself already using that spelling is what upgrades a
            # web-sourced correction from "사람 확인" to "자동 적용"
            corpus_agrees = counts.get(target, 0) >= max(3, counts.get(var, 0) * 3)
            st = "추론" if (corpus_agrees and a.trust_web) else "후보"
            entry.setdefault("misspellings", []).append(
                {"form": var, "status": st, "source": "web",
                 "learned": datetime.now().strftime("%Y-%m-%d")})
            spell.append((var, target, st,
                          f"코퍼스 {counts.get(var, 0)}회 vs {target} {counts.get(target, 0)}회"))
        if formal and formal != target and formal not in {norm(x) for x in entry.get("aliases") or []}:
            entry.setdefault("aliases", []).append(formal)
            lex_changes.append((ent, "정식 표기(별칭)", formal))

    print(f"사전 반영 {len(lex_changes)}건 · 표기 교정 {len(spell)}건 · 레지스트리 {len(reg_changes)}건")
    for ent, what, val in lex_changes:
        print(f"  사전  {ent}: {what} ← {val}")
    for var, off, st, why in spell:
        print(f"  표기  {var} → {off}  [{st}]  {why}")
    for e, field, val in reg_changes:
        label = "웹 요약(외부 출처로 표시)" if field == "_web" else field
        print(f"  인물  {norm(e.get('name'))}: {label} ← {val[:60]}  (빈 값만 채움)")
    if not (lex_changes or spell or reg_changes):
        print("반영할 것이 없습니다.")
        return
    if not a.apply:
        print("\n(dry run) --apply 로 반영합니다. 표기 교정은 사전에만 들어가고, 본문은 "
              "`lexicon.py apply --apply` 가 고칩니다.")
        return
    for e, field, val in reg_changes:
        if field == "_web":
            d = store["entities"].get(norm(e.get("name", "")), {})
            e["web"] = {"summary": val, "status": d.get("status", ""),
                        "url": (d.get("facts") or [{}])[0].get("url", ""),
                        "fetched": d.get("fetched", "")}
        else:
            e[field] = val
    if reg_changes and os.path.exists(reg_path):
        json.dump(registry, open(reg_path, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
    lx.save_store(corpus, lex)
    print(f"\n반영 완료 → {lx.STORE_REL}"
          + (f" · _meta/speakers.json" if reg_changes else ""))
    print("본문 교정: `lexicon.py <corpus> apply --apply` → build_index → build_db → build_dossiers")


def cmd_list(a, corpus, store):
    ents = store["entities"]
    by = Counter(v.get("status", "?") for v in ents.values())
    print(f"외부 보강 {len(ents)}건 — " + " · ".join(f"{k} {v}" for k, v in by.items())
          + f" (updated {store.get('updated', '?')})")
    for name, d in sorted(ents.items()):
        if a.status and d.get("status") != a.status:
            continue
        print(f"  {name:22s} [{d.get('kind')}/{d.get('status')}] {d.get('summary', '')[:60]}")
        for f in d.get("facts", [])[:3]:
            print(f"      · {f['text'][:70]}  ({f['url'][:50]}, {f.get('fetched', '')})")


def cmd_forget(a, corpus, store):
    ent = norm(a.entity)
    if ent not in store["entities"]:
        sys.exit(f"ERROR: '{ent}' 는 캐시에 없습니다.")
    print(f"삭제 대상: {ent} [{store['entities'][ent].get('status')}]")
    if not a.apply:
        print("(dry run) --apply 로 삭제합니다.")
        return
    del store["entities"][ent]
    save_store(corpus, store)
    print("삭제 완료. (사전·레지스트리에 이미 반영된 값은 그대로입니다)")


def main():
    ap = argparse.ArgumentParser(description="외부(웹) 정보로 용어·인물 정확도 보강")
    ap.add_argument("corpus")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("plan", help="무엇을 검색할지 + 질의문을 만든다")
    p.add_argument("--min-count", type=int, default=5)
    p.add_argument("--limit", type=int, default=15)
    p.add_argument("--since", default="")
    p.add_argument("--include-people", action="store_true",
                   help="공인 게이트를 통과한 인물도 검색 후보에 포함")
    p.add_argument("--refresh", action="store_true", help="이미 확인된 항목도 다시 계획")
    p.add_argument("--json", default="")

    p = sub.add_parser("save", help="검색 결과를 캐시에 저장")
    p.add_argument("--file", required=True)

    p = sub.add_parser("apply", help="캐시를 사전·레지스트리에 반영")
    p.add_argument("--apply", action="store_true")
    p.add_argument("--trust-web", action="store_true",
                   help="코퍼스가 정식 표기에 동의하면 표기 교정을 '추론'으로 승격")

    p = sub.add_parser("list", help="캐시 내용")
    p.add_argument("--status", choices=STATUS)

    p = sub.add_parser("forget", help="캐시에서 항목 삭제")
    p.add_argument("--entity", required=True)
    p.add_argument("--apply", action="store_true")

    a = ap.parse_args()
    corpus = os.path.abspath(a.corpus)
    if not os.path.isdir(corpus):
        sys.exit(f"ERROR: 코퍼스 경로가 없습니다 — {corpus}")
    store = load_store(corpus)
    {"plan": cmd_plan, "save": cmd_save, "apply": cmd_apply, "list": cmd_list,
     "forget": cmd_forget}[a.cmd](a, corpus, store)


if __name__ == "__main__":
    main()
