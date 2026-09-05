#!/usr/bin/env python3
"""Terminology lexicon + STT typo correction — the corpus learns its own vocabulary.

STT gets the same proper nouns wrong over and over (커넥티비티 → 커텍티비티, 넥스트라 →
넥스토라). Every wrong spelling is a term SQL cannot find, a quote validate.py cannot
ground, and — when it is a person's name — a speaker build_db.py cannot join. This script
builds the corpus's own dictionary out of what has actually been said, and repairs the
transcripts with it: deterministically, with a backup and an audit line for every single
replacement, so nothing is ever silently rewritten.

Store:    <corpus>/_meta/lexicon.json               ← the dictionary (data of record)
Log:      <corpus>/_meta/lexicon-corrections.jsonl  ← every replacement ever applied
Backups:  <corpus>/_ontology/_work/lexicon-backup-<batch>/  ← revert target

Commands
  mine    transcripts → frequent terms + misspelling candidates (report; --apply learns)
  add     write a confirmed term / misspelling pair into the lexicon
  list    what the lexicon knows
  apply   correct transcripts from the lexicon           (dry run by default)
  patch   apply reader-decided find→replace pairs to files (dry run by default)
  revert  restore a batch from its backup                (dry run by default)
  log     what was corrected, when, and on what grounds
  forget  delete a term

Why two edit paths: `apply` is dictionary-driven and deterministic. `patch` is the
token-economy primitive for the edits only a reader can make (일반 오탈자, 지시어 해소):
the LLM emits find→replace pairs, python touches the file — the transcript body is never
re-emitted through the model. Both back up, both log, both are reverted the same way.

Two honesty rules are wired into the code, not just the docs:
  1. **Names are never auto-corrected.** A misspelled person is fixed by adding an ALIAS
     to _meta/speakers.json (which is how build_db.py joins), not by rewriting what was
     said — rewriting could silently merge two real people. `mine` reports name
     candidates separately and refuses to auto-learn them.
  2. **An inferred pair says so.** status 확정 = the user confirmed it, 추론 = the
     thresholds below decided it, 후보 = reported only, never applied. The log records
     which, so "왜 이렇게 고쳐졌지?" always has an answer.

No external dependencies (python3 stdlib only).
"""
import argparse, json, glob, os, re, shutil, sys, unicodedata
from collections import Counter, defaultdict
from datetime import datetime

STORE_REL = "_meta/lexicon.json"
LOG_REL = "_meta/lexicon-corrections.jsonl"
BACKUP_REL = "_ontology/_work"

# ---- thresholds (edit here; every report prints the numbers it used) -------------
MIN_TERM_COUNT = 3     # a token must be said this often to be reported as a new term
CAND_MIN_CANON = 3     # a misspelling pair needs a canonical at least this frequent
CAND_RATIO = 3         # ... and canonical ≥ ratio × variant
MAX_JAMO_DIST = 3      # ... within this jamo-level edit distance
MAX_JAMO_RATIO = 0.20  # ... and that distance ≤ 20% of the canonical's jamo length
AUTO_MIN_CANON = 5     # auto(추론) tier: canonical this frequent
AUTO_MAX_VARIANT = 2   # ... variant at most this rare
AUTO_RATIO = 5         # ... canonical ≥ 5× variant
AUTO_MIN_LEN = 4       # ... canonical at least this long (한글 음절/라틴 문자),
                       #     unless it is already a known term — short words like
                       #     결재/결제 are real pairs of DIFFERENT words, not typos
AUTO_MAX_DIST = 1      # ... single-jamo error (2 allowed when the term is long)
AUTO_LONG_JAMO = 12    # ... "long" = this many jamo

KINDS = ["인물", "조직", "제품", "약어", "용어", "기타"]
STATUS = ["확정", "추론", "후보"]

# Particles that may trail a term. A trailing Hangul run that is NOT one of these
# means we hit a different word and must leave it alone.
PARTICLES = [
    "은", "는", "이", "가", "을", "를", "에", "의", "와", "과", "도", "만", "로", "으로",
    "에서", "에서는", "에는", "에도", "에게", "에게는", "한테", "께", "께서", "부터", "까지",
    "보다", "처럼", "마다", "밖에", "조차", "라도", "이라도", "라고", "이라고", "라는",
    "이라는", "라며", "이라며", "이나", "나", "이란", "란", "이든", "든", "이며", "며",
    "으로는", "로는", "으로도", "로도", "으로서", "로서", "으로써", "로써", "와는", "과는",
    "은요", "는요", "요", "님", "님은", "님이", "님을", "님과", "님도", "님께", "씨", "들",
    "들이", "들은", "들을", "들과", "들도", "측", "사", "쪽", "팀", "건", "발", "형",
]
PART_SET = set(PARTICLES)

