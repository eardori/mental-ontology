# Playbook — Querying the Ontology & Turning It into Strategy

This is the reference for **Stage 8 (Query mode)** and **Stage 9 (Strategy mode)**.
It defines how to answer questions over the corpus/ontology DB, and the structured
workflows for business ideation and strategy planning.

The DB lives at `<corpus>/_ontology/ontology.db` (built by `scripts/build_db.py`,
rebuild after every ontology update). Query it with the `sqlite3` CLI or python stdlib.

---

## Part 1 — Query mode (질문 모드)

### Grounding rules (always)

1. **Answer from data, cite the data.** Every claim should reference meeting dates,
   quotes, or model ids. Format: `(2026-07-14 리더십 얼라인먼트 회의)`.
2. **Respect evidence grades.** `high` = assert; `mid` = "~로 보입니다(추정)";
   `low` = "근거 부족" — say so.
3. **Combine SQL + reading.** SQL finds *where*; then Read the actual transcript md
   (path in `meetings.path`) for nuance before answering non-trivial questions.
4. **Sensitive data stays masked** in answers shown/exported outside the owner's session.

### SQL recipes

```sql
-- A. Person profile (사람 한 명의 전체 프레임)
SELECT m.category, m.title, m.evidence, m.count, m.quote
FROM models m JOIN model_people mp ON mp.model_id = m.id
WHERE mp.person LIKE '%Kevin%' ORDER BY m.count DESC;

-- B. Tension map (조직의 대립 지점)
SELECT from_person, to_person, topic, note FROM relations WHERE type='tension';

-- C. Full-text search across every meeting (FTS5)
SELECT date, title, speaker, snippet(utterances_fts, 1, '[', ']', '…', 12) AS hit
FROM utterances_fts WHERE utterances_fts MATCH '유료화 AND 가격'
ORDER BY date DESC LIMIT 20;
-- (fts5 OFF fallback:  SELECT ... FROM utterances u JOIN meetings m ON m.rowid=u.meeting_rowid
--  WHERE u.text LIKE '%유료화%' ...)

-- D. Thinking evolution (시간축)
SELECT date, change FROM timeline ORDER BY date;

-- E. Who talks about X the most (주제별 오너십 힌트)
SELECT speaker, COUNT(*) n FROM utterances_fts WHERE utterances_fts MATCH '정산'
GROUP BY speaker ORDER BY n DESC;

-- F. Meeting lookup then deep-read
SELECT rowid, date, title, category, path FROM meetings
WHERE date BETWEEN '2026-06-01' AND '2026-07-31' AND category='내부-전략';
```

### Question patterns → how to answer

| User asks (예) | Do |
|---|---|
| "X는 어떤 사람이야 / 어떻게 생각해?" | Recipe A + relations where X appears → profile card: 핵심 프레임 3–5개(인용 포함) + 근거 등급 + 최근 변화(evolution/timeline) |
| "X에게 이 일 맡겨도 될까?" | Recipe A for X → match the task against X's models (fit/anti-fit) → tensions involving X → verdict: 맡기면 잘 될 조건 / 부딪힐 지점 / 보완 파트너 |
| "X랑 미팅인데 뭘 준비하지?" | X's profile + last meetings with X (Recipe F + read) → 1-page brief: 상대 프레임 · 지난 논의 미결점 · 반응 예상 · 여는 질문 3개 |
| "우리 조직 어디가 안 맞아?" | Recipe B + timeline 최근 국면 → tension별: 누가·무엇·언제부터·현재 상태 · 방치 리스크 |
| "Y 주제 논의 이력 정리해줘" | Recipe C/E/F → 시간순 논의 요약 + 입장 변화 + 미결 사항 |
| "지난 분기에 뭐가 변했어?" | Recipe D + 해당 기간 meetings 훑기 → 국면 변화 서술 |

---

## Part 2 — Strategy mode (사업구상·전략 모드)

Structured workflows. Each produces a **written deliverable** (md), not just chat.
Always end with an honesty footer: what the data supports vs. what is speculation.

