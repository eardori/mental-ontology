# Corpus Folder Structure

Created at the user's chosen `corpus_path` (config: `~/.mental-ontology.json`).
Plain markdown — works standalone or inside an Obsidian vault.

```
<corpus>/
├── transcripts/                  # cleaned meeting markdown (the corpus)
│   └── <YYYY>/<YYYY-MM>/
│       └── <YYYY-MM-DD>_<slug>.md        # frontmatter + summary + transcript
├── _index/
│   ├── INDEX.md                  # human-readable index (category/month, standard md links)
│   ├── BROWSE.md                 # 인물별 · 회사별 · 주제별 탐색 인덱스 (build_browse.py, 🔒 = L3·기밀)
│   └── catalog.json              # machine-readable index (for agents/tools)
├── people/                       # person dossiers (build_dossiers.py) — the 인물 중심 artifact
│   ├── INDEX.md                  # tiers, contacts (auto-collected), promotion candidates
│   └── <이름>.md                  # identity · 개인 맥락 · 멘탈모델 · 관계 · 접촉 이력 · 수기 메모(보존)
├── _meta/
│   ├── speakers.json             # PERSON REGISTRY (Stage 3) — aliases power DB joins;
│   │                             #   tier/first_met_context/intro_by/personal[] power dossiers
│   ├── voiceprints.json          # VOICE IDENTITY (Stage 2b/3) — per-person voice centroids;
│   │                             #   biometric, local only, purged by purge_person.py
│   ├── lexicon.json              # 용어 사전 (Stage 4b) — 이 조직이 쓰는 말 + STT가 그걸
│   │                             #   틀리는 방식. 본문 교정의 근거이자 query mode의 terms 테이블
│   ├── lexicon-corrections.jsonl # 교정 감사 로그 — 언제 무엇을 무슨 근거로 바꿨는지 (append-only)
│   ├── enrichment.json           # 웹 보강 캐시 (Stage 4c) — 주장마다 URL·수집일. 근거 아님
│   ├── calendar/                 # 캘린더 캐시 (Stage 1b) — 월별 일정, 매칭의 입력
│   │   └── <YYYY-MM>.json        #   {fetched, range, owner_domain, events[]}
│   ├── topics.json               # BROWSE.md 분류 규칙 — 주제·회사별 키워드 (예시: assets/topics.example.json)
│   ├── state.json                # {"last_synced": "YYYY-MM-DD"}
│   └── deletion-candidates.md    # junk recordings to delete in the Plaud app
├── _whisper/                     # local transcription workspace
│   └── <id>.json                 # whisper output {id, text, segments}
├── _ontology/
│   ├── objects.json              # the ontology, schema v2 (data of record)
│   ├── objects_v1_backup*.json   # migration backups (safe to archive)
│   ├── ontology.db               # SQLite DB (Stage 7 — rebuilt, don't hand-edit)
│   ├── index.html                # self-contained viewer (embedded data)
│   ├── REPORT.md                 # narrative report
│   └── _work/                    # intermediate files ONLY — batch-pipeline workdirs
│       ├── <date-label>/         #  (extract/synth files) + purge-backup-<이름>/;
│       │                         #  deletable after a validated build / final purge
│       └── lexicon-backup-<batch>/  # 교정 직전 원본 — `lexicon.py revert --batch` 의 대상
└── _strategy/                    # Stage 9 deliverables (OPPORTUNITIES-*, STRATEGY-*, …)
```

## Conventions

- **Transcript filename**: date + short content slug (Korean OK, spaces → `-`);
  split recordings get `_part1`, `_part2`.
- **Dedup key**: frontmatter `source_id` (Plaud file id) — check `catalog.json` before processing.
- **Scratch discipline**: anything intermediate (batch lists, per-meeting extraction
  parts, aggregation passes) lives under `_ontology/_work/<date-label>/` or the session
  scratchpad — never loose files in `_ontology/` or `_meta/`. After `validate.py`
  passes, `_work/` contents may be deleted.
