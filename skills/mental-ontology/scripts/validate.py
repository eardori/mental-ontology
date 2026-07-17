#!/usr/bin/env python3
"""Validate the ontology (objects.json) + database against the spec.

Usage: python3 validate.py <corpus_path>
Exit code: 0 = clean (warnings allowed), 1 = errors found.

Checks
  structure   required fields, enum values, unique model ids
  integrity   holders/about/relations reference people[]; people[].models
              reference models[].id AND the person is one of that model's holders
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
                checked, missq = verify_quotes(c, models, fts_on)
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