### Workflow S1 — 기회 발굴 (Opportunity mining)

*Trigger: "사업 아이디어 뽑아줘", "우리 데이터에서 기회 찾아줘", "what opportunities do you see"*

1. **Mine pain signals**: FTS-sweep the corpus for recurring pain/desire language
   (아쉽/불편/비싸/못 구해/직접 만들/누가 해줬으면/문제는 + domain terms). Fan out
   cheap parallel subagents by month/category for large corpora.
2. **Mine unmet-need statements from counterparts** (외부 미팅 카테고리 우선) —
   what partners/customers repeatedly ask for.
3. **Cluster into opportunity candidates** (5–10): each = {문제, 누가 겪나, 반복 횟수
   ·근거 회의들, 기존 대안의 한계}.
4. **Fit check against the owner's models**: does each candidate align with their
   canonical beliefs (e.g. "먼저 넓히고 수익화")? tension with their risk models?
5. **Deliverable** `OPPORTUNITIES-<date>.md`: 후보 테이블(문제/근거 회의 수/기존 대안/
   본인 프레임 정합/첫 검증 실험) + top 3 상세.

### Workflow S2 — 전략 옵션 설계 (Strategy options)

*Trigger: "Z에 대한 전략 짜줘", "우리 다음 분기 뭐에 베팅해야 해?"*

1. **Ground**: pull bets + risks + timeline 최근 2 국면 + Z 관련 발언(FTS).
2. **Generate 3 options** from different frames *the owner actually holds*
   (e.g. 속도-프레임 옵션 / 해자-프레임 옵션 / 현금-프레임 옵션) — 각 옵션에 근거
   모델 id를 명시. 서로 다른 canonical model에서 출발해야 진짜 옵션이 된다.
3. **Stress-test with tensions**: for each option, who in the org/partners will push
   back and why (use relations + their models). This is the pre-mortem.
4. **Deliverable** `STRATEGY-<topic>-<date>.md`: 옵션 비교표(가정/필요 리소스/
   반대할 사람과 논거/선행 지표) + 추천 1개 + 결정을 위해 답해야 할 질문 3개.

### Workflow S3 — 설득 전략 (Persuasion brief)

*Trigger: "투자자/파트너/팀원 X를 설득해야 해"*

1. X's model profile (그의 판단 기준·리스크 감수성·반복 관심사).
2. Map your ask onto **X's frames** — X의 언어로 번역한 3개 논거 + X가 우려할
   2가지와 선제 대응.
3. Deliverable `PERSUASION-<X>-<date>.md`: 오프닝 훅(그의 최근 발언 인용) →
   프레임 정렬 논거 → 예상 반론·응답 → 다음 스텝 제안.

### Workflow S4 — 정렬 리포트 (Alignment report)

*Trigger: "조직 정렬 상태 점검해줘", 정기 실행 추천(월 1회)*

1. relations tension 전수 + 최근 N주 meetings에서 새 대립/해소 신호 스캔.
2. Deliverable `ALIGNMENT-<date>.md`: tension별 상태(신규/지속/악화/해소) ·
   방치 시 비용 · 개입 제안(누구와 누구를 어떤 의제로).

### Workflow S5 — 결정 시뮬레이션 (Decision simulation)

*Trigger: "이 결정하면 다들 어떻게 반응할까?"*

For a proposed decision, simulate each key person's likely reaction **from their
models** (not from stereotypes): 예상 입장 + 근거 모델/인용 + 설득 포인트.
Label clearly: **시뮬레이션 — 실제 반응은 다를 수 있음.** Deliverable optional.

### Strategy-mode honesty rules

- Opportunities/strategies are **hypotheses**; the data shows *what people said*,
  not market truth. Recommend the cheapest real-world validation step for each.
- Never let the simulation (S5) be treated as the person's actual view — it's a
  planning aid. Remind the user.
- Deliverables default into `<corpus>/_strategy/` (create if missing) so they
  accumulate next to the data that produced them.
