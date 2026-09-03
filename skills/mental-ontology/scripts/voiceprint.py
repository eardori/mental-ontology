#!/usr/bin/env python3
"""Persistent voice identity — recognize known people by voice across recordings.

Diarization (diarize.py → recluster.py) says "there are 3 speakers"; it cannot say WHO.
This script remembers voices: once a cluster is confirmed as 정우진, every later
recording of 정우진 is labeled automatically. That is what makes casual, frequent
recording (식사, 통화, 잡담) cheap enough to actually keep doing — the speaker question
is asked once per person, not once per recording.

Store: <corpus>/_meta/voiceprints.json  (plain JSON, greppable, hand-editable)
  {"version":1, "model":"campplus.onnx", "dim":192,
   "people": {"정우진": {"centroids":[{"id","vec","dur","n","sources","updated"}]}}}
Multiple centroids per person on purpose: a phone call and an in-person dinner sound
different, and one averaged blob would fit neither.

Usage
  # 1) audio → per-cluster embeddings (needs sherpa-onnx; models as in diarize.py)
  python3 voiceprint.py <corpus> embed    --wav in.wav --regions diar_re.json --out emb.json
  # 2) who is each cluster?
  python3 voiceprint.py <corpus> identify --embeddings emb.json [--out labels.json]
  # 3) after the user confirms, learn (cluster id → canonical registry name)
  python3 voiceprint.py <corpus> enroll   --embeddings emb.json --map '{"0":"정우진"}' --source <rec-id>
  python3 voiceprint.py <corpus> list
  python3 voiceprint.py <corpus> forget   --name "이름" [--apply]

`identify` and `enroll` also accept `--wav`+`--regions` directly (embeds on the fly).
Feed labels.json to merge_diar.py --labels to get real names in the transcript.

Decisions are reported with the actual cosine scores — never a silent guess:
  auto     score ≥ --accept AND beats the runner-up by ≥ --margin  → label it
  ask      plausible but not certain (or the cluster is too short)  → Stage 3 asks the user
  unknown  nobody enrolled comes close                              → Stage 3 asks the user
Only `auto` is applied without a human in the loop.

Deps: stdlib only for matching/storage (so it is testable and portable);
      `embed` lazily imports numpy + soundfile + sherpa-onnx.
"""
import argparse, json, math, os, sys, unicodedata
from datetime import date

STORE_REL = "_meta/voiceprints.json"

# Cosine thresholds for campplus embeddings. Deliberately conservative: a wrong
# auto-label silently poisons the corpus, an "ask" costs one question.
ACCEPT = 0.62          # ≥ this (and clear of the runner-up) → auto-label
FLOOR = 0.45           # < this → nobody plausible, ask from scratch
MARGIN = 0.05          # best must beat the runner-up by this much
MIN_ID_DUR = 3.0       # a cluster with less speech than this can't be identified
MIN_ENROLL_DUR = 5.0   # ... or enrolled (too noisy to remember)
MERGE_SIM = 0.55       # merge into an existing centroid if this close, else add one
MAX_CENTROIDS = 5      # per person; the least-heard one is evicted


def norm(s):
    return unicodedata.normalize("NFC", (s or "").strip())


# ---------------------------------------------------------------- store + math

def load_store(corpus):
    p = os.path.join(corpus, STORE_REL)
    if os.path.exists(p):
        st = json.load(open(p, encoding="utf-8"))
        st.setdefault("people", {})
        return st
    return {"version": 1, "model": "campplus.onnx", "dim": None, "people": {}}