# Very common Korean words. Never a misspelling target (correcting toward them would
# rewrite ordinary prose) and never reported as a new term.
STOPWORDS = set("""
그리고 그래서 하지만 그런데 그러니까 그러면 그니까 근데 이제 지금 다음 오늘 내일 어제
우리 저희 사람 사람들 생각 이야기 얘기 부분 경우 정도 진짜 조금 약간 그냥 이런 저런 그런
때문 여기 거기 저기 다시 계속 이번 저번 지난 대해 대한 관련 통해 위해 만약 물론 아마
문제 상황 방법 내용 결과 이유 사실 필요 가능 시간 회의 말씀 정리 확인 진행 준비 시작
마지막 처음 하나 둘째 조건 얼마 무슨 어떤 어디 언제 누구 뭔가 그거 이거 저거 그것 이것
저것 여러 모두 전부 각각 서로 보통 대부분 실제 당연 결국 일단 아무 아직 벌써 항상 가끔
자주 많이 조금씩 그때 이때 요즘 최근 향후 이상 이하 이후 이전 관계 이야기가 라고 니까
안녕하세요 감사합니다 죄송합니다 알겠습니다 그렇죠 맞아요 네네 아니요 그러면은
""".split())

CHO = list("ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ")
JUNG = list("ㅏㅐㅑㅒㅓㅔㅕㅖㅗㅘㅙㅚㅛㅜㅝㅞㅟㅠㅡㅢㅣ")
JONG = ["", "ㄱ", "ㄲ", "ㄳ", "ㄴ", "ㄵ", "ㄶ", "ㄷ", "ㄹ", "ㄺ", "ㄻ", "ㄼ", "ㄽ", "ㄾ",
        "ㄿ", "ㅀ", "ㅁ", "ㅂ", "ㅄ", "ㅅ", "ㅆ", "ㅇ", "ㅈ", "ㅊ", "ㅋ", "ㅌ", "ㅍ", "ㅎ"]

TOKEN = re.compile(r'[가-힣]{2,}|[A-Za-z][A-Za-z0-9\-.]*[A-Za-z0-9]')
DEICTIC = re.compile(r'(그거|이거|저거|그건|그 건|이 건|그쪽|저쪽|저번|지난번|그때|'
                     r'그 부분|이 부분|아까 그|그 안건|그 얘기|그 내용)')


def norm(s):
    return unicodedata.normalize("NFC", (s or "").strip())


