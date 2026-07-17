#!/usr/bin/env python3
"""Build a queryable SQLite database from the corpus + ontology.

Usage: python3 build_db.py <corpus_path>
Output: <corpus>/_ontology/ontology.db   (rebuilt from scratch — idempotent)

Tables
  people(name, type, role, org, summary, evidence)   -- type: person | org
  models(id, category, title, desc, evidence, quote, count, first_seen, last_seen)
  model_people(model_id, person)     -- HOLDERS: who holds the belief
  model_about(model_id, entity)     -- SUBJECTS: whom/what the belief is about
  model_related(model_id, related_id)
  person_aliases(canonical, alias)  -- from _meta/speakers.json + auto name variants
  relations(from_person, to_person, type, topic, note)
  timeline(date, meeting, change)   bets(tag, title, desc)   risks(level, title, desc)
  meetings(source_id, date, title, category, duration_min, transcribed_by, path, participants)
  utterances(meeting_rowid, speaker, speaker_raw, ts, text)
      -- speaker = canonical name when resolvable via person_aliases, else raw label
  utterances_fts  -- FTS5 over utterances (speaker = canonical), if available

Prints a coverage report and WARNs about everything it could not parse or resolve —
never fails silently. No external dependencies (python3 stdlib only).
"""
import os, sys, json, re, glob, sqlite3, unicodedata
from collections import Counter, defaultdict

def parse_fm(text):
    m = re.match(r'^---\s*\n(.*?)\n---\s*\n', text, re.S)
    if not m:
        return {}, text
    fm = {}
    for line in m.group(1).splitlines():
        mm = re.match(r'^(\w+):\s*(.*)$', line)
        if not mm:
            continue
        k, v = mm.group(1), mm.group(2).strip().strip('"')
        if v.startswith('[') and v.endswith(']'):
            v = [x.strip().strip('"') for x in v[1:-1].split(',') if x.strip()]
        fm[k] = v
    return fm, text[m.end():]

# Utterance line shapes, tried in order:
#   **[Name] (mm:ss)** text        (Name may be empty: **[] (mm:ss)**)
#   **Name (mm:ss)** text  /  **(mm:ss)** text    (ts inside the bold)
#   **Name** (mm:ss)[:] text       (ts outside the bold; text may sit on NEXT lines)
#   [mm:ss] text  /  [mm:ss - mm:ss] text         (bracket ts/range, no speaker)
#   (mm:ss) text
TS = r'\d+:\d{2}(?::\d{2})?'
PTS = rf'\((?:시간:\s*)?(?P<ts>{TS})\)'   # "(mm:ss)" or "(시간: mm:ss)"
UTT_PATTERNS = [
    re.compile(rf'^\*\*\[(?P<name>[^\]]*)\]\s*{PTS}\*\*\s*(?P<text>.*)$'),
    re.compile(rf'^\*\*(?P<name>.*?)\s*{PTS}\*\*\s*(?P<text>.*)$'),
    re.compile(rf'^\*\*(?P<name>[^*]+?)\*\*\s*{PTS}\s*:?\s*(?P<text>.*)$'),
    re.compile(rf'^\[(?P<ts>{TS})(?:\s*-\s*{TS})?\]\s*:?\s*(?P<text>.*)$'),
    re.compile(rf'^{PTS}\s*(?P<text>.*)$'),
]
# a line that *looks* like it carries an utterance timestamp near the start
UTT_MAYBE = re.compile(rf'^\s*(?:\*{{0,2}}\s*\[?[^\n]{{0,40}}?\({TS}\)|\[{TS})')
GENERIC = re.compile(r'^(speaker|발화자|화자)\s*\d*$', re.I)
# commitment checkbox: - [ ] (요청자→담당자) 내용 (기한: YYYY-MM-DD) — 화살표/기한은 선택
COMMIT = re.compile(r'^-\s*\[([ xX])\]\s*(?:\(([^)→>]*?)(?:→|->)([^)]*)\)\s*)?(.+?)'
                    r'(?:\s*\((?:기한|due)[:\s]*([0-9./-]+)\))?\s*$')