- **speakers.json = the person registry.** The `name` is the canonical name used
  everywhere (ontology `people[].name`, DB joins, dossier filenames). `aliases`
  must list **every raw label** the person appears under in transcripts;
  `Name(Other)` names match both halves automatically:
  ```json
  [{ "name": "James(정우진)", "role": "CEO", "org": "Acme", "owner": true,
     "aliases": ["제임스", "Speaker 2(2026-07-10)"],
     "traits": "구조 먼저, 숫자로 검증", "meetings": ["2026-07-10"],
     "tier": "core",
     "relationship": "파트너",
     "team": "경영진", "manager": "",
     "first_met_context": "SaaS 밋업에서 패널로 처음 만남",
     "intro_by": "이서연",
     "personal": [{ "date": "2026-06-24", "note": "10월 마라톤 준비 중", "use": "사적" }] }]
  ```
  `owner: true` marks the corpus owner — exactly one entry should have it; it is what
  lets `build_briefing.py` separate 내가 한 약속 from 상대가 한 약속 (absent → it guesses
  the most-attending person and labels the guess).
  `relationship` = 나(owner)와의 관계 (팀원/내부-타팀/상사·보드/파트너/고객/투자자/지인/가족 —
  자유 텍스트). `team`/`manager` = **조직도** — org chart lives as per-person edges here,
  and `build_db.py` derives them into the `network` table as `보고` edges so the
  relationship graph and the org chart are one queryable graph.
  `tier`: `core`(멘탈모델까지 깊게) / `acquaintance`(가벼운 도시에) / `contact`(이름·회의만,
  도시에 없음 — INDEX에 자동 수집). Registry entries without `tier` default to core.
  People found in transcripts but not in the registry are auto-listed as contacts;
  ≥3 meetings → promotion candidate in `people/INDEX.md`.
- **`voiceprints.json` = who each voice belongs to.** Written by `voiceprint.py` after the
  user confirms a speaker, and read on every later audio import so the same person is never
  asked about twice. Shape:
  ```json
  {"version": 1, "model": "campplus.onnx", "dim": 192,
   "people": {"정우진": {"centroids": [
     {"id": "c1", "vec": [0.031, ...], "dur": 812.4, "n": 5,
      "sources": ["plaud-abc123"], "updated": "2026-09-03"}]}}}
  ```
  Keys are **registry canonical names** (same join key as `speakers.json`). Several centroids
  per person is normal — a phone call and a dinner table sound different, and each condition
  earns its own. `dur` is how much speech backs it, so an old sighting never outweighs a
  well-heard one. It is derived-but-not-rebuildable data (the source audio is usually gone):
  back it up with the corpus, and never hand-edit `vec`.
- **`_meta/calendar/` = 그 자리가 무슨 자리였는지.** 스킬이 캘린더 MCP로 받아 캐시하고
  (`match_calendar.py`는 이 캐시만 읽는다 — 스크립트는 MCP를 호출할 수 없고, 캐시여야
  재실행이 같은 답을 낸다), 매칭 결과가 회의록 프론트매터의 `setting`(TPO)·
  `calendar_event`로 들어간다. 참석자 명단은 Stage 3 화자 추정의 정답지다.
  일정 본문에 민감 정보가 섞이기 쉬우니 `description`은 아젠다·링크만 짧게 남긴다.
- **`_meta/lexicon.json` = 코퍼스가 스스로 배운 어휘.** `terms[]`는
  `{term, kind, desc, aliases[], misspellings[{form,status,source}], status, protect, web{}}`.
  `status`는 **확정**(사용자 확인) / **추론**(스크립트 임계값이 판단) / **후보**(리포트만).
  확정·추론만 본문에 적용되고, 적용 사실은 `lexicon-corrections.jsonl`에 남으며
  `_ontology/_work/lexicon-backup-<batch>/`로 되돌릴 수 있다. **인물 이름은 사전이 아니라
  `speakers.json`의 `aliases`로 고친다** — 본문을 고치면 서로 다른 두 사람이 조용히 하나로
  합쳐질 수 있고, DB 조인은 어차피 alias로 돈다. `protect: true`인 용어는 영원히 교정 대상 밖.
- **`_meta/enrichment.json` = 밖에서 알아낸 것.** `entities`는 이름 → `{kind, canonical,
  summary, facts[{text,url,fetched}], spelling_variants[], status(확인됨|불확실|기각)}`.
  캘린더와 같은 캐시 규약이다(스크립트는 웹을 못 부른다 → 스킬이 채우고 스크립트는 읽는다).
  **URL 없는 주장은 저장되지 않는다.** DB에서는 `entity_facts` 테이블로만 보이고 근거 등급과
  무관하다. 인물은 프라이버시 게이트를 통과해야 들어온다(팀원·가족·지인은 검색 자체를 안 한다;
  레지스트리 `"public": true|false`로 사용자가 직접 정할 수 있다).
- **Privacy**: the corpus is sensitive. Keep local; if it lives near a git repo, gitignore it.
  Recommended location: a dedicated folder or the user's Obsidian vault (iCloud-synced, off-repo).
  `voiceprints.json` is **biometric data** — the most sensitive file in the corpus.
  `purge_person.py` removes a person's voiceprint along with everything else, and
  `voiceprint.py <corpus> forget --name X --apply` removes just the voice.
