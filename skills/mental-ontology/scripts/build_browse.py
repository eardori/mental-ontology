#!/usr/bin/env python3
"""Build _index/BROWSE.md — 인물별 · 회사별 · 주제별 탐색 인덱스.

build_index.py 끝에서 자동 호출된다. 단독 실행도 가능:
    python3 build_browse.py <corpus_path>

- 인물: 참석자 프론트매터 → speakers.json 이름·별칭으로 정규화, 없으면 괄호·직함 제거
- 회사·주제: <corpus>/_meta/topics.json 의 키워드 부분일치 (회사=참석자+제목, 주제=제목+파일명)
- 🔒 = sensitivity L3 또는 confidentiality 지정 문서
"""
import os, sys, json, re
from collections import defaultdict

TITLES = ("대표", "부사장", "사장", "이사", "상무", "전무", "팀장", "파트장", "본부장", "실장",
          "차장", "부장", "과장", "책임", "프로", "매니저", "고문", "교수", "심사역", "수석", "님")
SKIP = re.compile(r"^(Speaker\s*\d+|미상|사회자|참석자|동석|동행|다수|청중|기타|담당자|상대방?|대표|CEO|\?)", re.I)
GENERIC = {"대표", "내부", "담당자", "상대", "상대방", "ceo", "고객", "직원", "실무자"}


def load_speakers(corpus):
    """→ (alias map lower→canonical, owner canonical name or None). owner = 레지스트리 `"owner": true`."""
    try:
        sp = json.load(open(os.path.join(corpus, "_meta", "speakers.json"), encoding="utf-8"))
    except Exception:
        return {}, None
    alias, owner = {}, None
    for s in sp:
        name = s.get("name", "")
        if not name:
            continue
        keys = [name] + list(s.get("aliases", []))
        m = re.match(r"^([^(]+)\(([^)]+)\)$", name)          # "Jade(원경묵)" → Jade, 원경묵
        if m:
            keys += [m.group(1).strip(), m.group(2).strip()]
        for k in keys:
            alias.setdefault(k.strip().lower(), name)
        if s.get("owner") is True:
            owner = name
    return alias, owner


def norm_person(raw, alias, skip=()):
    raw = raw.strip().strip("[]'\"").strip()
    if "\\u" in raw:                                          # JSON 이스케이프로 저장된 옛 문서
        try:
            raw = raw.encode().decode("unicode_escape")
        except Exception:
            pass
    if not raw or SKIP.match(raw):
        return None
    if raw.lower() in alias:
        return alias[raw.lower()]
    base = re.sub(r"\(.*$", "", raw).strip()                  # 괄호 앞부분
    for t in TITLES:
        base = re.sub(rf"\s*{t}$", "", base).strip()
    if not base or base.lower() in GENERIC or base.lower().split()[0] in skip or "미상" in raw:   # "온다 팀" 등 접두 일치
        return None
    if base.lower() in alias:
        return alias[base.lower()]
    inner = re.search(r"\(([^,)·/]+)", raw)                   # "Jayce(장재훈, ...)" → 장재훈
    if inner and inner.group(1).strip().lower() in alias:
        return alias[inner.group(1).strip().lower()]
    org = re.search(r"\(([^,)·/ ]+)", raw)                    # 동명이인 구분: "신승민 대표(큐비트시큐리티)" → 신승민(큐비트시큐리티)
    return f"{base}({org.group(1)})" if org else base


def has(keys, text):
    """대문자 약어(AI·IR·CRS)는 대소문자 구분 — 'email'·'detail'에 AI가 걸리는 오탐 방지."""
    low = text.lower()
    return any((k in text) if (k.isascii() and k.isupper()) else (k.lower() in low) for k in keys)


def lock(r):
    return "🔒 " if (r.get("confidential") or str(r.get("sensitivity", "")).startswith("L3")) else ""


def md(r):
    """표준 마크다운 링크 — Obsidian·Typora·GitHub 모두 동작. <> 로 감싸 공백·괄호 있는 경로도 안전."""
    t = (r.get("title") or r["vault_link"]).replace("[", "(").replace("]", ")").replace("|", "／")
    return f'{lock(r)}[{t}](<../{r["path"]}>)'


def link(r):
    dur = f' · {r["duration_min"]}min' if r.get("duration_min") else ""
    return f'- `{r["date"]}` {md(r)}{dur}'


