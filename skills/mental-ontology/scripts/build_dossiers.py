#!/usr/bin/env python3
"""Generate per-person dossiers (people/<이름>.md) + people/INDEX.md from the
registry (_meta/speakers.json) and the database (ontology.db).

Usage: python3 build_dossiers.py <corpus_path>

The dossier is the person-centric artifact of the corpus: identity, personal
context, mental models (core tier), relations & network, top co-attendees, and
the full interaction timeline (participants-based — works even for unattributed
phone calls). A manual-notes section between the markers below survives every
regeneration:

    <!-- manual:start -->  ...user's own notes...  <!-- manual:end -->

Registry fields used (all optional, see corpus-structure.md):
  tier: core | acquaintance | contact   (default: core for registry entries)
  first_met_context, intro_by, personal: ["...", {"date","note"}]

Dossiers are written for core + acquaintance. Contacts (auto-discovered from
the DB, not in the registry) are listed in INDEX.md with promotion candidates
(≥3 meetings). Run after build_db.py. No external dependencies.
"""
import os, re, sys, json, sqlite3, datetime

MANUAL_START, MANUAL_END = "<!-- manual:start -->", "<!-- manual:end -->"
GENERIC = re.compile(r'^(speaker|발화자|화자)\s*\d*$', re.I)

def safe_name(name):
    return re.sub(r'[/\\:]', '-', name)

def manual_block(path):
    if not os.path.exists(path):
        return "(여기에 자유롭게 메모하세요 — 도시에를 다시 생성해도 이 섹션은 보존됩니다)"
    t = open(path, encoding="utf-8").read()
    m = re.search(re.escape(MANUAL_START) + r'\n(.*?)\n' + re.escape(MANUAL_END), t, re.S)
    return m.group(1) if m else "(여기에 자유롭게 메모하세요 — 도시에를 다시 생성해도 이 섹션은 보존됩니다)"

def wikilink(path, title):
    base = os.path.splitext(os.path.basename(path))[0]
    return f"[[{base}|{title or base}]]"

def dossier(name, entry, db, models_of, out_path):
    q = lambda s, *a: db.execute(s, a).fetchall()
    mts = q("""SELECT m.date, m.title, m.category, m.path FROM person_meetings pm
               JOIN meetings m ON m.rowid = pm.meeting_rowid
               WHERE pm.person = ? ORDER BY m.date DESC""", name)
    dates = [d for d, *_ in mts if d]
    first = min(dates) if dates else ""
    last = max(dates) if dates else ""
    co = q("""SELECT p2.person, COUNT(DISTINCT p2.meeting_rowid) n FROM person_meetings p1
              JOIN person_meetings p2 ON p2.meeting_rowid = p1.meeting_rowid
              WHERE p1.person = ? AND p2.person != ? GROUP BY p2.person
              ORDER BY n DESC LIMIT 8""", name, name)
    co = [(p, n) for p, n in co if not GENERIC.match(p or "")]
    rels = q("""SELECT type, from_person, to_person, topic, note FROM relations
                WHERE from_person = ? OR to_person = ?""", name, name)
    net = q("""SELECT kind, a, b, since, note FROM network WHERE a = ? OR b = ?""", name, name)

    L = ["---",
         f"name: {name}",
         f"tier: {entry.get('tier', 'core')}",
         f"role: {entry.get('role', '')}",
         f"org: {entry.get('org', '')}",
         f"first_met: {first}",
         f"last_met: {last}",
         f"meetings: {len(mts)}",
         f"updated: {datetime.date.today().isoformat()}",
         "---", "",
         f"# {name}" + (f" — {entry.get('role')}" if entry.get("role") else "")
         + (f", {entry.get('org')}" if entry.get("org") else ""), ""]

    intro = [x for x in (entry.get("first_met_context"),
                         f"소개: {entry['intro_by']}" if entry.get("intro_by") else None) if x]
    L += ["## 개요", entry.get("traits", "") or "(성향 메모 없음)"]
    if intro:
        L += ["", "- " + "\n- ".join(intro)]
    L.append("")

    personal = entry.get("personal") or []
    if personal:
        L.append("## 개인 맥락")
        for p in personal:
            L.append(f"- ({p['date']}) {p['note']}" if isinstance(p, dict) else f"- {p}")
        L.append("")

    if models_of.get(name):
        L.append("## 사고방식 (멘탈모델)")
        for cat, title, ev, quote in models_of[name][:12]:
            L.append(f"- **[{cat}] {title}** ({ev})" + (f' — "{quote}"' if quote else ""))
        L.append("")

    if rels or net or co:
        L.append("## 관계")
        KR = {"tension": "대립", "agree": "합의", "builds-on": "발전"}
        for t, f_, to, topic, note in rels:
            other = to if f_ == name else f_
            L.append(f"- {KR.get(t, t)} ↔ **{other}**" + (f" · {topic}" if topic else "")
                     + (f" — {note}" if note else ""))
        for kind, a, b, since, note in net:
            other = b if a == name else a
            L.append(f"- {kind} ↔ **{other}**" + (f" (since {since})" if since else "")
                     + (f" — {note}" if note else ""))
        if co:
            L.append("- 자주 함께: " + ", ".join(f"{p}({n}회)" for p, n in co[:6]))
        L.append("")

    L.append(f"## 접촉 이력 ({len(mts)}회)")
    for date, title, cat, path in mts[:30]:
        L.append(f"- `{date}` {wikilink(path, title)}" + (f" · {cat}" if cat else ""))
    if len(mts) > 30:
        L.append(f"- … 외 {len(mts) - 30}건")
    L += ["", "## 수기 메모", MANUAL_START, manual_block(out_path), MANUAL_END, ""]
    open(out_path, "w", encoding="utf-8").write("\n".join(L))

