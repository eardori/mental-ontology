#!/usr/bin/env python3
"""Batch re-extraction step 2: aggregate per-batch extraction files into
synthesis tasks (see EXTRACTION.md "Batch pipeline").

Usage: python3 prepare_synthesis.py <corpus> <workdir> [--split-threshold 30]

Reads   <workdir>/extract-b*.json      (written by extraction agents)
        <corpus>/_ontology/objects.json  (existing canonical models)
        <corpus>/_meta/speakers.json     (canonical holders)
Writes  <workdir>/synth-task-<key>.json  {existing_models, instances}
        <workdir>/synth_keys.json        (keys that NEED a synthesis agent)
        <workdir>/pool_tensions.json, pool_network.json, pool_timeline.json

Assignment: every existing model belongs to exactly ONE task (primary holder =
holders[0]); a person whose workload exceeds --split-threshold is split by
category. Instances with non-canonical holders are dropped (reported).
"""
import glob, json, os, sys, unicodedata
from collections import Counter, defaultdict

def norm(s):
    return unicodedata.normalize("NFC", (s or "").strip())

def main():
    argv = [a for a in sys.argv[1:] if not a.startswith("--")]
    corpus, work = os.path.abspath(argv[0]), os.path.abspath(argv[1])
    thresh = 30
    for a in sys.argv[1:]:
        if a.startswith("--split-threshold"):
            thresh = int(a.split("=")[1]) if "=" in a else thresh
    onto = json.load(open(f"{corpus}/_ontology/objects.json", encoding="utf-8"))
    canon = {norm(e["name"]) for e in
             json.load(open(f"{corpus}/_meta/speakers.json", encoding="utf-8")) if e.get("name")}
    processed = set(onto.get("meta", {}).get("processed_source_ids", []))

    by_person = defaultdict(list)
    tensions, network, timeline = [], [], []
    n_meet, n_skip_done, dropped = 0, 0, Counter()
    for p in sorted(glob.glob(os.path.join(work, "extract-b*.json"))):
        try:
            d = json.load(open(p, encoding="utf-8"))
        except Exception as ex:
            print(f"WARN: unreadable {os.path.basename(p)}: {ex}")
            continue
        for m in d.get("meetings", []):
            if m.get("source_id") in processed:
                n_skip_done += 1
                continue
            n_meet += 1
            ctx = {"mtg_source_id": m.get("source_id", ""), "mtg_date": m.get("date", ""),
                   "mtg_title": m.get("title", "")}
            for i in m.get("instances", []):
                h = norm(i.get("holder", ""))
                if h not in canon:
                    dropped[h or "<empty>"] += 1
                    continue
                by_person[h].append({**i, "holder": h, **ctx})
            for t in m.get("tensions", []):
                tensions.append({**t, **ctx})
            for nf in m.get("network_facts", []):
                network.append({**nf, **ctx})
            if m.get("timeline_signal"):
                timeline.append({"date": ctx["mtg_date"], "title": ctx["mtg_title"],
                                 "signal": m["timeline_signal"]})

    # tasks: primary-holder assignment; heavy persons split by category
    tasks = defaultdict(lambda: {"existing_models": [], "instances": []})
    heavy = {p for p, items in by_person.items() if len(items) > thresh}

    def model_key(m):
        ph = norm((m.get("holders") or m.get("people") or ["?"])[0])
        return f"{ph}-{m.get('category', '기타')}" if ph in heavy else f"person-{ph}"

    def inst_key(i):
        return (f"{i['holder']}-{i.get('category', '기타')}" if i["holder"] in heavy
                else f"person-{i['holder']}")

    for m in onto.get("models", []):
        tasks[model_key(m)]["existing_models"].append(m)
    for person, items in by_person.items():
        for i in items:
            tasks[inst_key(i)]["instances"].append(i)

    # tiny category tasks of heavy persons fold into their -기타 task
    merged, folded = {}, []
    for k, t in tasks.items():
        person_cat = any(k.startswith(f"{h}-") for h in heavy)
        if person_cat and not k.endswith("-기타") and \
                len(t["existing_models"]) + len(t["instances"]) < 8:
            folded.append((k, t))
        else:
            merged[k] = t
    for k, t in folded:
        owner = k.rsplit("-", 1)[0]
        tgt = merged.setdefault(f"{owner}-기타", {"existing_models": [], "instances": []})
        tgt["existing_models"] += t["existing_models"]
        tgt["instances"] += t["instances"]

    need_agent = []
    for k, t in merged.items():
        safe = k.replace("/", "-")
        json.dump(t, open(f"{work}/synth-task-{safe}.json", "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        if t["instances"]:
            need_agent.append(safe)
    json.dump(sorted(need_agent), open(f"{work}/synth_keys.json", "w", encoding="utf-8"),
              ensure_ascii=False)
    json.dump(tensions, open(f"{work}/pool_tensions.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    json.dump(network, open(f"{work}/pool_network.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    json.dump(sorted(timeline, key=lambda x: x["date"]),
              open(f"{work}/pool_timeline.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    print(f"OK: {n_meet} meetings ({n_skip_done} already-processed skipped) → "
          f"{len(merged)} tasks, {len(need_agent)} need a synthesis agent")
    for k, t in sorted(merged.items(), key=lambda x: -len(x[1]["instances"])):
        mark = "" if k in need_agent or k.replace("/", "-") in need_agent else "  (no instances — carries over)"
        print(f"  {k:32} existing={len(t['existing_models']):3} instances={len(t['instances']):3}{mark}")
    print(f"pools: tensions {len(tensions)} | network {len(network)} | timeline {len(timeline)}")
    if dropped:
        print(f"WARN: {sum(dropped.values())} instances dropped (non-canonical holder) — "
              f"top: {dropped.most_common(5)}")

if __name__ == "__main__":
    main()