def build(corpus, rows):
    cfg_p = os.path.join(corpus, "_meta", "topics.json")
    cfg = json.load(open(cfg_p, encoding="utf-8")) if os.path.exists(cfg_p) else {"topics": [], "orgs": []}
    skip = {x.lower() for x in cfg.get("skip_people", [])}   # 사람이 아닌 참석자 표기 (예: 회사명)
    alias, owner = load_speakers(corpus)   # 본인은 인물 목록에서 뺀다 (모든 회의에 나오므로)

    people, orgs, topics = defaultdict(list), defaultdict(list), defaultdict(list)
    untagged = []
    for r in rows:
        if not r.get("date"):
            continue
        parts = r.get("participants") or []
        for p in parts:
            n = norm_person(p, alias, skip)
            if n and n != owner:
                if r not in people[n]:
                    people[n].append(r)
        pstr = " ".join(parts) + " " + r.get("title", "")
        for o in cfg.get("orgs", []):
            if has(o["keywords"], pstr):
                orgs[o["name"]].append(r)
        hay = r.get("title", "") + " " + r.get("vault_link", "")
        hit = False
        for t in cfg.get("topics", []):
            if t.get("since") and r["date"] < t["since"]:
                continue
            if has(t["keywords"], hay):
                topics[t["name"]].append(r)
                hit = True
        if not hit:
            untagged.append(r)

    newest = lambda lst: sorted(lst, key=lambda x: x["date"], reverse=True)
    L = ["# 코퍼스 탐색 인덱스 — 인물별 · 회사별 · 주제별", "",
         f"> {len(rows)}개 문서 · 자동 생성(build_browse.py, build_index.py 실행 시 함께 갱신) · "
         "분류 규칙 `_meta/topics.json` · 🔒 = L3·기밀", "",
         "## 바로가기", "", "- [주제별](#주제별) · [회사·기관별](#회사기관별) · [인물별](#인물별)", "",
         "---", "## 주제별", "", "| 주제 | 건수 | 최근 |", "|---|---:|---|"]
    tnames = [t["name"] for t in cfg.get("topics", []) if topics.get(t["name"])]
    for n in tnames:
        L.append(f"| {n} | {len(topics[n])} | {max(x['date'] for x in topics[n])} |")
    L.append(f"| (미분류) | {len(untagged)} | — |")
    for n in tnames:
        L += ["", f"### {n} ({len(topics[n])})", ""] + [link(r) for r in newest(topics[n])]

    L += ["", "---", "## 회사·기관별", "", "| 회사·기관 | 건수 | 최근 |", "|---|---:|---|"]
    onames = sorted(orgs, key=lambda k: (-len(orgs[k]), k))
    for n in onames:
        L.append(f"| {n} | {len(orgs[n])} | {max(x['date'] for x in orgs[n])} |")
    for n in onames:
        L += ["", f"### {n} ({len(orgs[n])})", ""] + [link(r) for r in newest(orgs[n])]

    multi = sorted((k for k in people if len(people[k]) >= 2), key=lambda k: (-len(people[k]), k))
    single = sorted(k for k in people if len(people[k]) == 1)
    L += ["", "---", "## 인물별", "",
          f"> 2회 이상 {len(multi)}명 · 1회 {len(single)}명. 핵심 인물 성향·이력은 `people/` 도시에.", ""]
    for n in multi:
        L += [f"### {n} ({len(people[n])}회)", ""] + [link(r) for r in newest(people[n])] + [""]
    L += ["### 1회 만남", "", "| 인물 | 날짜 | 문서 |", "|---|---|---|"]
    for n in single:
        r = people[n][0]
        L.append(f'| {n} | {r["date"]} | {md(r)} |')

    out = os.path.join(corpus, "_index", "BROWSE.md")
    open(out, "w", encoding="utf-8").write("\n".join(L) + "\n")
    os.chmod(out, 0o600)
    print(f"OK: BROWSE.md — 주제 {len(tnames)} · 회사 {len(onames)} · 인물 {len(people)} (미분류 {len(untagged)})")


if __name__ == "__main__":
    c = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.getcwd()
    build(c, json.load(open(os.path.join(c, "_index", "catalog.json"), encoding="utf-8")))
