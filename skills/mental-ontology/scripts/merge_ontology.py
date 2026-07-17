#!/usr/bin/env python3
"""Batch re-extraction step 4: merge synthesis outputs + pools into objects.json.

Usage: python3 merge_ontology.py <corpus> <workdir> [--apply]

Reads   <corpus>/_ontology/objects.json    (base — models assigned to tasks are replaced)
        <workdir>/synth_keys.json + synth-<key>.json + synth-task-<key>.json
        <workdir>/pool_tensions.json / pool_network.json / pool_timeline.json
        <workdir>/batches.json             (optional — marks source_ids as processed)
Writes  <corpus>/_ontology/objects.json    (--apply; numbered backup kept)

Guarantees: stable ids (collisions renamed + reported), every model keeps ≥1
holder, people[].models rebuilt from holders, entity names normalized against
people[] + registry variants, self-org network edges dropped, dedup on all
pools, timeline capped at 2 entries/month. Dry-run prints the full plan.
Run validate.py + build_db.py afterwards.
"""
import json, os, re, shutil, sys, unicodedata
from collections import defaultdict

def norm(s):
    return unicodedata.normalize("NFC", (s or "").strip())

def variants(name):
    out = {norm(name)}
    m = re.match(r'^(.+?)\s*\((.+?)\)$', name.strip())
    if m:
        out |= {norm(m.group(1)), norm(m.group(2))}
    return {v.lower() for v in out if v}