def main():
    corpus = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.getcwd()
    dbp = os.path.join(corpus, "_ontology", "ontology.db")
    if not os.path.exists(dbp):
        sys.exit("ERROR: ontology.db not found — run build_db.py first.")
    db = sqlite3.connect(dbp)
    q = lambda s, *a: db.execute(s, a).fetchall()

    registry = []
    sp = os.path.join(corpus, "_meta", "speakers.json")
    if os.path.exists(sp):
        registry = json.load(open(sp, encoding="utf-8"))
    by_name = {e["name"]: e for e in registry if e.get("name")}

    models_of = {}
    for person, cat, title, ev, quote in q(
            """SELECT mp.person, m.category, m.title, m.evidence, m.quote
               FROM model_people mp JOIN models m ON m.id = mp.model_id
               ORDER BY m.count DESC, m.evidence"""):
        models_of.setdefault(person, []).append((cat, title, ev, quote))

    pdir = os.path.join(corpus, "people")
    os.makedirs(pdir, exist_ok=True)
    written = []
    for e in registry:
        name = e.get("name", "")
        if not name or e.get("tier", "core") == "contact":
            continue
        out = os.path.join(pdir, f"{safe_name(name)}.md")
        dossier(name, e, db, models_of, out)
        written.append(name)

    # contacts: everyone in the DB who is not in the registry
    stats = {}
    for person, n, first, last in q(
            """SELECT person, COUNT(DISTINCT meeting_rowid), MIN(m.date), MAX(m.date)
               FROM person_meetings pm JOIN meetings m ON m.rowid = pm.meeting_rowid
               GROUP BY person"""):
        if person and not GENERIC.match(person) and person not in by_name:
            stats[person] = (n, first, last)
    contacts = sorted(stats.items(), key=lambda x: (-x[1][0], x[0]))
    promote = [(p, s) for p, s in contacts if s[0] >= 3]

    L = ["# People Index", "",
         f"> {len(written)}명 도시에 · contact {len(contacts)}명 자동 수집 · "
         f"generated by build_dossiers.py", ""]
    for tier, label in (("core", "Core"), ("acquaintance", "Acquaintance")):
        rows = [e for e in registry if e.get("tier", "core") == tier and e.get("name") in written]
        if not rows:
            continue
        L += [f"## {label} ({len(rows)})", "", "| 이름 | 역할 | 만남 | 최근 |", "|---|---|---|---|"]
        for e in rows:
            name = e["name"]
            r = q("""SELECT COUNT(DISTINCT meeting_rowid), MAX(m.date) FROM person_meetings pm
                     JOIN meetings m ON m.rowid=pm.meeting_rowid WHERE person=?""", name)[0]
            L.append(f"| [[{safe_name(name)}\\|{name}]] | {e.get('role','')} | {r[0]}회 | {r[1] or ''} |")
        L.append("")
    if promote:
        L += ["## 승격 후보 (3회 이상 만남 — 레지스트리 등록 추천)", "",
              "| 이름 | 만남 | 처음 | 최근 |", "|---|---|---|---|"]
        for p, (n, first, last) in promote:
            L.append(f"| {p} | {n}회 | {first} | {last} |")
        L.append("")
    L += [f"## Contacts ({len(contacts)}) — 트랜스크립트에서 자동 수집", ""]
    for p, (n, first, last) in contacts:
        L.append(f"- {p} · {n}회 · {first} ~ {last}")
    open(os.path.join(pdir, "INDEX.md"), "w", encoding="utf-8").write("\n".join(L) + "\n")

    print(f"OK: {len(written)} dossiers → people/ | contacts {len(contacts)} "
          f"| promotion candidates {len(promote)} → people/INDEX.md")

if __name__ == "__main__":
    main()
