#!/usr/bin/env python3
"""녹음 ↔ 캘린더 일정 매칭 — 그 자리가 어떤 자리였는지(TPO)를 회의록에 붙인다.

Plaud는 녹음이 '언제 몇 분'인지만 안다. 캘린더는 그 시간에 **무슨 자리였는지**를 안다:
제목, 참석자 명단, 장소, 정기 여부. 셋 다 이 코퍼스가 추론으로 때우던 것들이다.

- **참석자 = 화자 정답지.** "Speaker 2가 누구지"를 추측할 필요가 없다. 명단이 있다.
- **TPO = 발언을 읽는 문맥.** 같은 문장도 임원 전략회의와 저녁 식사 자리에서 무게가
  다르다. `setting`은 EXTRACTION.md의 sincerity 판단에 그대로 들어간다.
- **제목·분류.** Plaud의 "2026-07-10 16:15:15" 대신 실제 안건명.

캘린더는 스크립트가 못 읽는다(MCP는 Claude만 호출 가능) — 스킬이 일정을 받아
`_meta/calendar/<YYYY-MM>.json`에 캐시하고, 이 스크립트는 그 캐시로 **결정적으로**
매칭한다. 그래야 재실행이 같은 답을 내고 테스트할 수 있다.

캐시 형식 (스킬이 씀):
  {"fetched": "YYYY-MM-DD", "range": ["YYYY-MM-DD", "YYYY-MM-DD"],
   "owner_domain": "onda.me",
   "events": [{"id", "title", "start": "YYYY-MM-DDTHH:MM", "end": "...",
               "location": "", "description": "", "recurring": false,
               "attendees": [{"name": "", "email": "", "self": false}]}]}

Usage:
  python3 match_calendar.py <corpus>                    # 매칭 리포트 (기본: 미적용)
  python3 match_calendar.py <corpus> --apply            # 회의록 프론트매터 반영
  python3 match_calendar.py <corpus> --since 2026-08-01 --min-overlap 0.5

`--apply`는 비어 있거나 자동 생성된 값만 채운다: 자동 타임스탬프 제목, 빈/기타 분류,
빈 참석자. 사람이 적은 값은 절대 덮어쓰지 않고 리포트에만 남긴다. `setting`과
`calendar_event`(출처)는 항상 채운다.

Deps: python3 stdlib only.
"""
import argparse, glob, json, os, re, sys
from datetime import datetime, timedelta, timezone

# Plaud 자동 제목("2026-07-10 16:15:15")만 잡는다. 끝까지 앵커하지 않으면
# "2026-07-10 넥스트라 협상 3차" 같은 사람이 쓴 제목까지 덮어쓴다.
AUTO_TITLE = re.compile(
    r'^\s*\d{4}[-.\s/]\d{1,2}[-.\s/]\d{1,2}'
    r'([\s_T]+\d{1,2}[:\-]\d{2}([:\-]\d{2})?)?\s*$')
CANON_CATS = {"내부-주간회의", "내부-전략", "내부-1on1", "외부-파트너", "외부-고객영업",
              "외부-투자IR", "강연-세미나", "인터뷰", "개인-통화", "기타"}
# 짧은 토큰의 부분일치가 자리를 오분류하면 EXTRACTION의 근거 보정까지 흘러간다
# ('기술 로드맵'이 식사자리로 분류되면 그 회의 발언이 mid로 깎인다). 변별력 있는 말만 쓴다.
MEAL_WORDS = ("식당", "식사", "점심", "회식", "런치", "디너", "브런치", "카페", "커피",
              "술자리", "술집", "맥주", "소주", "와인", "반주", "만찬")
MEAL_LATIN = r'\b(lunch|dinner|brunch|cafe|coffee|restaurant|bar|drinks)\b'
VIDEO_WORDS = ("zoom", "meet.google", "teams", "webex", "hangout", "화상", "온라인", "구글밋")
OFFICE_WORDS = ("회의실", "사무실", "office", "본사", "room", "미팅룸")


