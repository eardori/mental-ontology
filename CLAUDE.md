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

Changes reach a user only after they re-copy the skill directory — there is no update channel.

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
```

Every script takes `<corpus_path>` as its first argument. The destructive ones
(`migrate_objects.py`, `merge_ontology.py`, `purge_person.py`, `consolidate.py`) **dry-run by
default** and need `--apply` / `--apply-recalib`; they back up into `_ontology/_work/` first.
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
  `conflict_axes` and `readings` now have tables; `meta_patterns` still does not (viewer-only).
  This bit the repo once already — the shipped v3 character data was invisible to SQL for a
  release.
- **Two copies of the sample data.** `examples/sample-objects.json` and the embedded
  `<script id="sample-data">` block in `assets/viewer.html` are the same object except that the
  viewer copy also carries `meta_patterns`. Update both when changing the demo.
- **Whisper language detection.** Defaults to `auto` sampling mid-file; never force a language
  from the first 30 seconds (intros/music cause fluent hallucination loops). `repetition_ratio`
  > 0.3 in the output means re-run with an explicit `--lang`.
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