def save_store(corpus, st):
    p = os.path.join(corpus, STORE_REL)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    json.dump(st, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return p


def unit(vec):
    n = math.sqrt(sum(x * x for x in vec))
    return [x / n for x in vec] if n else list(vec)


def cos(a, b):
    """Cosine similarity. Stored/emitted vectors are unit-normalized, but never assume.

    Different lengths mean different embedding models — comparing them by truncating
    to the shorter one would produce a confident, meaningless score, so refuse.
    """
    if len(a) != len(b):
        return 0.0
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if not na or not nb:
        return 0.0
    return sum(x * y for x, y in zip(a, b)) / (na * nb)


def score_person(store, name, vec):
    """A person's score = their best-matching centroid (not the average of all)."""
    best, cid = 0.0, None
    for c in store["people"].get(name, {}).get("centroids", []) or []:
        s = cos(vec, c["vec"])
        if s > best:
            best, cid = s, c.get("id")
    return best, cid


# ---------------------------------------------------------------- identify

def identify(store, clusters, accept=ACCEPT, floor=FLOOR, margin=MARGIN,
             min_dur=MIN_ID_DUR):
    """Assign enrolled people to diarization clusters.

    Each person is claimed by at most ONE cluster (the same voice cannot be two
    speakers in one recording); a loser that wanted the same person is downgraded
    to `ask` with a note instead of being silently mislabeled.
    """
    names = sorted(store["people"])
    ranked = {}                       # label -> [(name, score, centroid_id), ...] desc
    for c in clusters:
        lst = []
        for n in names:
            s, cid = score_person(store, n, c["vec"])
            lst.append((n, s, cid))
        lst.sort(key=lambda x: -x[1])
        ranked[c["label"]] = lst

    # greedy global assignment: highest score wins the pair, both sides then taken
    pairs = sorted(((s, lab, n) for lab, lst in ranked.items() for n, s, _ in lst),
                   key=lambda x: (-x[0], x[1], x[2]))
    picked, used = {}, {}
    for s, lab, n in pairs:
        if s < floor or lab in picked or n in used:
            continue
        picked[lab], used[n] = (n, s), lab

    out = []
    for c in clusters:
        lst = ranked[c["label"]]
        top = lst[0] if lst else None
        got = picked.get(c["label"])
        # `name` is ALWAYS this cluster's best candidate and `runner_up` the second —
        # Stage 3 offers `name` as the default answer, so it must never be the weaker one.
        row = {"label": c["label"], "dur": round(c.get("dur", 0.0), 1),
               "name": None, "score": 0.0, "runner_up": None,
               "decision": "unknown", "reason": ""}
        second = [lst[1][0], round(lst[1][1], 3)] if len(lst) > 1 else None
        if not names:
            row["reason"] = "등록된 목소리 없음"
        elif not top or top[1] < floor:
            row.update(score=round(top[1], 3) if top else 0.0,
                       reason=f"최고 유사도 {top[1]:.2f} < {floor}" if top else "등록된 목소리 없음")
        elif got and got[0] == top[0]:
            s = got[1]
            gap = s - (lst[1][1] if len(lst) > 1 else 0.0)
            row.update(name=top[0], score=round(s, 3), runner_up=second)
            if c.get("dur", 0.0) < min_dur:
                row.update(decision="ask",
                           reason=f"발화 {c.get('dur', 0):.0f}s < {min_dur:.0f}s — 확인 필요")
            elif s >= accept and gap >= margin:
                row.update(decision="auto", reason=f"cos {s:.2f} (2위 대비 +{gap:.2f})")
            elif s >= accept:
                row.update(decision="ask", reason=f"2위와 차이 {gap:.2f} < {margin} — 확인 필요")
            else:
                row.update(decision="ask", reason=f"cos {s:.2f} < {accept} — 후보만 제시")
        else:
            # This cluster's best candidate belongs to another cluster that matched them
            # better. Usually ONE person got split into two clusters — say so, and never
            # auto-label; the runner-up is offered only as the second option.
            where = used.get(top[0])
            row.update(name=top[0], score=round(top[1], 3), runner_up=second, decision="ask",
                       reason=f"최고 후보 {top[0]}({top[1]:.2f})가 클러스터 "
                              f"[{where}]에도 매칭됨 — 화자 과다분할 가능성 "
                              f"(recluster.py 임계값을 0.5~0.6으로 올려 재실행)"
                              if where is not None else
                              f"cos {top[1]:.2f} — 다른 클러스터와 경합, 확인 필요")
        out.append(row)
    return out


# ---------------------------------------------------------------- enroll / forget

def enroll(store, name, vec, dur, source, merge_sim=MERGE_SIM, max_c=MAX_CENTROIDS):
    """Fold one cluster embedding into a person's voiceprint (duration-weighted)."""
    name = norm(name)
    vec = unit(vec)
    dim = store.get("dim")
    if dim and len(vec) != dim:
        # Truncating to the shorter vector would silently corrupt a stored voiceprint,
        # and the source audio is usually gone — this file cannot be rebuilt.
        raise ValueError(f"임베딩 차원 {len(vec)} ≠ 저장된 차원 {dim} — "
                         "다른 임베딩 모델입니다. 같은 모델로 다시 추출하거나 "
                         "voiceprints.json을 새로 시작하세요.")
    person = store["people"].setdefault(name, {"centroids": []})
    person.setdefault("centroids", [])
    cents = person["centroids"]
    store["dim"] = dim or len(vec)

    best, bi = 0.0, -1
    for i, c in enumerate(cents):
        s = cos(vec, c["vec"])
        if s > best:
            best, bi = s, i

    if bi >= 0 and best >= merge_sim:
        c = cents[bi]
        w0, w1 = c.get("dur", 1.0), max(dur, 0.1)
        c["vec"] = unit([(a * w0 + b * w1) / (w0 + w1) for a, b in zip(c["vec"], vec)])
        c["dur"] = round(w0 + w1, 1)
        c["n"] = c.get("n", 1) + 1
        if source and source not in c.setdefault("sources", []):
            c["sources"].append(source)
        c["updated"] = date.today().isoformat()
        action = f"기존 센트로이드 {c['id']}에 병합 (cos {best:.2f})"
    else:
        cid = f"c{len(cents) + 1}"
        while any(c.get("id") == cid for c in cents):
            cid += "x"
        cents.append({"id": cid, "vec": vec, "dur": round(max(dur, 0.1), 1), "n": 1,
                      "sources": [source] if source else [],
                      "updated": date.today().isoformat()})
        action = f"새 센트로이드 {cid} 추가" + (f" (최고 유사도 {best:.2f} < {merge_sim})" if bi >= 0 else "")
        if len(cents) > max_c:
            # Evict from the PRE-EXISTING centroids only. Dropping the one just added
            # (the common case for a short new recording condition) would report success
            # while learning nothing — the phone-call voice would be asked about forever.
            drop = min(cents[:-1], key=lambda c: c.get("dur", 0.0))
            cents.remove(drop)
            action += f" · 가장 적게 들은 {drop['id']}({drop.get('dur', 0):.0f}s) 제거 (상한 {max_c})"
    return action


def forget(store, name):
    return store["people"].pop(norm(name), None)


# ---------------------------------------------------------------- embeddings io

def read_clusters(path):
    """[{label, vec, dur}] — accepts a bare list or {"clusters": [...]}"""
    d = json.load(open(path, encoding="utf-8"))
    cl = d["clusters"] if isinstance(d, dict) else d
    out = []
    for c in cl:
        out.append({"label": str(c["label"]), "vec": list(c["vec"]),
                    "dur": float(c.get("dur", 0.0))})
    return out


def embed_wav(wav, regions_path, min_region=1.5):
    """Duration-weighted mean campplus embedding per diarization cluster."""
    try:
        import numpy as np, soundfile as sf, sherpa_onnx
    except ImportError as e:
        sys.exit(f"ERROR: {e.name} 없음 — 임베딩에는 음성 라이브러리가 필요합니다.\n"
                 "  pip3 install sherpa-onnx soundfile numpy")
    base = (os.environ.get("DIAR_MODELS")
            or next((p for p in [os.path.expanduser("~/.cache/mental-ontology/diar-models"),
                                 os.path.expanduser("~/.cache/onda-diar/models")]
                     if os.path.isdir(p)),
                    os.path.expanduser("~/.cache/mental-ontology/diar-models")))
    model = f"{base}/campplus.onnx"
    if not os.path.exists(model):
        sys.exit(f"ERROR: {model} 없음 — diarize.py와 같은 모델 디렉터리가 필요합니다 "
                 "(env DIAR_MODELS로 지정).")
    samples, sr = sf.read(wav, dtype="float32")
    if samples.ndim > 1:
        samples = samples.mean(axis=1)
    if sr != 16000:
        sys.exit(f"ERROR: 16kHz mono WAV가 필요합니다 (현재 {sr}Hz). "
                 "ffmpeg -i in.mp3 -ac 1 -ar 16000 in.wav")
    regions = json.load(open(regions_path, encoding="utf-8"))
    ex = sherpa_onnx.SpeakerEmbeddingExtractor(
        sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=model, num_threads=8))
    acc, dur = {}, {}
    for r in regions:
        d = float(r["end"]) - float(r["start"])
        if d < min_region:
            continue
        seg = samples[int(float(r["start"]) * sr):int(float(r["end"]) * sr)]
        if len(seg) < sr * 0.5:
            continue
        st = ex.create_stream()
        st.accept_waveform(sr, seg)
        st.input_finished()
        e = np.array(ex.compute(st), dtype=np.float64)
        n = np.linalg.norm(e)
        if n:
            e = e / n
        lab = str(r["speaker"])
        acc[lab] = acc.get(lab, np.zeros_like(e)) + e * d
        dur[lab] = dur.get(lab, 0.0) + d
    clusters = []
    for lab in sorted(acc, key=lambda x: -dur[x]):
        clusters.append({"label": lab, "vec": unit(list(acc[lab])), "dur": round(dur[lab], 1)})
    return clusters


