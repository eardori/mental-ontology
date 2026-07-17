#!/usr/bin/env python3
"""Migrate objects.json from schema v1 to v2.

v1 -> v2 changes
  people[].type        person | org  (v1 mixed real people and counterpart orgs)
  models[].holders     who HOLDS the belief   (v1 'people' mixed holders & subjects)
  models[].about       whom/what the belief is ABOUT
  meetings[].source_id/path   provenance links into the corpus (matched via catalog)
  meta.schema_version = 2, meta.processed_source_ids

Classification: an entity is a PERSON iff it matches a _meta/speakers.json profile
(name or alias, including 'Latin(한글)' variants); everything else is an ORG.
Override with --person NAME / --org NAME (repeatable).

Usage:
  python3 migrate_objects.py <corpus_path>            # dry run — prints the plan
  python3 migrate_objects.py <corpus_path> --apply    # backup + write

Splitting rule: person-type entries in models[].people stay as holders; org-type
entries move to about. A model left with org-only holders keeps them as holders
but its evidence is capped at 'mid' (third-party inference). people[].models is
rebuilt so it only lists models the person actually holds.
"""
import os, sys, json, re, shutil, difflib, unicodedata

def norm(s):
    return re.sub(r'\s+', ' ', unicodedata.normalize("NFC", s.strip()))

def variants(name):
    out = {norm(name)}
    m = re.match(r'^(.+?)\s*\((.+?)\)$', name.strip())
    if m:
        out.add(norm(m.group(1)))
        out.add(norm(m.group(2)))
    return {v.lower() for v in out if v}

def slug(s):
    return re.sub(r'[^0-9a-z가-힣]', '', unicodedata.normalize("NFC", str(s)).lower())

def main():
    args = sys.argv[1:]
    apply_ = "--apply" in args
    force_person, force_org = set(), set()
    corpus = None
    it = iter(args)
    for a in it:
        if a == "--person":
            force_person.add(next(it))
        elif a == "--org":
            force_org.add(next(it))
        elif a != "--apply":
            corpus = a
    corpus = os.path.abspath(corpus or os.getcwd())
    op = os.path.join(corpus, "_ontology", "objects.json")
    d = json.load(open(op, encoding="utf-8"))
    if d.get("meta", {}).get("schema_version", 1) >= 2:
        print("already schema v2 — nothing to do.")
        return

    # --- person set from speakers.json ---
    person_keys = set()
    sp = os.path.join(corpus, "_meta", "speakers.json")
    if os.path.exists(sp):
        for e in json.load(open(sp, encoding="utf-8")):
            for a in {e.get("name", ""), *(e.get("aliases") or [])}:
                person_keys |= variants(a)
    else:
        print("WARN: no _meta/speakers.json — classify with --person/--org flags.")

    def is_person(name):
        if name in force_person:
            return True
        if name in force_org:
            return False
        return bool(variants(name) & person_keys)

    # --- classify people ---
    for p in d.get("people", []):
        p["type"] = "person" if is_person(p["name"]) else "org"
        if p["type"] == "org" and p.get("evidence") == "high":
            p["evidence"] = "mid"   # org profile = third-party inference, cap at mid
    persons = {p["name"] for p in d["people"] if p["type"] == "person"}
    orgs = {p["name"] for p in d["people"] if p["type"] == "org"}

    # canonicalize name variants against people[] (e.g. '제임스(정우진)' → 'James(정우진)')
    vmap = {}
    for n in persons | orgs:
        for v in variants(n):
            vmap.setdefault(v, set()).add(n)
    def canon(x):
        if x in persons or x in orgs:
            return x
        hits = set()
        for v in variants(x):
            hits |= vmap.get(v, set())
        return hits.pop() if len(hits) == 1 else x

    # --- holders/about come from BOTH v1 directions ---
    # v1 stored the linkage two ways: models[].people (spotty) AND people[].models
    # (the person/org's own model list). Union them, split person→holders / org→about.
    normalized = []
    link_h, link_a = {}, {}
    for m in d.get("models", []):
        for x in m.pop("people", []):
            cx = canon(x)
            if cx != x:
                normalized.append(f"{x} → {cx}")
            (link_h if cx in persons else link_a).setdefault(m["id"], set()).add(cx)
    for p in d["people"]:
        tgt = link_h if p["type"] == "person" else link_a
        for mid in p.get("models", []):
            tgt.setdefault(mid, set()).add(p["name"])
    capped = []
    for m in d["models"]:
        m["holders"] = sorted(link_h.get(m["id"], set()))
        m["about"] = sorted(set(m.get("about", [])) | link_a.get(m["id"], set()))
        if not m["holders"]:
            m["holders"] = m["about"]  # org-held (no person source): keep, cap evidence
            m["about"] = []
            if m.get("evidence") == "high":
                m["evidence"] = "mid"
                capped.append(m["id"])

    # --- rebuild people[].models = models they actually hold ---
    holds = {}
    for m in d["models"]:
        for h in m["holders"]:
            holds.setdefault(h, []).append(m["id"])
    for p in d["people"]:
        p["models"] = holds.get(p["name"], [])

    # --- meetings provenance from catalog (date + title similarity) ---
    matched = unmatched = 0
    cat_path = os.path.join(corpus, "_index", "catalog.json")
    if os.path.exists(cat_path):
        cat = json.load(open(cat_path, encoding="utf-8"))
        by_date = {}
        for r in cat:
            by_date.setdefault(str(r.get("date", "")), []).append(r)
        for mt in d.get("meetings", []):
            if mt.get("source_id"):
                matched += 1
                continue
            best, best_r = 0.0, None
            for r in by_date.get(str(mt.get("date", "")), []):
                score = difflib.SequenceMatcher(None, slug(mt.get("title", "")),
                                                slug(r.get("title", ""))).ratio()
                if score > best:
                    best, best_r = score, r
            if best_r and best >= 0.55:
                mt["source_id"], mt["path"] = best_r["source_id"], best_r["path"]
                matched += 1
            else:
                unmatched += 1

    d["meta"]["schema_version"] = 2
    d["meta"]["processed_source_ids"] = sorted(
        {mt["source_id"] for mt in d.get("meetings", []) if mt.get("source_id")})

    # --- report ---
    print(f"people: {len(persons)} person / {len(orgs)} org")
    for p in d["people"]:
        print(f"  [{p['type']:6}] {p['name']}  ({p.get('role','')[:40]})")
    n_about = sum(1 for m in d['models'] if m['about'])
    print(f"models: {len(d['models'])} — {n_about} gained about[], "
          f"{len(capped)} org-held capped high→mid {capped}")
    if normalized:
        print(f"name variants canonicalized: {sorted(set(normalized))}")
    print(f"meetings: {matched} matched to corpus provenance, {unmatched} unmatched")

    if not apply_:
        print("\nDRY RUN — rerun with --apply to write "
              "(use --person/--org NAME to fix any misclassification above).")
        return
    bak = os.path.join(corpus, "_ontology", "objects_v1_backup.json")
    n = 2
    while os.path.exists(bak):
        bak = os.path.join(corpus, "_ontology", f"objects_v1_backup-{n}.json")
        n += 1
    shutil.copy2(op, bak)
    json.dump(d, open(op, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\nOK: migrated to schema v2. Backup: {os.path.relpath(bak, corpus)}")
    print("Next: python3 build_db.py && python3 validate.py")

if __name__ == "__main__":
    main()
