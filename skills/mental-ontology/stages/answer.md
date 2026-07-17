# Mental Ontology — Stages 8–9: Query mode · Strategy mode

> Stage reference. Loaded on demand from SKILL.md (the router).
> Speak to the user in the user's language; these instructions are English for precision.

## Stage 8 — Query mode (Q&A over the data)

When the user asks anything about people, meetings, topics, or history — answer from
the DB + transcripts, per **`assets/PLAYBOOK.md` Part 1**. Core discipline:

- SQL to locate (recipes in the playbook: person profile, tension map, FTS search,
  timeline, topic ownership) → **Read the actual transcript** (`meetings.path`) for
  nuance → answer with citations `(date · meeting)` and evidence grades.
- Honesty: `high` assert / `mid` mark as 추정 / `low` say 근거 부족. Never fabricate.
- **Freshness**: a model whose `last_seen` is 6+ months behind the newest meeting
  (validate.py flags these as STALE) is answered in past tense — "당시에는 ~라고
  봤습니다 (이후 확인 없음)" — never as their current view. People change.
- If the DB is missing or stale (ontology newer than db mtime), run Stage 7 first.

## Stage 9 — Strategy mode (business ideation & planning)

For "find opportunities / build a strategy / prepare persuasion / check alignment /
simulate a decision" requests, run the structured workflows in **`assets/PLAYBOOK.md`
Part 2** (S1 기회 발굴 · S2 전략 옵션 · S3 설득 전략 · S4 정렬 리포트 · S5 결정 시뮬레이션).

- **The strategy register is a living asset**: `bets[]`/`risks[]` in objects.json
  carry `status` (검토중→진행중→실현/폐기 · 관찰중→완화중/현실화/해소), `owner`,
  `source` meetings, `related_models`. Every S1/S2/S4 run **updates the register**
  (new entries, status transitions with the evidencing meeting) — never re-extract
  from scratch. Then rebuild the DB so queries see it.
- Each workflow produces a **written md deliverable** in `<corpus>/_strategy/`
  (create the folder if missing) and appends one line to `_strategy/INDEX.md`
  (date · workflow · file · 한 줄 결론) so strategy work accumulates instead of
  scattering.
- Deliverables must ground in the register: cite bet/risk entries and model ids,
  and end with a **register diff** ("이번 실행으로 바뀐 것: bet X 검토중→진행중").
- Always include the honesty footer: data shows what people *said*, not market truth;
  recommend the cheapest real-world validation per idea; label simulations as
  simulations.
- Large corpus sweeps (S1 step 1): fan out cheap parallel subagents by month/category.