def parse_map(raw):
    """--map accepts inline JSON or a path. Keys: cluster id ("0") or "Speaker 1" (=cluster 0)."""
    d = json.load(open(raw, encoding="utf-8")) if os.path.exists(raw) else json.loads(raw)
    out = {}
    for k, v in d.items():
        k = str(k).strip()
        m = k.lower().replace("발화자", "speaker")
        if m.startswith("speaker"):
            rest = m.replace("speaker", "").strip()
            if not rest.isdigit():
                sys.exit(f"ERROR: --map 키 '{k}' 를 클러스터 번호로 해석할 수 없습니다 "
                         "(클러스터 id \"0\" 또는 \"Speaker 1\" 형식).")
            k = str(int(rest) - 1)
        out[k] = norm(v)
    return out


def registry_names(corpus):
    p = os.path.join(corpus, "_meta/speakers.json")
    if not os.path.exists(p):
        return set()
    try:
        return {norm(e.get("name", "")) for e in json.load(open(p, encoding="utf-8"))}
    except (json.JSONDecodeError, TypeError, AttributeError):
        return set()


# ---------------------------------------------------------------- CLI

def main():
    ap = argparse.ArgumentParser(description="Persistent voice identity for the corpus.")
    ap.add_argument("corpus")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def io_args(p, need_out=False):
        p.add_argument("--embeddings")
        p.add_argument("--wav")
        p.add_argument("--regions")
        p.add_argument("--out", required=need_out)

    p_emb = sub.add_parser("embed", help="audio + regions → per-cluster embeddings")
    io_args(p_emb, need_out=True)

    p_id = sub.add_parser("identify", help="which enrolled person is each cluster?")
    io_args(p_id)
    p_id.add_argument("--accept", type=float, default=ACCEPT)
    p_id.add_argument("--floor", type=float, default=FLOOR)
    p_id.add_argument("--margin", type=float, default=MARGIN)
    p_id.add_argument("--min-dur", type=float, default=MIN_ID_DUR)

    p_en = sub.add_parser("enroll", help="learn confirmed cluster→person mappings")
    io_args(p_en)
    p_en.add_argument("--map", required=True)
    p_en.add_argument("--source", default="")
    p_en.add_argument("--min-dur", type=float, default=MIN_ENROLL_DUR)
    p_en.add_argument("--force", action="store_true", help="enroll short/conflicting clusters anyway")
    p_en.add_argument("--dry-run", action="store_true")

    sub.add_parser("list", help="who is enrolled, and how much voice was heard")

    p_fg = sub.add_parser("forget", help="delete a person's voiceprint")
    p_fg.add_argument("--name", required=True)
    p_fg.add_argument("--apply", action="store_true")

    a = ap.parse_args()
    corpus = os.path.abspath(a.corpus)
    store = load_store(corpus)

    def check_dims(cl):
        dim = store.get("dim")
        bad = [c for c in cl if dim and len(c["vec"]) != dim]
        if bad:
            sys.exit(f"ERROR: 임베딩 차원 {len(bad[0]['vec'])} ≠ 저장된 차원 {dim} — "
                     "다른 임베딩 모델로 만든 파일입니다. 같은 모델(campplus)로 다시 "
                     "추출하세요 (섞으면 voiceprints.json이 손상됩니다).")
        return cl

    def clusters_from_args():
        if getattr(a, "embeddings", None):
            return check_dims(read_clusters(a.embeddings))
        if getattr(a, "wav", None) and getattr(a, "regions", None):
            return check_dims(embed_wav(a.wav, a.regions))
        sys.exit("ERROR: --embeddings 또는 --wav + --regions 중 하나가 필요합니다.")

    if a.cmd == "embed":
        cl = embed_wav(a.wav, a.regions) if a.wav and a.regions else clusters_from_args()
        json.dump({"clusters": cl}, open(a.out, "w", encoding="utf-8"))
        print(f"{a.out}: {len(cl)} clusters — " +
              " · ".join(f"{c['label']}({c['dur']:.0f}s)" for c in cl))
        return

    if a.cmd == "identify":
        cl = clusters_from_args()
        rows = identify(store, cl, a.accept, a.floor, a.margin, a.min_dur)
        auto = {r["label"]: r["name"] for r in rows if r["decision"] == "auto"}
        res = {"decisions": rows, "auto": auto,
               "ask": [r["label"] for r in rows if r["decision"] != "auto"],
               "params": {"accept": a.accept, "floor": a.floor, "margin": a.margin,
                          "min_dur": a.min_dur},
               "enrolled": len(store["people"])}
        if a.out:
            json.dump(res, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"등록된 목소리 {len(store['people'])}명 · 클러스터 {len(rows)}개")
        for r in rows:
            tag = {"auto": "✓ 자동", "ask": "? 확인", "unknown": "· 미상"}[r["decision"]]
            who = r["name"] or "—"
            print(f"  [{r['label']}] {r['dur']:>6.1f}s  {tag}  {who:<12} {r['reason']}")
        if res["ask"]:
            print(f"WARN: {len(res['ask'])} clusters need a human answer "
                  f"(Stage 3 질문 대상): {', '.join(res['ask'])}")
        if a.out:
            print(f"→ {a.out}  (merge_diar.py --labels 로 전달)")
        return

    if a.cmd == "enroll":
        cl = {c["label"]: c for c in clusters_from_args()}
        mapping = parse_map(a.map)
        known = registry_names(corpus)
        applied, skipped = [], []
        for lab, name in mapping.items():
            c = cl.get(lab)
            if not c:
                skipped.append(f"[{lab}] → {name}: 임베딩에 해당 클러스터 없음 "
                               f"(있는 것: {', '.join(sorted(cl)) or '없음'})")
                continue
            if c["dur"] < a.min_dur and not a.force:
                skipped.append(f"[{lab}] → {name}: 발화 {c['dur']:.0f}s < {a.min_dur:.0f}s "
                               "(--force 로 강제 가능)")
                continue
            if known and name not in known:
                print(f"WARN: '{name}'은 _meta/speakers.json에 없는 이름입니다 — "
                      "오타면 지금 고치세요 (레지스트리 정식 이름이 조인 키).")
            clash = [(n, s) for n, s in ((n, score_person(store, n, c["vec"])[0])
                                         for n in store["people"]) if n != name and s >= ACCEPT]
            if clash and not a.force:
                skipped.append(f"[{lab}] → {name}: 이미 {clash[0][0]}({clash[0][1]:.2f})와 "
                               "매우 유사 — 화자 라벨 오류 가능성 (--force 로 강제)")
                continue
            if a.dry_run:
                applied.append(f"[{lab}] {c['dur']:.0f}s → {name} (dry-run)")
                continue
            try:
                act = enroll(store, name, c["vec"], c["dur"], a.source)
            except ValueError as e:
                skipped.append(f"[{lab}] → {name}: {e}")
                continue
            applied.append(f"[{lab}] {c['dur']:.0f}s → {name}: {act}")
        for line in applied:
            print("  " + line)
        for line in skipped:
            print("  SKIP " + line)
        if applied and not a.dry_run:
            print(f"저장: {os.path.relpath(save_store(corpus, store), corpus)} "
                  f"({len(store['people'])}명 등록됨)")
        elif a.dry_run:
            print("DRY RUN — 저장하지 않았습니다.")
        if skipped:
            print(f"WARN: {len(skipped)}개 매핑이 학습되지 않았습니다 (위 SKIP 사유 확인).")
        return

    if a.cmd == "list":
        if not store["people"]:
            print("등록된 목소리 없음 — enroll 로 학습시키세요.")
            return
        print(f"{len(store['people'])}명 등록됨 (model: {store.get('model')}, "
              f"dim: {store.get('dim')})")
        def cents_of(n):
            return store["people"][n].get("centroids") or []
        for name in sorted(store["people"], key=lambda n: -sum(
                c.get("dur", 0) for c in cents_of(n))):
            cs = cents_of(name)
            tot = sum(c.get("dur", 0) for c in cs)
            srcs = sorted({s for c in cs for s in c.get("sources", [])})
            last = max((c.get("updated", "") for c in cs), default="")
            print(f"  {name:<14} {tot/60:6.1f}분  센트로이드 {len(cs)}  "
                  f"녹음 {len(srcs)}건  최근 {last or '—'}")
        return

    if a.cmd == "forget":
        name = norm(a.name)
        p = store["people"].get(name)
        if not p:
            print(f"'{name}' 은 등록되어 있지 않습니다.")
            return
        cs = p.get("centroids") or []
        tot = sum(c.get("dur", 0) for c in cs)
        print(f"{'APPLIED' if a.apply else 'DRY RUN'} — '{name}' 삭제: "
              f"센트로이드 {len(cs)}개, 누적 {tot/60:.1f}분")
        if a.apply:
            forget(store, name)
            save_store(corpus, store)
            print(f"삭제 완료 ({len(store['people'])}명 남음)")
        else:
            print("--apply 를 붙이면 실행됩니다.")
        return


if __name__ == "__main__":
    main()