def jamo(s):
    """'커넥' → ['ㅋ','ㅓ','ㄴ','ㅔ','ㄱ'] — STT errors are jamo-sized, not syllable-sized."""
    out = []
    for ch in s.lower():
        c = ord(ch)
        if 0xAC00 <= c <= 0xD7A3:
            i = c - 0xAC00
            out.append(CHO[i // 588])
            out.append(JUNG[(i % 588) // 28])
            if JONG[i % 28]:
                out.append(JONG[i % 28])
        else:
            out.append(ch)
    return out


def lev(a, b, cap=4):
    """Levenshtein with an early cap — we only care about near-misses."""
    if abs(len(a) - len(b)) > cap:
        return cap + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        best = i
        for j, cb in enumerate(b, 1):
            v = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb))
            cur.append(v)
            best = min(best, v)
        if best > cap:
            return cap + 1
        prev = cur
    return prev[-1]


def strip_particle(tok):
    for p in sorted(PARTICLES, key=len, reverse=True):
        if tok.endswith(p) and len(tok) - len(p) >= 2:
            return tok[:-len(p)]
    return tok


# ------------------------------------------------------------------ corpus IO

def split_fm(text):
    m = re.match(r'^---\s*\n(.*?)\n---\s*\n', text, re.S)
    return (m.group(0), text[m.end():]) if m else ("", text)


def fm_date(head):
    m = re.search(r'^date:\s*(\S+)', head, re.M)
    return m.group(1).strip().strip('"') if m else ""


def iter_docs(corpus, since="", only_path=""):
    """(abs path, rel path, date, frontmatter, body) for each transcript."""
    if only_path:
        paths = [only_path if os.path.isabs(only_path) else os.path.join(corpus, only_path)]
    else:
        paths = sorted(glob.glob(os.path.join(corpus, "transcripts", "**", "*.md"),
                                 recursive=True))
    for p in paths:
        if not os.path.exists(p):
            print(f"WARN: 파일 없음 — {p}")
            continue
        try:
            text = unicodedata.normalize("NFC", open(p, encoding="utf-8").read())
        except Exception as ex:
            print(f"WARN: 읽기 실패 {p}: {ex}")
            continue
        head, body = split_fm(text)
        d = fm_date(head)
        if since and d and d < since:
            continue
        yield p, os.path.relpath(p, corpus), d, head, body


# ------------------------------------------------------------------ the store

def load_store(corpus):
    p = os.path.join(corpus, STORE_REL)
    if os.path.exists(p):
        try:
            d = json.load(open(p, encoding="utf-8"))
            d.setdefault("terms", [])
            return d
        except Exception as ex:
            sys.exit(f"ERROR: {STORE_REL} 파싱 실패 — {ex}")
    return {"version": 1, "updated": "", "terms": []}


def save_store(corpus, store):
    store["updated"] = datetime.now().strftime("%Y-%m-%d")
    p = os.path.join(corpus, STORE_REL)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    json.dump(store, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def find_term(store, term):
    t = norm(term)
    for e in store["terms"]:
        if norm(e.get("term", "")) == t:
            return e
    return None


def load_registry(corpus):
    p = os.path.join(corpus, "_meta", "speakers.json")
    if not os.path.exists(p):
        return []
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception as ex:
        print(f"WARN: speakers.json 파싱 실패 — {ex}")
        return []


def name_tokens(registry):
    """Every string that is a PERSON — protected from rewriting in both directions."""
    out = set()
    for e in registry:
        for s in [e.get("name", "")] + list(e.get("aliases") or []):
            s = norm(s)
            if not s:
                continue
            out.add(s)
            m = re.match(r'^(.+?)\s*\((.+?)\)$', s)
            if m:
                out |= {norm(m.group(1)), norm(m.group(2))}
    return {s for s in out if s}


def lexicon_index(store):
    """term(lower) → entry, plus every alias, plus every known misspelling form."""
    canon, miss = {}, {}
    for e in store["terms"]:
        canon[norm(e["term"]).lower()] = e
        for a in e.get("aliases") or []:
            canon[norm(a).lower()] = e
        for m in e.get("misspellings") or []:
            miss[norm(m["form"]).lower()] = (e, m)
    return canon, miss


# ------------------------------------------------------------------- mining

def count_tokens(corpus, since="", only_path=""):
    counts, docs, first, last = Counter(), defaultdict(set), {}, {}
    n_docs = 0
    for _p, rel, d, _head, body in iter_docs(corpus, since, only_path):
        n_docs += 1
        for line in body.splitlines():
            if line.lstrip().startswith("#"):
                continue                       # section headers are template text
            for raw in TOKEN.findall(line):
                tok = strip_particle(norm(raw))
                if len(tok) < 2 or tok.isdigit():
                    continue
                counts[tok] += 1
                docs[tok].add(rel)
                if d:
                    first[tok] = min(first.get(tok, d), d)
                    last[tok] = max(last.get(tok, d), d)
    return counts, docs, first, last, n_docs


def term_like(tok, docs_n, n_docs):
    """Cheap noun filter for the NEW-TERM report only (never gates corrections).

    Drops verb/adjective forms (…한다/…하자/…이네) and boilerplate that shows up in
    nearly every file. A survivor is only a candidate — a human still confirms it.
    """
    if re.search(r'[A-Za-z0-9]', tok):
        return True
    if len(tok) >= 3 and tok[-1] in "다자죠네까요냐군":
        return False
    return not (n_docs >= 8 and docs_n >= n_docs * 0.9)


def pair_candidates(counts, docs, protected_names, known_canon, known_miss):
    """Rare token ~ frequent token, jamo-close → (variant, canonical, tier, why)."""
    freq = {t: c for t, c in counts.items()
            if c >= CAND_MIN_CANON and t not in STOPWORDS}

    def keys(tok):
        """`tok` plus every 1-character deletion. Two strings sharing a key are within
        two character edits — a cheap index that keeps the real STT errors and drops
        the 99.9% of pairs a full comparison would waste time on."""
        return {tok} | {tok[:i] + tok[i + 1:] for i in range(len(tok))}

    index = defaultdict(set)
    for t in freq:
        for k in keys(t):
            index[k].add(t)

    out = []
    for var, vc in counts.items():
        if var in STOPWORDS or len(var) < 2:
            continue
        if var.lower() in known_canon:          # a legitimate term of its own
            continue
        cands = set()
        for k in keys(var):
            cands |= index.get(k, set())
        best = None
        for can in cands:
            if can == var or abs(len(can) - len(var)) > 2:
                continue
            cc = counts[can]
            if cc < CAND_MIN_CANON or cc < vc * CAND_RATIO:
                continue
            ja, jb = jamo(can), jamo(var)
            d = lev(ja, jb, cap=MAX_JAMO_DIST)
            if d == 0 or d > MAX_JAMO_DIST or d > max(1, int(len(ja) * MAX_JAMO_RATIO)):
                continue
            score = (d, -cc)
            if best is None or score < best[0]:
                best = (score, can, cc, d, len(ja))
        if not best:
            continue
        _s, can, cc, d, jlen = best
        is_name = can in protected_names or var in protected_names
        known = can.lower() in known_canon
        auto = (not is_name and cc >= AUTO_MIN_CANON and vc <= AUTO_MAX_VARIANT
                and cc >= vc * AUTO_RATIO
                and (known or len(can) >= AUTO_MIN_LEN)
                and (d <= AUTO_MAX_DIST or (jlen >= AUTO_LONG_JAMO and d <= 2)))
        already = var.lower() in known_miss
        out.append({
            "variant": var, "canonical": can, "variant_count": vc, "canonical_count": cc,
            "jamo_dist": d, "docs": len(docs[var]),
            "kind": "인물" if is_name else ("용어" if known else "미등록"),
            "tier": "이미등록" if already else ("인물" if is_name else
                                             ("추론" if auto else "후보")),
        })
    out.sort(key=lambda r: (r["tier"] != "추론", -r["canonical_count"]))
    return out


def cmd_mine(a, corpus, store):
    registry = load_registry(corpus)
    names = name_tokens(registry)
    known_canon, known_miss = lexicon_index(store)
    counts, docs, first, last, n_docs = count_tokens(corpus, a.since)
    pairs = pair_candidates(counts, docs, names, known_canon, known_miss)

    paired = {p["variant"] for p in pairs}
    new_terms = [
        {"term": t, "count": c, "docs": len(docs[t]),
         "first_seen": first.get(t, ""), "last_seen": last.get(t, "")}
        for t, c in counts.most_common()
        if c >= a.min_count and t not in STOPWORDS and t.lower() not in known_canon
        and t not in names and t.lower() not in known_miss
        and term_like(t, len(docs[t]), n_docs) and t not in paired
    ][:a.limit]

    deictics = []
    for _p, rel, _d, _head, body in iter_docs(corpus, a.since):
        for line in body.splitlines():
            if line.strip().startswith("- [") and DEICTIC.search(line):
                deictics.append({"path": rel, "line": line.strip()})

    auto = [p for p in pairs if p["tier"] == "추론"]
    ask = [p for p in pairs if p["tier"] == "후보"][:a.limit]
    nm = [p for p in pairs if p["tier"] == "인물"][:a.limit]

    print(f"사전 {len(store['terms'])}개 등록 · 전사 {n_docs}개 스캔"
          + (f" (since {a.since})" if a.since else "")
          + f" · 어휘 {len(counts)}종")
    print(f"기준: 정답어 ≥{CAND_MIN_CANON}회·변형의 {CAND_RATIO}배, 자모거리 ≤{MAX_JAMO_DIST}"
          f" | 자동(추론): 정답어 ≥{AUTO_MIN_CANON}회·변형 ≤{AUTO_MAX_VARIANT}회·거리 {AUTO_MAX_DIST}")

    def show(rows, title):
        if not rows:
            return
        print(f"\n{title} ({len(rows)})")
        for r in rows:
            print(f"  {r['variant']} → {r['canonical']}"
                  f"   ({r['variant_count']}회 vs {r['canonical_count']}회 · 자모거리 {r['jamo_dist']})")

    show(auto, "오타 후보 — 자동 적용 대상(추론)")
    show(ask, "오타 후보 — 사람 확인 필요(후보)")
    if nm:
        print(f"\n인물 이름 오인식 후보 ({len(nm)}) — 본문을 고치지 말고 "
              f"speakers.json의 aliases에 추가하세요 (build_db가 그걸로 조인합니다)")
        for r in nm:
            print(f"  {r['variant']} → {r['canonical']}   ({r['variant_count']}회)")
    if new_terms:
        print(f"\n새 용어 후보 — 사전에 없음 ({len(new_terms)})")
        for r in new_terms:
            print(f"  {r['term']:20s} {r['count']:4d}회 · {r['docs']}개 회의"
                  f" · {r['first_seen']}~{r['last_seen']}")
    if deictics:
        print(f"\n지시어가 남은 액션아이템 ({len(deictics)}) — 무엇을 가리키는지 "
              f"본문에서 확인해 〔=…〕로 명시하세요 (patch 사용)")
        for r in deictics[:a.limit]:
            print(f"  {r['path']}: {r['line'][:80]}")

    if a.json:
        os.makedirs(os.path.dirname(os.path.abspath(a.json)), exist_ok=True)
        json.dump({"scanned": n_docs, "since": a.since, "auto": auto, "ask": ask,
                   "names": nm, "new_terms": new_terms, "deictics": deictics},
                  open(a.json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"\n→ {a.json}")

    if not a.apply:
        print("\n(dry run) --apply 를 붙이면 '추론' 오타쌍을 사전에 학습시킵니다. "
              "'후보'와 인물 이름은 사람이 확인해야 들어갑니다.")
        return
    learned = 0
    for r in auto:
        e = find_term(store, r["canonical"])
        if not e:
            e = {"term": r["canonical"], "kind": "용어", "desc": "", "aliases": [],
                 "misspellings": [], "status": "추론", "source": "inferred",
                 "count": r["canonical_count"], "first_seen": first.get(r["canonical"], ""),
                 "last_seen": last.get(r["canonical"], ""), "protect": False}
            store["terms"].append(e)
        forms = {norm(m["form"]) for m in e.get("misspellings") or []}
        if r["variant"] in forms:
            continue
        e.setdefault("misspellings", []).append({
            "form": r["variant"], "status": "추론", "source": "inferred",
            "count": r["variant_count"], "jamo_dist": r["jamo_dist"],
            "learned": datetime.now().strftime("%Y-%m-%d")})
        learned += 1
    save_store(corpus, store)
    print(f"\n학습: 오타쌍 {learned}건 → {STORE_REL} (status=추론). "
          f"적용은 `apply --apply`.")


# -------------------------------------------------------------- replacement

def make_rx(form):
    """Match `form` as a whole word, allowing a trailing Korean particle.

    A trailing Hangul run that is not a particle means we are inside a different
    word (커넥 in 커넥터) — those are left alone.
    """
    esc = re.escape(form)
    return re.compile(rf'(?<![가-힣A-Za-z0-9_]){esc}([가-힣]*)(?![A-Za-z0-9])')


def replace_all(text, form, to):
    rx = make_rx(form)
    n = 0

    def sub(m):
        nonlocal n
        tail = m.group(1)
        if tail and tail not in PART_SET:
            return m.group(0)          # different word — do not touch
        n += 1
        return to + tail
    return rx.sub(sub, text), n


def new_batch():
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def backup_file(corpus, path, batch):
    dst = os.path.join(corpus, BACKUP_REL, f"lexicon-backup-{batch}",
                       os.path.relpath(path, corpus))
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(path, dst)


def log_rows(corpus, rows):
    p = os.path.join(corpus, LOG_REL)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def edit_files(corpus, edits, only_path="", since="", apply_=False, cmd="apply"):
    """edits: [{from,to,kind,status,source,note}] applied to every transcript body."""
    batch = new_batch()
    rows, touched = [], 0
    for p, rel, _d, head, body in iter_docs(corpus, since, only_path):
        out, hits = body, []
        for e in edits:
            out, n = replace_all(out, e["from"], e["to"])
            if n:
                hits.append((e, n))
        if not hits:
            continue
        touched += 1
        for e, n in hits:
            rows.append({"batch": batch, "ts": datetime.now().isoformat(timespec="seconds"),
                         "cmd": cmd, "path": rel, "from": e["from"], "to": e["to"], "n": n,
                         "kind": e.get("kind", ""), "status": e.get("status", ""),
                         "source": e.get("source", ""), "note": e.get("note", "")})
        print(f"  {rel}")
        for e, n in hits:
            print(f"      {e['from']} → {e['to']}  ×{n}"
                  + (f"  [{e.get('status','')}]" if e.get("status") else "")
                  + (f"  {e['note']}" if e.get("note") else ""))
        if apply_:
            backup_file(corpus, p, batch)
            open(p, "w", encoding="utf-8").write(head + out)
    total = sum(r["n"] for r in rows)
    if not rows:
        print("고칠 것이 없습니다.")
        return batch, 0, 0
    if apply_:
        log_rows(corpus, rows)
        print(f"\n적용: 파일 {touched}개 · 치환 {total}건 · batch {batch}")
        print(f"  백업 {BACKUP_REL}/lexicon-backup-{batch}/ · 되돌리기 "
              f"`lexicon.py <corpus> revert --batch {batch} --apply`")
        print("  본문이 바뀌었습니다 → build_index.py → build_db.py → build_dossiers.py 재실행")
    else:
        print(f"\n(dry run) 파일 {touched}개 · 치환 {total}건 — 적용하려면 --apply")
    return batch, touched, total


def cmd_apply(a, corpus, store):
    edits = []
    allowed = {"확정"} if a.strict else {"확정", "추론"}
    names = name_tokens(load_registry(corpus))
    for e in store["terms"]:
        if e.get("protect"):
            continue
        for m in e.get("misspellings") or []:
            if m.get("status", "후보") not in allowed:
                continue
            if norm(m["form"]) in names or norm(e["term"]) in names:
                print(f"SKIP(인물): {m['form']} → {e['term']} — 이름은 본문을 고치지 않고 "
                      f"speakers.json aliases 로 처리합니다")
                continue
            edits.append({"from": norm(m["form"]), "to": norm(e["term"]),
                          "kind": e.get("kind", "용어"), "status": m.get("status", ""),
                          "source": m.get("source", "")})
    if not edits:
        print(f"적용할 오타쌍이 없습니다 (status {'/'.join(sorted(allowed))}). "
              f"먼저 `mine --apply` 또는 `add`.")
        return
    print(f"오타쌍 {len(edits)}개 적용 대상 (status {'/'.join(sorted(allowed))})")
    edit_files(corpus, edits, a.path or "", a.since, a.apply, cmd="apply")


def cmd_patch(a, corpus, _store):
    """Reader-decided edits. The LLM emits pairs; python touches the file."""
    try:
        raw = json.load(open(a.file, encoding="utf-8"))
    except Exception as ex:
        sys.exit(f"ERROR: {a.file} 읽기 실패 — {ex}")
    edits = raw["edits"] if isinstance(raw, dict) else raw
    ok = []
    names = name_tokens(load_registry(corpus))
    for e in edits:
        if not e.get("from") or not e.get("to"):
            print(f"SKIP: from/to 누락 — {e}")
            continue
        kind = e.get("kind", "오탈자")
        if norm(e["from"]) in names and kind != "인물":
            print(f"SKIP(인물): '{e['from']}' 는 등록된 인물입니다 — 이름 교정은 "
                  f"speakers.json aliases 또는 purge/backfill 플로우로 처리하세요")
            continue
        ok.append({"from": norm(e["from"]), "to": norm(e["to"]), "kind": kind,
                   "status": "확정", "source": e.get("source", "reader"),
                   "note": e.get("note", "")})
    if not ok:
        sys.exit("ERROR: 적용할 편집이 없습니다.")
    print(f"편집 {len(ok)}건" + (f" · 대상 {a.path}" if a.path else " · 코퍼스 전체"))
    edit_files(corpus, ok, a.path or "", a.since, a.apply, cmd="patch")


def cmd_revert(a, corpus, _store):
    root = os.path.join(corpus, BACKUP_REL, f"lexicon-backup-{a.batch}")
    if not os.path.isdir(root):
        sys.exit(f"ERROR: 백업이 없습니다 — {root}")
    files = [p for p in glob.glob(os.path.join(root, "**", "*.md"), recursive=True)]
    print(f"batch {a.batch}: 파일 {len(files)}개 복원")
    for p in files:
        rel = os.path.relpath(p, root)
        print(f"  {rel}")
        if a.apply:
            dst = os.path.join(corpus, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(p, dst)
    if a.apply:
        log_rows(corpus, [{"batch": a.batch, "ts": datetime.now().isoformat(timespec="seconds"),
                           "cmd": "revert", "path": "", "from": "", "to": "",
                           "n": len(files), "note": f"reverted batch {a.batch}"}])
        print("복원 완료 → build_index.py → build_db.py 재실행")
    else:
        print("(dry run) --apply 로 복원합니다.")


def cmd_log(a, corpus, _store):
    p = os.path.join(corpus, LOG_REL)
    if not os.path.exists(p):
        print("교정 기록이 없습니다.")
        return
    rows = [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]
    by_batch = defaultdict(list)
    for r in rows:
        by_batch[r["batch"]].append(r)
    print(f"교정 기록 {len(rows)}건 · batch {len(by_batch)}개")
    for b in sorted(by_batch, reverse=True)[:a.limit]:
        rs = by_batch[b]
        n = sum(x.get("n", 0) for x in rs)
        print(f"\n[{b}] {rs[0]['cmd']} · 파일 {len({x['path'] for x in rs if x['path']})}개 "
              f"· 치환 {n}건")
        for r in rs[:12]:
            if r["from"]:
                print(f"    {r['from']} → {r['to']} ×{r['n']}  {r['path']}"
                      + (f"  [{r.get('status','')}]" if r.get("status") else ""))
        if len(rs) > 12:
            print(f"    … 외 {len(rs) - 12}건")


def cmd_add(a, corpus, store):
    items = []
    if a.file:
        raw = json.load(open(a.file, encoding="utf-8"))
        items = raw["terms"] if isinstance(raw, dict) else raw
    if a.term:
        items.append({"term": a.term, "kind": a.kind, "desc": a.desc or "",
                      "aliases": a.alias or [], "misspellings": a.misspelling or [],
                      "status": a.status, "protect": a.protect})
    if not items:
        sys.exit("ERROR: --term 또는 --file 이 필요합니다.")
    names = name_tokens(load_registry(corpus))
    added, updated = 0, 0
    for it in items:
        term = norm(it.get("term", ""))
        if not term:
            print(f"SKIP: term 없음 — {it}")
            continue
        e = find_term(store, term)
        if not e:
            e = {"term": term, "kind": it.get("kind") or "용어", "desc": it.get("desc", ""),
                 "aliases": [], "misspellings": [], "status": it.get("status") or "확정",
                 "source": it.get("source", "user"), "count": 0,
                 "first_seen": "", "last_seen": "", "protect": bool(it.get("protect"))}
            store["terms"].append(e)
            added += 1
        else:
            updated += 1
            for k in ("kind", "desc"):
                if it.get(k):
                    e[k] = it[k]
            if it.get("status"):
                e["status"] = it["status"]
            if it.get("protect") is not None:
                e["protect"] = bool(it["protect"]) or e.get("protect", False)
        for al in it.get("aliases") or []:
            if norm(al) not in {norm(x) for x in e["aliases"]}:
                e["aliases"].append(norm(al))
        for m in it.get("misspellings") or []:
            form = norm(m if isinstance(m, str) else m.get("form", ""))
            if not form or form == term:
                continue
            if form in names:
                print(f"SKIP(인물): '{form}' 는 등록된 인물 이름입니다 — 사전이 아니라 "
                      f"speakers.json aliases 로 처리하세요")
                continue
            if form in {norm(x["form"]) for x in e["misspellings"]}:
                continue
            e["misspellings"].append({
                "form": form,
                "status": (m.get("status") if isinstance(m, dict) else None) or "확정",
                "source": (m.get("source") if isinstance(m, dict) else None) or "user",
                "learned": datetime.now().strftime("%Y-%m-%d")})
    save_store(corpus, store)
    print(f"사전: 신규 {added} · 갱신 {updated} → 총 {len(store['terms'])}개 ({STORE_REL})")
    print("본문 교정은 `apply --apply`.")


def cmd_list(a, corpus, store):
    rows = store["terms"]
    if a.kind:
        rows = [r for r in rows if r.get("kind") == a.kind]
    if a.status:
        rows = [r for r in rows if r.get("status") == a.status]
    by_status = Counter(r.get("status", "?") for r in store["terms"])
    print(f"용어 사전 {len(store['terms'])}개 — " +
          " · ".join(f"{k} {v}" for k, v in by_status.items()) +
          f" (updated {store.get('updated', '?')})")
    for r in sorted(rows, key=lambda x: (-len(x.get("misspellings") or []), x["term"])):
        miss = ", ".join(f"{m['form']}({m.get('status', '?')})"
                         for m in r.get("misspellings") or [])
        web = r.get("web") or {}
        print(f"  {r['term']:22s} [{r.get('kind', '')}/{r.get('status', '')}]"
              + (f"  ← {miss}" if miss else "")
              + (f"  · {r['desc'][:48]}" if r.get("desc") else "")
              + (f"  · 출처 {web.get('url', '')[:40]}" if web.get("url") else ""))


def cmd_forget(a, corpus, store):
    e = find_term(store, a.term)
    if not e:
        sys.exit(f"ERROR: '{a.term}' 는 사전에 없습니다.")
    print(f"삭제 대상: {e['term']} [{e.get('kind')}] "
          f"오타쌍 {len(e.get('misspellings') or [])}개")
    if not a.apply:
        print("(dry run) --apply 로 삭제합니다. 이미 적용된 본문 교정은 되돌리지 않습니다 "
              "(revert --batch 사용).")
        return
    store["terms"] = [x for x in store["terms"] if x is not e]
    save_store(corpus, store)
    print("삭제 완료.")


def main():
    ap = argparse.ArgumentParser(description="용어 사전 + STT 오타 교정")
    ap.add_argument("corpus")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("mine", help="전사에서 용어·오타 후보를 뽑는다")
    p.add_argument("--min-count", type=int, default=MIN_TERM_COUNT)
    p.add_argument("--since", default="")
    p.add_argument("--limit", type=int, default=40)
    p.add_argument("--json", default="")
    p.add_argument("--apply", action="store_true", help="'추론' 오타쌍을 사전에 학습")

    p = sub.add_parser("add", help="확인된 용어/오타쌍을 사전에 넣는다")
    p.add_argument("--term")
    p.add_argument("--kind", choices=KINDS, default="용어")
    p.add_argument("--desc", default="")
    p.add_argument("--alias", action="append")
    p.add_argument("--misspelling", action="append")
    p.add_argument("--status", choices=STATUS, default="확정")
    p.add_argument("--protect", action="store_true", help="이 용어는 절대 자동 교정 대상이 아님")
    p.add_argument("--file", help="여러 건을 한 번에: [{term,kind,desc,aliases,misspellings}]")

    p = sub.add_parser("list", help="사전 내용")
    p.add_argument("--kind", choices=KINDS)
    p.add_argument("--status", choices=STATUS)

    p = sub.add_parser("apply", help="사전으로 전사를 교정한다")
    p.add_argument("--path", default="", help="이 파일만 (기본: 코퍼스 전체)")
    p.add_argument("--since", default="")
    p.add_argument("--strict", action="store_true", help="status=확정 만 적용")
    p.add_argument("--apply", action="store_true")

    p = sub.add_parser("patch", help="읽고 판단한 편집쌍을 파일에 적용한다(토큰 절약 경로)")
    p.add_argument("--file", required=True, help='[{"from","to","kind","note"}]')
    p.add_argument("--path", default="")
    p.add_argument("--since", default="")
    p.add_argument("--apply", action="store_true")

    p = sub.add_parser("revert", help="배치 단위로 되돌린다")
    p.add_argument("--batch", required=True)
    p.add_argument("--apply", action="store_true")

    p = sub.add_parser("log", help="교정 기록")
    p.add_argument("--limit", type=int, default=10)

    p = sub.add_parser("forget", help="사전에서 용어 삭제")
    p.add_argument("--term", required=True)
    p.add_argument("--apply", action="store_true")

    a = ap.parse_args()
    corpus = os.path.abspath(a.corpus)
    if not os.path.isdir(corpus):
        sys.exit(f"ERROR: 코퍼스 경로가 없습니다 — {corpus}")
    store = load_store(corpus)
    {"mine": cmd_mine, "add": cmd_add, "list": cmd_list, "apply": cmd_apply,
     "patch": cmd_patch, "revert": cmd_revert, "log": cmd_log,
     "forget": cmd_forget}[a.cmd](a, corpus, store)


if __name__ == "__main__":
    main()
