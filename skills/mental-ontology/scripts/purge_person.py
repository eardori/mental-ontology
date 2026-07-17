#!/usr/bin/env python3
"""Purge a person from the corpus — right-to-be-forgotten support.

Usage:
  python3 purge_person.py <corpus> --name "<이름>"            # dry run — shows the plan
  python3 purge_person.py <corpus> --name "<이름>" --apply    # backup + purge

What it does (anonymize mode — the default and only mode):
  transcripts/   speaker labels AND body mentions of the name/aliases → "[삭제된 인물]"
  _meta/speakers.json   registry entry removed
  _ontology/objects.json  people[] entry removed; models held ONLY by them removed,
                shared models lose them as holder; about/relations/network entries
                involving them removed; evolution/timeline text left (name replaced)
  people/<이름>.md  dossier deleted
Everything touched is first copied to _ontology/_work/purge-backup-<이름>/ preserving
relative paths, so the purge is reversible until you delete that folder.

Honest limitations (printed in the dry run):
  - aliases shorter than 2 chars (한글) / 3 chars (latin) are only replaced inside
    speaker labels, not free text — replacing "원" everywhere would destroy prose.
  - STT misspellings of the name that are not registered as aliases are NOT found.
  - the DB is rebuilt data — rerun build_index/build_db/build_dossiers afterwards.
"""
import glob, json, os, re, shutil, sys, unicodedata

MASK = "[삭제된 인물]"

def norm(s):
    return unicodedata.normalize("NFC", (s or "").strip())

def variants(name):
    out = {norm(name)}
    m = re.match(r'^(.+?)\s*\((.+?)\)$', name.strip())
    if m:
        out |= {norm(m.group(1)), norm(m.group(2))}
    return {v for v in out if v}

def body_safe(tok):
    return len(tok) >= (3 if re.match(r'^[A-Za-z .]+$', tok) else 2)

def main():
    apply_ = "--apply" in sys.argv
    corpus = os.path.abspath(sys.argv[1])
    name = norm(sys.argv[sys.argv.index("--name") + 1])
    reg_path = f"{corpus}/_meta/speakers.json"
    registry = json.load(open(reg_path, encoding="utf-8")) if os.path.exists(reg_path) else []
    entry = next((e for e in registry if norm(e.get("name", "")) == name), None)
    toks = variants(name) | {norm(a) for e in ([entry] if entry else [])
                             for a in e.get("aliases", [])}
    toks = {t for t in toks if t}
    body_toks = sorted({t for t in toks if body_safe(t)}, key=len, reverse=True)
    label_only = sorted(toks - set(body_toks))
    print(f"purging '{name}' — tokens: {sorted(toks)}")
    if label_only:
        print(f"  (short tokens replaced only in speaker labels, not body text: {label_only})")

    bak_root = f"{corpus}/_ontology/_work/purge-backup-{name.replace('/', '-')}"
    changes = []

    def backup(path):
        rel = os.path.relpath(path, corpus)
        dst = os.path.join(bak_root, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(path, dst)

    # 1) transcripts
    label_re = [(re.compile(rf'(\*\*\[?){re.escape(t)}(\]?\s*\()'), rf'\g<1>{MASK}\g<2>')
                for t in sorted(toks, key=len, reverse=True)]
    for p in sorted(glob.glob(f"{corpus}/transcripts/**/*.md", recursive=True)):
        t = unicodedata.normalize("NFC", open(p, encoding="utf-8").read())
        orig = t
        for rx, rep in label_re:
            t = rx.sub(rep, t)
        for tok in body_toks:
            t = t.replace(tok, MASK)
        if t != orig:
            n_hits = orig.count(name) + sum(orig.count(b) for b in body_toks if b != name)
            changes.append((os.path.relpath(p, corpus), f"~{max(n_hits, 1)} mentions"))
            if apply_:
                backup(p)
                open(p, "w", encoding="utf-8").write(t)

    # 2) registry
    if entry:
        changes.append(("_meta/speakers.json", "registry entry removed"))
        if apply_:
            backup(reg_path)
            json.dump([e for e in registry if norm(e.get("name", "")) != name],
                      open(reg_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    # 3) ontology
    opath = f"{corpus}/_ontology/objects.json"
    if os.path.exists(opath):
        d = json.load(open(opath, encoding="utf-8"))
        stats = {"people": 0, "models_removed": 0, "models_unheld": 0,
                 "relations": 0, "network": 0, "about": 0}
        before = len(d["people"])
        d["people"] = [p for p in d["people"] if norm(p.get("name", "")) != name]
        stats["people"] = before - len(d["people"])
        keep = []
        for m in d.get("models", []):
            holders = [h for h in m.get("holders", []) if norm(h) != name]
            if not holders and m.get("holders"):
                stats["models_removed"] += 1
                continue
            if len(holders) != len(m.get("holders", [])):
                stats["models_unheld"] += 1
            m["holders"] = holders
            if m.get("about"):
                a2 = [a for a in m["about"] if norm(a) != name]
                stats["about"] += len(m["about"]) - len(a2)
                m["about"] = a2
            keep.append(m)
        d["models"] = keep
        ids = {m["id"] for m in keep}
        for p in d["people"]:
            p["models"] = [x for x in p.get("models", []) if x in ids]
        n0 = len(d.get("relations", []))
        d["relations"] = [r for r in d.get("relations", [])
                          if name not in (norm(r.get("from", "")), norm(r.get("to", "")))]
        stats["relations"] = n0 - len(d["relations"])
        n0 = len(d.get("network", []))
        d["network"] = [x for x in d.get("network", [])
                        if name not in (norm(x.get("a", "")), norm(x.get("b", "")))]
        stats["network"] = n0 - len(d["network"])
        changes.append(("_ontology/objects.json", json.dumps(stats, ensure_ascii=False)))
        if apply_:
            backup(opath)
            json.dump(d, open(opath, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    # 4) dossier
    dp = f"{corpus}/people/{name.replace('/', '-')}.md"
    if os.path.exists(dp):
        changes.append((f"people/{os.path.basename(dp)}", "dossier deleted"))
        if apply_:
            backup(dp)
            os.remove(dp)

    print(f"\n{'APPLIED' if apply_ else 'DRY RUN'} — {len(changes)} files affected:")
    for rel, what in changes[:30]:
        print(f"  {rel}: {what}")
    if len(changes) > 30:
        print(f"  … and {len(changes) - 30} more")
    if apply_:
        print(f"\nBackup: {os.path.relpath(bak_root, corpus)}  (delete it to make the purge final)")
        print("Next: build_index.py → build_db.py → build_dossiers.py (rebuild derived data)")
    else:
        print("\nRerun with --apply to execute.")

if __name__ == "__main__":
    main()
