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
- **Readings (대화 의도) are 추정, never fact.** Cite them with the actual words
  (`surface`) and the signal (`basis`) — "3회 반복 + 마무리발언" — and say 추정 out loud.
  Mention past `빗나감` readings about that person when relevant; an honest miss buys more
  trust than a hidden one. When the user asks "저 사람이 뭘 원하는 거야 / 내가 뭘 놓쳤어",
  this layer is the answer, paired with the open commitments.
- **"미팅 준비해줘 / 내일 〈이름〉 만나" → run the script first**:
  `python3 <skill_dir>/scripts/build_briefing.py <corpus> --with "<이름>"` gives the
  computed 30-second brief (내가 안 한 약속 → 확인할 추정 → 이 사람과 일하는 법 → 충돌 축의
  공유 공리 → 개인 맥락 with △/⛔ → 최근 접촉). Add prose and transcript nuance on top of
  it; never replace its facts with your own recollection. Same script covers "지난주 뭐
  놓쳤지?" (`--days 7`) and "어제 회의 정리해줘" (`--meeting <source_id>`).
- **"내일 뭐 있지 / 내일 일정 브리핑"** → `build_briefing.py <corpus> --upcoming`
  (캐시된 캘린더 기준; 하루치 일정마다 만날 사람의 미이행 약속·미확인 추정·마지막 접촉을
  붙여준다). 캐시가 없거나 오래됐으면 Stage 1b로 캘린더를 먼저 받아 캐시한다. 캘린더에만
  있고 코퍼스에 없는 이름은 **별칭 후보로만** 제시된다 — 사람이 확정해야 하는 조인 키다.
- **용어와 외부 정보**: 사용자가 모르는 말을 물으면 `terms` 먼저(Recipe N) — 사전에 있으면
  뜻과 함께 답하고, 없으면 실제 쓰임을 보여준 뒤 사전에 넣을지 묻는다. 검색이 비면 오표기가
  남아 있을 수 있으니 `term_misspellings`까지 함께 조회한다. `entity_facts`(웹)는 **문단을
  나눠** "웹 출처(수집일)"로 인용하고, 회의 근거와 절대 한 문장에 섞지 않는다.
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
