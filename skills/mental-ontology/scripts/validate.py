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
import os, sys, json, sqlite3

EV = {"high", "mid", "low"}
REL = {"agree", "tension", "builds-on"}

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
    mtg_ids = {m.get("id") for m in d.get("meetings", [])}
    for t in d.get("timeline", []):
        if t.get("meeting") and t["meeting"] not in mtg_ids:
            warns.append(f"timeline[{t.get('date')}]: meeting '{t['meeting']}' not in meetings[]")

    # --- honesty ---
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
            total = c.execute("SELECT COUNT(*) FROM utterances").fetchone()[0]
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
