# Mental Ontology — Stages 6–7: Ontology analysis · Database

> Stage reference. Loaded on demand from SKILL.md (the router).
> Speak to the user in the user's language; these instructions are English for precision.

## Stage 6 — Ontology analysis & documentation

Follow the full extraction spec in `assets/EXTRACTION.md`. Summary:

1. **Scope**: ask the user once — whole corpus vs. a period/category vs. one person deep-dive. Exclude `개인-통화` and junk by default.
   - **Cold start**: with fewer than ~10 meetings the ontology will be thin and low-evidence — say so honestly, lead with the 회의록 정리+검색 value, and suggest returning to ontology once 10+ meetings accumulate. Don't oversell a map drawn from 3 data points.
2. **Extract per meeting** (parallel subagents on cheap model for large corpora): each person's mental models — *reusable beliefs/decision criteria*, not one-off opinions — with `evidence: high|mid|low` graded honestly (verbatim quote → high; role-based inference → mid; presence only → low), plus counterparts and tensions.
   - **Attribution discipline** (EXTRACTION.md rule 0): a model's `holders` = who *holds* the belief; `about` = whom it *concerns*. "정우진이 경쟁사 메가스테이에 대해 한 말"의 holder는 정우진이다. Org-held models (제3자 추정) cap at `mid`. Person names must be `_meta/speakers.json` canonical names — that's what joins the ontology to transcripts in the DB.
3. **Synthesize** (stronger model): cluster instances into canonical models; build people cards, relations (`agree|tension|builds-on` — tensions are the most valuable signal), timeline of thinking evolution, strategy bets ↔ risks.
4. **Sensitive data policy**: financial specifics (equity %, amounts, valuations) are always generalized in outputs. Personal-life context (가족, 건강, 취향, 근황) follows the config key `personal_context` in `~/.mental-ontology.json`: `"record"` = keep it in dossiers/outputs (relationship-tool mode — remembering "딸이 수험생" is the point), `"mask"` = exclude it everywhere (default when unset). Ask the user once on first Stage 6 run and save their choice to the config.
5. **Ask how to visualize** (AskUserQuestion, once per analysis run — skip if the user already said):
   - **인터랙티브 HTML 뷰어** — self-contained page (double-click to open)
   - **md 종합 리포트** — narrative report (Obsidian/Notion friendly)
   - **인물 도시에 (people/)** — one file per person (see below; supersedes the old profile cards)
   - **전부** (default recommendation)
6. **Generate per choice** into `<corpus>/_ontology/`:
   - Always: `objects.json` per `assets/schema.json` (schema v2: `meta.schema_version: 2`, `people[].type`, `models[].holders/about`, `meetings[].source_id+path`, `meta.processed_source_ids`) — this is the data of record regardless of visualization choice. Working/intermediate files (per-meeting extracts, aggregates) go in `_ontology/_work/<date-label>/`, never loose in `_ontology/`.
   - **Then validate — mandatory**: `python3 <skill_dir>/scripts/validate.py <corpus_path>`. Fix every ERROR before proceeding; surface WARNs to the user. (Legacy v1 objects.json → run `scripts/migrate_objects.py` first.)
   - HTML → `index.html`: copy `assets/viewer.html`, then **embed** objects.json by replacing the content of `<script id="sample-data" type="application/json">…</script>` and hiding the sample banner (`class="banner"` → `class="banner hidden"`) so it renders on double-click without a server.
   - md report → `REPORT.md`: executive summary (3–5 bullets: the person's/org's core thinking axes), per-person one-liners with evidence grades, notable tensions, timeline.
   - Person dossiers → run `python3 <skill_dir>/scripts/build_dossiers.py <corpus_path>` → `people/<이름>.md` (core + acquaintance) + `people/INDEX.md` (contacts 전원 + 승격 후보). The script assembles everything data can prove (identity, personal[], models, relations/network, co-attendees, full interaction timeline as wikilinks); the `<!-- manual:start/end -->` block preserves the user's own notes across regenerations. After the script, the LLM may refresh only the 개요/traits line for changed core people. **These dossiers are the artifact people actually reuse** — before a 1:1, before delegation, before a pitch.
   - Also extract **`network[]`** (사회적 관계: 소개/협업/투자/사제 — who introduced whom is the most valuable) into objects.json alongside relations (which stay 사고의 관계).