def parse_utt(line):
    for pat in UTT_PATTERNS:
        m = pat.match(line)
        if m:
            g = m.groupdict()
            return (g.get("name") or "").strip(), g["ts"], (g.get("text") or "").strip()
    return None

def norm(s):
    return re.sub(r'\s+', ' ', unicodedata.normalize("NFC", s.strip()))

def variants(name):
    """'James(정우진)' -> {'James(정우진)', 'James', '정우진'} — both halves of a
    'Latin(한글)' style name are labels people actually get in transcripts."""
    out = {norm(name)}
    m = re.match(r'^(.+?)\s*\((.+?)\)$', name.strip())
    if m:
        out.add(norm(m.group(1)))
        out.add(norm(m.group(2)))
    return {v for v in out if v}

def load_alias_map(corpus, ontology_people):
    """alias(lower) -> canonical. Sources: _meta/speakers.json (name + aliases)
    and ontology person entries; every name also contributes its auto variants."""
    cands = defaultdict(set)  # canonical -> aliases
    sp = os.path.join(corpus, "_meta", "speakers.json")
    if os.path.exists(sp):
        try:
            for e in json.load(open(sp, encoding="utf-8")):
                name = norm(e.get("name", ""))
                if not name:
                    continue
                for a in {name, *(e.get("aliases") or [])}:
                    cands[name] |= variants(a)
        except Exception as ex:
            print(f"WARN: could not parse _meta/speakers.json: {ex}")
    for p in ontology_people:
        if (p.get("type") or "person") != "person":
            continue
        name = norm(p.get("name", ""))
        if name:
            cands[name] |= variants(name)
    amap, conflicts = {}, set()
    for canon, aliases in cands.items():
        for a in aliases:
            k = a.lower()
            if k in amap and amap[k] != canon:
                conflicts.add(a)
                continue
            amap[k] = canon
    for a in conflicts:
        amap.pop(a.lower(), None)
    return amap, conflicts, len(cands)

def resolve(raw, amap):
    r = norm(raw)
    if not r:
        return ""
    if GENERIC.match(r):
        return raw
    return amap.get(r.lower(), raw)

# names in older files may carry junk wrappers ([[X]], quotes, \u-escapes) and role-words
PART_STOP = {"대표", "대표님", "담당자", "상담원", "직원", "참석자", "발신자", "수신자", "고객", "기타"}

def strip_wrappers(s):
    """'[[오현석]]' / '[오현석]' / \"'오현석'\" / '\\uc624\\ud604\\uc11d' → 오현석"""
    s = re.sub(r'\\u([0-9a-fA-F]{4})', lambda m: chr(int(m.group(1), 16)), str(s))
    return norm(re.sub(r"^[\[\s'\"]+|[\]\s'\"]+$", "", s))

def clean_participant(s):
    """strip wrappers; generic labels, role-words, single letters → '' (not a person)"""
    s = strip_wrappers(s)
    if not s or len(s) < 2 or GENERIC.match(s) or s in PART_STOP:
        return ""
    return s