def parse_dt(s):
    """ISO timestamp → naive LOCAL datetime.

    An offset (`Z` or `±HH:MM`) is converted to this machine's local time, never
    dropped: discarding it would shift a 10:00 KST meeting to 01:00 and match the
    recording against the wrong event — silently, with the wrong TPO written into the
    transcript.
    """
    if not s:
        return None
    s = str(s).strip()
    m = re.search(r'(Z|[+-]\d{2}:?\d{2})$', s)
    if m:
        base = s[:m.start()]
        off = "+0000" if m.group(1) == "Z" else m.group(1).replace(":", "")
        for f in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
            try:
                aware = datetime.strptime(base, f).replace(
                    tzinfo=timezone(timedelta(
                        hours=int(off[:3]), minutes=int(off[0] + off[3:5]))))
                return aware.astimezone().replace(tzinfo=None)
            except ValueError:
                continue
        return None
    for f in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S",
              "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(s[:19] if len(s) >= 19 else s, f)
        except ValueError:
            continue
    return None


def load_events(corpus):
    out = []
    for p in sorted(glob.glob(os.path.join(corpus, "_meta", "calendar", "*.json"))):
        try:
            d = json.load(open(p, encoding="utf-8"))
        except json.JSONDecodeError as e:
            print(f"WARN: {os.path.basename(p)} 파싱 실패 ({e}) — 건너뜁니다")
            continue
        dom = d.get("owner_domain", "")
        for e in d.get("events", []):
            st, en = parse_dt(e.get("start")), parse_dt(e.get("end"))
            if not st:
                continue
            # 종일 일정(연차·휴가·공휴일)은 자정~자정이라 그날 어떤 녹음과도 100% 겹친다 —
            # 후보로 두면 모든 녹음이 '연차'라는 제목과 TPO를 뒤집어쓴다.
            if not re.search(r'\d{2}:\d{2}', str(e.get("start", ""))):
                continue
            out.append({**e, "_start": st, "_end": en or st + timedelta(minutes=60),
                        "_domain": dom, "_src": os.path.basename(p)})
    out.sort(key=lambda e: e["_start"])
    return out


def describe_setting(ev):
    """TPO — 셀 수 있는 것만으로 자리의 성격을 적는다 (추론 아님, 캘린더에 적힌 것)."""
    st, en = ev["_start"], ev["_end"]
    h = st.hour
    when = ("아침" if h < 10 else "오전" if h < 11 else "점심" if h < 14 else
            "오후" if h < 17 else "저녁" if h < 21 else "야간")
    dow = "월화수목금토일"[st.weekday()]
    blob = f"{ev.get('location','')} {ev.get('title','')} {ev.get('description','')}".lower()
    if any(w in blob for w in VIDEO_WORDS):
        where = "화상"
    elif any(w in blob for w in MEAL_WORDS) or re.search(MEAL_LATIN, blob):
        where = "식사자리"
    elif any(w in blob for w in OFFICE_WORDS):
        where = "사무실"
    elif ev.get("location"):
        where = "외부장소"
    else:
        where = ""
    dom = (ev.get("_domain") or "").lower()
    ext_domains, n_att, n_email = set(), 0, 0
    for a in ev.get("attendees", []) or []:
        email = (a.get("email") or "").lower()
        n_att += 1
        d = email.split("@")[-1] if "@" in email else ""
        if d:
            n_email += 1
            if dom and d != dom:
                ext_domains.add(d)
    # 내부/외부는 이메일 도메인이 있을 때만 말할 수 있다. owner_domain이 없거나 참석자가
    # 이름만 있으면 "모른다"가 정답 — 외부 저녁 자리를 '내부'로 단정하면 그 오해가
    # 분류와 근거 등급(EXTRACTION의 sincerity 보정)까지 흘러간다.
    knows_sides = bool(dom) and n_email > 0
    if not n_att:
        who = ""
    elif not knows_sides:
        who = f"{n_att}인(내부·외부 미상)"
    else:
        who = ("외부 포함" if ext_domains else "내부") + f"({n_att}인)"
    parts = [f"{when}·{dow}", where, who]
    if ev.get("recurring"):
        parts.append("정기")
    return (" · ".join(x for x in parts if x), sorted(ext_domains),
            n_att if knows_sides else 0)


