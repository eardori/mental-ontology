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
├── _meta/
│   ├── speakers.json             # learning speaker profiles (Stage 3) — aliases power DB joins
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
│   ├── profiles/
│   │   └── PROFILE-<이름>.md      # per-person profile cards
│   └── _work/                    # intermediate files ONLY (per-meeting extracts,
│       └── <date-label>/         #  aggregates) — deletable after a validated build
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
- **speakers.json** — the `name` here is the canonical name used everywhere
  (ontology `people[].name`, DB joins). `aliases` must list **every raw label** the
  person appears under in transcripts; `Name(Other)` names match both halves
  automatically:
  ```json
  [{ "name": "James(정우진)", "role": "CEO", "org": "Acme",
     "aliases": ["제임스", "Speaker 2(2026-07-10)"],
     "traits": "구조 먼저, 숫자로 검증", "meetings": ["2026-07-10"] }]
  ```
- **Privacy**: the corpus is sensitive. Keep local. If it lives near a git repo, gitignore it.
  Recommended location: a dedicated folder or the user's Obsidian vault (iCloud-synced, off-repo).