def main():
    corpus = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.getcwd()
    onto_dir = os.path.join(corpus, "_ontology")
    db_path = os.path.join(onto_dir, "ontology.db")
    os.makedirs(onto_dir, exist_ok=True)
    if os.path.exists(db_path):
        os.remove(db_path)
    db = sqlite3.connect(db_path)
    c = db.cursor()
    c.executescript("""
    CREATE TABLE people(name TEXT PRIMARY KEY, type TEXT, role TEXT, org TEXT, summary TEXT, evidence TEXT);
    CREATE TABLE models(id TEXT PRIMARY KEY, category TEXT, title TEXT, desc TEXT, evidence TEXT,
                        quote TEXT, count INTEGER, first_seen TEXT, last_seen TEXT);
    CREATE TABLE model_people(model_id TEXT, person TEXT);
    CREATE TABLE model_about(model_id TEXT, entity TEXT);
    CREATE TABLE model_related(model_id TEXT, related_id TEXT);
    CREATE TABLE person_aliases(canonical TEXT, alias TEXT);
    CREATE TABLE relations(from_person TEXT, to_person TEXT, type TEXT, topic TEXT, note TEXT);
    CREATE TABLE network(a TEXT, b TEXT, kind TEXT, since TEXT, note TEXT, source TEXT);
    CREATE TABLE person_meetings(person TEXT, meeting_rowid INTEGER, src TEXT);
    CREATE INDEX idx_pm_person ON person_meetings(person);
    CREATE TABLE timeline(date TEXT, meeting TEXT, change TEXT);
    CREATE TABLE bets(tag TEXT, title TEXT, desc TEXT, status TEXT, owner TEXT, date TEXT, source TEXT);
    CREATE TABLE risks(level TEXT, title TEXT, desc TEXT, status TEXT, mitigation TEXT, source TEXT);
    CREATE TABLE commitments(meeting_rowid INTEGER, done INTEGER, from_person TEXT,
                             to_person TEXT, text TEXT, due TEXT);
    CREATE TABLE meetings(source_id TEXT, date TEXT, title TEXT, category TEXT,
                          duration_min INTEGER, transcribed_by TEXT, path TEXT, participants TEXT);
    CREATE TABLE utterances(meeting_rowid INTEGER, speaker TEXT, speaker_raw TEXT, ts TEXT, text TEXT);
    CREATE INDEX idx_utt_meeting ON utterances(meeting_rowid);
    CREATE INDEX idx_utt_speaker ON utterances(speaker);
    CREATE INDEX idx_meet_date ON meetings(date);
    """)

    # --- ontology (objects.json) ---
    op = os.path.join(onto_dir, "objects.json")
    d = {}
    if os.path.exists(op):
        d = json.load(open(op, encoding="utf-8"))
        for p in d.get("people", []):
            c.execute("INSERT OR REPLACE INTO people VALUES(?,?,?,?,?,?)",
                      (p.get("name"), p.get("type", "person"), p.get("role", ""),
                       p.get("org", ""), p.get("summary", ""), p.get("evidence", "")))
        holder_pairs, about_pairs = set(), set()
        for m in d.get("models", []):
            c.execute("INSERT OR REPLACE INTO models VALUES(?,?,?,?,?,?,?,?,?)",
                      (m.get("id"), m.get("category", ""), m.get("title", ""), m.get("desc", ""),
                       m.get("evidence", ""), m.get("quote", ""), m.get("count", 1),
                       m.get("first_seen", ""), m.get("last_seen", "")))
            for h in m.get("holders", m.get("people", [])):  # legacy v1: people == holders
                holder_pairs.add((m.get("id"), h))
            for a in m.get("about", []):
                about_pairs.add((m.get("id"), a))
            for r in m.get("related", []):
                c.execute("INSERT INTO model_related VALUES(?,?)", (m.get("id"), r))
        if d.get("meta", {}).get("schema_version", 1) < 2:
            # legacy v1 also stored the linkage as people[].models — union it in
            for p in d.get("people", []):
                pairs = holder_pairs if (p.get("type") or "person") == "person" else about_pairs
                for mid in p.get("models", []):
                    pairs.add((mid, p.get("name")))
        c.executemany("INSERT INTO model_people VALUES(?,?)", sorted(holder_pairs))
        c.executemany("INSERT INTO model_about VALUES(?,?)", sorted(about_pairs))
        for r in d.get("relations", []):
            c.execute("INSERT INTO relations VALUES(?,?,?,?,?)",
                      (r.get("from"), r.get("to"), r.get("type", ""), r.get("topic", ""), r.get("note", "")))
        for n in d.get("network", []):
            c.execute("INSERT INTO network VALUES(?,?,?,?,?,?)",
                      (n.get("a"), n.get("b"), n.get("kind", ""), n.get("since", ""),
                       n.get("note", ""), n.get("source", "")))
        for t in d.get("timeline", []):
            c.execute("INSERT INTO timeline VALUES(?,?,?)",
                      (t.get("date", ""), t.get("meeting", ""), t.get("change", "")))
        for b in d.get("bets", []):
            c.execute("INSERT INTO bets VALUES(?,?,?,?,?,?,?)",
                      (b.get("tag", ""), b.get("title", ""), b.get("desc", ""), b.get("status", ""),
                       b.get("owner", ""), b.get("date", ""), ", ".join(b.get("source", []))))
        for r in d.get("risks", []):
            c.execute("INSERT INTO risks VALUES(?,?,?,?,?,?)",
                      (r.get("level", ""), r.get("title", ""), r.get("desc", ""),
                       r.get("status", ""), r.get("mitigation", ""), ", ".join(r.get("source", []))))

    # --- speaker alias map ---
    amap, conflicts, n_canon = load_alias_map(corpus, d.get("people", []))
    for alias, canon in sorted(amap.items()):
        c.execute("INSERT INTO person_aliases VALUES(?,?)", (canon, alias))

    # --- transcripts ---
    n_utt = 0
    zero_files, dropped = [], Counter()
    spk_stats = Counter()  # canonical / raw-name / generic / unattributed
    sid_paths = defaultdict(list)

    def classify(raw, speaker):
        if not speaker:
            return "unattributed"
        if GENERIC.match(norm(speaker)):
            return "generic"
        if speaker in amap.values() or norm(raw).lower() in amap:
            return "canonical"
        return "raw-name"

    for p in sorted(glob.glob(os.path.join(corpus, "transcripts", "**", "*.md"), recursive=True)):
        try:
            fm, body = parse_fm(open(p, encoding="utf-8").read())
        except Exception as ex:
            print(f"WARN: unreadable transcript skipped: {os.path.relpath(p, corpus)} ({ex})")
            continue
        parts = fm.get("participants", [])
        c.execute("INSERT INTO meetings VALUES(?,?,?,?,?,?,?,?)",
                  (fm.get("source_id", ""), str(fm.get("date", "")), fm.get("title", ""),
                   fm.get("category", ""),
                   int(fm["duration_min"]) if str(fm.get("duration_min", "")).isdigit() else None,
                   fm.get("transcribed_by", ""), os.path.relpath(p, corpus),
                   ", ".join(parts) if isinstance(parts, list) else str(parts)))
        mid = c.lastrowid
        if fm.get("source_id"):
            # split recordings (_part1/_part2) legitimately share a source_id
            sid_paths[(fm["source_id"], str(fm.get("part", "")))].append(os.path.relpath(p, corpus))
        # interaction record: who was in this meeting (works even when utterances
        # carry no speaker labels — e.g. phone calls — via frontmatter participants)
        pm = set()
        for part in (parts if isinstance(parts, list) else [parts]):
            cleaned = clean_participant(part) if part else ""
            if cleaned:
                pm.add((resolve(cleaned, amap), "participant"))
        file_utt = 0
        pending, buf = None, []  # header with no same-line text: body follows on next lines

        def emit(raw, ts, text):
            nonlocal n_utt, file_utt
            speaker = resolve(strip_wrappers(raw), amap) if raw.strip() else ""
            kind = classify(raw, speaker)
            spk_stats[kind] += 1
            if kind in ("canonical", "raw-name") and clean_participant(speaker):
                pm.add((speaker, "speaker"))
            c.execute("INSERT INTO utterances VALUES(?,?,?,?,?)", (mid, speaker, raw, ts, text))
            n_utt += 1
            file_utt += 1

        def flush():
            nonlocal pending, buf
            if pending and buf:
                emit(pending[0], pending[1], " ".join(buf))
            pending, buf = None, []

        for line in body.splitlines():
            s = line.strip()
            if not s:
                flush()
                continue
            cm = COMMIT.match(s)
            if cm:
                flush()
                done, frm, to, text, due = cm.groups()
                c.execute("INSERT INTO commitments VALUES(?,?,?,?,?,?)",
                          (mid, 0 if done == " " else 1,
                           resolve(strip_wrappers(frm or ""), amap),
                           resolve(strip_wrappers(to or ""), amap), text.strip(), due or ""))
                continue
            got = parse_utt(s)
            if got:
                flush()
                raw, ts, text = got
                if text:
                    emit(raw, ts, text)
                else:
                    pending = (raw, ts)
                continue
            if s.startswith("#"):
                flush()
                continue
            if pending:
                buf.append(s)
                continue
            if UTT_MAYBE.match(s):
                dropped[os.path.relpath(p, corpus)] += 1
        flush()
        for person, src in sorted(pm):
            if src == "participant" and (person, "speaker") in pm:
                continue  # speaker evidence wins over the participant listing
            c.execute("INSERT INTO person_meetings VALUES(?,?,?)", (person, mid, src))
        if file_utt == 0:
            zero_files.append(os.path.relpath(p, corpus))
    dup_sids = {k: v for k, v in sid_paths.items() if len(v) > 1}

    # --- full-text search (FTS5 if available) ---
    fts = False
    try:
        c.executescript("""
        CREATE VIRTUAL TABLE utterances_fts USING fts5(
            speaker, text, date UNINDEXED, title UNINDEXED, meeting_rowid UNINDEXED);
        INSERT INTO utterances_fts(speaker, text, date, title, meeting_rowid)
          SELECT u.speaker, u.text, m.date, m.title, u.meeting_rowid
          FROM utterances u JOIN meetings m ON m.rowid = u.meeting_rowid;
        """)
        fts = True
    except sqlite3.OperationalError:
        pass  # FTS5 unavailable → LIKE fallback documented in PLAYBOOK
    c.execute("CREATE TABLE meta(key TEXT, value TEXT)")
    c.execute("INSERT INTO meta VALUES('fts5', ?)", ("yes" if fts else "no",))
    db.commit()

    # --- report (loud about gaps) ---
    q = lambda s: c.execute(s).fetchone()[0]
    n_person = q("SELECT COUNT(*) FROM people WHERE type='person' OR type IS NULL OR type=''")
    n_org = q("SELECT COUNT(*) FROM people WHERE type='org'")
    print(f"OK: {db_path}")
    print(f"  people {q('SELECT COUNT(*) FROM people')} (person {n_person} / org {n_org}) | "
          f"models {q('SELECT COUNT(*) FROM models')} | relations {q('SELECT COUNT(*) FROM relations')} | "
          f"meetings {q('SELECT COUNT(*) FROM meetings')} | utterances {n_utt} | fts5 {'ON' if fts else 'OFF'}")
    print(f"  alias map: {n_canon} canonical names, {len(amap)} aliases"
          + (f" | CONFLICTS dropped: {sorted(conflicts)}" if conflicts else ""))
    print(f"  interactions: {q('SELECT COUNT(*) FROM person_meetings')} person-meeting links "
          f"across {q('SELECT COUNT(DISTINCT person) FROM person_meetings')} people | "
          f"network edges {q('SELECT COUNT(*) FROM network')} | "
          f"commitments {q('SELECT COUNT(*) FROM commitments')} "
          f"({q('SELECT COUNT(*) FROM commitments WHERE done=0')} open)")
    if n_utt:
        pct = lambda k: f"{100.0 * spk_stats[k] / n_utt:.1f}%"
        print(f"  speaker attribution: canonical {pct('canonical')} · other-name {pct('raw-name')}"
              f" · generic(Speaker N) {pct('generic')} · unattributed {pct('unattributed')}")
    if conflicts:
        print("WARN: ambiguous aliases were dropped from the map — fix them in _meta/speakers.json.")
    if dup_sids:
        print(f"WARN: {len(dup_sids)} source_ids appear in MULTIPLE transcript files "
              "(same recording saved twice — double-counts in search; keep one, delete the other):")
        for (sid, _part), paths in list(dup_sids.items())[:8]:
            print(f"    {sid}: " + " | ".join(paths))
        if len(dup_sids) > 8:
            print(f"    … and {len(dup_sids) - 8} more")
    if dropped:
        total = sum(dropped.values())
        print(f"WARN: {total} timestamp-looking lines in {len(dropped)} files did not parse as utterances:")
        for f, n in dropped.most_common(10):
            print(f"    {f} ({n} lines)")
        if len(dropped) > 10:
            print(f"    … and {len(dropped) - 10} more files")
    if zero_files:
        print(f"WARN: {len(zero_files)} meetings produced ZERO utterances (invisible to full-text search):")
        for f in zero_files[:10]:
            print(f"    {f}")
        if len(zero_files) > 10:
            print(f"    … and {len(zero_files) - 10} more files")
    if not dropped and not zero_files:
        print("  all transcript files parsed cleanly.")

if __name__ == "__main__":
    main()
