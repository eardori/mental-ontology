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
import json, os, shutil, sqlite3, subprocess, sys, tempfile
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
    db.close()

    rc, out = run("validate.py", root)
    check("validate passes on clean v2 corpus", rc == 0, out)
    check("validate reports attribution coverage", "coverage:" in out, out)
    check("quote verification: grounded quote passes", "quotes: 1/1 grounded" in out, out)

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

def test_validate_catches_errors(tmp):
    print("\n[2] validate — must catch integrity & honesty violations")
    root, bad = tmp / "corpus_v2", tmp / "corpus_bad"
    shutil.copytree(root, bad)
    op = bad / "_ontology" / "objects.json"
    d = json.loads(op.read_text(encoding="utf-8"))
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

def main():
    with tempfile.TemporaryDirectory(prefix="mental-ontology-tests-") as td:
        tmp = Path(td)
        test_pipeline_v2(tmp)
        test_dossiers(tmp)
        test_validate_catches_errors(tmp)
        test_migration_v1_to_v2(tmp)
    print(f"\n{'FAIL' if FAILURES else 'PASS'}: {PASS} passed, {len(FAILURES)} failed"
          + (f" — {FAILURES}" if FAILURES else ""))
    sys.exit(1 if FAILURES else 0)

if __name__ == "__main__":
    main()
