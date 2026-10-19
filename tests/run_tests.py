#!/usr/bin/env python3
"""Self-contained test suite for the mental-ontology pipeline scripts.

Usage: python3 tests/run_tests.py

Builds fictional (Acme) corpora in a temp dir, then exercises the real CLI
contract of every script: build_index → build_db → validate → migrate.
Asserts: all utterance line formats parse, aliases resolve to canonical names,
warnings fire (zero-utterance files, duplicate source_ids — but not _part
splits), validate catches integrity/honesty violations, and the v1→v2
migration classifies, canonicalizes, and caps evidence correctly.

No external dependencies (python3 stdlib only). Exit 0 = all green.
"""
import json, os, re, shutil, sqlite3, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "skills" / "mental-ontology" / "scripts"

PASS = 0
FAILURES = []

def check(name, cond, detail=""):
    global PASS
    if cond:
        PASS += 1
        print(f"  ok  {name}")
    else:
        FAILURES.append(name)
        print(f"FAIL  {name}" + (f"\n      {detail}" if detail else ""))

def run(script, *args):
    r = subprocess.run([sys.executable, str(SCRIPTS / script), *map(str, args)],
                       capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr

def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")

FM = """---
title: "{title}"
date: {date}
category: {cat}
participants: [{parts}]
source_id: {sid}
duration_min: 10
transcribed_by: plaud
{extra}---

# {title}

## 요약
가상 테스트 데이터.

## 트랜스크립트
{body}
"""

def make_transcript(root, fname, title, date, sid, body, cat="내부-전략",
                    parts="정우진, 이서연", extra=""):
    write(root / "transcripts" / date[:4] / date[:7] / fname,
          FM.format(title=title, date=date, cat=cat, parts=parts, sid=sid,
                    extra=extra, body=body))

SPEAKERS = [
    {"name": "정우진", "role": "CEO", "org": "Acme",
     "aliases": ["우진님", "James(정우진)"], "traits": "", "meetings": [],
     "personal": [{"date": "2026-05-20", "note": "10월 마라톤 준비 중", "use": "사적"},
                  {"date": "2026-05-21", "note": "가족 건강 이슈 언급", "use": "언급금지"}]},
    {"name": "이서연", "role": "CPO", "org": "Acme", "aliases": ["서연님"],
     "traits": "", "meetings": [], "relationship": "팀원",
     "team": "제품본부", "manager": "정우진"},
    {"name": "박도현", "role": "CFO", "org": "Acme", "aliases": [],
     "traits": "", "meetings": []},
]

def objects_v2(m1_path, m2_path):
    return {
        "meta": {"schema_version": 2, "title": "Acme 온톨로지 (테스트)", "org": "Acme",
                 "sensitivity": "L2", "processed_source_ids": ["acme-0520", "acme-0521"]},
        "meetings": [
            {"id": "m1", "date": "2026-05-20", "title": "전략회의",
             "source_id": "acme-0520", "path": m1_path},
            {"id": "m2", "date": "2026-05-21", "title": "통화 선지급",
             "source_id": "acme-0521", "path": m2_path},
        ],
        "people": [
            {"name": "정우진", "type": "person", "role": "CEO", "summary": "속도 지향",
             "evidence": "high", "models": ["speed-first", "competitor-watch"]},
            {"name": "이서연", "type": "person", "role": "CPO", "summary": "가치 우선",
             "evidence": "mid", "models": ["value-first"]},
            {"name": "넥스트라", "type": "org", "role": "경쟁사", "summary": "가상 경쟁사",
             "evidence": "mid", "models": []},
        ],
        "models": [
            {"id": "speed-first", "category": "전략", "title": "속도가 먼저다",
             "evidence": "high", "holders": ["정우진"], "quote": "일단 던지고 배운다"},
            {"id": "value-first", "category": "제품", "title": "가치가 먼저다",
             "evidence": "mid", "holders": ["이서연"]},
            {"id": "competitor-watch", "category": "리스크", "title": "경쟁사 견제 대비",
             "evidence": "mid", "holders": ["정우진"], "about": ["넥스트라"]},
        ],
        "relations": [
            {"from": "정우진", "to": "이서연", "type": "tension", "topic": "속도 vs 가치"},
        ],
        "network": [
            {"a": "이서연", "b": "정우진", "kind": "소개", "since": "2024-11-01",
             "note": "SaaS 밋업에서 소개"},
        ],
        "bets": [{"tag": "test", "title": "구독료 단계적 인상", "status": "진행중",
                  "owner": "정우진", "date": "2026-05-20", "source": ["2026-05-20"]}],
        "timeline": [{"date": "2026-05-20", "meeting": "m1", "change": "방향 제시"}],
        "readings": [
            {"id": "r-1", "who": "정우진", "meeting": "m1", "date": "2026-05-20",
             "surface": "속도가 먼저다, 일단 던지고 배운다",
             "reading": "이번 분기 안에 뭐라도 내보내길 원한다",
             "basis": [{"kind": "반복", "detail": "2회",
                        "quote": "속도가 먼저다, 일단 던지고 배운다"},
                       {"kind": "마무리발언", "detail": "회의 종료 직전"}],
             "confidence": "보통", "evidence_type": "direct", "status": "추정",
             "related_models": ["speed-first"]},
            {"id": "r-2", "who": "이서연", "meeting": "m1", "date": "2026-05-20",
             "surface": "번들 기능 스펙은 다음 주에", "reading": "리소스 부족을 우회적으로 말한다",
             "basis": [{"kind": "양보조건", "detail": "동의하되 기한을 미룸"}],
             "confidence": "낮음", "evidence_type": "direct", "status": "확인됨",
             "resolution": {"date": "2026-05-21", "meeting": "m2",
                            "note": "다음 통화에서 인력 요청으로 확인됨"}},
        ],
        "traps": [{"who": "정우진", "model_id": "speed-first",
                   "desc": "선언이 반복되면 신뢰 예산이 소진된다", "state": "미해결",
                   "evidence_type": "direct", "source": "2026-05-20 회의"}],
        "conflict_axes": [{"a": "정우진", "b": "이서연", "axis": "속도 vs 가치",
                           "shared_axiom": "LTV가 전부다", "a_side": "먼저 던진다",
                           "b_side": "먼저 준다", "evidence_type": "direct"}],
    }

def build_corpus_v2(root):
    write(root / "_meta" / "speakers.json", json.dumps(SPEAKERS, ensure_ascii=False))
    make_transcript(root, "2026-05-20_전략회의.md", "전략회의", "2026-05-20", "acme-0520",
        "**[정우진] (00:01)** 대괄호 기본 형식.\n"
        "**[Speaker 2] (00:15)** 미확정 화자.\n"
        "**우진님 (00:30)** 대괄호 없는 별칭.\n"
        "**[James(정우진)] (00:45)** 괄호 포함 별칭.\n"
        "**[정우진] (00:50)** 속도가 먼저다, 일단 던지고 배운다.\n"
        "**(01:00)** 화자 없는 별표.\n"
        "(01:10) 맨 괄호 타임스탬프.\n"
        "**[] (01:20)** 빈 대괄호.\n"
        "**[Naomi Park] (1:02:33)** 한 시간 넘는 타임스탬프.\n"
        "\n"
        "## 액션아이템\n"
        "- [ ] (정우진→이서연) 번들 기능 스펙 초안 (기한: 2026-05-27)\n"
        "- [x] (서연님→정우진) 가격 리서치 공유")
    make_transcript(root, "2026-05-21_통화-선지급.md", "통화 선지급", "2026-05-21", "acme-0521",
        "**(시간: 0:00)** 시간 접두어 형식.\n"
        "[00:01 - 00:36] 대괄호 범위 형식.\n"
        "[01:20] 대괄호 단일 형식.", cat="개인-통화", parts="정우진")
    make_transcript(root, "2026-05-22_외부미팅-넥스트라.md", "외부미팅 넥스트라",
        "2026-05-22", "acme-0522",
        "**정우진** (00:09)\n다음 줄에 있는 본문.\n\n**Mina** (00:12): 콜론 인라인 본문.",
        cat="외부-파트너", parts="정우진, Mina")
    make_transcript(root, "2026-05-23_요약만.md", "요약만 있는 파일", "2026-05-23",
        "acme-0523", "(요약만 있고 발화 없음)")
    for suffix in ("a", "b"):  # same source_id, different slugs → duplicate
        make_transcript(root, f"2026-05-24_중복-{suffix}.md", f"중복 {suffix}",
            "2026-05-24", "acme-0524", "**[정우진] (00:01)** 중복 테스트.")
    for n in ("1", "2"):       # _part split shares source_id → NOT a duplicate
        make_transcript(root, f"2026-05-25_긴녹음_part{n}.md", f"긴 녹음 part{n}",
            "2026-05-25", "acme-0525", "**[정우진] (00:01)** 파트 테스트.",
            extra=f'part: "{n}/2"\n')
    # polluted participants: wikilink wrapper, quoted alias, \u-escapes, role-word, letter
    # + wikilink-wrapped SPEAKER label in the transcript body
    make_transcript(root, "2026-05-26_오염된-참석자.md", "오염된 참석자", "2026-05-26",
        "acme-0526",
        "**[정우진] (00:01)** 참석자 정제 테스트.\n"
        "**[[정우진]]** (00:05) 위키링크 화자 라벨.",
        parts="[[정우진]], '서연님', \\uc774\\uc11c\\uc5f0, 대표, A")
    write(root / "_ontology" / "objects.json", json.dumps(objects_v2(
        "transcripts/2026/2026-05/2026-05-20_전략회의.md",
        "transcripts/2026/2026-05/2026-05-21_통화-선지급.md"), ensure_ascii=False))

def test_pipeline_v2(tmp):
    print("\n[1] build_index + build_db on a v2 corpus — formats, aliases, warnings")
    root = tmp / "corpus_v2"
    build_corpus_v2(root)
    rc, out = run("build_index.py", root)
    check("build_index exits 0", rc == 0, out)
    rc, out = run("build_db.py", root)
    check("build_db exits 0", rc == 0, out)
    check("zero-utterance WARN names the summary-only file",
          "요약만" in out and "ZERO utterances" in out, out)
    check("duplicate source_id WARN fires for acme-0524", "acme-0524" in out, out)
    check("_part split is NOT flagged as duplicate", "acme-0525" not in out, out)
    check("no unparsed-line WARN on clean fixture", "did not parse" not in out, out)

    db = sqlite3.connect(root / "_ontology" / "ontology.db")
    q = lambda s, *a: db.execute(s, a).fetchall()
    check("utterance count == 20", q("SELECT COUNT(*) FROM utterances")[0][0] == 20,
          str(q("SELECT COUNT(*) FROM utterances")))
    got = q("SELECT done, from_person, to_person, due FROM commitments ORDER BY done")
    check("commitments parsed with alias resolution (서연님→이서연)",
          got == [(0, "정우진", "이서연", "2026-05-27"), (1, "이서연", "정우진", "")], str(got))
    got = q("SELECT status, owner FROM bets")
    check("strategy register status/owner in DB", got == [("진행중", "정우진")], str(got))
    got = q("SELECT a, b, note FROM network WHERE kind='보고' AND source='조직도'")
    check("org chart derived from registry into network (이서연→정우진 보고)",
          got == [("이서연", "정우진", "제품본부")], str(got))
    got = q("SELECT tier, relationship, team FROM people WHERE name='이서연'")
    check("registry fields merged into people table",
          got == [("core", "팀원", "제품본부")], str(got))
    got = q("SELECT speaker FROM utterances WHERE text LIKE '위키링크 화자%'")
    check("wikilink-wrapped speaker label resolves ([[정우진]] → 정우진)",
          got == [("정우진",)], str(got))
    got = sorted(x[0] for x in q("""SELECT DISTINCT pm.person FROM person_meetings pm
        JOIN meetings m ON m.rowid=pm.meeting_rowid WHERE m.title='오염된 참석자'"""))
    check("polluted participants cleaned ([[..]]/quotes/\\u-escape → canonical; 대표·A dropped)",
          got == ["이서연", "정우진"], str(got))
    for raw in ("우진님", "James(정우진)"):
        got = q("SELECT DISTINCT speaker FROM utterances WHERE speaker_raw=?", raw)
        check(f"alias '{raw}' resolves to 정우진", got == [("정우진",)], str(got))
    got = q("SELECT speaker FROM utterances WHERE speaker_raw='Speaker 2'")
    check("generic label stays as-is", got == [("Speaker 2",)], str(got))
    got = q("SELECT text FROM utterances WHERE speaker='정우진' AND text LIKE '다음 줄%'")
    check("**Name** (ts) next-line body is captured", len(got) == 1, str(got))
    got = q("SELECT ts FROM utterances WHERE text LIKE '시간 접두어%'")
    check("(시간: mm:ss) prefix parses", got == [("0:00",)], str(got))
    got = q("SELECT ts FROM utterances WHERE text LIKE '대괄호 범위%'")
    check("[ts - ts] range parses", got == [("00:01",)], str(got))
    got = q("SELECT COUNT(*) FROM model_about WHERE entity='넥스트라'")
    check("model_about populated", got[0][0] == 1, str(got))
    got = sorted(x[0] for x in q("SELECT kind FROM network"))
    check("network table populated (소개 from ontology + derived 보고)",
          got == ["보고", "소개"], str(got))
    got = q("""SELECT pm.src FROM person_meetings pm JOIN meetings m
               ON m.rowid=pm.meeting_rowid
               WHERE pm.person='정우진' AND m.title='통화 선지급'""")
    check("interaction recorded from participants (unattributed call)",
          got == [("participant",)], str(got))
    got = q("""SELECT COUNT(*) FROM person_meetings p1
               JOIN person_meetings p2 ON p2.meeting_rowid=p1.meeting_rowid
               WHERE p1.person='정우진' AND p2.person='이서연'""")
    check("co-attendance derivable (정우진·이서연 동석)", got[0][0] >= 1, str(got))
    fts = q("SELECT value FROM meta WHERE key='fts5'")[0][0]
    if fts == "yes":
        got = q("SELECT COUNT(*) FROM utterances_fts WHERE utterances_fts MATCH '별칭'")
        check("FTS search finds utterances", got[0][0] == 2, str(got))
    got = q("""SELECT r.reading, r.status, COUNT(b.kind) FROM readings r
               LEFT JOIN reading_basis b ON b.reading_id = r.id
               WHERE r.who='정우진' GROUP BY r.id""")
    check("readings land in the DB with their basis signals (queryable, not viewer-only)",
          got and got[0][1] == "추정" and got[0][2] == 2, str(got))
    got = q("SELECT resolved_meeting, resolved_note FROM readings WHERE status='확인됨'")
    check("a resolved reading keeps which meeting settled it", got and got[0][0] == "m2", str(got))
    check("v3 fields traps/conflict_axes are now queryable too",
          q("SELECT COUNT(*) FROM traps")[0][0] == 1
          and q("SELECT COUNT(*) FROM conflict_axes")[0][0] == 1, "")
    db.close()

    rc, out = run("validate.py", root)
    check("validate passes on clean v2 corpus", rc == 0, out)
    check("validate reports attribution coverage", "coverage:" in out, out)
    check("quote verification covers model quotes AND reading basis quotes",
          "quotes: 2/2 grounded" in out, out)
    check("validate reports the reading hit rate", "적중률 100%" in out, out)

def test_dossiers(tmp):
    print("\n[1b] build_dossiers — person dossiers, INDEX, manual-notes preservation")
    root = tmp / "corpus_v2"
    rc, out = run("build_dossiers.py", root)
    check("build_dossiers exits 0", rc == 0, out)
    dp = root / "people" / "정우진.md"
    check("dossier file created", dp.exists())
    t = dp.read_text(encoding="utf-8")
    check("dossier has interaction timeline incl. participant-only call",
          "접촉 이력" in t and "통화-선지급" in t, t[:400])
    check("dossier shows held models", "속도가 먼저다" in t, "")
    check("dossier shows network edge", "소개" in t and "이서연" in t, "")
    check("dossier shows open loops (commitments)",
          "오픈 루프" in t and "번들 기능 스펙 초안" in t, t[:600])
    check("personal-context usability tags rendered (⛔ + caution)",
          "⛔언급금지" in t and "먼저 꺼낼 때만" in t, "")
    dp.write_text(t.replace(
        "(여기에 자유롭게 메모하세요 — 도시에를 다시 생성해도 이 섹션은 보존됩니다)",
        "마라톤 완주 축하 문자 보낼 것"), encoding="utf-8")
    run("build_dossiers.py", root)
    check("manual notes survive regeneration",
          "마라톤 완주 축하 문자 보낼 것" in dp.read_text(encoding="utf-8"))
    t2 = (root / "people" / "이서연.md").read_text(encoding="utf-8")
    check("dossier shows relationship + org line (관계·소속·보고)",
          "관계: 팀원" in t2 and "소속: 제품본부 · 보고: 정우진" in t2, t2[:400])
    idx = (root / "people" / "INDEX.md").read_text(encoding="utf-8")
    check("INDEX lists core tier", "Core" in idx and "정우진" in idx, idx[:300])
    check("INDEX auto-collects contacts (Naomi Park, Mina)",
          "Naomi Park" in idx and "Mina" in idx, "")
    check("dossier links are standard markdown (no [[wikilinks]])",
          "[[" not in t and "](<../transcripts/" in t and "[[" not in idx, t[:300])


def test_browse(tmp):
    print("\n[1c] build_browse — 인물·회사·주제별 BROWSE.md, topics.json, 표준 링크")
    root = tmp / "corpus_v2"
    write(root / "_meta" / "topics.json", json.dumps({
        "topics": [{"name": "번들 가격", "keywords": ["번들", "선지급"]}],
        "orgs": [{"name": "Acme 내부", "keywords": ["이서연"]}]}, ensure_ascii=False))
    rc, out = run("build_index.py", root)
    check("build_index (with browse) exits 0", rc == 0 and "BROWSE.md" in out, out)
    b = (root / "_index" / "BROWSE.md").read_text(encoding="utf-8")
    check("BROWSE has topic, org and person sections",
          "## 주제별" in b and "### 번들 가격" in b and "### Acme 내부" in b and "## 인물별" in b, b[:500])
    check("BROWSE links are standard markdown", "[[" not in b and "](<../transcripts/" in b, b[:300])
    ix = (root / "_index" / "INDEX.md").read_text(encoding="utf-8")
    check("INDEX links are standard markdown", "[[" not in ix and "](<../transcripts/" in ix, ix[:300])
    check("paren-aware participant split keeps '정우진(대표, Acme)' as one person",
          (sys.path.insert(0, str(SCRIPTS)) or __import__("build_index")).split_list("정우진(대표, Acme), 이서연")
          == ["정우진(대표, Acme)", "이서연"], "")

def readings_case(base, mutate):
    """copy the clean corpus, mutate readings[], return validate's output"""
    import copy
    d = json.loads((base / "_ontology" / "objects.json").read_text(encoding="utf-8"))
    mutate(d)
    write(base / "_ontology" / "objects.json", json.dumps(d, ensure_ascii=False))
    return run("validate.py", base)

def test_readings(tmp):
    print("\n[7] readings — 대화 의도 layer: grounded, capped, and accountable")
    root = tmp / "corpus_v2"
    doss = (root / "people" / "정우진.md").read_text(encoding="utf-8")
    check("dossier renders the reading with what was actually said",
          "## 대화 의도" in doss and "이번 분기 안에 뭐라도" in doss
          and '실제 발언: "속도가 먼저다' in doss, doss[:600])
    check("dossier shows the justifying signals",
          "신호:" in doss and "반복(2회)" in doss, doss[:600])
    check("dossier warns that a reading is an inference, not a statement",
          "**추정**입니다" in doss and "본인이 그렇게 말한 적은 없습니다" in doss, doss[:600])
    doss2 = (root / "people" / "이서연.md").read_text(encoding="utf-8")
    check("a confirmed reading is marked confirmed with its resolving meeting",
          "✅" in doss2 and "확인됨" in doss2, doss2[:800])

    bad = tmp / "corpus_reads"
    shutil.copytree(root, bad)
    rc, out = readings_case(bad, lambda d: d["readings"][0].update(confidence="높음"))
    check("confidence 높음 is rejected — an intent reading is never high evidence",
          rc == 1 and "높음" in out, out)
    rc, out = readings_case(bad, lambda d: (d["readings"][0].update(confidence="보통", basis=[])))
    check("a reading with no textual signal is rejected as mind-reading",
          rc == 1 and "mind-reading" in out, out)
    rc, out = readings_case(bad, lambda d: d["readings"][0].update(
        basis=[{"kind": "직감", "detail": "표정"}]))
    check("basis kind must come from the closed signal set",
          rc == 1 and "직감" in out, out)
    rc, out = readings_case(bad, lambda d: (
        d["readings"][0].update(basis=[{"kind": "반복", "detail": "2회"}]),
        d["readings"][1].pop("resolution")))
    check("a resolved status without the resolving meeting is rejected",
          rc == 1 and "resolution" in out, out)
    rc, out = readings_case(bad, lambda d: (
        d["readings"][1].update(resolution={"date": "2026-05-21", "meeting": "m9"})))
    check("resolution must point at a real meeting", rc == 1 and "m9" in out, out)
    rc, out = readings_case(bad, lambda d: (
        d["readings"][1].update(resolution={"date": "2026-05-21", "meeting": "m2"}),
        d["readings"][0].update(who="없는사람")))
    check("a reading about someone outside the registry is rejected",
          rc == 1 and "없는사람" in out, out)
    rc, out = readings_case(bad, lambda d: (
        d["readings"][0].update(who="정우진"),
        d["readings"].extend([
            {"id": f"r-m{i}", "who": "정우진", "meeting": "m1", "date": "2026-05-20",
             "surface": "s", "reading": "r", "basis": [{"kind": "반복", "detail": "2회"}],
             "confidence": "낮음", "status": "빗나감",
             "resolution": {"date": "2026-05-21", "meeting": "m2", "note": "아님"}}
            for i in range(5)])))
    check("a layer that mostly misses says so instead of getting louder",
          rc == 0 and "적중률 17%" in out and "비중을 줄이고" in out, out)

def test_briefing(tmp):
    print("\n[8] build_briefing — push what the user missed (computed, not inferred)")
    root = tmp / "corpus_v2"

    rc, out = run("build_briefing.py", root, "--meeting", "acme-0520")
    check("meeting briefing leads with what I owe someone",
          rc == 0 and "내가 해야 할 것" in out and "번들 기능 스펙 초안" in out, out)
    check("meeting briefing surfaces the open reading with its signal",
          "대화 의도" in out and "이번 분기 안에" in out and "반복(2회)" in out, out)
    check("talk share is reported WITH the unattributed share (no lying by omission)",
          "발화 비중" in out and "화자 미상" in out, out)
    check("owner was guessed, and the briefing says so",
          "최다 참석자" in out and "owner" in out, out)

    rc, out = run("build_briefing.py", root, "--meeting", "acme-0526")
    check("participants come from the cleaned join, not raw frontmatter",
          rc == 0 and "[[정우진]]" not in out and "\\uc774" not in out
          and "이서연" in out.split("##")[0] and "정우진" in out.split("##")[0], out)

    rc, out = run("build_briefing.py", root, "--meeting", "없는회의")
    check("an unknown meeting key fails gracefully, exit 0",
          rc == 0 and "찾지 못했습니다" in out, out)

    rc, out = run("build_briefing.py", root, "--with", "이서연", "--me", "정우진")
    check("pre-meeting briefing puts MY unfinished promise first",
          rc == 0 and "내가 아직 안 한 것" in out
          and out.index("내가 아직 안 한 것") < out.index("최근 접촉"), out)
    check("pre-meeting briefing carries the shared axiom of our conflict",
          "공유 공리" in out and "LTV가 전부다" in out, out)

    rc, out = run("build_briefing.py", root, "--with", "정우진", "--me", "이서연")
    check("personal context keeps its use markers (사적/언급금지 are not for me to raise)",
          "△" in out and "⛔" in out and "먼저 꺼내지 않는다" in out, out)

    rc, out = run("build_briefing.py", root, "--with", "서연님", "--me", "정우진")
    check("--with resolves an alias to the canonical person",
          rc == 0 and "만나기 전 브리핑 — 이서연" in out
          and "기록이 없습니다" not in out, out[:300])

    rc, out = run("build_briefing.py", root, "--meeting", "acme-0520")
    pct = [int(x) for x in re.findall(r"(\d+)%\(질문", out)]
    unattr = int(re.search(r"화자 미상 (\d+)%", out).group(1)) if "화자 미상" in out else 0
    check("talk shares are of the whole meeting, so they do not sum to 100% when some "
          "speech is unattributed", sum(pct) + unattr <= 101 and sum(pct) < 100,
          f"shares={pct} unattr={unattr}")
    check("마무리발언 is not filed under '답 없이 지나간 대목' (it is not an evasion)",
          "답 없이 지나간" not in out or "마무리발언" not in
          out.split("## 답 없이 지나간")[1].split("##")[0], out)
    sect = (out.split("## 처음 만난 사람")[1].split("---")[0].split("##")[0]
            if "## 처음 만난 사람" in out else "")
    check("the owner is not listed as someone they just met",
          "정우진" not in sect and "이서연" in sect, sect)

    rc, out = run("build_briefing.py", root, "--days", "30", "--me", "정우진")
    check("digest reports the reading hit rate so the layer stays accountable",
          rc == 0 and "적중률" in out, out)
    check("digest flags people who are in the corpus but not the registry",
          "레지스트리에 없음" in out, out)

    # owner:true in the registry must beat the most-attending guess
    reg = json.loads((root / "_meta" / "speakers.json").read_text(encoding="utf-8"))
    reg[1]["owner"] = True          # 이서연
    write(root / "_meta" / "speakers.json", json.dumps(reg, ensure_ascii=False))
    rc, out = run("build_briefing.py", root, "--meeting", "acme-0520")
    check("registry owner:true is used and no guess warning is printed",
          rc == 0 and "최다 참석자" not in out, out)
    reg[1].pop("owner")
    write(root / "_meta" / "speakers.json", json.dumps(reg, ensure_ascii=False))

    stale = tmp / "corpus_staledb"
    (stale / "_ontology").mkdir(parents=True)
    con = sqlite3.connect(stale / "_ontology" / "ontology.db")
    con.execute("CREATE TABLE meetings(source_id TEXT, date TEXT)")
    con.commit(); con.close()
    rc, out = run("build_briefing.py", stale, "--days", "7")
    check("a pre-v4 database says to rebuild instead of throwing OperationalError",
          rc != 0 and "build_db.py" in out and "readings" in out, out)

    empty = tmp / "corpus_nodb"
    (empty / "_meta").mkdir(parents=True)
    rc, out = run("build_briefing.py", empty)
    check("no database → a clear instruction, not a traceback",
          rc != 0 and "build_db.py" in out, out)

CAL = {"fetched": "2026-05-27", "range": ["2026-05-01", "2026-05-31"],
       "owner_domain": "acme.io", "events": [
    {"id": "ev1", "title": "제품 전략 회의 — 다음 분기", "start": "2026-05-20T10:00",
     "end": "2026-05-20T11:30", "location": "본사 3층 회의실", "recurring": False,
     "attendees": [{"name": "정우진", "email": "wj@acme.io", "self": True},
                   {"name": "이서연", "email": "sy@acme.io"}]},
    {"id": "ev2", "title": "넥스트라 김상무님 저녁", "start": "2026-05-22T19:00",
     "end": "2026-05-22T21:00", "location": "삼청동 한식당", "recurring": False,
     "attendees": [{"name": "정우진", "email": "wj@acme.io", "self": True},
                   {"name": "Mina Kim", "email": "mina@nextra.co.kr"}]},
    {"id": "ev3", "title": "주간 스탠드업", "start": "2026-05-25T09:30",
     "end": "2026-05-25T10:00", "description": "https://meet.google.com/abc",
     "recurring": True,
     "attendees": [{"name": "정우진", "email": "wj@acme.io", "self": True},
                   {"name": "이서연", "email": "sy@acme.io"},
                   {"name": "박도현", "email": "dh@acme.io"}]}]}

def test_calendar(tmp):
    print("\n[9] match_calendar — 녹음 ↔ 일정 매칭, TPO를 근거의 일부로")
    root = tmp / "corpus_cal"
    build_corpus_v2(root)
    write(root / "_meta" / "calendar" / "2026-05.json", json.dumps(CAL, ensure_ascii=False))
    for rel, t in [("2026-05-20_전략회의.md", "10:05"),
                   ("2026-05-22_외부미팅-넥스트라.md", "19:10")]:
        p = root / "transcripts" / "2026" / "2026-05" / rel
        p.write_text(p.read_text(encoding="utf-8").replace(
            "duration_min: 10", 'duration_min: 60\nstart_time: "%s"' % t, 1), encoding="utf-8")
    run("build_index.py", root)

    rc, out = run("match_calendar.py", root)
    check("dry run by default, and it says so", rc == 0 and "DRY RUN" in out, out[-300:])
    check("time overlap matches the right event",
          "제품 전략 회의" in out and "시간 겹침" in out, out)
    check("TPO is derived from the calendar, not guessed",
          "저녁·금 · 식사자리 · 외부 포함(2인)" in out and "외부도메인 nextra.co.kr" in out, out)
    check("a same-day-only candidate is offered but not confirmed",
          "시작 시각 없음 — 그날 유일한 일정" in out and "확인 필요 2" in out, out)
    check("a human-set title/category is reported, never silently replaced",
          "제목 유지(사람이 정함)" in out and "분류 유지" in out, out)
    before = (root / "transcripts" / "2026" / "2026-05" / "2026-05-20_전략회의.md").read_text(encoding="utf-8")
    check("dry run wrote nothing", "setting:" not in before, before[:200])

    rc, out = run("match_calendar.py", root, "--apply")
    check("apply patches only confirmed matches", rc == 0 and "프론트매터 2건 갱신" in out, out[-300:])
    md = (root / "transcripts" / "2026" / "2026-05" / "2026-05-22_외부미팅-넥스트라.md").read_text(encoding="utf-8")
    check("setting + provenance land in the frontmatter",
          '설정' not in md and 'setting: "저녁·금 · 식사자리 · 외부 포함(2인)"' in md
          and 'calendar_event: "ev2"' in md, md[:400])
    body_before = before.split("\n---\n", 1)[1]
    after20 = (root / "transcripts" / "2026" / "2026-05" / "2026-05-20_전략회의.md").read_text(encoding="utf-8")
    check("only the frontmatter changed — the transcript body is byte-identical",
          after20.split("\n---\n", 1)[1] == body_before, "")
    check("a human-set title survives the patch", 'title: "외부미팅 넥스트라"' in md, md[:200])

    run("build_index.py", root)
    run("build_db.py", root)
    db = sqlite3.connect(root / "_ontology" / "ontology.db")
    got = db.execute("SELECT setting, start_time FROM meetings WHERE source_id='acme-0522'").fetchone()
    check("setting reaches the database (so answers and briefings can use it)",
          got and "식사자리" in got[0] and got[1] == "19:10", str(got))
    db.close()

    rc, out = run("build_briefing.py", root, "--meeting", "acme-0522", "--me", "정우진")
    check("the meeting briefing header carries the TPO",
          rc == 0 and "식사자리" in out.split("##")[0], out[:300])

    rc, out = run("build_briefing.py", root, "--upcoming", "2026-05-20", "--me", "정우진")
    check("--upcoming lists the day's events with who I am meeting",
          rc == 0 and "제품 전략 회의" in out and "이서연" in out, out)
    check("--upcoming leads with what I owe that person",
          "내가 안 한 것" in out and "번들 기능 스펙 초안" in out, out)
    reg = json.loads((root / "_meta" / "speakers.json").read_text(encoding="utf-8"))
    reg.append({"name": "Mina", "role": "파트너", "org": "넥스트라", "aliases": [],
                "meetings": [], "tier": "contact"})
    write(root / "_meta" / "speakers.json", json.dumps(reg, ensure_ascii=False))
    rc, out = run("build_briefing.py", root, "--upcoming", "2026-05-22", "--me", "정우진")
    check("an unknown calendar name is a name-variant candidate, never a silent match",
          "기록 없음" in out and "혹시" in out and "aliases" in out, out)
    rc, out = run("build_briefing.py", root, "--upcoming", "2026-06-30", "--me", "정우진")
    check("a day with no cached events says so plainly", rc == 0 and "일정이 없습니다" in out, out)

    # --- regressions from code review: each of these wrote wrong data into a transcript
    cal2 = tmp / "corpus_cal2"
    build_corpus_v2(cal2)
    write(cal2 / "_meta" / "calendar" / "2026-05.json", json.dumps({
        "fetched": "2026-05-27", "events": [          # no owner_domain, name-only attendees
            {"id": "x1", "title": "김상무님 저녁", "start": "2026-05-20T19:00",
             "end": "2026-05-20T21:00", "location": "한식당",
             "attendees": [{"name": "정우진"}, {"name": "Kim, Mina"}]}]}, ensure_ascii=False))
    p20 = cal2 / "transcripts" / "2026" / "2026-05" / "2026-05-20_전략회의.md"
    p20.write_text(p20.read_text(encoding="utf-8").replace(
        'duration_min: 10', 'duration_min: 60\nstart_time: "19:05"', 1)
        .replace("category: 내부-전략", "category: 기타")
        .replace('participants: [정우진, 이서연]', 'participants: []'), encoding="utf-8")
    run("build_index.py", cal2)
    rc, out = run("match_calendar.py", cal2, "--apply")
    md = p20.read_text(encoding="utf-8")
    check("without domains it says 내부·외부 미상 instead of asserting 내부",
          "미상" in md and "내부(2인)" not in md, md[:400])
    check("...and it suggests no category rather than a wrong one",
          "category: 기타" in md, md[:400])
    run("build_index.py", cal2)
    cat = json.loads((cal2 / "_index" / "catalog.json").read_text(encoding="utf-8"))
    row = next(r for r in cat if r["source_id"] == "acme-0520")
    write(cal2 / "transcripts" / "2026" / "2026-05" / "2026-05-27_아포스트로피.md",
          FM.format(title="아포스트로피", date="2026-05-27", cat="외부-파트너",
                    parts="정우진, O'Brien, 이서연", sid="acme-0527", extra="",
                    body="**[정우진] (00:01)** 테스트."))
    run("build_index.py", cal2)
    cat0 = json.loads((cal2 / "_index" / "catalog.json").read_text(encoding="utf-8"))
    row0 = next(r for r in cat0 if r["source_id"] == "acme-0527")
    check("an apostrophe in a name does not swallow the rest of the list",
          row0["participants"] == ["정우진", "O'Brien", "이서연"], str(row0["participants"]))
    check("a comma inside an attendee name does not split them into two people",
          row["participants"] == ["정우진", "Kim, Mina"], str(row["participants"]))

    cal3 = tmp / "corpus_cal3"
    build_corpus_v2(cal3)
    write(cal3 / "_meta" / "calendar" / "2026-05.json", json.dumps({
        "fetched": "2026-05-27", "owner_domain": "acme.io", "events": [
            {"id": "allday", "title": "연차", "start": "2026-05-20", "end": "2026-05-21",
             "attendees": []},
            {"id": "tech", "title": "기술 로드맵 검토", "start": "2026-05-20T14:00",
             "end": "2026-05-20T15:00",
             "attendees": [{"name": "정우진", "email": "wj@acme.io"},
                           {"email": "guest@partner.io"}]}]}, ensure_ascii=False))
    p3 = cal3 / "transcripts" / "2026" / "2026-05" / "2026-05-20_전략회의.md"
    p3.write_text(p3.read_text(encoding="utf-8")
                  .replace('duration_min: 10', 'duration_min: 60\nstart_time: "14:05"', 1)
                  .replace('title: "전략회의"', 'title: "2026-05-20 넥스트라 협상 3차"'),
                  encoding="utf-8")
    run("build_index.py", cal3)
    rc, out = run("match_calendar.py", cal3, "--apply")
    md = p3.read_text(encoding="utf-8")
    check("an all-day event never swallows a recording (it overlaps everything)",
          "연차" not in md and "기술 로드맵" in out, out[:600])
    check("'기술' is not read as 술자리 — that would downgrade the meeting's evidence",
          "식사자리" not in md, md[:400])
    check("a human title that merely starts with a date is not overwritten",
          'title: "2026-05-20 넥스트라 협상 3차"' in md, md[:300])
    check("표시 이름 없는 참석자는 이메일 전체가 아니라 아이디로 올라간다",
          "@partner.io" not in md and "표시 이름이 없어" in out, out[:900])

    # --- 실제 Google Calendar 응답 형태에서 나온 회귀들 (2026-09-04 실사용 테스트) ---
    real = tmp / "corpus_realshape"
    build_corpus_v2(real)
    write(real / "_meta" / "calendar" / "2026-05.json", json.dumps({
        "fetched": "2026-05-27", "owner_domain": "acme.io", "events": [
            {"id": "dir1", "title": "acme direction", "start": "2026-05-20T14:00",
             "end": "2026-05-20T15:00", "location": "ACME-3층-다실 (6인 회의실)",
             "recurring": True, "attendees": [
                 {"name": "ACME-3층-다실 (6인 회의실)",
                  "email": "c_188xyz@resource.calendar.google.com", "resource": True},
                 {"email": "wj@acme.io"}, {"email": "sy@acme.io"},
                 {"email": "dh@acme.io", "responseStatus": "declined"}]},
            {"id": "din1", "title": "정우진 이서연 디너", "start": "2026-05-22T19:00",
             "end": "2026-05-22T21:00",
             "description": "https://meet.google.com/abc-defg-hij",
             "attendees": [{"email": "wj@acme.io"}, {"email": "sy@acme.io"}]}]},
        ensure_ascii=False))
    for rel, t in [("2026-05-20_전략회의.md", "14:05"),
                   ("2026-05-22_외부미팅-넥스트라.md", "19:10")]:
        f = real / "transcripts" / "2026" / "2026-05" / rel
        f.write_text(f.read_text(encoding="utf-8").replace(
            "duration_min: 10", 'duration_min: 60\nstart_time: "%s"' % t, 1)
            .replace("category: 내부-전략", "category: 기타")
            .replace("category: 외부-파트너", "category: 기타")
            .replace("participants: [정우진, 이서연]", "participants: []")
            .replace("participants: [정우진, Mina]", "participants: []"), encoding="utf-8")
    run("build_index.py", real)
    rc, out = run("match_calendar.py", real, "--apply")
    md20 = (real / "transcripts" / "2026" / "2026-05" / "2026-05-20_전략회의.md").read_text(encoding="utf-8")
    check("회의실 예약이 참석자로 계수되지 않는다 (내부 회의가 '외부 포함'이 되던 문제)",
          "내부(2인)" in md20 and "외부" not in md20.split("setting:")[1].split("\n")[0], md20[:400])
    check("참석을 거절한 사람은 그 자리에 없던 것으로 센다", "내부(2인)" in md20, md20[:400])
    check("'direction' 의 ir 이 IR 미팅으로 오분류되지 않는다",
          "외부-투자IR" not in md20 and "내부-" in md20, md20[:400])
    check("표시 이름 없는 참석자는 버리지 않고 이메일 아이디로 올린다",
          "wj" in md20 and "표시 이름이 없어" in out, out[:900])
    md22 = (real / "transcripts" / "2026" / "2026-05" / "2026-05-22_외부미팅-넥스트라.md").read_text(encoding="utf-8")
    check("자동으로 붙는 화상 링크가 '식사자리' 판정을 가리지 않는다",
          "식사자리" in md22 and "화상" not in md22, md22[:400])

    tz = tmp / "corpus_tz"
    build_corpus_v2(tz)
    import datetime as _dt
    off = _dt.datetime.now().astimezone().strftime("%z")      # this machine's offset
    _local = _dt.datetime(2026, 5, 20, 10, 0)
    _shift = _dt.timedelta(hours=int(off[:3]), minutes=int(off[0] + off[3:5]))
    utc_start = (_local - _shift).strftime("%Y-%m-%dT%H:%M:%SZ")
    utc_end = (_local + _dt.timedelta(minutes=90) - _shift).strftime("%Y-%m-%dT%H:%M:%SZ")
    write(tz / "_meta" / "calendar" / "2026-05.json", json.dumps({
        "fetched": "2026-05-27", "owner_domain": "acme.io", "events": [
            {"id": "utc1", "title": "UTC로 적힌 일정", "start": utc_start,
             "end": utc_end, "attendees": [{"email": "wj@acme.io"}]}]},
        ensure_ascii=False))
    p2 = tz / "transcripts" / "2026" / "2026-05" / "2026-05-20_전략회의.md"
    p2.write_text(p2.read_text(encoding="utf-8").replace(
        'duration_min: 10', 'duration_min: 60\nstart_time: "10:05"', 1), encoding="utf-8")
    run("build_index.py", tz)
    rc, out = run("match_calendar.py", tz)
    check("a UTC timestamp is converted to local time, not silently shifted",
          "UTC로 적힌 일정" in out and "시간 겹침" in out, out)

    empty = tmp / "corpus_nocal"
    build_corpus_v2(empty)
    run("build_index.py", empty)
    rc, out = run("match_calendar.py", empty)
    check("no calendar cache → a clear instruction, not a crash",
          rc != 0 and "_meta/calendar" in out, out)

def test_validate_catches_errors(tmp):
    print("\n[2] validate — must catch integrity & honesty violations")
    root, bad = tmp / "corpus_v2", tmp / "corpus_bad"
    shutil.copytree(root, bad)
    op = bad / "_ontology" / "objects.json"
    d = json.loads(op.read_text(encoding="utf-8"))
    for p in d["people"]:
        if p["name"] == "넥스트라":
            p["evidence"] = "high"             # org entity with high evidence → error
    for m in d["models"]:
        if m["id"] == "competitor-watch":
            m["holders"] = ["넥스트라"]        # org-only holder …
            m["evidence"] = "high"             # … with high evidence → error
        if m["id"] == "value-first":
            m["related"] = ["no-such-model"]   # broken reference → error
            m["quote"] = "이 발언은 회의록 어디에도 존재하지 않는 환각 인용이다"
            m["last_seen"] = "2024-01-01"      # far behind newest meeting → stale
    op.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    rc, out = run("validate.py", bad)
    check("validate exits 1 on corrupted ontology", rc == 1, out)
    check("org-evidence cap violation reported", "capped at 'mid'" in out, out)
    check("org ENTITY evidence cap reported", "org-type entity with evidence=high" in out, out)
    check("broken related id reported", "no-such-model" in out, out)
    check("holder-list inconsistency reported", "not one of its holders" in out, out)
    check("hallucinated quote flagged as NOT grounded", "NOT grounded" in out, out)
    check("stale model flagged", "STALE" in out, out)

def test_migration_v1_to_v2(tmp):
    print("\n[3] migrate_objects — v1 → v2 classification, canonicalization, capping")
    root = tmp / "corpus_v1"
    write(root / "_meta" / "speakers.json", json.dumps(SPEAKERS, ensure_ascii=False))
    make_transcript(root, "2026-05-20_전략회의.md", "전략회의", "2026-05-20", "v1-0520",
                    "**[정우진] (00:01)** v1 테스트.")
    write(root / "_ontology" / "objects.json", json.dumps({
        "meta": {"title": "Acme v1", "org": "Acme"},
        "meetings": [{"id": "m1", "date": "2026-05-20", "title": "전략회의"}],
        "people": [
            {"name": "정우진", "role": "CEO", "summary": "", "evidence": "high",
             "models": ["speed-first"]},
            {"name": "넥스트라", "role": "경쟁사", "summary": "", "evidence": "high",
             "models": ["competitor-watch"]},   # v1: org 'holding' a model
        ],
        "models": [
            {"id": "speed-first", "category": "전략", "title": "속도가 먼저다",
             "evidence": "high", "people": ["제임스(정우진)"]},   # variant name
            {"id": "competitor-watch", "category": "리스크", "title": "경쟁사 견제 대비",
             "evidence": "high", "people": []},
        ],
    }, ensure_ascii=False))
    run("build_index.py", root)

    rc, out = run("migrate_objects.py", root)
    check("dry run exits 0 and does not write", rc == 0 and "DRY RUN" in out, out)
    rc, out = run("migrate_objects.py", root, "--apply")
    check("apply exits 0 with backup", rc == 0 and "objects_v1_backup" in out, out)

    d = json.loads((root / "_ontology" / "objects.json").read_text(encoding="utf-8"))
    types = {p["name"]: p["type"] for p in d["people"]}
    check("person/org classified via speakers.json",
          types == {"정우진": "person", "넥스트라": "org"}, str(types))
    m = {x["id"]: x for x in d["models"]}
    check("variant holder canonicalized (제임스(정우진) → 정우진)",
          m["speed-first"]["holders"] == ["정우진"], str(m["speed-first"]))
    check("org-held model capped high → mid",
          m["competitor-watch"]["holders"] == ["넥스트라"]
          and m["competitor-watch"]["evidence"] == "mid", str(m["competitor-watch"]))
    check("meeting gained provenance from catalog",
          d["meetings"][0].get("source_id") == "v1-0520"
          and d["meetings"][0].get("path", "").endswith("전략회의.md"), str(d["meetings"]))
    check("people[].models rebuilt to held models only",
          next(p for p in d["people"] if p["name"] == "정우진")["models"] == ["speed-first"],
          str(d["people"]))

    rc, out = run("migrate_objects.py", root, "--apply")
    check("second migrate is a no-op", "already schema v2" in out, out)
    rc, out = run("build_db.py", root)
    check("build_db OK on migrated corpus", rc == 0, out)
    rc, out = run("validate.py", root)
    check("validate passes on migrated corpus", rc == 0, out)

def test_batch_pipeline(tmp):
    print("\n[4] prepare_synthesis + merge_ontology — batch re-extraction pipeline")
    root = tmp / "corpus_v2"
    W = root / "_ontology" / "_work" / "batch-test"
    W.mkdir(parents=True)
    make_transcript(root, "2026-06-01_6월전략회의.md", "6월 전략회의", "2026-06-01",
                    "acme-9001", "**[정우진] (00:01)** 채용은 문화 적합이 먼저다.")
    run("build_index.py", root)      # 배치는 실제 회의록을 처리한다 — 카탈로그에 있어야 한다
    # fake extraction output: one restating instance, one new belief, junk holder,
    # a tension, a self-org network fact and a real one
    (W / "extract-b00.json").write_text(json.dumps({"batch": "b00", "meetings": [{
        "source_id": "acme-9001", "date": "2026-06-01", "title": "6월 전략회의",
        "instances": [
            {"holder": "정우진", "title": "완성도보다 학습 속도가 먼저다", "category": "전략",
             "quote": "일단 던지고 배운다", "evidence": "high", "about": []},
            {"holder": "정우진", "title": "채용은 문화 적합이 먼저다", "category": "조직",
             "quote": "", "evidence": "mid", "about": []},
            {"holder": "Speaker 3", "title": "버려질 인스턴스", "category": "기타",
             "quote": "", "evidence": "low", "about": []}],
        "tensions": [{"from": "정우진", "to": "이서연", "topic": "채용 속도",
                      "note": "속도 vs 검증", "direction": "one-way"}],
        "network_facts": [{"a": "Acme", "b": "그로우캐피탈", "kind": "투자", "note": "자사 엣지 — 드롭돼야 함"},
                          {"a": "박도현", "b": "제임스(정우진)", "kind": "협업", "note": "변형 이름 — 정규화돼야 함"}],
        "readings": [
            {"id": "r-b00-1", "who": "정우진", "date": "2026-06-01",
             "surface": "채용은 천천히 해도 된다", "reading": "이번 분기 안에 팀을 늘리길 원한다",
             "basis": [{"kind": "선제언급", "detail": "안건 첫 순서로 꺼냄"}],
             "confidence": "보통", "status": "추정"},
            {"id": "r-1", "who": "정우진", "status": "확인됨",
             "resolution": {"date": "2026-06-01", "meeting": "m1",
                            "note": "6월 회의에서 직접 확인됨"}},
            {"id": "r-junk", "who": "Speaker 3", "surface": "x", "reading": "y",
             "basis": [{"kind": "반복", "detail": "1회"}], "confidence": "낮음",
             "status": "추정"}],
        "timeline_signal": "채용 확대 국면 진입"}]}, ensure_ascii=False), encoding="utf-8")
    (W / "batches.json").write_text(json.dumps([{"id": "b00", "sids": ["acme-9001"]}]), encoding="utf-8")

    rc, out = run("prepare_synthesis.py", root, W)
    check("prepare_synthesis exits 0", rc == 0, out)
    check("junk holder dropped and reported", "dropped" in out and "Speaker 3" in out, out)
    keys = json.loads((W / "synth_keys.json").read_text(encoding="utf-8"))
    check("only instance-bearing task needs an agent", keys == ["person-정우진"], str(keys))
    task = json.loads((W / "synth-task-person-정우진.json").read_text(encoding="utf-8"))
    check("task carries existing models + new instances",
          len(task["existing_models"]) == 2 and len(task["instances"]) == 2, str(task)[:200])

    # fake synthesis output: update existing model + one new + one id COLLIDING with
    # another person's existing model (value-first belongs to 이서연)
    upd = next(m for m in task["existing_models"] if m["id"] == "speed-first")
    upd = {**upd, "count": upd.get("count", 1) + 1, "last_seen": "2026-06-01"}
    (W / "synth-person-정우진.json").write_text(json.dumps({"key": "person-정우진", "models": [
        m if m["id"] != "speed-first" else upd for m in task["existing_models"]] + [
        {"id": "hiring-culture-fit-first", "category": "조직", "title": "채용은 문화 적합이 먼저다",
         "evidence": "mid", "holders": ["정우진"], "about": [], "count": 1,
         "first_seen": "2026-06-01", "last_seen": "2026-06-01"},
        {"id": "value-first", "category": "제품", "title": "충돌 테스트용 중복 id",
         "evidence": "mid", "holders": ["정우진"], "about": [], "count": 1}],
        "evolution": [{"person": "정우진", "date": "2026-06-01", "note": "채용 방침 전환"}],
        "summary": "test"}, ensure_ascii=False), encoding="utf-8")

    rc, out = run("merge_ontology.py", root, W)
    check("merge dry-run exits 0 without writing", rc == 0 and "DRY RUN" in out, out)
    rc, out = run("merge_ontology.py", root, W, "--apply")
    check("merge apply exits 0 with backup", rc == 0 and "objects_backup" in out, out)
    check("id collision renamed and reported", "value-first → value-first-2" in out, out)
    d = json.loads((root / "_ontology" / "objects.json").read_text(encoding="utf-8"))
    m = {x["id"]: x for x in d["models"]}
    check("existing model updated in place (count·last_seen)",
          m["speed-first"]["count"] == upd["count"]
          and m["speed-first"]["last_seen"] == "2026-06-01", str(m["speed-first"]))
    check("new model merged", "hiring-culture-fit-first" in m, "")
    check("이서연's untouched model carried over", "value-first" in m
          and m["value-first"]["holders"] == ["이서연"], "")
    reads = {r["id"]: r for r in d.get("readings", [])}
    check("batch pipeline carries new readings (대화 의도 survives a bulk catch-up)",
          "r-b00-1" in reads and reads["r-b00-1"]["who"] == "정우진", str(list(reads)))
    check("an agent's re-check resolves the open reading in place",
          reads["r-1"]["status"] == "확인됨"
          and reads["r-1"]["resolution"]["meeting"] == "m1"
          and reads["r-1"]["surface"].startswith("속도가 먼저다"), str(reads.get("r-1")))
    check("a reading held by a non-canonical speaker is dropped, not guessed",
          "r-junk" not in reads, str(list(reads)))
    mids = {m["id"]: m for m in d["meetings"]}
    check("the batch pipeline registers the meeting it processed (provenance)",
          any(m.get("source_id") == "acme-9001" for m in d["meetings"]),
          str([m.get("source_id") for m in d["meetings"]]))
    check("batch readings get a real meetings[].id, not a bare date",
          reads["r-b00-1"].get("meeting") in {m["id"] for m in d["meetings"]}
          and "mtg_source_id" not in reads["r-b00-1"], str(reads.get("r-b00-1")))
    check("readings that were already resolved are not double-counted",
          "+reading 1" in out and "resolved 1" in out, out)
    check("one-way tension merged into relations",
          any(r.get("topic") == "채용 속도" and r.get("direction") == "one-way"
              for r in d["relations"]), str(d["relations"][-1]))
    net = {(n["a"], n["b"]) for n in d.get("network", [])}
    check("self-org network edge dropped, variant name normalized",
          ("Acme", "그로우캐피탈") not in net and ("박도현", "정우진") in net, str(net))
    check("processed_source_ids updated",
          "acme-9001" in d["meta"]["processed_source_ids"], "")
    check("people[].models rebuilt with new model",
          "hiring-culture-fit-first" in next(p for p in d["people"] if p["name"] == "정우진")["models"], "")
    rc, out = run("validate.py", root)
    check("validate passes after batch merge", rc == 0, out)

def test_purge_person(tmp):
    print("\n[5] purge_person — right-to-be-forgotten")
    root, pp = tmp / "corpus_v2", tmp / "corpus_purge"
    shutil.copytree(root, pp)
    write(pp / "_meta" / "voiceprints.json", json.dumps(
        {"version": 1, "model": "campplus.onnx", "dim": 4, "people": {
            "이서연": {"centroids": [{"id": "c1", "vec": vp_vec((0, 1.0)), "dur": 300.0,
                                      "n": 2, "sources": ["acme-0520"], "updated": "2026-05-20"}]},
            "정우진": {"centroids": [{"id": "c1", "vec": vp_vec((1, 1.0)), "dur": 400.0,
                                      "n": 3, "sources": ["acme-0520"], "updated": "2026-05-20"}]}}},
        ensure_ascii=False))
    rc, out = run("purge_person.py", pp, "--name", "이서연")
    check("purge dry-run exits 0 and lists files", rc == 0 and "DRY RUN" in out
          and "speakers.json" in out, out)
    assert "APPLIED" not in out
    rc, out = run("purge_person.py", pp, "--name", "이서연", "--apply")
    check("purge apply exits 0 with backup", rc == 0 and "purge-backup" in out, out)
    reg = json.loads((pp / "_meta" / "speakers.json").read_text(encoding="utf-8"))
    check("registry entry removed", all(e["name"] != "이서연" for e in reg), "")
    d = json.loads((pp / "_ontology" / "objects.json").read_text(encoding="utf-8"))
    check("person removed from ontology", all(p["name"] != "이서연" for p in d["people"]), "")
    ids = {m["id"] for m in d["models"]}
    check("solely-held models removed", "value-first" not in ids, str(sorted(ids)))
    check("relations involving person removed",
          all("이서연" not in (r.get("from"), r.get("to")) for r in d.get("relations", [])), "")
    t = (pp / "transcripts" / "2026" / "2026-05" / "2026-05-20_전략회의.md").read_text(encoding="utf-8")
    check("transcript mentions anonymized (alias 서연님 included)",
          "이서연" not in t and "서연님" not in t and "[삭제된 인물]" in t, t[:300])
    check("readings about the purged person are gone (the most personal layer)",
          all(r.get("who") != "이서연" for r in d.get("readings", [])),
          json.dumps(d.get("readings", []), ensure_ascii=False)[:300])
    check("their name is masked out of readings that survive",
          "이서연" not in json.dumps(d.get("readings", []), ensure_ascii=False), "")
    check("conflict axes involving them are removed",
          all("이서연" not in (x.get("a"), x.get("b")) for x in d.get("conflict_axes", [])), "")
    check("traps keep no dangling model_id after their solely-held models went",
          all(t.get("model_id") in {m["id"] for m in d["models"]}
              for t in d.get("traps", []) if t.get("model_id")), "")
    rc2, out2 = run("build_db.py", pp)
    rc3, out3 = run("validate.py", pp)
    check("the documented post-purge rebuild still validates (no orphan rows left behind)",
          rc2 == 0 and rc3 == 0, out3[-600:])
    vp = json.loads((pp / "_meta" / "voiceprints.json").read_text(encoding="utf-8"))
    check("voiceprint purged (biometric data does not survive)",
          "이서연" not in vp["people"] and "정우진" in vp["people"], str(list(vp["people"])))
    check("backup preserves originals",
          (pp / "_ontology" / "_work").glob("purge-backup-*") is not None
          and "이서연" in next((pp / "_ontology" / "_work").glob("purge-backup-*/_meta/speakers.json")).read_text(encoding="utf-8"), "")

# ---- voiceprint helpers: synthetic unit vectors, no audio/sherpa needed ------
VP_DIM = 8

def vp_vec(*pairs):
    v = [0.0] * VP_DIM
    for i, x in pairs:
        v[i] = x
    n = sum(x * x for x in v) ** 0.5
    return [round(x / n, 6) for x in v]

def vp_emb(path, clusters):
    """clusters: [(label, vec, dur)] → the --embeddings file voiceprint.py reads."""
    write(path, json.dumps({"clusters": [{"label": l, "vec": v, "dur": d}
                                         for l, v, d in clusters]}, ensure_ascii=False))
    return path

def test_voiceprint(tmp):
    print("\n[6] voiceprint — persistent speaker identity across recordings")
    root = tmp / "corpus_vp"
    write(root / "_meta" / "speakers.json", json.dumps(SPEAKERS, ensure_ascii=False))

    A1 = vp_vec((0, 1.0))                    # 정우진, recording 1
    A2 = vp_vec((0, 1.0), (1, 0.12))         # 정우진, recording 2 (cos ≈ 0.99)
    A3 = vp_vec((0, 1.0), (2, 0.15))         # 정우진 again, same recording as A2
    B1 = vp_vec((1, 1.0))                    # 이서연 (cos with A ≈ 0.12)
    MAYBE = vp_vec((0, 0.52), (3, 0.85))     # ~0.52 vs A — between floor and accept
    STRANGER = vp_vec((0, 0.30), (4, 0.95))  # ~0.30 vs A — below floor
    FARSIDE = vp_vec((0, 0.40), (5, 0.92))   # 정우진 on the phone: cos 0.40 < merge 0.55

    # 1) empty store — nothing is ever guessed
    e0 = vp_emb(root / "e0.json", [("0", A1, 60.0)])
    rc, out = run("voiceprint.py", root, "identify", "--embeddings", e0)
    check("identify on an empty store returns unknown, exit 0",
          rc == 0 and "미상" in out and "등록된 목소리 없음" in out, out)

    # 2) enroll from recording 1
    rc, out = run("voiceprint.py", root, "enroll", "--embeddings", e0,
                  "--map", '{"0": "정우진"}', "--source", "rec-1")
    check("enroll writes the store", rc == 0 and "voiceprints.json" in out, out)
    st = json.loads((root / "_meta" / "voiceprints.json").read_text(encoding="utf-8"))
    check("store holds one centroid for the person",
          list(st["people"]) == ["정우진"] and len(st["people"]["정우진"]["centroids"]) == 1,
          json.dumps(st, ensure_ascii=False)[:300])

    # 3) recognize the same voice in a later recording
    e1 = vp_emb(root / "e1.json", [("0", A2, 120.0), ("1", B1, 90.0)])
    labels = root / "labels.json"
    rc, out = run("voiceprint.py", root, "identify", "--embeddings", e1, "--out", labels)
    L = json.loads(labels.read_text(encoding="utf-8"))
    check("known voice auto-identified in a new recording",
          L["auto"] == {"0": "정우진"}, json.dumps(L, ensure_ascii=False)[:400])
    check("unenrolled voice is not guessed", L["ask"] == ["1"]
          and L["decisions"][1]["decision"] == "unknown", json.dumps(L["decisions"][1], ensure_ascii=False))
    check("scores are reported, not hidden",
          L["decisions"][0]["score"] > 0.9 and "cos" in L["decisions"][0]["reason"], out)

    # 4) one person cannot be two speakers in one recording
    e2 = vp_emb(root / "e2.json", [("0", A2, 120.0), ("1", A3, 100.0)])
    rc, out = run("voiceprint.py", root, "identify", "--embeddings", e2, "--out", labels)
    L = json.loads(labels.read_text(encoding="utf-8"))
    check("same person claimed by only one cluster; the loser asks",
          len(L["auto"]) == 1 and len(L["ask"]) == 1
          and "다른 클러스터" not in L["decisions"][int(L["ask"][0])]["reason"]
          and "과다분할" in L["decisions"][int(L["ask"][0])]["reason"],
          json.dumps(L["decisions"], ensure_ascii=False)[:500])

    # 5) the middle band asks instead of asserting
    e3 = vp_emb(root / "e3.json", [("0", MAYBE, 60.0), ("1", STRANGER, 60.0)])
    rc, out = run("voiceprint.py", root, "identify", "--embeddings", e3, "--out", labels)
    L = json.loads(labels.read_text(encoding="utf-8"))
    check("plausible-but-unsure → ask with a named candidate",
          L["decisions"][0]["decision"] == "ask" and L["decisions"][0]["name"] == "정우진",
          json.dumps(L["decisions"][0], ensure_ascii=False))
    check("below the floor → unknown, no candidate",
          L["decisions"][1]["decision"] == "unknown" and L["decisions"][1]["name"] is None,
          json.dumps(L["decisions"][1], ensure_ascii=False))
    check("identify warns when a human answer is needed",
          "WARN" in out and L["auto"] == {}, out)

    # 6) a too-short cluster is never identified or learned
    e4 = vp_emb(root / "e4.json", [("0", A2, 2.0)])
    rc, out = run("voiceprint.py", root, "identify", "--embeddings", e4)
    check("cluster shorter than min-dur is asked, not auto-labeled",
          rc == 0 and "확인" in out and "발화 2s" in out, out)
    rc, out = run("voiceprint.py", root, "enroll", "--embeddings", e4, "--map", '{"0": "정우진"}')
    check("enroll refuses a too-short cluster and says why",
          rc == 0 and "SKIP" in out and "--force" in out, out)

    # 7) enroll guards against a mislabeled cluster
    rc, out = run("voiceprint.py", root, "enroll", "--embeddings", e1,
                  "--map", '{"0": "박도현"}', "--source", "rec-2")
    check("enroll blocks a cluster that is clearly someone already enrolled",
          rc == 0 and "SKIP" in out and "정우진" in out, out)
    rc, out = run("voiceprint.py", root, "enroll", "--embeddings", e1,
                  "--map", '{"1": "이서연"}', "--source", "rec-2")
    check("a genuinely new voice enrolls fine", rc == 0 and "SKIP" not in out, out)
    e_new = vp_emb(root / "e_new.json", [("0", vp_vec((6, 1.0)), 40.0)])
    rc, out = run("voiceprint.py", root, "enroll", "--embeddings", e_new,
                  "--map", '{"0": "없는사람"}', "--source", "rec-2")
    check("enroll warns on a name missing from the registry",
          "WARN" in out and "speakers.json" in out, out)

    # 8) merging vs. a second centroid (same person, different recording conditions)
    rc, out = run("voiceprint.py", root, "enroll", "--embeddings", e1,
                  "--map", '{"0": "정우진"}', "--source", "rec-2")
    check("re-enrolling the same voice merges instead of duplicating",
          rc == 0 and "병합" in out, out)
    st = json.loads((root / "_meta" / "voiceprints.json").read_text(encoding="utf-8"))
    check("similar enrollment merged into the existing centroid, duration accumulated",
          len(st["people"]["정우진"]["centroids"]) == 1
          and st["people"]["정우진"]["centroids"][0]["dur"] > 150, 
          json.dumps(st["people"]["정우진"], ensure_ascii=False)[:200])
    e5 = vp_emb(root / "e5.json", [("0", FARSIDE, 200.0)])
    rc, out = run("voiceprint.py", root, "enroll", "--embeddings", e5,
                  "--map", '{"Speaker 1": "정우진"}', "--source", "rec-3", "--force")
    check("'Speaker 1' style keys map to cluster 0", rc == 0 and "SKIP" not in out, out)
    st = json.loads((root / "_meta" / "voiceprints.json").read_text(encoding="utf-8"))
    check("a distinctly different recording condition gets its own centroid",
          len(st["people"]["정우진"]["centroids"]) == 2,
          json.dumps([c["id"] for c in st["people"]["정우진"]["centroids"]]))
    rc, out = run("voiceprint.py", root, "identify", "--embeddings", e5, "--out", labels)
    check("the second centroid recognizes that condition later",
          json.loads(labels.read_text(encoding="utf-8"))["auto"] == {"0": "정우진"}, out)

    # 9) list + forget
    rc, out = run("voiceprint.py", root, "list")
    check("list reports who is enrolled and how much voice was heard",
          rc == 0 and "정우진" in out and "이서연" in out and "분" in out, out)
    rc, out = run("voiceprint.py", root, "forget", "--name", "이서연")
    check("forget dry-runs by default", rc == 0 and "DRY RUN" in out, out)
    check("forget dry-run did not write",
          "이서연" in json.loads((root / "_meta" / "voiceprints.json").read_text(encoding="utf-8"))["people"], "")
    rc, out = run("voiceprint.py", root, "forget", "--name", "이서연", "--apply")
    st = json.loads((root / "_meta" / "voiceprints.json").read_text(encoding="utf-8"))
    check("forget --apply removes the voiceprint",
          rc == 0 and "이서연" not in st["people"] and "정우진" in st["people"], out)

    # 9b) regressions from code review — each of these shipped as a real bug once
    vp_path = root / "_meta" / "voiceprints.json"
    write(vp_path, json.dumps({"version": 1, "model": "campplus.onnx", "dim": VP_DIM,
        "people": {"박도현": {"centroids": [
            {"id": f"c{i}", "vec": vp_vec((0, 1.0), (i, 0.9)), "dur": 300.0 - i,
             "n": 2, "sources": ["old"], "updated": "2026-01-01"} for i in range(1, 6)]}}},
        ensure_ascii=False))
    e6 = vp_emb(root / "e6.json", [("0", vp_vec((7, 1.0)), 30.0)])   # new condition, short
    rc, out = run("voiceprint.py", root, "enroll", "--embeddings", e6,
                  "--map", '{"0": "박도현"}', "--source", "phone-call")
    st = json.loads(vp_path.read_text(encoding="utf-8"))
    cs = st["people"]["박도현"]["centroids"]
    check("a new centroid at the cap evicts an OLD one, never itself",
          len(cs) == 5 and any(c["sources"] == ["phone-call"] for c in cs)
          and "c5" not in [c["id"] for c in cs], out + "\n" + str([c["id"] for c in cs]))
    rc, out = run("voiceprint.py", root, "identify", "--embeddings", e6, "--out", labels)
    check("the newly learned condition is recognized (it was actually stored)",
          json.loads(labels.read_text(encoding="utf-8"))["auto"] == {"0": "박도현"}, out)

    wrongdim = vp_emb(root / "e7.json", [("0", [0.6, 0.8], 60.0)])
    rc, out = run("voiceprint.py", root, "enroll", "--embeddings", wrongdim,
                  "--map", '{"0": "박도현"}')
    check("a different embedding model is refused, not truncated into the store",
          "차원" in out and json.loads(vp_path.read_text(encoding="utf-8"))
          == st, out)
    rc, out = run("voiceprint.py", root, "identify", "--embeddings", wrongdim)
    check("identify refuses a mismatched embedding file too",
          rc != 0 and "차원" in out, out)

    write(vp_path, json.dumps({"version": 1, "model": "campplus.onnx", "dim": VP_DIM,
        "people": {"정우진": {"centroids": [{"id": "c1", "vec": vp_vec((0, 1.0)),
                                             "dur": 300.0, "n": 1, "sources": []}]},
                   "이서연": {"centroids": [{"id": "c1", "vec": vp_vec((1, 1.0)),
                                             "dur": 300.0, "n": 1, "sources": []}]}}},
        ensure_ascii=False))
    e8 = vp_emb(root / "e8.json", [("0", vp_vec((0, 1.0), (1, 0.1)), 100.0),
                                   ("1", vp_vec((0, 1.0), (1, 0.9)), 100.0)])
    rc, out = run("voiceprint.py", root, "identify", "--embeddings", e8, "--out", labels)
    L = json.loads(labels.read_text(encoding="utf-8"))
    loser = L["decisions"][1]
    check("an over-split cluster is offered its BEST candidate, not a worse one",
          loser["name"] == "정우진" and loser["score"] > loser["runner_up"][1],
          json.dumps(loser, ensure_ascii=False))
    check("...and the over-split remedy is stated, since that is the likely cause",
          "과다분할" in loser["reason"] and "recluster" in loser["reason"],
          loser["reason"])

    # 10) merge_diar consumes labels.json: auto → real name, rest stays Speaker N
    write(root / "w.json", json.dumps({"id": "x", "text": "", "segments": [
        {"start": 0.0, "end": 4.0, "text": "안녕하세요 시작하죠"},
        {"start": 5.0, "end": 9.0, "text": "네 자료 공유드릴게요"}]}, ensure_ascii=False))
    write(root / "diar.json", json.dumps([{"start": 0.0, "end": 4.5, "speaker": 0},
                                          {"start": 4.5, "end": 9.5, "speaker": 1}]))
    write(root / "lab.json", json.dumps({"auto": {"0": "정우진"}, "ask": ["1"]}, ensure_ascii=False))
    rc, out = run("merge_diar.py", root / "w.json", root / "diar.json", root / "out.txt",
                  "--labels", root / "lab.json")
    txt = (root / "out.txt").read_text(encoding="utf-8")
    check("merge_diar labels identified clusters and leaves the rest generic",
          rc == 0 and "정우진: 안녕하세요" in txt and "Speaker 2: 네 자료" in txt, txt)
    rc, out2 = run("merge_diar.py", root / "w.json", root / "diar.json", root / "out2.txt")
    check("merge_diar without --labels is unchanged",
          rc == 0 and "Speaker 1:" in (root / "out2.txt").read_text(encoding="utf-8"), out2)
    rc, out3 = run("merge_diar.py", root / "w.json", root / "diar.json", root / "out3.txt",
                   "--label", root / "lab.json")     # typo: singular
    check("a typo'd flag fails loudly instead of silently dropping every name",
          rc != 0 and "알 수 없는 옵션" in out3, out3)
    rc, out4 = run("merge_diar.py", root / "w.json", root / "diar.json", root / "out4.txt",
                   "--labels")
    check("--labels without a value fails with a usable message",
          rc != 0 and "labels.json" in out4, out4)


def test_lexicon(tmp):
    print("\n[11] lexicon — 용어 사전, 오타 교정, 되돌리기")
    root = tmp / "corpus_lex"
    build_corpus_v2(root)
    # a term said many times, and the same term mis-heard once in a later meeting
    make_transcript(root, "2026-06-01_커넥티비티.md", "커넥티비티 논의", "2026-06-01",
        "acme-0601", "\n".join(
            f"**[정우진] (00:0{i})** 커넥티비티가 핵심이다. 넥스트라와 커넥티비티를 늘리자."
            for i in range(1, 6)))
    make_transcript(root, "2026-06-02_오타.md", "오타 회의", "2026-06-02", "acme-0602",
        "**[정우진] (00:01)** 커텍티비티가 문제다. 이서면 님은 어떻게 보세요?\n"
        "**[이서연] (00:05)** 그거 다음 주까지 정리할게요.\n"
        "\n## 액션아이템\n- [ ] (이서연→정우진) 그 건 정리해서 공유 (기한: 2026-06-09)")

    rc, out = run("lexicon.py", root, "mine")
    check("mine exits 0 and separates 추론 from 후보", rc == 0
          and "커텍티비티 → 커넥티비티" in out and "자동 적용 대상(추론)" in out, out)
    check("mine flags a misheard PERSON name separately, not as a text fix",
          "인물 이름 오인식" in out and "이서면" in out, out)
    check("mine reports deictics left in action items", "지시어가 남은 액션아이템" in out, out)
    check("mine without --apply writes no lexicon",
          not (root / "_meta" / "lexicon.json").exists(), "")

    rc, out = run("lexicon.py", root, "mine", "--apply")
    lex = json.loads((root / "_meta" / "lexicon.json").read_text(encoding="utf-8"))
    forms = {m["form"]: m["status"] for t in lex["terms"] for m in t.get("misspellings", [])}
    check("mine --apply learns only the 추론 tier", forms.get("커텍티비티") == "추론"
          and "이서면" not in forms, json.dumps(forms, ensure_ascii=False))

    rc, out = run("lexicon.py", root, "apply")
    typo_file = root / "transcripts" / "2026" / "2026-06" / "2026-06-02_오타.md"
    check("apply dry-run reports but does not write", rc == 0 and "dry run" in out
          and "커텍티비티" in typo_file.read_text(encoding="utf-8"), out)
    rc, out = run("lexicon.py", root, "apply", "--apply")
    body = typo_file.read_text(encoding="utf-8")
    check("apply --apply corrects the transcript", rc == 0 and "커텍티비티" not in body
          and "커넥티비티가 문제다" in body, body[:300])
    check("apply names its backup batch and the rebuild chain",
          "lexicon-backup-" in out and "build_db.py" in out, out)
    batch = re.search(r"batch (\d{8}-\d{6})", out).group(1)
    check("backup holds the pre-correction original",
          "커텍티비티" in (root / "_ontology" / "_work" / f"lexicon-backup-{batch}"
                        / "transcripts" / "2026" / "2026-06" / "2026-06-02_오타.md")
          .read_text(encoding="utf-8"), "")
    log = [json.loads(l) for l in
           (root / "_meta" / "lexicon-corrections.jsonl").read_text(encoding="utf-8").splitlines()]
    check("every replacement is logged with its grounds",
          any(r["from"] == "커텍티비티" and r["status"] == "추론" and r["cmd"] == "apply"
              for r in log), json.dumps(log, ensure_ascii=False)[:300])

    rc, out = run("lexicon.py", root, "revert", "--batch", batch, "--apply")
    check("revert restores the batch", rc == 0
          and "커텍티비티" in typo_file.read_text(encoding="utf-8"), out)
    run("lexicon.py", root, "apply", "--apply")   # put it back for the rest of the test

    # patch: reader-decided edits (오탈자 · 지시어), names refused
    edits = tmp / "edits.json"
    write(edits, json.dumps([
        {"from": "그 건 정리해서", "to": "그 건〔=커넥티비티 안건〕 정리해서", "kind": "지시어"},
        {"from": "정우진", "to": "정우진2", "kind": "오탈자"}], ensure_ascii=False))
    rc, out = run("lexicon.py", root, "patch", "--file", edits,
                  "--path", "transcripts/2026/2026-06/2026-06-02_오타.md", "--apply")
    body = typo_file.read_text(encoding="utf-8")
    check("patch annotates the deictic instead of deleting the words",
          "그 건〔=커넥티비티 안건〕" in body, body[-200:])
    check("patch refuses to rewrite a registered person's name",
          "SKIP(인물)" in out and "정우진2" not in body, out)

    # a "misspelling" that is really another term must be caught by the gate
    lex = json.loads((root / "_meta" / "lexicon.json").read_text(encoding="utf-8"))
    lex["terms"].append({"term": "결제", "kind": "용어", "aliases": [], "status": "확정",
                         "misspellings": [{"form": "커넥티비티", "status": "확정"}]})
    write(root / "_meta" / "lexicon.json", json.dumps(lex, ensure_ascii=False))
    run("build_index.py", root)
    run("build_db.py", root)
    rc, out = run("validate.py", root)
    check("validate ERRORs when a misspelling collides with a real term",
          rc == 1 and "would destroy real text" in out, out[-500:])

    lex["terms"] = [t for t in lex["terms"] if t["term"] != "결제"]
    write(root / "_meta" / "lexicon.json", json.dumps(lex, ensure_ascii=False))
    rc, out = run("lexicon.py", root, "add", "--term", "넥스트라", "--kind", "조직",
                  "--misspelling", "넥스토라", "--desc", "가상의 파트너사")
    check("add records a user-confirmed pair as 확정", rc == 0 and "신규" in out, out)
    rc, out = run("lexicon.py", root, "add", "--term", "테스트용어",
                  "--misspelling", "정우진")
    check("add refuses a person's name as a misspelling form", "SKIP(인물)" in out, out)

    # DB surface: terms are queryable, and an unapplied correction is loud
    write(root / "transcripts" / "2026" / "2026-06" / "2026-06-03_재발.md",
          (root / "transcripts" / "2026" / "2026-06" / "2026-06-02_오타.md")
          .read_text(encoding="utf-8").replace("acme-0602", "acme-0603")
          .replace("커넥티비티가 문제다", "커텍티비티가 문제다"))
    run("build_index.py", root)
    rc, out = run("build_db.py", root)
    check("build_db WARNs about known misspellings still in the transcripts",
          "known misspellings are STILL" in out and "커텍티비티 → 커넥티비티" in out, out)
    db = sqlite3.connect(root / "_ontology" / "ontology.db")
    check("terms + term_misspellings are queryable (query mode can cite the lexicon)",
          db.execute("SELECT COUNT(*) FROM terms").fetchone()[0] >= 2
          and db.execute("SELECT desc FROM terms WHERE term='넥스트라'").fetchone()[0]
              == "가상의 파트너사", "")
    db.close()


def test_enrich(tmp):
    print("\n[12] enrich — 웹 보강 계획·캐시·반영 (프라이버시 게이트 포함)")
    root = tmp / "corpus_lex"
    rc, out = run("enrich.py", root, "plan", "--min-count", "4")
    check("plan exits 0 and composes its own queries", rc == 0 and "검색:" in out, out)
    check("plan never puts transcript sentences in a query",
          "문제다" not in out and "늘리자" not in out, out)
    check("people are not planned without --include-people",
          "[인물]" not in out.split("검색 제외")[0], out)
    rc, out = run("enrich.py", root, "plan", "--include-people")
    check("private relationships are excluded by the gate with a reason",
          "이서연" in out.split("검색 제외")[1] and "사적 관계" in out, out[-600:])
    check("a public role + org passes the gate", "[인물] 정우진" in out, out)

    res = tmp / "results.json"
    write(res, json.dumps({"results": [
        {"entity": "넥스트라", "kind": "조직", "canonical": "넥스트라(Nextra Inc.)",
         "summary": "숙박 유통 API를 제공하는 가상의 파트너사",
         "facts": [{"text": "2019년 설립", "url": "https://example.com/nextra"}],
         "spelling_variants": ["넥스트러"], "status": "확인됨"},
        {"entity": "커넥티비티", "kind": "용어", "summary": "연결 개수",
         "facts": [], "status": "확인됨"}]}, ensure_ascii=False))
    rc, out = run("enrich.py", root, "save", "--file", res)
    check("a claim with no URL is refused, and 확인됨 without facts is downgraded",
          rc == 0 and "DOWNGRADE(커넥티비티)" in out, out)
    enr = json.loads((root / "_meta" / "enrichment.json").read_text(encoding="utf-8"))
    check("cache keeps the URL and the fetch date on every fact",
          enr["entities"]["넥스트라"]["facts"][0]["url"].startswith("http")
          and enr["entities"]["넥스트라"]["facts"][0]["fetched"], "")

    rc, out = run("enrich.py", root, "apply")
    lex = json.loads((root / "_meta" / "lexicon.json").read_text(encoding="utf-8"))
    check("apply dry-run writes nothing",
          rc == 0 and "dry run" in out
          and not any(t.get("desc") == "연결 개수" for t in lex["terms"]), out)
    rc, out = run("enrich.py", root, "apply", "--apply")
    lex = json.loads((root / "_meta" / "lexicon.json").read_text(encoding="utf-8"))
    nx = next(t for t in lex["terms"] if t["term"] == "넥스트라")
    check("the formal name becomes an ALIAS, never the correction target",
          "넥스트라(Nextra Inc.)" in nx["aliases"]
          and all(m["form"] != "넥스트라(Nextra Inc.)" for m in nx["misspellings"]),
          json.dumps(nx, ensure_ascii=False))
    check("a web-sourced spelling fix needs a human unless --trust-web",
          next(m for m in nx["misspellings"] if m["form"] == "넥스트러")["status"] == "후보",
          json.dumps(nx["misspellings"], ensure_ascii=False))
    check("apply does not overwrite a description a human already wrote",
          nx["desc"] == "가상의 파트너사", nx["desc"])

    rc, out = run("build_db.py", root)
    db = sqlite3.connect(root / "_ontology" / "ontology.db")
    rows = db.execute("SELECT entity, fact, url, source FROM entity_facts").fetchall()
    check("web facts land in their own table with a URL (never in models/evidence)",
          any(r[0] == "넥스트라" and r[3] == "web" and r[2].startswith("http") for r in rows),
          str(rows))
    db.close()
    rc, out = run("validate.py", root)
    check("validate reports web facts as external, not as evidence",
          "외부 출처" in out and "근거 등급을 올리지 않음" in out, out[-400:])

    # right to be forgotten reaches the dictionary and the web cache too
    pp = tmp / "corpus_lex_purge"
    shutil.copytree(root, pp)
    reg = json.loads((pp / "_meta" / "speakers.json").read_text(encoding="utf-8"))
    for e in reg:
        if e["name"] == "정우진":
            e["public"] = True
    write(pp / "_meta" / "speakers.json", json.dumps(reg, ensure_ascii=False))
    enr = json.loads((pp / "_meta" / "enrichment.json").read_text(encoding="utf-8"))
    enr["entities"]["정우진"] = {"kind": "인물", "summary": "가상 인물", "status": "불확실",
                                "facts": [{"text": "x", "url": "https://example.com/p",
                                           "fetched": "2026-09-01"}]}
    write(pp / "_meta" / "enrichment.json", json.dumps(enr, ensure_ascii=False))
    rc, out = run("purge_person.py", pp, "--name", "정우진", "--apply")
    enr = json.loads((pp / "_meta" / "enrichment.json").read_text(encoding="utf-8"))
    check("purge removes cached web findings about the person",
          rc == 0 and "정우진" not in enr["entities"], out[-400:])
    log = (pp / "_meta" / "lexicon-corrections.jsonl")
    check("purge scrubs correction-log lines naming them",
          not log.exists() or "정우진" not in log.read_text(encoding="utf-8"), "")


def main():
    with tempfile.TemporaryDirectory(prefix="mental-ontology-tests-") as td:
        tmp = Path(td)
        test_pipeline_v2(tmp)
        test_dossiers(tmp)
        test_browse(tmp)
        test_readings(tmp)
        test_briefing(tmp)
        test_calendar(tmp)
        test_validate_catches_errors(tmp)
        test_batch_pipeline(tmp)
        test_purge_person(tmp)
        test_voiceprint(tmp)
        test_lexicon(tmp)
        test_enrich(tmp)
        test_migration_v1_to_v2(tmp)
    print(f"\n{'FAIL' if FAILURES else 'PASS'}: {PASS} passed, {len(FAILURES)} failed"
          + (f" — {FAILURES}" if FAILURES else ""))
    sys.exit(1 if FAILURES else 0)

if __name__ == "__main__":
    main()