def suggest_category(ev, setting, ext_domains, n_att):
    """기존 분류 체계로의 제안. 확신할 수 없으면 빈 문자열 — 억지로 찍지 않는다.

    n_att == 0 은 '참석자를 못 셌다'(도메인 정보 없음)는 뜻이므로 내부/외부 판단을
    하지 않는다 — describe_setting이 그렇게 넘겨준다.
    """
    title = (ev.get("title") or "")
    if ext_domains:
        if "식사자리" in setting:
            return "외부-파트너"
        if re.search(r'IR|투자|심사|벤처|캐피탈|파트너스', title, re.I):
            return "외부-투자IR"
        if re.search(r'데모|제안|영업|도입|견적', title, re.I):
            return "외부-고객영업"
        return "외부-파트너"
    if n_att:
        if ev.get("recurring") and n_att >= 3:
            return "내부-주간회의"
        if n_att == 2:
            return "내부-1on1"
        return "내부-전략"
    return ""


def overlap_score(r_start, r_end, ev):
    lo, hi = max(r_start, ev["_start"]), min(r_end, ev["_end"])
    ov = (hi - lo).total_seconds()
    if ov <= 0:
        return 0.0
    shorter = min((r_end - r_start).total_seconds(),
                  (ev["_end"] - ev["_start"]).total_seconds()) or 1
    return ov / shorter


def match_all(rows, events, min_overlap):
    """각 녹음에 대해 (event, score, reason). 시간이 없으면 같은 날 후보로 낮춰 제안."""
    out = []
    for r in rows:
        d = str(r.get("date") or "")[:10]
        same_day = [e for e in events if e["_start"].strftime("%Y-%m-%d") == d]
        st = parse_dt(f"{d}T{r['start_time']}") if r.get("start_time") else None
        if st:
            dur = r.get("duration_min") or 60
            en = st + timedelta(minutes=int(dur))
            scored = sorted(((overlap_score(st, en, e), e) for e in same_day),
                            key=lambda x: -x[0])
            if scored and scored[0][0] >= min_overlap:
                out.append((r, scored[0][1], round(scored[0][0], 2), "시간 겹침"))
                continue
            if scored and scored[0][0] > 0.15:
                out.append((r, scored[0][1], round(scored[0][0], 2), "부분 겹침 — 확인 필요"))
                continue
            out.append((r, None, 0.0, f"같은 날 일정 {len(same_day)}건 중 겹치는 것 없음"))
            continue
        if len(same_day) == 1:
            out.append((r, same_day[0], 0.0, "시작 시각 없음 — 그날 유일한 일정"))
        elif same_day:
            titles = ", ".join(e.get("title", "?") for e in same_day[:4])
            out.append((r, None, 0.0, f"시작 시각 없음 · 그날 일정 {len(same_day)}건: {titles}"))
        else:
            out.append((r, None, 0.0, "해당 날짜 일정 없음"))
    return out


def patch_frontmatter(path, updates):
    """프론트매터의 키만 갱신/추가한다. 본문은 건드리지 않는다(토큰 이코노미 규칙)."""
    text = open(path, encoding="utf-8").read()
    m = re.match(r'^(---\s*\n)(.*?)(\n---\s*\n)', text, re.S)
    if not m:
        return False
    head, body, tail = m.group(1), m.group(2), m.group(3)
    lines = body.split("\n")
    def q(x):
        # 값 안의 쉼표는 참석자 목록을 쪼개고("Kim, Mina" → 두 사람), 따옴표는 YAML을
        # 깨뜨린다. 항상 감싸고 이스케이프한다.
        return '"' + str(x).replace('\\', '\\\\').replace('"', '\\"') + '"'

    for k, v in updates.items():
        val = ("[" + ", ".join(q(x) for x in v) + "]") if isinstance(v, list) else q(v)
        line = f"{k}: {val}"
        for i, ln in enumerate(lines):
            if re.match(rf'^{re.escape(k)}\s*:', ln):
                lines[i] = line
                # 블록 스타일("key:\n  - a\n  - b")이면 뒤따르는 항목 줄이 고아로 남는다
                j = i + 1
                while j < len(lines) and re.match(r'^\s+-\s', lines[j]):
                    lines.pop(j)
                break
        else:
            lines.append(line)
    open(path, "w", encoding="utf-8").write(head + "\n".join(lines) + tail + text[m.end():])
    return True


