# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

A **distribution repo for one Claude Code skill** — not an application. The product is
`skills/mental-ontology/`, which `INSTALL.md` copies to `~/.claude/skills/mental-ontology`.
There is no build, no package manager, no lockfile; the scripts are Python 3 **stdlib only**
(heavy deps are confined to the opt-in Whisper/diarization scripts).

Two consequences that shape every change here:

1. **Prose is executable.** `SKILL.md`, `stages/*.md`, and `assets/*.md` are instructions Claude
   follows at runtime. Editing a spec sentence changes product behavior exactly as much as
   editing Python does — and nothing type-checks it. The scripts only cover the deterministic
   half of the pipeline.
2. **The data lives outside the repo.** The runtime corpus (transcripts, `objects.json`,
   `ontology.db`, dossiers) sits at `corpus_path` from `~/.mental-ontology.json` — typically an
   Obsidian vault. It is private and must never land in this repo. All examples and tests use
   the fictional "Acme" cast (정우진 / 이서연 / 박도현 …); keep it that way.

The repo is also a **Claude Code plugin and its own marketplace** (`.claude-plugin/plugin.json`
+ `marketplace.json`, plugin source `"./"` — so `skills/` must stay at the repo root). Users
install with `claude plugin marketplace add eardori/mental-ontology` and update with
`claude plugin update`; the plugin is **copied** into `~/.claude/plugins/cache/<marketplace>/
<plugin>/<version>/`, so bump `version` in `.claude-plugin/plugin.json` when shipping a change
or clients keep the cached copy (`marketplace.json` carries no version field — the plugin
manifest is the single source of truth). Editing this repo never affects an installed copy — develop against
`tests/run_tests.py`, not the cache. `INSTALL.md` also documents the manual
`cp -R` path for forks (never run both — the skill would load twice). User-visible changes belong in `CHANGELOG.md`:
the repo versions itself there (currently 2.2.0), and a reader landing on the repo uses it
plus the README's "30초 요약" to understand what this is.

## Commands

```bash
python3 tests/run_tests.py        # full suite: temp dirs, fictional data, exit 0 = green
```

The suite has no framework and no per-test CLI. Tests share state through `tmp` (most reuse the
`corpus_v2` built by `test_pipeline_v2`), so run a subset by importing the module:

```bash
python3 - <<'EOF'
import sys, tempfile; from pathlib import Path
sys.path.insert(0, "tests"); import run_tests as t
with tempfile.TemporaryDirectory() as td:
    tmp = Path(td)
    t.test_pipeline_v2(tmp)      # builds corpus_v2 — prerequisite for most others
    t.test_purge_person(tmp)
print(len(t.FAILURES), "failed")
EOF
```

To exercise a script by hand, build a throwaway corpus from the same fixtures:

```bash
python3 -c "import sys; sys.path.insert(0,'tests'); import run_tests as t
from pathlib import Path; t.build_corpus_v2(Path('/tmp/mo-corpus'))"
python3 skills/mental-ontology/scripts/build_index.py /tmp/mo-corpus
python3 skills/mental-ontology/scripts/build_db.py    /tmp/mo-corpus
python3 skills/mental-ontology/scripts/validate.py    /tmp/mo-corpus   # exit 1 = errors, 0 = clean/warns
python3 skills/mental-ontology/scripts/lexicon.py    /tmp/mo-corpus mine   # 용어·오타 후보 (dry run)
python3 skills/mental-ontology/scripts/enrich.py     /tmp/mo-corpus plan   # 무엇을 검색할지 + 질의문
```

Every script takes `<corpus_path>` as its first argument. The destructive ones
(`migrate_objects.py`, `merge_ontology.py`, `purge_person.py`, `consolidate.py`, and every
mutating `lexicon.py` / `enrich.py` subcommand) **dry-run by default** and need `--apply` /
`--apply-recalib`; they back up into `_ontology/_work/` first.
Keep that contract for any new script.

## Architecture

### Router → stages (lazy instruction loading)

`SKILL.md` is a router only: it maps a user request to one of stages 0–9 and says *read the
stage file before executing*. Stage detail lives in `stages/ingest.md` (0–5: setup, Plaud fetch,
Whisper, speaker attribution, save, index), `stages/ontology.md` (6–7: extraction, DB, batch
pipeline, hygiene), `stages/answer.md` (8–9: query mode, strategy mode). `assets/EXTRACTION.md`
(what a mental model is, holder/about, evidence grading) and `assets/PLAYBOOK.md` (Part 1 SQL
recipes, Part 2 strategy workflows S1–S5) are the deep references. **Put new detail in a stage
or asset file and add at most a router line** — the router is loaded on every activation.

### The data pipeline

```
Plaud MCP / audio → transcripts/*.md (frontmatter + 요약 + 액션아이템 + transcript)
                  → _meta/lexicon.json   (용어 사전 — corrects the text before it is indexed)
                  → _meta/speakers.json  (person registry — the join key)
                  → _ontology/objects.json  (THE data of record)
                  → derived: index.html · ontology.db · people/*.md
```

