#!/usr/bin/env python3
"""Validate the ontology (objects.json) + database against the spec.

Usage: python3 validate.py <corpus_path>
Exit code: 0 = clean (warnings allowed), 1 = errors found.

Checks
  structure   required fields, enum values, unique model ids
  integrity   holders/about/relations reference people[]; people[].models
              reference models[].id AND the person is one of that model's holders
  readings    (대화 의도) basis signals present & from the closed set, confidence never
              높음, status/resolution consistent, quotes grounded, hit rate reported
  honesty     models held only by org-type entities may not be evidence=high
              (a third party's inference about an org is 'mid' at best);
              evidence=high without a quote is flagged
  provenance  meetings[] carry source_id + path that exist in the corpus
  coverage    (if ontology.db exists) speaker attribution %, persons with zero
              matched utterances, meetings invisible to full-text search

Run after every Stage 6/7. No external dependencies (python3 stdlib only).
"""
import os, re, sys, json, sqlite3, difflib
from datetime import date, timedelta

EV = {"high", "mid", "low"}
REL = {"agree", "tension", "builds-on"}
BASIS = {"반복", "무응답", "화제전환", "선제언급", "마무리발언", "양보조건", "되묻기", "호칭변화"}
READ_STATUS = {"추정", "확인됨", "빗나감"}
READ_CONF = {"낮음", "보통"}          # 높음 is never allowed — a reading is an inference
OPEN_READING_DAYS = 90                # 추정 older than this vs the newest meeting → nag
STALE_DAYS = 180  # last_seen older than this (vs newest meeting) → belief may have changed

def _norm_text(s):
    return re.sub(r'[\s.,!?\'"“”‘’…()\[\]]+', '', s)

def _frag_score(frag, cand):
    """how much of `frag` appears contiguously inside `cand` (0..1)"""
    if not frag:
        return 1.0
    m = difflib.SequenceMatcher(None, frag, cand).find_longest_match(0, len(frag), 0, len(cand))
    return m.size / len(frag)

def verify_quotes(c, models, fts_on):
    """Ground every model quote in the actual utterances (STT-tolerant).
    Returns (checked, misses:[(model_id, best_score)])."""
    checked, misses = 0, []
    for m in models:
        quote = (m.get("quote") or "").strip()
        if not quote:
            continue
        checked += 1
        frags = [f.strip() for f in re.split(r'\.{2,}|…', quote) if len(f.strip()) >= 6] or [quote]
        # rank candidate-search tokens by SELECTIVITY — common tokens flood the
        # candidate cap and hide the true match (recall bug)
        toks = sorted(set(re.findall(r'[가-힣A-Za-z0-9]{2,}', quote)), key=len, reverse=True)[:6]
        scored = []
        for t in toks:
            try:
                if fts_on:
                    n = c.execute("SELECT COUNT(*) FROM utterances_fts WHERE utterances_fts "
                                  "MATCH ?", (f'"{t}"',)).fetchone()[0]
                else:
                    n = c.execute("SELECT COUNT(*) FROM utterances WHERE text LIKE ?",
                                  (f"%{t}%",)).fetchone()[0]
            except sqlite3.OperationalError:
                continue
            if n:
                scored.append((n, t))
        scored.sort()
        cands = []
        for _n, t in scored[:2]:  # two most selective tokens
            try:
                if fts_on:
                    cands += [r[0] for r in c.execute(
                        "SELECT text FROM utterances_fts WHERE utterances_fts MATCH ? LIMIT 400",
                        (f'"{t}"',))]
                else:
                    cands += [r[0] for r in c.execute(
                        "SELECT text FROM utterances WHERE text LIKE ? LIMIT 400", (f"%{t}%",))]
            except sqlite3.OperationalError:
                pass
        best = 0.0
        nfrags = [_norm_text(f) for f in frags]
        for cand in cands:
            nc = _norm_text(cand)
            score = min(_frag_score(nf, nc) for nf in nfrags)
            best = max(best, score)
            if best >= 0.55:
                break
        if best < 0.55:
            misses.append((m.get("id"), round(best, 2)))
    return checked, misses

