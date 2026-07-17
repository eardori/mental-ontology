# Corpus Folder Structure

Created at the user's chosen `corpus_path` (config: `~/.mental-ontology.json`).
Plain markdown — works standalone or inside an Obsidian vault.

```
<corpus>/
├── transcripts/                  # cleaned meeting markdown (the corpus)
│   └── <YYYY>/<YYYY-MM>/
│       └── <YYYY-MM-DD>_<slug>.md        # frontmatter + summary + transcript
├── _index/
│   ├── INDEX.md                  # human-readable index (category/month, wikilinks)
│   └── catalog.json              # machine-readable index (for agents/tools)
├── people/                       # person dossiers (build_dossiers.py) — the 인물 중심 artifact
│   ├── INDEX.md                  # tiers, contacts (auto-collected), promotion candidates
│   └── <이름>.md                  # identity · 개인 맥락 · 멘탈모델 · 관계 · 접촉 이력 · 수기 메모(보존)
├── _meta/
│   ├── speakers.json             # PERSON REGISTRY (Stage 3) — aliases power DB joins;
│   │                             #   tier/first_met_context/intro_by/personal[] power dossiers
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
│       └── <date-label>/         #  (extract/synth files) + purge-backup-<이름>/;
│                                 #  deletable after a validated build / final purge
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
  [{ "name": "James(정우진)", "role": "CEO", "org": "Acme",
     "aliases": ["제임스", "Speaker 2(2026-07-10)"],
     "traits": "구조 먼저, 숫자로 검증", "meetings": ["2026-07-10"],
     "tier": "core",
     "relationship": "파트너",
     "team": "경영진", "manager": "",
     "first_met_context": "SaaS 밋업에서 패널로 처음 만남",
     "intro_by": "이서연",
     "personal": [{ "date": "2026-06-24", "note": "10월 마라톤 준비 중", "use": "사적" }] }]
  ```
  `relationship` = 나(owner)와의 관계 (팀원/내부-타팀/상사·보드/파트너/고객/투자자/지인/가족 —
  자유 텍스트). `team`/`manager` = **조직도** — org chart lives as per-person edges here,
  and `build_db.py` derives them into the `network` table as `보고` edges so the
  relationship graph and the org chart are one queryable graph.
  `tier`: `core`(멘탈모델까지 깊게) / `acquaintance`(가벼운 도시에) / `contact`(이름·회의만,
  도시에 없음 — INDEX에 자동 수집). Registry entries without `tier` default to core.
  People found in transcripts but not in the registry are auto-listed as contacts;
  ≥3 meetings → promotion candidate in `people/INDEX.md`.
- **Privacy**: the corpus is sensitive. Keep local. If it lives near a git repo, gitignore it.
  Recommended location: a dedicated folder or the user's Obsidian vault (iCloud-synced, off-repo).
