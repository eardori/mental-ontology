#!/usr/bin/env python3
"""브리핑 — surface what the user missed, without them having to ask.

Every other script in this corpus is pull: you ask, it answers. But you cannot ask
about what you did not notice. This one pushes: after a sync it says what happened in
the room that deserves attention, and before a meeting it says what you owe the person
you are about to see.

Everything here is COMPUTED from the database — commitments, open readings, dates,
turn counts. Nothing is inferred at briefing time, so a briefing cannot hallucinate;
the honest numbers are the product. The LLM may add prose on top, never new facts.

Usage
  python3 build_briefing.py <corpus> --meeting <source_id|path-substring>   # 회의 직후
  python3 build_briefing.py <corpus> --with "<이름>"                        # 만나기 전 30초
  python3 build_briefing.py <corpus> --upcoming [YYYY-MM-DD]               # 내일 일정 기준
  python3 build_briefing.py <corpus> [--days 7]                            # 주간 다이제스트
  ... [--me "<내 이름>"] [--out FILE]

`--me` is the corpus owner (whose promises are "내가 한 약속"). It defaults to the
registry entry marked `"owner": true`, else the most-attending person (reported as a
guess). Output is markdown on stdout; `--out` also writes it to a file.

Deps: python3 stdlib only. Reads _ontology/ontology.db (+ _meta/speakers.json).
"""
import argparse, glob, json, os, re, sqlite3, sys
from datetime import date, timedelta

QUIET_DAYS = 45          # 이 기간 넘게 접촉 없으면 관계 신호로 올림
AGING_DAYS = 14          # 약속이 이 기간 넘게 열려 있으면 강조
GENERIC = re.compile(r'^(speaker|발화자|화자)\s*\d*$', re.I)


def load_registry(corpus):
    p = os.path.join(corpus, "_meta", "speakers.json")
    if not os.path.exists(p):
        return []
    try:
        return json.load(open(p, encoding="utf-8"))
    except json.JSONDecodeError:
        return []


def pick_owner(db, registry, explicit):
    """Who is '나'? Explicit > registry owner flag > most-attending person (a guess)."""
    if explicit:
        return explicit, "지정"
    for e in registry:
        if e.get("owner") is True:
            return e.get("name"), "레지스트리"
    row = db.execute("""SELECT person, COUNT(*) n FROM person_meetings
                        GROUP BY person ORDER BY n DESC LIMIT 1""").fetchone()
    if row and not GENERIC.match(row[0] or ""):
        return row[0], "추정"
    return None, "없음"