7. **Incremental**: if `_ontology/objects.json` exists, merge — process only transcripts whose `source_id` is NOT in `meta.processed_source_ids`; keep canonical model ids stable, add new evidence/quotes, append timeline entries, upgrade `evidence` when verbatim support appears; append the new source_ids to `processed_source_ids`. Regenerate whichever visualizations the user chose (profiles: only changed people).
8. Tell the user what was created and where; adding more meetings enriches the timeline. Then offer Stage 7–9 ("이제 데이터에 질문하거나 전략을 뽑을 수 있습니다").

## Stage 7 — Build the database

Run after every ontology update (and offer it to users still on viewer-only):

```bash
python3 <skill_dir>/scripts/build_db.py <corpus_path>
```

→ `<corpus>/_ontology/ontology.db` (SQLite, rebuilt idempotently): `people` (with
`type` person/org), `models` (+`model_people` = holders, `model_about` = subjects,
`model_related`), `person_aliases` (speaker-label → canonical-name map from
`_meta/speakers.json`), `relations` (사고), `network` (사회적 관계),
`person_meetings` (interaction records from participants + speakers — powers
접촉 타임라인·동석 분석 even for unattributed phone calls), `timeline`, `bets`,
`risks`, `meetings`, `utterances` (`speaker` = canonical where resolvable,
`speaker_raw` = original label), and `utterances_fts` (FTS5 full-text search;
check `meta.fts5` — if `no`, fall back to `LIKE`). No external dependencies.

**Read the build report.** It prints speaker-attribution coverage and WARNs about
zero-utterance meetings, unparsed lines, and alias conflicts. WARNs mean data is
missing from query mode — fix the cause (usually Stage 3 aliases) or tell the user
what's not covered. Then run `validate.py` for the full integrity/coverage check.

## Batch re-extraction pipeline (large corpora / catching up on many meetings)

The proven procedure for "N개 미처리 회의 반영해줘" at scale (10+ meetings). Four
steps; steps 1 and 3 are parallel agent fan-outs, steps 2 and 4 are shipped scripts.
All intermediates live in `<corpus>/_ontology/_work/<date-label>/` (the workdir).

**Step 1 — Extract (agents, ~10 meetings per batch):** build `batches.json`
(`[{id, paths, sids}]`) from catalog entries whose `source_id` is not in
`meta.processed_source_ids`. One agent per batch writes `extract-<id>.json`:
`{"batch", "meetings": [{source_id, date, title, instances[], tensions[],
network_facts[], timeline_signal}]}`. Non-negotiables in the agent prompt:
- holder = canonical registry name only; unmappable generic speakers → SKIP, never guess
- quote = **EXACT verbatim substring** copied from the transcript (no paraphrase,
  no "..." stitching) — this is what makes validate.py's quote grounding pass
- evidence "high" needs verbatim + sincerity (jokes/venting are not models)
- max ~5 significant instances per meeting; financial specifics generalized
- tensions only for REAL clashes (empty is normal); network_facts for 소개/협업/투자

**Step 2 — Prepare (script):**
```bash
python3 <skill_dir>/scripts/prepare_synthesis.py <corpus> <workdir>
```
Aggregates extract files into per-task `synth-task-<key>.json` (every existing model
assigned to exactly ONE task by primary holder; heavy holders split by category),
plus pooled tensions/network/timeline. Prints dropped non-canonical holders.

**Step 3 — Synthesize (agents, one per key in `synth_keys.json`):** each reads its
task file and writes `synth-<key>.json` `{"key", "models": [existing(updated)+new],
"evolution": [{person,date,note}], "summary"}`. Non-negotiables:
- existing ids are STABLE — update in place (count/first_seen/last_seen/about/quote)
- consolidate aggressively; one-off remarks drop; contradiction → downgrade or evolution
- new ids: descriptive kebab-case

**Step 4 — Merge (script):**
```bash
python3 <skill_dir>/scripts/merge_ontology.py <corpus> <workdir>          # dry-run plan
python3 <skill_dir>/scripts/merge_ontology.py <corpus> <workdir> --apply  # backup + write
```
Handles carry-over, id collisions (renamed + reported — review any `-2` ids and
merge duplicates by hand), people[].models rebuild, entity-name normalization,
self-org edge drops, pool dedupe, timeline capping, `processed_source_ids`.
Then: `validate.py` (quote grounding + integrity) → `build_db.py` →
`build_dossiers.py` → re-embed the viewer. Report the before/after numbers honestly
(models, grounding rate, coverage) — including what was downgraded or dropped.