- **`objects.json` is the single source of truth.** `index.html`, `ontology.db`, and the
  dossiers are all derived. Anything that edits `objects.json` must re-run the full derivation
  chain in order (`stages/ontology.md` spells it out): `consolidate.py --apply-recalib` →
  `build_meta.py` → **viewer re-embed** → `build_db.py` → `build_dossiers.py`. Stale derived
  artifacts is the failure mode this repo has actually hit.
- **The viewer re-embed has no script.** Copy `assets/viewer.html`, replace the contents of
  `<script id="sample-data" type="application/json">` with `objects.json`, and flip
  `class="banner"` → `class="banner hidden"`. It is done inline every time — if you add a
  viewer field, the template and this step are what carry it.
- **`_meta/speakers.json` is a person registry, not an STT map.** `aliases` are load-bearing:
  `build_db.py` joins utterances to the ontology through them, so a missing alias silently
  removes a person from query mode. `tier` (core/acquaintance/contact) gates dossier depth;
  `team`/`manager` become `보고` edges in the `network` table so the org chart and the social
  graph are one queryable graph.
- **Two units of analysis, deliberately separate.** A `models[]` entry is a *reusable belief*
  ("속도가 먼저다"); a `readings[]` entry is *what one person wanted in one conversation*
  ("이번 분기 안에 공표를 원한다"). The extraction spec (`assets/EXTRACTION.md` §7) forbids
  a reading without a textual signal in `basis[]` (closed set: 반복/무응답/화제전환/선제언급/
  마무리발언/양보조건/되묻기/호칭변화), caps `confidence` at 보통, and requires `surface`
  (what was said) beside `reading` (what was inferred). Every reading starts `추정` and is
  resolved by a later meeting into `확인됨`/`빗나감`, which is what lets validate.py and
  build_db.py print a **hit rate** — the layer has to be able to say how often it was wrong.
- **Transcripts are only edited by `lexicon.py`.** Two paths, one contract: `apply` is
  dictionary-driven (misspelling pairs at status 확정/추론) and `patch` takes reader-decided
  find→replace pairs (일반 오탈자, 지시어 주석) so the LLM never re-emits a body. Both back
  up into `_ontology/_work/lexicon-backup-<batch>/`, append to `_meta/lexicon-corrections.jsonl`,
  and are undone by `revert --batch`. Two rules are enforced in code and pinned by tests:
  **a person's name is never fixed by rewriting text** (it becomes a `speakers.json` alias —
  rewriting can silently merge two people, and the DB joins by alias anyway), and **an inferred
  pair says so** (확정 = user, 추론 = thresholds at the top of the script, 후보 = report only).
  Because corrections change the text, `lexicon.py apply` runs BEFORE `build_index.py` in the
  Stage 5 chain; `build_db.py` WARNs when a known misspelling is still in the transcripts.
  `mine` learns only the 추론 tier — thresholds are printed in every report, and name
  candidates and deictic-laden action items are reported for humans, never auto-applied.
- **Web enrichment enters through a cache, exactly like the calendar.** `enrich.py plan`
  decides what is worth looking up AND **composes the query strings itself** (entity name +
  registry org — transcript text never reaches a search engine); the skill searches; `save`
  writes `_meta/enrichment.json`; `apply` folds it into the lexicon and the registry, filling
  **empty fields only**. A claim without a URL is dropped and a sourceless `확인됨` is
  downgraded to `불확실`. People are gated: 팀원/가족/지인 are never planned, public role +
  org (or explicit `"public": true`) is the only way in. Web facts live in `entity_facts` and
  **raise no evidence grade** — that rule is written in `EXTRACTION.md`, checked by
  `validate.py`, and rendered as a separate dossier section.
- **Calendar data enters through a cache, never live.** Scripts cannot call MCP tools, so
  the skill fetches events and writes `_meta/calendar/<YYYY-MM>.json`; `match_calendar.py`
  reads only that. This is what makes matching deterministic, re-runnable and testable. The
  match writes `setting` (TPO) and `calendar_event` into transcript frontmatter, fills only
  empty/auto-generated fields (a human-set title or category is reported, never overwritten),
  and flows into `meetings.setting` in the DB and into the evidence-grading rules in
  `EXTRACTION.md` — a belief voiced only over dinner or only in an IR meeting caps at `mid`.
- **The briefing is the only push surface, and it is deliberately dumb.**
  `build_briefing.py` computes everything it prints from `ontology.db` — open commitments,
  open readings and their basis signals, contact gaps, turn/character/question counts — so a
  briefing cannot hallucinate. The skill relays it verbatim and may add prose, never facts.
  Talk-share always prints the unattributed share alongside it. `--me` / registry
  `"owner": true` is what separates "내가 한 약속" from everyone else's; without it the
  script guesses the most-attending person and labels the guess.