def stale_models(models, newest):
    """models whose last evidence predates the newest meeting by STALE_DAYS+"""
    try:
        ref = date.fromisoformat(str(newest)[:10])
    except (ValueError, TypeError):
        return []
    out = []
    for m in models:
        d = str(m.get("last_seen") or m.get("first_seen") or "")[:10]
        try:
            if ref - date.fromisoformat(d) > timedelta(days=STALE_DAYS):
                out.append((m.get("id"), d))
        except ValueError:
            continue
    return out

def main():
    corpus = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.getcwd()
    op = os.path.join(corpus, "_ontology", "objects.json")
    errors, warns, infos = [], [], []
    if not os.path.exists(op):
        print(f"ERROR: {op} not found — run Stage 6 first.")
        sys.exit(1)
    d = json.load(open(op, encoding="utf-8"))
    ver = d.get("meta", {}).get("schema_version", 1)
    if ver < 2:
        warns.append("objects.json is schema v1 (no holders/about, no entity types) — "
                     "run scripts/migrate_objects.py to upgrade.")

    people = d.get("people", [])
    models = d.get("models", [])
    names = {p.get("name") for p in people}
    types = {p.get("name"): (p.get("type") or "person") for p in people}
    mids = set()

    # --- structure ---
    for k in ("meta", "people", "models"):
        if k not in d:
            errors.append(f"missing top-level key: {k}")
    for p in people:
        n = p.get("name") or "<unnamed>"
        if not p.get("name"):
            errors.append("people[]: entry without name")
        if not p.get("summary"):
            warns.append(f"people[{n}]: no summary")
        if p.get("evidence") not in EV:
            errors.append(f"people[{n}]: evidence must be one of {sorted(EV)}")
        if ver >= 2 and p.get("type") not in ("person", "org"):
            errors.append(f"people[{n}]: type must be 'person' or 'org' (schema v2)")
    for m in models:
        i = m.get("id") or "<no-id>"
        if not m.get("id"):
            errors.append("models[]: entry without id")
        elif m["id"] in mids:
            errors.append(f"models[{i}]: duplicate id")
        mids.add(m.get("id"))
        for k in ("category", "title"):
            if not m.get(k):
                errors.append(f"models[{i}]: missing {k}")
        if m.get("evidence") not in EV:
            errors.append(f"models[{i}]: evidence must be one of {sorted(EV)}")
        if ver >= 2 and "holders" not in m:
            errors.append(f"models[{i}]: schema v2 requires holders[] (who holds the belief)")
        # v3 checks
        et = m.get("evidence_type")
        if et is not None and et not in ("direct", "hearsay", "reference"):
            errors.append(f"models[{i}]: evidence_type must be direct/hearsay/reference")
        if et == "hearsay" and m.get("evidence") == "high":
            warns.append(f"models[{i}]: hearsay evidence_type should cap evidence at mid")
        if et == "reference" and m.get("evidence") in ("high", "mid"):
            warns.append(f"models[{i}]: reference evidence_type should cap evidence at low")
        tr = m.get("trap")
        if tr is not None and not (isinstance(tr, dict) and tr.get("desc")):
            errors.append(f"models[{i}]: trap must be an object with desc")
    names = {p.get("name") for p in people}
    for x in d.get("conflict_axes", []) or []:
        for side in ("a", "b"):
            if x.get(side) and x[side] not in names:
                warns.append(f"conflict_axes: unknown person '{x.get(side)}'")
        if not x.get("axis"):
            errors.append("conflict_axes: entry without axis")
    for t in d.get("traps", []) or []:
        if not t.get("who") or not t.get("desc"):
            errors.append("traps: entry needs who + desc")
        elif t["who"] not in names:
            warns.append(f"traps: unknown person '{t.get('who')}'")
        if t.get("model_id") and t["model_id"] not in mids:
            errors.append(f"traps: model_id '{t['model_id']}' not in models[]")

    # --- integrity ---
    for m in models:
        i = m.get("id") or "<no-id>"
        holders = m.get("holders", m.get("people", []))
        if not holders:
            errors.append(f"models[{i}]: no holders — every belief needs someone who holds it")
        for h in holders:
            if h not in names:
                errors.append(f"models[{i}]: holder '{h}' not in people[]")
        for a in m.get("about", []):
            if a not in names:
                warns.append(f"models[{i}]: about '{a}' not in people[] — add the entity or drop it")
        for r in m.get("related", []):
            if r not in mids:
                errors.append(f"models[{i}]: related id '{r}' does not exist")
    for p in people:
        n = p.get("name")
        for mid in p.get("models", []):
            if mid not in mids:
                errors.append(f"people[{n}]: model id '{mid}' does not exist")
            else:
                mm = next(m for m in models if m.get("id") == mid)
                if n not in mm.get("holders", mm.get("people", [])):
                    errors.append(f"people[{n}]: lists model '{mid}' but is not one of its holders")
    for r in d.get("relations", []):
        for end in ("from", "to"):
            if r.get(end) not in names:
                errors.append(f"relations[]: {end} '{r.get(end)}' not in people[]")
        if r.get("type") not in REL:
            errors.append(f"relations[{r.get('from')}→{r.get('to')}]: type must be one of {sorted(REL)}")
    reg_names, registry = set(), []
    reg_path = os.path.join(corpus, "_meta", "speakers.json")
    if os.path.exists(reg_path):
        registry = json.load(open(reg_path, encoding="utf-8"))
        reg_names = {e.get("name") for e in registry}
    for e in registry:
        mgr = (e.get("manager") or "").strip()
        if mgr and mgr not in reg_names:
            warns.append(f"registry[{e.get('name')}]: manager '{mgr}' not in the registry — "
                         "조직도 edge will dangle (add them or fix the name)")
    for n in d.get("network", []):
        if not n.get("kind"):
            errors.append(f"network[{n.get('a')}↔{n.get('b')}]: kind is required")
        for end in ("a", "b"):
            v = n.get(end)
            if not v:
                errors.append(f"network[]: missing '{end}'")
            elif v not in names and v not in reg_names:
                warns.append(f"network[]: '{v}' not in people[] or the registry (speakers.json)")
    mtg_ids = {m.get("id") for m in d.get("meetings", [])}
    for t in d.get("timeline", []):
        if t.get("meeting") and t["meeting"] not in mtg_ids:
            warns.append(f"timeline[{t.get('date')}]: meeting '{t['meeting']}' not in meetings[]")

    # --- honesty ---
    for p in people:
        if (p.get("type") == "org") and p.get("evidence") == "high":
            errors.append(f"people[{p.get('name')}]: org-type entity with evidence=high — "
                          "an org profile is third-party inference, capped at 'mid'")
    for m in models:
        i = m.get("id")
        holders = m.get("holders", m.get("people", []))
        if holders and all(types.get(h) == "org" for h in holders):
            if m.get("evidence") == "high":
                errors.append(f"models[{i}]: held only by org-type entities but evidence=high — "
                              "third-party inference about an org is capped at 'mid'")
        if m.get("evidence") == "high" and not m.get("quote"):
            warns.append(f"models[{i}]: evidence=high but no supporting quote")

    # --- readings (대화 의도) ---
    readings = d.get("readings", [])
    meet_ids = {m.get("id") for m in d.get("meetings", [])}
    rids, open_reads, hits, misses = set(), [], 0, 0
    for r in readings:
        rid = r.get("id") or "<no-id>"
        if not r.get("id"):
            errors.append("readings[]: entry without id")
        elif rid in rids:
            errors.append(f"readings[{rid}]: duplicate id")
        rids.add(rid)
        who = r.get("who")
        if not who:
            errors.append(f"readings[{rid}]: no 'who'")
        elif who not in names and who not in reg_names:
            errors.append(f"readings[{rid}]: who '{who}' is neither in people[] nor the registry")
        if meet_ids and r.get("meeting") and r["meeting"] not in meet_ids:
            errors.append(f"readings[{rid}]: meeting '{r['meeting']}' not in meetings[]")
        if not r.get("surface") or not r.get("reading"):
            errors.append(f"readings[{rid}]: both 'surface' (said) and 'reading' (inferred) "
                          "are required — a reading must never be shown without what was said")
        basis = r.get("basis") or []
        if not basis:
            errors.append(f"readings[{rid}]: no basis — a reading without a textual signal "
                          "is mind-reading, not extraction")
        for b in basis:
            if b.get("kind") not in BASIS:
                errors.append(f"readings[{rid}]: basis kind '{b.get('kind')}' not in {sorted(BASIS)}")
            if not b.get("detail"):
                warns.append(f"readings[{rid}]: basis '{b.get('kind')}' without detail "
                             "(count / the unanswered question / the topic switched away from)")
        if r.get("confidence") not in READ_CONF:
            errors.append(f"readings[{rid}]: confidence must be one of {sorted(READ_CONF)} "
                          "— an intent reading is never '높음'")
        st = r.get("status", "추정")
        if st not in READ_STATUS:
            errors.append(f"readings[{rid}]: status must be one of {sorted(READ_STATUS)}")
        if st == "추정":
            open_reads.append(r)
        else:
            hits += st == "확인됨"
            misses += st == "빗나감"
            res = r.get("resolution") or {}
            if not (res.get("meeting") or res.get("date")):
                errors.append(f"readings[{rid}]: status '{st}' without a resolution "
                              "(which later meeting settled it)")
            elif res.get("meeting") and meet_ids and res["meeting"] not in meet_ids:
                errors.append(f"readings[{rid}]: resolution.meeting '{res['meeting']}' not in meetings[]")
        for mid in r.get("related_models", []):
            if mid not in mids:
                warns.append(f"readings[{rid}]: related_models '{mid}' is not a known model id")
    if readings:
        rate = f"{100.0 * hits / (hits + misses):.0f}%" if hits + misses else "미측정"
        infos.append(f"readings: {len(readings)}건 · 미확인 {len(open_reads)} · "
                     f"확인 {hits} / 빗나감 {misses} — 적중률 {rate}")
        if hits + misses >= 5 and hits < misses:
            warns.append(f"readings: 적중률 {rate} — 의도 추정이 절반 이상 빗나갔습니다. "
                         "브리핑에서 비중을 줄이고 basis 규칙을 다시 보세요 "
                         "(맞히는 척하는 것보다 모른다고 하는 게 낫습니다).")
        newest_meeting = max((m.get("date", "") for m in d.get("meetings", [])), default="")
        if newest_meeting and open_reads:
            def age(r):
                try:
                    return (date.fromisoformat(newest_meeting[:10])
                            - date.fromisoformat(str(r.get("date", ""))[:10])).days
                except (ValueError, TypeError):
                    return 0
            stale_open = [r for r in open_reads if age(r) > OPEN_READING_DAYS]
            if stale_open:
                warns.append(f"readings: {len(stale_open)} open 추정 older than "
                             f"{OPEN_READING_DAYS} days never got resolved "
                             f"(e.g. {stale_open[0].get('id')}) — 확인하거나 지우세요")

    # --- provenance ---
    cat_ids = set()
    cat_path = os.path.join(corpus, "_index", "catalog.json")
    if os.path.exists(cat_path):
        cat_ids = {r.get("source_id") for r in json.load(open(cat_path, encoding="utf-8"))}
    no_prov = 0
    for m in d.get("meetings", []):
        sid, path = m.get("source_id"), m.get("path")
        if not sid or not path:
            no_prov += 1
            continue
        if path and not os.path.exists(os.path.join(corpus, path)):
            warns.append(f"meetings[{m.get('id')}]: path '{path}' not found in corpus")
        if cat_ids and sid not in cat_ids:
            warns.append(f"meetings[{m.get('id')}]: source_id not in _index/catalog.json")
    if no_prov:
        warns.append(f"{no_prov}/{len(d.get('meetings', []))} meetings[] lack source_id/path provenance "
                     "(legacy entries; new Stage 6 runs must record both)")
    psi = d.get("meta", {}).get("processed_source_ids")
    if psi is not None and cat_ids:
        infos.append(f"provenance: {len(set(psi) & cat_ids)}/{len(cat_ids)} corpus transcripts "
                     "recorded as processed into the ontology")

    # --- DB coverage ---
    dbp = os.path.join(corpus, "_ontology", "ontology.db")
    if os.path.exists(dbp):
        if os.path.getmtime(dbp) < os.path.getmtime(op):
            warns.append("ontology.db is OLDER than objects.json — rerun build_db.py (Stage 7)")
        db = sqlite3.connect(dbp)
        c = db.cursor()
        try:
            fts_on = (c.execute("SELECT value FROM meta WHERE key='fts5'").fetchone()
                      or ["no"])[0] == "yes"
            total = c.execute("SELECT COUNT(*) FROM utterances").fetchone()[0]
            if total:
                # basis quotes are graded exactly like model quotes — an intent reading
                # resting on an ungrounded quote is the worst failure mode this tool has
                quoted_basis = [{"id": f"{r.get('id')}/{b.get('kind')}", "quote": b.get("quote")}
                                for r in d.get("readings", [])
                                for b in (r.get("basis") or []) if b.get("quote")]
                checked, missq = verify_quotes(c, models + quoted_basis, fts_on)
                if missq:
                    warns.append(f"{len(missq)}/{checked} model quotes NOT grounded in any "
                                 f"utterance (환각이거나 원문 유실 — 재확인 필요): "
                                 + ", ".join(f"{i}({s})" for i, s in missq[:8])
                                 + (" …" if len(missq) > 8 else ""))
                else:
                    infos.append(f"quotes: {checked}/{checked} grounded in utterances")
                newest = c.execute("SELECT MAX(date) FROM meetings").fetchone()[0]
                st = stale_models(models, newest)
                if st:
                    warns.append(f"{len(st)} models STALE (last evidence {STALE_DAYS}+ days "
                                 f"before newest meeting {newest}) — answer in past tense "
                                 "('당시에는') until re-confirmed: "
                                 + ", ".join(f"{i}({d})" for i, d in st[:8])
                                 + (" …" if len(st) > 8 else ""))
            if total:
                canon = c.execute("""SELECT COUNT(*) FROM utterances
                    WHERE speaker IN (SELECT DISTINCT canonical FROM person_aliases)""").fetchone()[0]
                infos.append(f"coverage: {100.0*canon/total:.1f}% of {total} utterances attributed "
                             "to a canonical person")
                zero_p = [r[0] for r in c.execute("""SELECT p.name FROM people p
                    WHERE (p.type='person' OR p.type IS NULL OR p.type='')
                    AND NOT EXISTS (SELECT 1 FROM utterances u WHERE u.speaker = p.name)""")]
                if zero_p:
                    warns.append(f"persons with ZERO matched utterances (alias gap? check "
                                 f"_meta/speakers.json): {', '.join(zero_p)}")
                zero_m = c.execute("""SELECT COUNT(*) FROM meetings m WHERE NOT EXISTS
                    (SELECT 1 FROM utterances u WHERE u.meeting_rowid = m.rowid)""").fetchone()[0]
                if zero_m:
                    warns.append(f"{zero_m} meetings have zero utterances in the DB "
                                 "(invisible to full-text search — check build_db WARNs)")
        except sqlite3.OperationalError as ex:
            warns.append(f"DB coverage checks skipped (old DB layout? rebuild): {ex}")
    else:
        infos.append("ontology.db not found — run build_db.py (Stage 7) for query mode")

    # --- lexicon (용어 사전) + web enrichment ---
    # The dictionary rewrites transcripts, so its failure mode is destroying real content:
    # a "misspelling" that is actually another term, or a person's name. Those are ERRORs.
    lex_path = os.path.join(corpus, "_meta", "lexicon.json")
    reg_names = set()
    reg = {}
    rp = os.path.join(corpus, "_meta", "speakers.json")
    if os.path.exists(rp):
        try:
            for e in json.load(open(rp, encoding="utf-8")):
                nm = (e.get("name") or "").strip()
                if nm:
                    reg[nm] = e
                    reg_names |= {nm, *(a.strip() for a in e.get("aliases") or [])}
                    mm = re.match(r'^(.+?)\s*\((.+?)\)$', nm)
                    if mm:
                        reg_names |= {mm.group(1).strip(), mm.group(2).strip()}
        except Exception as ex:
            warns.append(f"_meta/speakers.json unreadable for lexicon checks: {ex}")
    if os.path.exists(lex_path):
        try:
            lex = json.load(open(lex_path, encoding="utf-8"))
        except Exception as ex:
            errors.append(f"_meta/lexicon.json does not parse: {ex}")
            lex = {"terms": []}
        terms = lex.get("terms", [])
        canon = {}
        for e in terms:
            for k in [e.get("term", "")] + list(e.get("aliases") or []):
                if k:
                    canon[k.strip()] = e.get("term", "")
        n_auto = 0
        dupes = {t for t in (x.get("term") for x in terms)
                 if t and sum(1 for y in terms if y.get("term") == t) > 1}
        if dupes:
            errors.append(f"lexicon: duplicate terms (one entry wins in the DB): "
                          + ", ".join(sorted(dupes)))
        for e in terms:
            t = (e.get("term") or "").strip()
            if not t:
                errors.append("lexicon: an entry has no `term`")
                continue
            if e.get("status") not in (None, "", "확정", "추론", "후보"):
                errors.append(f"lexicon[{t}]: status '{e.get('status')}' not in 확정/추론/후보")
            for m in e.get("misspellings") or []:
                form = (m.get("form") or "").strip()
                st = m.get("status", "후보")
                if st in ("확정", "추론"):
                    n_auto += 1
                if not form:
                    errors.append(f"lexicon[{t}]: a misspelling entry has no `form`")
                elif form == t:
                    errors.append(f"lexicon[{t}]: '{form}' is the term itself")
                elif form in canon and canon[form] != t:
                    errors.append(f"lexicon[{t}]: '{form}' is ALSO the term/alias "
                                  f"'{canon[form]}' — correcting it would destroy real text")
                elif form in reg_names and st in ("확정", "추론"):
                    errors.append(f"lexicon[{t}]: '{form}' is a registered person "
                                  "— fix names with speakers.json aliases, not by rewriting")
        infos.append(f"lexicon: {len(terms)} terms, {n_auto} auto-appliable misspelling pairs")
        log_path = os.path.join(corpus, "_meta", "lexicon-corrections.jsonl")
        if os.path.exists(log_path):
            batches = set()
            for line in open(log_path, encoding="utf-8"):
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                if r.get("cmd") in ("apply", "patch"):
                    batches.add(r.get("batch"))
            missing = [b for b in batches if not os.path.isdir(
                os.path.join(corpus, "_ontology", "_work", f"lexicon-backup-{b}"))]
            infos.append(f"corrections: {len(batches)} batches logged"
                         + (f", {len(missing)} without a backup (not revertable)" if missing else ""))
    enr_path = os.path.join(corpus, "_meta", "enrichment.json")
    if os.path.exists(enr_path):
        try:
            enr = json.load(open(enr_path, encoding="utf-8"))
        except Exception as ex:
            errors.append(f"_meta/enrichment.json does not parse: {ex}")
            enr = {"entities": {}}
        n_fact = 0
        for name, e in (enr.get("entities") or {}).items():
            facts = e.get("facts") or []
            n_fact += len(facts)
            for f in facts:
                if not (f.get("url") or "").strip():
                    errors.append(f"enrichment[{name}]: a fact has no source URL "
                                  "(a web claim without a URL is indistinguishable from a guess)")
            if e.get("status") == "확인됨" and not facts:
                warns.append(f"enrichment[{name}]: status 확인됨 but no facts with URLs")
            if e.get("kind") == "인물":
                r = reg.get(name, {})
                if r.get("public") is not True and (r.get("relationship") or "") in \
                        {"팀원", "가족", "지인", "친구", "동료"}:
                    warns.append(f"enrichment[{name}]: 사적 관계"
                                 f"({r.get('relationship')})인 사람이 웹 검색 캐시에 있습니다 "
                                 "— 의도한 것이 아니면 `enrich.py forget --entity` 로 지우세요")
        infos.append(f"web enrichment: {len(enr.get('entities') or {})} entities, "
                     f"{n_fact} sourced facts (외부 출처 — 근거 등급을 올리지 않음)")

    # --- report ---
    for e in errors:
        print(f"ERROR: {e}")
    for w in warns:
        print(f"WARN:  {w}")
    for i in infos:
        print(f"info:  {i}")
    print(f"\n{'FAIL' if errors else 'PASS'}: {len(errors)} errors, {len(warns)} warnings "
          f"({len(people)} people, {len(models)} models, schema v{ver})")
    sys.exit(1 if errors else 0)

if __name__ == "__main__":
    main()