def onto_meeting_id(corpus, source_id):
    """objects.json meetings[].id for a transcript's source_id (None if unmapped)."""
    op = os.path.join(corpus, "_ontology", "objects.json")
    if not os.path.exists(op) or not source_id:
        return None
    try:
        d = json.load(open(op, encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    for m in d.get("meetings", []):
        if m.get("source_id") == source_id:
            return m.get("id")
    return None


def days_between(a, b):
    try:
        return (date.fromisoformat(str(a)[:10]) - date.fromisoformat(str(b)[:10])).days
    except (ValueError, TypeError):
        return None


def newest_date(db):
    row = db.execute("SELECT MAX(date) FROM meetings").fetchone()
    return row[0] if row and row[0] else date.today().isoformat()


def open_readings(db, who=None, meeting=None):
    q = """SELECT r.id, r.who, r.date, r.surface, r.reading, r.confidence, r.meeting
           FROM readings r WHERE r.status = '추정'"""
    args = []
    if who:
        q += " AND r.who = ?"
        args.append(who)
    if meeting:
        q += " AND r.meeting = ?"
        args.append(meeting)
    rows = db.execute(q + " ORDER BY r.date DESC", args).fetchall()
    out = []
    for rid, w, dt, surface, reading, conf, mtg in rows:
        sig = db.execute("""SELECT kind, detail FROM reading_basis WHERE reading_id = ?""",
                         (rid,)).fetchall()
        out.append({"id": rid, "who": w, "date": dt, "surface": surface, "reading": reading,
                    "confidence": conf, "meeting": mtg,
                    "signals": [(k, d) for k, d in sig]})
    return out


def commitments_for(db, person=None, meeting_rowid=None, only_open=True):
    q = """SELECT c.done, c.from_person, c.to_person, c.text, c.due, m.date, m.title
           FROM commitments c JOIN meetings m ON m.rowid = c.meeting_rowid WHERE 1=1"""
    args = []
    if only_open:
        q += " AND c.done = 0"
    if person:
        q += " AND (c.from_person = ? OR c.to_person = ?)"
        args += [person, person]
    if meeting_rowid is not None:
        q += " AND c.meeting_rowid = ?"
        args.append(meeting_rowid)
    return db.execute(q + " ORDER BY m.date DESC", args).fetchall()


def talk_shares(db, meeting_rowid):
    """Turn counts, characters and questions per speaker — countable, so honest.

    Returns (rows, unattributed_pct). Unattributed share is always reported: a talk
    share computed over 60% of the room is a number that lies by omission.
    """
    rows = db.execute("""SELECT speaker, COUNT(*) turns, SUM(LENGTH(text)) chars,
                                SUM(CASE WHEN text LIKE '%?%' THEN 1 ELSE 0 END) qs
                         FROM utterances WHERE meeting_rowid = ?
                         GROUP BY speaker""", (meeting_rowid,)).fetchall()
    named, unattr = [], 0
    for spk, turns, chars, qs in rows:
        if not spk or GENERIC.match(spk):
            unattr += chars or 0
            continue
        named.append([spk, turns, chars or 0, qs or 0])
    total = sum(r[2] for r in named) + unattr
    named.sort(key=lambda r: -r[2])
    # percentages are of the WHOLE meeting, not of the identified part — renormalizing
    # over named speakers only would inflate every share by 1/(1-unattributed).
    for r in named:
        r.append(100.0 * r[2] / total if total else 0.0)
    return named, (100.0 * unattr / total if total else 0.0)


# ------------------------------------------------------------------ briefings

def brief_meeting(db, corpus, key, me):
    row = db.execute("""SELECT rowid, source_id, date, title, category, participants, path
                        FROM meetings WHERE source_id = ? OR path LIKE ?
                        ORDER BY CASE WHEN source_id = ? THEN 0 ELSE 1 END, date DESC
                        LIMIT 1""", (key, f"%{key}%", key)).fetchone()
    if not row:
        return [f"# 브리핑", "", f"'{key}' 에 해당하는 회의를 찾지 못했습니다 "
                "(source_id 또는 파일명 일부로 지정하세요)."]
    rid, sid, mdate, title, cat, parts, path = row
    # participants[] in frontmatter is raw (wikilinks, \u escapes, role words); person_meetings
    # is the cleaned, alias-resolved set build_db derived from participants + speakers.
    people = [r[0] for r in db.execute(
        "SELECT DISTINCT person FROM person_meetings WHERE meeting_rowid = ? ORDER BY person",
        (rid,)).fetchall() if r[0] and not GENERIC.match(r[0])]
    setting = db.execute("SELECT setting FROM meetings WHERE rowid = ?", (rid,)).fetchone()
    setting = setting[0] if setting else ""
    L = [f"# 회의 직후 브리핑 — {title}", "",
         f"`{mdate}` · {cat or '분류 없음'}" + (f" · {setting}" if setting else "")
         + f" · {', '.join(people) or parts or ''}", ""]

    # 1) 내가 한 약속 / 내가 받은 약속 — 관계의 신뢰는 여기서 갈린다
    new_c = commitments_for(db, meeting_rowid=rid, only_open=False)
    mine = [c for c in new_c if me and c[1] == me]
    theirs = [c for c in new_c if not me or c[1] != me]
    if mine or theirs:
        L.append(f"## 이 회의에서 생긴 약속 ({len(new_c)})")
        for done, frm, to, text, due, *_ in mine:
            L.append((f"- ✓ ~~{text}~~ (완료)" if done else
                      f"- ⚡ **내가 해야 할 것** → {to or '?'}: {text}"
                      + (f" · 기한 `{due}`" if due else "")))
        for done, frm, to, text, due, *_ in theirs:
            L.append((f"- ✓ ~~{text}~~ (완료)" if done else
                      f"- ○ {frm or '?'} → {to or '?'}: {text}"
                      + (f" · 기한 `{due}`" if due else "")))
        L.append("")

    # 2) 상대가 원한 것 (추정) + 확인 질문
    # readings[].meeting is an objects.json meeting id (m1); the DB keys meetings by
    # source_id — map through objects.json so two meetings on ONE day never mix.
    onto_id = onto_meeting_id(corpus, sid)
    reads = [r for r in open_readings(db)
             if (r["meeting"] == onto_id if (onto_id and r["meeting"]) else r["date"] == mdate)]
    if reads:
        L.append(f"## 놓쳤을 수 있는 것 — 대화 의도 (추정 {len(reads)})")
        L.append("> 추정입니다. 다음에 한 번 확인하면 그때부터 데이터가 됩니다.")
        for r in reads:
            sig = ", ".join(f"{k}({d})" if d else k for k, d in r["signals"])
            L.append(f"- **{r['who']}**: {r['reading']} ({r['confidence']})")
            L.append(f"    - 실제 발언: \"{r['surface']}\"" + (f" · 신호: {sig}" if sig else ""))
        L.append("")

    # 3) 답 없이 지나간 것 — 무응답/화제전환은 그 자리에선 거의 안 보인다
    ids = [r["id"] for r in reads]
    dodged = db.execute(
        "SELECT r.who, b.kind, b.detail FROM readings r "
        "JOIN reading_basis b ON b.reading_id = r.id "
        f"WHERE r.id IN ({','.join('?' * len(ids))}) "
        "AND b.kind IN ('무응답','화제전환')", ids).fetchall() if ids else []
    closing = db.execute(
        "SELECT r.who, b.detail FROM readings r JOIN reading_basis b ON b.reading_id = r.id "
        f"WHERE r.id IN ({','.join('?' * len(ids))}) AND b.kind = '마무리발언'",
        ids).fetchall() if ids else []
    if dodged:
        L.append("## 답 없이 지나간 대목")
        for who, kind, detail in dodged:
            L.append(f"- {who} · **{kind}**" + (f" — {detail}" if detail else ""))
        L.append("")
    if closing:
        L.append("## 문 앞에서 나온 말 — 진짜 용건일 수 있음")
        for who, detail in closing:
            L.append(f"- {who}" + (f" · {detail}" if detail else ""))
        L.append("")

    # 4) 이 사람들과 아직 안 끝난 것 (이전 회의에서 넘어온 오픈 루프)
    carried = []
    for p in people:
        for c in commitments_for(db, person=p, only_open=True):
            if c[5] != mdate:
                carried.append(c)
    seen, uniq = set(), []
    for c in carried:
        k = (c[1], c[2], c[3])
        if k not in seen:
            seen.add(k)
            uniq.append(c)
    if uniq:
        L.append(f"## 아직 안 끝난 것 — 참석자와의 오픈 루프 ({len(uniq)})")
        newest = newest_date(db)
        for _d, frm, to, text, due, cdate, ctitle in uniq[:8]:
            age = days_between(newest, cdate)
            L.append(f"- {frm or '?'} → {to or '?'}: {text} · `{cdate}`"
                     + (f" · **{age}일 경과**" if age and age > AGING_DAYS else ""))
        L.append("")

    # 5) 관찰된 것 (셀 수 있는 것만 — 추정 아님)
    shares, unattr = talk_shares(db, rid)
    if shares:
        L.append("## 관찰 (추정 아님 — 센 것)")
        bits = [f"{s[0]} {s[4]:.0f}%(질문 {s[3]})" for s in shares[:5]]
        L.append(f"- 발화 비중: " + " · ".join(bits)
                 + (f" · 미상 {unattr:.0f}%" if unattr > 1 else ""))
        if unattr > 5:
            L.append(f"- ⚠ 화자 미상 {unattr:.0f}% — 비중은 그만큼 부정확합니다 "
                     "(화자 정리 후 다시 보세요)")
        qs = [s for s in shares if s[3] == 0]
        if qs and len(shares) > 1 and any(s[3] > 0 for s in shares):
            L.append(f"- 질문을 한 번도 하지 않은 사람: {', '.join(s[0] for s in qs)}")
        L.append("")

    # 6) 처음 등장한 사람 — 단, 어떻게 만났는지가 아직 기록되지 않은 사람만.
    #    이미 first_met_context가 있으면 알릴 이유가 없다 (브리핑은 할 일만 남긴다).
    reg = {e.get("name"): e for e in load_registry(corpus)}
    new_people = []
    for p in people:
        if me and p == me:
            continue
        e = reg.get(p, {})
        if e.get("first_met_context") or e.get("intro_by"):
            continue
        first = db.execute("""SELECT MIN(m.date) FROM person_meetings pm
                              JOIN meetings m ON m.rowid = pm.meeting_rowid
                              WHERE pm.person = ?""", (p,)).fetchone()
        if first and first[0] == mdate:
            new_people.append(p)
    if new_people:
        L.append("## 처음 만난 사람")
        for p in new_people:
            L.append(f"- **{p}** — 어떻게 알게 된 사이인지 지금 기록해두면 나중에 못 찾습니다 "
                     "(`_meta/speakers.json`의 first_met_context / intro_by)")
        L.append("")
    if len(L) <= 4:
        L.append("이 회의에서 특별히 챙길 것은 잡히지 않았습니다.")
    return L


def resolve_person(db, registry, name):
    """'서연님' → '이서연'. The entry point is natural language, so aliases are normal."""
    names = {e.get("name") for e in registry}
    if name in names:
        return name
    row = db.execute("SELECT canonical FROM person_aliases WHERE alias = ? LIMIT 1",
                     (name,)).fetchone()
    if row:
        return row[0]
    row = db.execute("SELECT person FROM person_meetings WHERE person = ? LIMIT 1",
                     (name,)).fetchone()
    return row[0] if row else name


def brief_person(db, corpus, name, me, registry):
    given, name = name, resolve_person(db, registry, name)
    L = [f"# 만나기 전 브리핑 — {name}"
         + (f"  <sub>('{given}' → 정식 이름)</sub>" if given != name else ""), ""]
    entry = next((e for e in registry if e.get("name") == name), {})
    mts = db.execute("""SELECT m.date, m.title, m.category FROM person_meetings pm
                        JOIN meetings m ON m.rowid = pm.meeting_rowid
                        WHERE pm.person = ? ORDER BY m.date DESC""", (name,)).fetchall()
    if not mts and not entry:
        return L + [f"'{name}' 에 대한 기록이 없습니다. 이름이 정확한지 확인하세요."]
    newest = newest_date(db)
    ident = " · ".join(x for x in [entry.get("role", ""), entry.get("org", ""),
                                   entry.get("relationship", "")] if x)
    if ident:
        L.append(ident)
    if mts:
        gap = days_between(newest, mts[0][0])
        L.append(f"마지막 접촉 `{mts[0][0]}` ({mts[0][1]})"
                 + (f" · {gap}일 전" if gap else "") + f" · 총 {len(mts)}회")
    L.append("")

    # 1) 내가 이 사람에게 빚진 것 — 브리핑의 첫 줄은 언제나 이것
    cs = commitments_for(db, person=name, only_open=True)
    mine = [c for c in cs if me and c[1] == me]
    theirs = [c for c in cs if not me or c[1] != me]
    if mine:
        L.append(f"## ⚡ 내가 아직 안 한 것 ({len(mine)})")
        for _d, frm, to, text, due, cdate, _t in mine:
            age = days_between(newest, cdate)
            L.append(f"- {text}" + (f" · 기한 `{due}`" if due else "") + f" · `{cdate}`"
                     + (f" · **{age}일 경과**" if age and age > AGING_DAYS else ""))
        L.append("")
    if theirs:
        L.append(f"## 상대가 하기로 한 것 ({len(theirs)})")
        for _d, frm, to, text, due, cdate, _t in theirs[:6]:
            L.append(f"- {frm or '?'} → {to or '?'}: {text} · `{cdate}`")
        L.append("")

    # 2) 확인할 추정 — 물어볼 질문 한 줄로 바꿔서
    reads = open_readings(db, who=name)
    if reads:
        L.append(f"## 확인해볼 것 — 미확인 의도 추정 ({len(reads)})")
        for r in reads[:5]:
            sig = ", ".join(f"{k}({d})" if d else k for k, d in r["signals"])
            L.append(f"- {r['reading']} ({r['confidence']}, `{r['date']}`)"
                     + (f" · 신호: {sig}" if sig else ""))
        L.append("> 한 번 물어보면 ✅/❌로 정산됩니다 — 추측을 데이터로 바꾸는 유일한 방법입니다.")
        L.append("")

    # 3) 이 사람과 일하는 법 (objects.json playbook) + 충돌 축
    op = os.path.join(corpus, "_ontology", "objects.json")
    if os.path.exists(op):
        try:
            d = json.load(open(op, encoding="utf-8"))
        except json.JSONDecodeError:
            d = {}          # mid-edit or truncated — degrade, do not crash a briefing
        person = next((p for p in d.get("people", []) if p.get("name") == name), {})
        if person.get("playbook"):
            L += ["## 이 사람과 일할 때", f"- {person['playbook']}", ""]
        axes = [x for x in d.get("conflict_axes", []) if me and name in (x.get("a"), x.get("b"))
                and me in (x.get("a"), x.get("b"))]
        if axes:
            L.append("## 나와의 충돌 축 — 공유하는 공리부터")
            for x in axes:
                L.append(f"- **{x.get('axis','')}**")
                if x.get("shared_axiom"):
                    L.append(f"    - 공유 공리: {x['shared_axiom']}")
            L.append("")

    # 4) 개인 맥락 — use 태그를 그대로 존중한다
    personal = entry.get("personal") or []
    if personal:
        L.append("## 개인 맥락")
        MARK = {"공개": "", "사적": "△ ", "언급금지": "⛔ "}
        for p in personal[-6:]:
            if isinstance(p, dict):
                L.append(f"- {MARK.get(p.get('use', ''), '')}({p.get('date','')}) {p.get('note','')}")
            else:
                L.append(f"- {p}")
        L.append("> △/⛔ 는 내가 먼저 꺼내지 않는다 — 상대가 말할 때만 반응.")
        L.append("")

    if mts:
        L.append("## 최근 접촉")
        for dt, title, cat in mts[:5]:
            L.append(f"- `{dt}` {title}" + (f" · {cat}" if cat else ""))
        L.append("")
    return L


def brief_digest(db, corpus, days, me, registry):
    newest = newest_date(db)
    try:
        since = (date.fromisoformat(newest[:10]) - timedelta(days=days)).isoformat()
    except ValueError:
        since = "0000-00-00"
    L = [f"# {days}일 다이제스트 — {since} ~ {newest}", ""]

    mts = db.execute("""SELECT date, title, category FROM meetings
                        WHERE date >= ? ORDER BY date DESC""", (since,)).fetchall()
    L.append(f"회의 {len(mts)}건" + (f" · 최근: {mts[0][1]}" if mts else ""))
    L.append("")

    # 1) 오래 열려 있는 약속 — 신뢰가 새는 곳
    cs = commitments_for(db, only_open=True)
    aged = []
    for c in cs:
        age = days_between(newest, c[5])
        if age is not None and age > AGING_DAYS:
            aged.append((age, c))
    aged.sort(key=lambda x: -x[0])
    if aged:
        L.append(f"## ⚡ 오래 열려 있는 약속 ({len(aged)})")
        for age, (_d, frm, to, text, due, cdate, _t) in aged[:8]:
            mark = "**내 것** · " if me and frm == me else ""
            L.append(f"- {mark}{frm or '?'} → {to or '?'}: {text} · `{cdate}` · **{age}일**")
        L.append("")

    # 2) 확인 안 된 추정
    reads = open_readings(db)
    if reads:
        L.append(f"## 확인 안 된 의도 추정 ({len(reads)})")
        for r in reads[:8]:
            L.append(f"- **{r['who']}** ({r['date']}): {r['reading']} ({r['confidence']})")
        hit = db.execute("SELECT COUNT(*) FROM readings WHERE status='확인됨'").fetchone()[0]
        miss = db.execute("SELECT COUNT(*) FROM readings WHERE status='빗나감'").fetchone()[0]
        if hit + miss:
            L.append(f"> 지금까지 적중률: {hit}/{hit + miss} "
                     f"({100.0 * hit / (hit + miss):.0f}%)")
        L.append("")

    # 3) 조용해진 관계 — 만나지 않으면 관계는 조용히 식는다
    quiet = []
    known = {e.get("name"): e for e in registry
             if (e.get("tier") or "core") in ("core", "acquaintance")}
    for name, e in known.items():
        row = db.execute("""SELECT MAX(m.date) FROM person_meetings pm
                            JOIN meetings m ON m.rowid = pm.meeting_rowid
                            WHERE pm.person = ?""", (name,)).fetchone()
        if not row or not row[0]:
            continue
        gap = days_between(newest, row[0])
        if gap is not None and gap >= QUIET_DAYS:
            quiet.append((gap, name, row[0], e.get("relationship", "")))
    quiet.sort(reverse=True)
    if quiet:
        L.append(f"## 조용해진 관계 ({len(quiet)}) — {QUIET_DAYS}일 이상 접촉 없음")
        for gap, name, last, rel in quiet[:8]:
            L.append(f"- **{name}**{f' ({rel})' if rel else ''} · 마지막 `{last}` · {gap}일 전")
        L.append("")

    # 4) 이 기간에 처음 만난 사람
    newp = db.execute("""SELECT pm.person, MIN(m.date) f FROM person_meetings pm
                         JOIN meetings m ON m.rowid = pm.meeting_rowid
                         GROUP BY pm.person HAVING f >= ? ORDER BY f DESC""",
                      (since,)).fetchall()
    newp = [(p, f) for p, f in newp if not GENERIC.match(p or "")]
    if newp:
        L.append(f"## 이 기간에 처음 만난 사람 ({len(newp)})")
        for p, f in newp[:10]:
            in_reg = "" if p in {e.get("name") for e in registry} else " · ⚠ 레지스트리에 없음"
            L.append(f"- **{p}** · 첫 접촉 `{f}`{in_reg}")
        L.append("")
    if len(L) <= 4:
        L.append("이 기간에 특별히 챙길 것은 잡히지 않았습니다.")
    return L


def brief_upcoming(db, corpus, when, me, registry):
    """캐시된 캘린더에서 그날 일정을 읽어, 만날 사람마다 '지금 걸려 있는 것'을 붙인다."""
    events = []
    for p in sorted(glob.glob(os.path.join(corpus, "_meta", "calendar", "*.json"))):
        try:
            d = json.load(open(p, encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        for e in d.get("events", []):
            if str(e.get("start", ""))[:10] == when:
                events.append(e)
    events.sort(key=lambda e: str(e.get("start", "")))
    L = [f"# 다가오는 일정 브리핑 — {when}", ""]
    if not events:
        return L + [f"`_meta/calendar/` 캐시에 {when} 일정이 없습니다 — "
                    "스킬에 '캘린더 가져와줘'라고 하면 채워집니다."]
    for e in events:
        t = str(e.get("start", ""))[11:16]
        L.append(f"## {t or '시간미상'} {e.get('title','(제목 없음)')}")
        if e.get("location"):
            L.append(f"장소: {e['location']}")
        names = [a.get("name") or a.get("email", "") for a in (e.get("attendees") or [])]
        known = []
        for raw in [n for n in names if n]:
            n = resolve_person(db, registry, raw)
            if me and n == me:
                continue
            mt = db.execute("""SELECT MAX(m.date), COUNT(*) FROM person_meetings pm
                               JOIN meetings m ON m.rowid = pm.meeting_rowid
                               WHERE pm.person = ?""", (n,)).fetchone()
            if not mt or not mt[0]:
                # 이름 표기가 다를 뿐인 경우가 흔하다(캘린더 'Mina Kim' ↔ 코퍼스 'Mina').
                # 단정하지 않고 후보만 제시한다 — 별칭은 사람이 확정해야 하는 조인 키다.
                base = re.sub(r'[^\w가-힣]', '', raw).lower()
                cand = [n for n in {e.get("name") for e in registry if e.get("name")}
                        if n and (base in re.sub(r'[^\w가-힣]', '', n).lower()
                                  or re.sub(r'[^\w가-힣]', '', n).lower() in base)]
                hint = (f" · 혹시 **{cand[0]}**? 맞으면 speakers.json의 aliases에 "
                        f"'{raw}' 를 추가하세요" if cand else "")
                L.append(f"- **{raw}** — 코퍼스에 기록 없음 (첫 만남이거나 이름 표기 차이){hint}")
                continue
            owed = [c for c in commitments_for(db, person=n, only_open=True)
                    if me and c[1] == me]
            reads = open_readings(db, who=n)
            gap = days_between(newest_date(db), mt[0])
            bits = [f"마지막 `{mt[0]}`" + (f" ({gap}일 전)" if gap else ""), f"총 {mt[1]}회"]
            if owed:
                bits.append(f"⚡**내가 안 한 것 {len(owed)}건**")
            if reads:
                bits.append(f"확인할 추정 {len(reads)}건")
            L.append(f"- **{n}** — " + " · ".join(bits))
            for _d, frm, to, text, due, cdate, _t in owed[:2]:
                L.append(f"    - ⚡ {text}" + (f" · 기한 `{due}`" if due else ""))
            for r in reads[:2]:
                L.append(f"    - ❓ {r['reading']} ({r['confidence']})")
            known.append(n)
        if known:
            L.append(f"> 상세: `build_briefing.py <corpus> --with \"{known[0]}\"`")
        L.append("")
    return L


def main():
    ap = argparse.ArgumentParser(description="놓친 것을 먼저 말해주는 브리핑 생성기")
    ap.add_argument("corpus")
    ap.add_argument("--meeting", help="회의 직후 브리핑 (source_id 또는 파일명 일부)")
    ap.add_argument("--with", dest="person", help="이 사람을 만나기 전 브리핑")
    ap.add_argument("--days", type=int, default=7, help="다이제스트 기간 (기본 7일)")
    ap.add_argument("--upcoming", nargs="?", const="tomorrow", metavar="YYYY-MM-DD",
                    help="캐시된 캘린더의 그날 일정 + 사람별 걸려 있는 것 (기본: 내일)")
    ap.add_argument("--me", help="내 정식 이름 (기본: 레지스트리 owner:true → 최다 참석자)")
    ap.add_argument("--out", help="마크다운을 파일로도 저장")
    a = ap.parse_args()

    corpus = os.path.abspath(a.corpus)
    dbp = os.path.join(corpus, "_ontology", "ontology.db")
    if not os.path.exists(dbp):
        sys.exit(f"ERROR: {dbp} 없음 — 먼저 build_db.py를 실행하세요.")
    db = sqlite3.connect(dbp)
    have = {r[0] for r in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    missing = {"readings", "reading_basis", "commitments", "person_meetings"} - have
    if not missing:   # tables can exist while a newer column does not
        cols = {r[1] for r in db.execute("PRAGMA table_info(meetings)").fetchall()}
        missing = {f"meetings.{c}" for c in ("setting", "start_time") if c not in cols}
    if missing:
        sys.exit(f"ERROR: ontology.db가 오래된 스키마입니다 (없는 것: {sorted(missing)}) — "
                 f"python3 build_db.py {a.corpus} 를 먼저 실행하세요.")
    registry = load_registry(corpus)
    me, how = pick_owner(db, registry, a.me)

    if a.upcoming:
        when = (date.today() + timedelta(days=1)).isoformat() \
            if a.upcoming == "tomorrow" else a.upcoming
        L = brief_upcoming(db, corpus, when, me, registry)
    elif a.meeting:
        L = brief_meeting(db, corpus, a.meeting, me)
    elif a.person:
        L = brief_person(db, corpus, a.person, me, registry)
    else:
        L = brief_digest(db, corpus, a.days, me, registry)

    if how == "추정" and me:
        L += ["---", f"> '나' = **{me}** 로 가정했습니다 (최다 참석자). 틀렸다면 "
              "`_meta/speakers.json`에서 본인 항목에 `\"owner\": true` 를 넣거나 `--me` 로 지정하세요."]
    elif how == "없음":
        L += ["---", "> 코퍼스 소유자를 특정하지 못해 '내가 한 약속'을 구분하지 못했습니다 — "
              "`_meta/speakers.json`에서 본인 항목에 `\"owner\": true` 를 넣으세요."]
    text = "\n".join(L).rstrip() + "\n"
    print(text)
    if a.out:
        os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
        open(a.out, "w", encoding="utf-8").write(text)
        print(f"(저장: {a.out})")


if __name__ == "__main__":
    main()