def main():
    apply_ = "--apply" in sys.argv
    argv = [a for a in sys.argv[1:] if not a.startswith("--")]
    corpus, work = os.path.abspath(argv[0]), os.path.abspath(argv[1])
    op = f"{corpus}/_ontology/objects.json"
    base = json.load(open(op, encoding="utf-8"))
    keys = json.load(open(f"{work}/synth_keys.json", encoding="utf-8"))

    # canonical name map from people[] + registry (for about/network normalization)
    vmap = {}
    entries = list(base.get("people", []))
    reg = f"{corpus}/_meta/speakers.json"
    if os.path.exists(reg):
        entries += json.load(open(reg, encoding="utf-8"))
    for p in entries:
        name = p.get("name")
        if name:
            for v in variants(name):
                vmap.setdefault(v, name)
    self_names = variants(base.get("meta", {}).get("org", "")) if base.get("meta", {}).get("org") else set()

    def cname(x):
        n = norm(x)
        hit = vmap.get(n.lower())
        if hit:
            return hit
        hits = {vmap[v] for v in variants(n) if v in vmap}
        return hits.pop() if len(hits) == 1 else n

    # replace task-assigned models with synthesis outputs; carry the rest
    assigned = set()
    for k in keys:
        t = json.load(open(f"{work}/synth-task-{k}.json", encoding="utf-8"))
        assigned |= {m["id"] for m in t["existing_models"]}
    new_models, evolution, missing, seen = [], [], [], {}
    synth_outputs = []
    for k in keys:
        p = f"{work}/synth-{k}.json"
        if not os.path.exists(p):
            missing.append(k)
            t = json.load(open(f"{work}/synth-task-{k}.json", encoding="utf-8"))
            assigned -= {m["id"] for m in t["existing_models"]}  # carry them over
            continue
        synth_outputs.append((k, json.load(open(p, encoding="utf-8"))))
    # ids that will carry over unchanged also participate in collision detection —
    # a synthesis agent inventing an id that another person already owns must not
    # silently replace that model
    carry_ids = {m["id"] for m in base["models"] if m["id"] not in assigned}
    for k, out in synth_outputs:
        for m in out.get("models", []):
            if not m.get("id") or not m.get("title") or not m.get("holders"):
                continue
            if m["id"] in seen or m["id"] in carry_ids:
                nid = m["id"] + "-2"
                owner = seen.get(m["id"], "carried-over model")
                print(f"WARN: id collision {m['id']} → {nid} ({owner} vs {k}) — "
                      "review and merge manually if they are the same belief")
                m["id"] = nid
            seen[m["id"]] = k
            m.setdefault("about", [])
            m.setdefault("count", 1)
            new_models.append(m)
        for e in out.get("evolution", []):
            if e.get("person") and e.get("note"):
                evolution.append(e)
    carry = [m for m in base["models"] if m["id"] not in assigned and m["id"] not in seen]
    print(f"models: {len(base['models'])} → {len(carry) + len(new_models)} "
          f"(carry {len(carry)} + synthesis {len(new_models)})"
          + (f" | missing outputs (carried over): {missing}" if missing else ""))
    base["models"] = carry + new_models

    # normalize about names
    for m in base["models"]:
        if m.get("about"):
            m["about"] = sorted({cname(a) for a in m["about"] if norm(a)})

    # people[].models rebuild + evolution merge
    names = {p["name"] for p in base["people"]}
    holds = defaultdict(list)
    for m in base["models"]:
        for h in m.get("holders", []):
            holds[h].append(m["id"])
    for p in base["people"]:
        p["models"] = holds.get(p["name"], [])
    unknown = sorted(set(holds) - names)
    if unknown:
        print(f"WARN: holders not in people[] (validate will flag): {unknown}")
    evo_by = defaultdict(list)
    for e in evolution:
        evo_by[e["person"]].append({"date": e.get("date", ""), "note": e["note"]})
    for p in base["people"]:
        have = {(x.get("date"), x.get("note")) for x in p.get("evolution", [])}
        for e in sorted(evo_by.get(p["name"], []), key=lambda x: x["date"]):
            if (e["date"], e["note"]) not in have:
                p.setdefault("evolution", []).append(e)

    # pools
    def load(name):
        p = f"{work}/{name}"
        return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else []
    added = {"tension": 0, "network": 0, "timeline": 0}
    have_rel = {(r.get("from"), r.get("to"), r.get("topic", "")) for r in base.get("relations", [])}
    for t in load("pool_tensions.json"):
        k3 = (t.get("from"), t.get("to"), t.get("topic", ""))
        if t.get("from") in names and t.get("to") in names and k3 not in have_rel:
            base.setdefault("relations", []).append(
                {"from": t["from"], "to": t["to"], "type": "tension",
                 **({"direction": "one-way"} if t.get("direction") == "one-way" else {}),
                 "topic": t.get("topic", ""),
                 "note": (t.get("note", "") + f" ({t.get('mtg_date', '')})").strip()})
            have_rel.add(k3)
            added["tension"] += 1
    have_n = {(n.get("a"), n.get("b"), n.get("kind")) for n in base.get("network", [])}
    for n in load("pool_network.json"):
        a, b = cname(n.get("a", "")), cname(n.get("b", ""))
        if not a or not b or a.lower() in self_names or b.lower() in self_names:
            continue
        k3 = (a, b, n.get("kind"))
        if all(k3) and k3 not in have_n:
            base.setdefault("network", []).append(
                {"a": a, "b": b, "kind": n["kind"], "note": n.get("note", ""),
                 "source": n.get("mtg_date", "")})
            have_n.add(k3)
            added["network"] += 1
    have_tl = {(t.get("date"), t.get("change")) for t in base.get("timeline", [])}
    by_month = defaultdict(list)
    for s in load("pool_timeline.json"):
        by_month[s["date"][:7]].append(s)
    for month in sorted(by_month):
        sigs = by_month[month]
        for s in ([sigs[0]] + ([sigs[-1]] if len(sigs) > 1 else [])):
            if (s["date"], s["signal"]) not in have_tl:
                base.setdefault("timeline", []).append({"date": s["date"], "change": s["signal"]})
                have_tl.add((s["date"], s["signal"]))
                added["timeline"] += 1
    base.get("timeline", []).sort(key=lambda t: t.get("date", ""))

    # meta
    bp = f"{work}/batches.json"
    if os.path.exists(bp):
        sids = {s for b in json.load(open(bp, encoding="utf-8")) for s in b.get("sids", [])}
        base["meta"]["processed_source_ids"] = sorted(
            set(base["meta"].get("processed_source_ids", [])) | sids)
    dates = sorted(x.get("date", "") for x in base.get("timeline", []) if x.get("date"))
    if dates:
        base["meta"]["date_range"] = f"{dates[0]} ~ {dates[-1]}"

    print(f"pools merged: +tension {added['tension']} +network {added['network']} "
          f"+timeline {added['timeline']} | processed_source_ids "
          f"{len(base['meta'].get('processed_source_ids', []))}")
    if not apply_:
        print("\nDRY RUN — rerun with --apply to write (numbered backup kept).")
        return
    bak, n = f"{corpus}/_ontology/objects_backup.json", 2
    while os.path.exists(bak):
        bak = f"{corpus}/_ontology/objects_backup-{n}.json"
        n += 1
    shutil.copy2(op, bak)
    json.dump(base, open(op, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"OK: written. Backup: {os.path.relpath(bak, corpus)}")
    print("Next: validate.py → build_db.py → build_dossiers.py")

if __name__ == "__main__":
    main()
