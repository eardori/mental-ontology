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
│   ├── speakers.json             # learning speaker profiles (Stage 3)
│   ├── state.json                # {"last_synced": "YYYY-MM-DD"}
│   └── deletion-candidates.md    # junk recordings to delete in the Plaud app
├── _whisper/                     # local transcription workspace
│   └── <id>.json                 # whisper output {id, text, segments}
└── _ontology/
    ├── objects.json              # the ontology (people/models/relations/timeline)
    ├── index.html                # self-contained viewer (embedded data)
    └── REPORT.md                 # narrative report
```

## Conventions

- **Transcript filename**: date + short content slug (Korean OK, spaces → `-`);
  split recordings get `_part1`, `_part2`.
- **Dedup key**: frontmatter `source_id` (Plaud file id) — check `catalog.json` before processing.
- **speakers.json**:
  ```json
  [{ "name": "김철수", "role": "CFO", "org": "Acme", "aliases": ["철수님", "Speaker 2(2026-07-10)"],
     "traits": "숫자 먼저, 짧은 문장", "meetings": ["2026-07-10"] }]
  ```
- **Privacy**: the corpus is sensitive. Keep local. If it lives near a git repo, gitignore it.
  Recommended location: a dedicated folder or the user's Obsidian vault (iCloud-synced, off-repo).
