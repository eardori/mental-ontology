#!/usr/bin/env python3
"""Build a queryable SQLite database from the corpus + ontology.

Usage: python3 build_db.py <corpus_path>
Output: <corpus>/_ontology/ontology.db   (rebuilt from scratch — idempotent)

Tables
  people(name, role, org, summary, evidence)
  models(id, category, title, desc, evidence, quote, count, first_seen, last_seen)
  model_people(model_id, person)          model_related(model_id, related_id)
  relations(from_person, to_person, type, topic, note)
  timeline(date, meeting, change)         bets(tag, title, desc)   risks(level, title, desc)
  meetings(source_id, date, title, category, duration_min, transcribed_by, path, participants)
  utterances(meeting_rowid, speaker, ts, text)
  utterances_fts  -- FTS5 full-text search over utterances (if available)

No external dependencies (python3 stdlib only).
"""
import os, sys, json, re, glob, sqlite3

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

# matches: **[Name] (m:ss)** text   |   **Name (mm:ss)** text   |   (mm:ss) text
UTT = re.compile(r'^(?:\*\*\[?([^\]*]+?)\]?\s*\((\d+:\d{2}(?::\d{2})?)\)\*\*|\((\d+:\d{2}(?::\d{2})?)\))\s*(.*)$')

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
    CREATE TABLE people(name TEXT PRIMARY KEY, role TEXT, org TEXT, summary TEXT, evidence TEXT);
    CREATE TABLE models(id TEXT PRIMARY KEY, category TEXT, title TEXT, desc TEXT, evidence TEXT,
                        quote TEXT, count INTEGER, first_seen TEXT, last_seen TEXT);
    CREATE TABLE model_people(model_id TEXT, person TEXT);
    CREATE TABLE model_related(model_id TEXT, related_id TEXT);
    CREATE TABLE relations(from_person TEXT, to_person TEXT, type TEXT, topic TEXT, note TEXT);
    CREATE TABLE timeline(date TEXT, meeting TEXT, change TEXT);
    CREATE TABLE bets(tag TEXT, title TEXT, desc TEXT);
    CREATE TABLE risks(level TEXT, title TEXT, desc TEXT);
    CREATE TABLE meetings(source_id TEXT, date TEXT, title TEXT, category TEXT,
                          duration_min INTEGER, transcribed_by TEXT, path TEXT, participants TEXT);
    CREATE TABLE utterances(meeting_rowid INTEGER, speaker TEXT, ts TEXT, text TEXT);
    CREATE INDEX idx_utt_meeting ON utterances(meeting_rowid);
    CREATE INDEX idx_meet_date ON meetings(date);
    """)

    # --- ontology (objects.json) ---
    op = os.path.join(onto_dir, "objects.json")
    if os.path.exists(op):
        d = json.load(open(op))
        for p in d.get("people", []):
            c.execute("INSERT OR REPLACE INTO people VALUES(?,?,?,?,?)",
                      (p.get("name"), p.get("role", ""), p.get("org", ""),
                       p.get("summary", ""), p.get("evidence", "")))
            for mid in p.get("models", []):
                c.execute("INSERT INTO model_people VALUES(?,?)", (mid, p.get("name")))
        for m in d.get("models", []):
            c.execute("INSERT OR REPLACE INTO models VALUES(?,?,?,?,?,?,?,?,?)",
                      (m.get("id"), m.get("category", ""), m.get("title", ""), m.get("desc", ""),
                       m.get("evidence", ""), m.get("quote", ""), m.get("count", 1),
                       m.get("first_seen", ""), m.get("last_seen", "")))
            for r in m.get("related", []):
                c.execute("INSERT INTO model_related VALUES(?,?)", (m.get("id"), r))
        for r in d.get("relations", []):
            c.execute("INSERT INTO relations VALUES(?,?,?,?,?)",
                      (r.get("from"), r.get("to"), r.get("type", ""), r.get("topic", ""), r.get("note", "")))
        for t in d.get("timeline", []):
            c.execute("INSERT INTO timeline VALUES(?,?,?)",
                      (t.get("date", ""), t.get("meeting", ""), t.get("change", "")))
        for b in d.get("bets", []):
            c.execute("INSERT INTO bets VALUES(?,?,?)", (b.get("tag", ""), b.get("title", ""), b.get("desc", "")))
        for r in d.get("risks", []):
            c.execute("INSERT INTO risks VALUES(?,?,?)", (r.get("level", ""), r.get("title", ""), r.get("desc", "")))

    # --- transcripts ---
    n_utt = 0
    for p in sorted(glob.glob(os.path.join(corpus, "transcripts", "**", "*.md"), recursive=True)):
        try:
            fm, body = parse_fm(open(p, encoding="utf-8").read())
        except Exception:
            continue
        parts = fm.get("participants", [])
        c.execute("INSERT INTO meetings VALUES(?,?,?,?,?,?,?,?)",
                  (fm.get("source_id", ""), str(fm.get("date", "")), fm.get("title", ""),
                   fm.get("category", ""),
                   int(fm["duration_min"]) if str(fm.get("duration_min", "")).isdigit() else None,
                   fm.get("transcribed_by", ""), os.path.relpath(p, corpus),
                   ", ".join(parts) if isinstance(parts, list) else str(parts)))
        mid = c.lastrowid
        for line in body.splitlines():
            m = UTT.match(line.strip())
            if not m:
                continue
            speaker = (m.group(1) or "").strip()
            ts = m.group(2) or m.group(3) or ""
            text = (m.group(4) or "").strip()
            if text:
                c.execute("INSERT INTO utterances VALUES(?,?,?,?)", (mid, speaker, ts, text))
                n_utt += 1

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

    q = lambda s: c.execute(s).fetchone()[0]
    print(f"OK: {db_path}")
    print(f"  people {q('SELECT COUNT(*) FROM people')} | models {q('SELECT COUNT(*) FROM models')} | "
          f"relations {q('SELECT COUNT(*) FROM relations')} | meetings {q('SELECT COUNT(*) FROM meetings')} | "
          f"utterances {n_utt} | fts5 {'ON' if fts else 'OFF'}")

if __name__ == "__main__":
    main()