def main():
    ap = argparse.ArgumentParser(description="녹음과 캘린더 일정을 맞추고 TPO를 회의록에 붙인다")
    ap.add_argument("corpus")
    ap.add_argument("--apply", action="store_true", help="프론트매터에 반영 (기본: 리포트만)")
    ap.add_argument("--since", default="", help="이 날짜 이후 녹음만")
    ap.add_argument("--min-overlap", type=float, default=0.5)
    a = ap.parse_args()
    corpus = os.path.abspath(a.corpus)

    cat_path = os.path.join(corpus, "_index", "catalog.json")
    if not os.path.exists(cat_path):
        sys.exit(f"ERROR: {cat_path} 없음 — build_index.py 를 먼저 실행하세요.")
    rows = [r for r in json.load(open(cat_path, encoding="utf-8"))
            if str(r.get("date", "")) >= a.since]
    events = load_events(corpus)
    if not events:
        sys.exit("ERROR: _meta/calendar/*.json 에 일정이 없습니다 — 스킬이 캘린더를 "
                 "받아 캐시한 뒤에 실행하세요 (stages/ingest.md Stage 1b).")

    print(f"녹음 {len(rows)}건 · 일정 {len(events)}건 (캐시 {len({e['_src'] for e in events})}개 파일)")
    matched = match_all(rows, events, a.min_overlap)
    n_ok = n_ask = n_none = 0
    changes = []
    for r, ev, score, why in matched:
        name = os.path.basename(r.get("path", ""))
        if not ev:
            n_none += 1
            print(f"  ·  {r['date']} {name}: {why}")
            continue
        setting, ext, n_att = describe_setting(ev)
        cat = suggest_category(ev, setting, ext, n_att)
        # 표시 이름이 없는 참석자는 건너뛴다 — 이메일을 이름으로 넣으면
        # person_meetings와 도시에가 'mina@nextra.co.kr' 이름으로 생긴다.
        att = [x.get("name", "").strip() for x in (ev.get("attendees") or [])]
        n_noname = sum(1 for x in (ev.get("attendees") or []) if not x.get("name"))
        att = [x for x in att if x]
        confident = score >= a.min_overlap
        n_ok += confident
        n_ask += not confident
        print(f"  {'✓' if confident else '?'}  {r['date']} {name}")
        print(f"       ↔ 「{ev.get('title','')}」 ({why}{f', {score}' if score else ''})")
        print(f"       TPO: {setting}" + (f" · 외부도메인 {', '.join(ext)}" if ext else ""))

        upd, notes = {}, []
        upd["setting"] = setting
        upd["calendar_event"] = ev.get("id", "")
        if AUTO_TITLE.match(str(r.get("title", ""))) or not r.get("title"):
            upd["title"] = ev.get("title", "")
        elif ev.get("title") and ev["title"] not in str(r.get("title", "")):
            notes.append(f"제목 유지(사람이 정함): '{r['title']}' ≠ 일정 '{ev['title']}'")
        if att and not r.get("participants"):
            upd["participants"] = att
        elif att and set(att) - set(r.get("participants") or []):
            notes.append("참석자 추가 후보: " + ", ".join(sorted(set(att) - set(r["participants"]))))
        if cat and (not r.get("category") or r["category"] == "기타"):
            upd["category"] = cat
        elif cat and r.get("category") != cat:
            notes.append(f"분류 유지: '{r.get('category')}' (일정 기준 제안 '{cat}')")
        if n_noname:
            notes.append(f"표시 이름 없는 참석자 {n_noname}명은 제외됨 (이메일은 이름이 아니다)")
        for n in notes:
            print(f"       ! {n}")
        if confident:
            changes.append((r, upd))

    print(f"\n{'APPLIED' if a.apply else 'DRY RUN'} — 확정 {n_ok} · 확인 필요 {n_ask} · 매칭 없음 {n_none}")
    if a.apply:
        n, failed = 0, []
        for r, upd in changes:
            if patch_frontmatter(os.path.join(corpus, r["path"]), upd):
                n += 1
            else:
                failed.append(r["path"])
        print(f"프론트매터 {n}건 갱신 — build_index.py → build_db.py 를 다시 실행하세요.")
        if failed:
            print(f"WARN: {len(failed)}건은 프론트매터가 없어 건너뛰었습니다: {failed[:3]}")
    elif changes:
        print("--apply 를 붙이면 확정 건의 setting/calendar_event(+빈 제목·참석자·분류)를 채웁니다.")
    if n_ask:
        print("WARN: 확인 필요 건은 사람이 판단해야 합니다 — 겹침이 부분적이거나 "
              "시작 시각이 없습니다 (프론트매터에 start_time: HH:MM 을 넣으면 정확해집니다).")


if __name__ == "__main__":
    main()