- **Voice identity closes the ingest loop.** `_meta/voiceprints.json` (written by
  `voiceprint.py`) maps campplus embeddings to registry canonical names, so a person confirmed
  once is auto-labeled in every later audio import: `diarize` → `recluster` → `voiceprint embed`
  → `voiceprint identify` → `merge_diar --labels` → Stage 3 asks only about what is left →
  `voiceprint enroll` learns the answer. Matching/storage is deliberately stdlib-only (pure
  python cosine) so it is testable without audio; only `embed` imports numpy/soundfile/sherpa.
  Thresholds live at the top of the script — `auto` requires both `ACCEPT` and a `MARGIN` over
  the runner-up, and one person can be claimed by at most one cluster per recording.
- **Token economy is an architectural rule, not an optimization.** Transcript bodies are only
  ever written/patched by Python (find→replace on one file); the LLM decides titles, categories,
  summaries, and speaker mappings, and never re-emits transcript text. Preserve this in any new
  flow.
- **Batch re-extraction** (`stages/ontology.md`) is agents → script → agents → script:
  extraction fan-out writes `extract-*.json`, `prepare_synthesis.py` builds per-holder synthesis
  tasks, synthesis fan-out writes `synth-*.json`, `merge_ontology.py` merges into `objects.json`
  with stable ids. All intermediates go in `_ontology/_work/<date-label>/`, never loose.

### Honesty rules are encoded in three places

Evidence grading is the product's core claim, and it is enforced redundantly: prose
(`EXTRACTION.md`, the cross-cutting rules in `SKILL.md`), deterministic recalibration
(`consolidate.py`: high needs count≥3 + direct + verbatim; hearsay/reference cap at mid),
and checks (`validate.py`: org-held models can't be `high`, `high` without a quote is flagged,
quote grounding against actual utterances, STALE `last_seen` flags, coverage stats).
`migrate_objects.py` applies the same org cap. **Change a grading rule in all of them or the
pipeline contradicts itself.**

`validate.py` is the gate after every ontology change: exit 1 on errors, warnings surfaced to
the user. `build_db.py` prints an attribution-coverage report and WARNs (duplicate `source_id`,
zero-utterance meetings, alias conflicts) — those WARNs mean data is invisible to query mode and
must be reported, not swallowed.

## Gotchas

- **Schema versions are additive, and the files disagree about the number.** v2 split
  holder/about, v3 added `evidence_type`/`traps`/`conflict_axes`/`playbook`, v4 added
  `readings` (대화 의도). `assets/schema.json` and `examples/sample-objects.json` are v4, while
  `migrate_objects.py` writes `schema_version: 2`. Treat v2 as the floor —
  `build_db.py` still has a v1 compat path (it unions `people[].models` into the holder table
  when `schema_version < 2`), so a legacy corpus fails loudly nowhere: run
  `migrate_objects.py` first.
- **A new top-level field needs a `build_db.py` table**, or query mode cannot cite it. `traps`,
  `conflict_axes`, `readings`, and now `terms`/`term_misspellings`/`entity_facts` (from
  `_meta/lexicon.json` + `_meta/enrichment.json`) have tables; `meta_patterns` still does not
  (viewer-only).
  This bit the repo once already — the shipped v3 character data was invisible to SQL for a
  release.
- **Two copies of the sample data.** `examples/sample-objects.json` and the embedded
  `<script id="sample-data">` block in `assets/viewer.html` are the same object except that the
  viewer copy also carries `meta_patterns`. Update both when changing the demo.
- **Whisper language detection.** Defaults to `auto` sampling mid-file; never force a language
  from the first 30 seconds (intros/music cause fluent hallucination loops). `repetition_ratio`
  > 0.3 in the output means re-run with an explicit `--lang`.
- **`_meta/` now holds three registries, and `purge_person.py` must reach all of them.**
  speakers · voiceprints · lexicon + enrichment + the corrections log. A purge that leaves the
  name in the dictionary or a cached search result has not deleted the person; tests pin this.
- **Voiceprints are biometric and not rebuildable.** The source audio is usually gone after
  ingest, so `_meta/voiceprints.json` cannot be regenerated like the DB or the dossiers — it is
  the one derived-looking file that must be backed up. Anything that deletes a person
  (`purge_person.py`) must delete their voiceprint too; a test pins this.
- **Diarization needs a re-cluster pass.** `diarize.py` alone over-splits badly (40 speakers on
  a 2-person call); always follow with `recluster.py` (cosine 0.45 tuned for Korean). Models
  resolve from `DIAR_MODELS` or `~/.cache/mental-ontology/diar-models`.

## Conventions

- **Language split**: instructions and code comments in English for precision; everything
  user-facing (questions, reports, dossiers, viewer labels) in the user's language — Korean by
  default. Category taxonomy, `tier`, `state`, and `status` enums are Korean string literals
  shared by scripts, schema, and viewer; changing one means changing all three.
- **Tests pin the CLI contract** — argv shape, exit codes, backup naming, and specific WARN/
  report strings. Extend `tests/run_tests.py` alongside any script change; it is the only
  automated check in the repo.
- Scripts warn loudly and continue rather than failing silently; the reports they print are part
  of the UX and are read back to the user.
