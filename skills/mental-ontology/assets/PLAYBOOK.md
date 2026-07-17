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

**Names first**: transcripts label speakers many ways (`정우진`, `James`, `James(정우진)`).
The DB resolves labels to canonical names via `person_aliases` (built from
`_meta/speakers.json`); `utterances.speaker` is already canonical where resolvable.
Start person questions with A0 so you query the right canonical name.

**Holder vs about**: `model_people` = who *holds* a belief. `model_about` = whom the
belief is *about*. "메가스테이에 대한 모델" (A2) are **our people's beliefs about that competitor** —
never present them as the competitor's own views.

```sql
-- A0. Resolve any label/alias to the canonical person
SELECT DISTINCT canonical FROM person_aliases WHERE alias LIKE '%james%';

-- A. Person profile (사람 한 명의 전체 프레임 — 그 사람이 '보유한' 모델)
SELECT m.category, m.title, m.evidence, m.count, m.quote
FROM models m JOIN model_people mp ON mp.model_id = m.id
WHERE mp.person = 'James(정우진)' ORDER BY m.count DESC;

-- A2. What do our people believe ABOUT an entity (경쟁사/파트너/고객)
SELECT m.title, m.evidence, m.quote,
       (SELECT GROUP_CONCAT(person, ', ') FROM model_people WHERE model_id=m.id) AS held_by
FROM models m JOIN model_about a ON a.model_id = m.id
WHERE a.entity LIKE '%메가스테이%';

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

-- E. Who talks about X the most (주제별 오너십 힌트 — speaker는 canonical)
SELECT speaker, COUNT(*) n FROM utterances_fts WHERE utterances_fts MATCH '정산'
GROUP BY speaker ORDER BY n DESC;
-- caveat: 빈 speaker(미부여 발화)가 상위에 오면 그 회의들은 화자 미상 — 단정하지 말 것

-- F. Meeting lookup then deep-read
SELECT rowid, date, title, category, path FROM meetings
WHERE date BETWEEN '2026-06-01' AND '2026-07-31' AND category='내부-전략';

-- G. Interaction timeline for one person (통화처럼 화자 미상이어도 잡힘)
SELECT m.date, m.title, m.category FROM person_meetings pm
JOIN meetings m ON m.rowid = pm.meeting_rowid
WHERE pm.person = 'James(정우진)' ORDER BY m.date DESC;

-- H. Neglect check — core/acquaintance 중 오래 못 만난 사람 (도시에 frontmatter의
--    last_met으로도 가능; SQL 버전)
SELECT pm.person, MAX(m.date) AS last_met, COUNT(DISTINCT pm.meeting_rowid) AS total
FROM person_meetings pm JOIN meetings m ON m.rowid = pm.meeting_rowid
GROUP BY pm.person HAVING total >= 3 ORDER BY last_met ASC LIMIT 15;

-- I. Co-attendance — 누구와 자주 같이 만나는가 / 두 사람의 공통 회의
SELECT p2.person, COUNT(DISTINCT p2.meeting_rowid) n FROM person_meetings p1
JOIN person_meetings p2 ON p2.meeting_rowid = p1.meeting_rowid
WHERE p1.person = 'James(정우진)' AND p2.person != p1.person
GROUP BY p2.person ORDER BY n DESC LIMIT 10;

-- J. Network — 소개의 연쇄, 관계 종류별 조회
SELECT kind, a, b, since, note FROM network WHERE a LIKE '%정우진%' OR b LIKE '%정우진%';
SELECT a AS 소개자, b AS 소개받은사람, note FROM network WHERE kind = '소개';

-- K. 오픈 루프 — 미완료 약속 (사람별·기한순; 트랜스크립트 액션아이템 체크박스에서 파싱)
SELECT c.from_person, c.to_person, c.text, c.due, m.date, m.title
FROM commitments c JOIN meetings m ON m.rowid = c.meeting_rowid
WHERE c.done = 0 ORDER BY CASE WHEN c.due='' THEN 1 ELSE 0 END, c.due;
```

### Question patterns → how to answer

| User asks (예) | Do |
|---|---|
| "X는 어떤 사람이야 / 어떻게 생각해?" | A0로 canonical 확정 → Recipe A + relations where X appears → profile card: 핵심 프레임 3–5개(인용 포함) + 근거 등급 + 최근 변화(evolution/timeline) |
| "경쟁사/파트너 Y를 우리는 어떻게 보고 있어?" | Recipe A2 → **누구의 믿음인지 holder를 명시**해 답한다 ("정우진은 Y를 ~로 본다") — Y 자신의 견해처럼 말하지 않기 |
| "X에게 이 일 맡겨도 될까?" | Recipe A for X → match the task against X's models (fit/anti-fit) → tensions involving X → verdict: 맡기면 잘 될 조건 / 부딪힐 지점 / 보완 파트너 |
| "X랑 미팅인데 뭘 준비하지?" | X's profile + last meetings with X (Recipe F + read) → 1-page brief: 상대 프레임 · 지난 논의 미결점 · 반응 예상 · 여는 질문 3개 |
| "우리 조직 어디가 안 맞아?" | Recipe B + timeline 최근 국면 → tension별: 누가·무엇·언제부터·현재 상태 · 방치 리스크 |
| "Y 주제 논의 이력 정리해줘" | Recipe C/E/F → 시간순 논의 요약 + 입장 변화 + 미결 사항 |
| "지난 분기에 뭐가 변했어?" | Recipe D + 해당 기간 meetings 훑기 → 국면 변화 서술 |
| "X를 언제 처음/마지막으로 만났지?" | Recipe G — 또는 `people/X.md` 도시에 frontmatter가 즉답 |
| "요즘 소홀했던 사람 없나?" | Recipe H → 오래 못 만난 상위 인물 + 마지막 회의의 미결 주제를 함께 제시(연락 명분) |
| "X를 누가 소개해줬지? / X랑 같이 아는 사람?" | Recipe J (network) + Recipe I (동석) + 레지스트리 `intro_by` |
| "X 근황/개인적인 거 뭐 있었지?" | `people/X.md` 도시에의 개인 맥락 + 수기 메모 — **△/⛔ 태그 확인**: 사적·언급금지 항목은 "상대가 먼저 꺼낼 때만"이라고 함께 알려줄 것 |
| "내가 뭐 약속했더라? / X한테 진 빚?" | Recipe K → 기한 지난 것 먼저, 근거 회의와 함께 |

---

## Part 2 — Strategy mode (사업구상·전략 모드)

Structured workflows. Each produces a **written deliverable** (md), not just chat.
Always end with an honesty footer: what the data supports vs. what is speculation.

**전략 대장 (the strategy register)** — `bets[]`/`risks[]` are living assets with
`status`/`owner`/`source`/`related_models` (see schema). Every workflow below reads
the register first, updates it last (status transitions cite the evidencing meeting),
and ends its deliverable with a register diff. Deliverables append one line to
`_strategy/INDEX.md` (date · workflow · file · 한 줄 결론).

```sql
-- 전략 대장 현황
SELECT status, tag, title, owner, date FROM bets ORDER BY
  CASE status WHEN '진행중' THEN 0 WHEN '검토중' THEN 1 WHEN '보류' THEN 2 ELSE 3 END, date DESC;
SELECT status, level, title, mitigation FROM risks ORDER BY
  CASE level WHEN 'high' THEN 0 WHEN 'mid' THEN 1 ELSE 2 END;
```

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

For a proposed decision, per key person, output **exactly this 3-part set** — a
single predicted stance is FORBIDDEN (users over-trust point predictions and act
on them, e.g. preemptively routing around a predicted objection that never existed):

1. **찬성 시나리오**: this person supports it IF … (근거 모델/인용)
2. **반대 시나리오**: this person pushes back IF … (근거 모델/인용)
3. **확인 질문 1개**: the single question to ask them that reveals which scenario
   is real — this is the actual deliverable. 시뮬레이션은 확인을 대체하지 못한다.

Label clearly: **시뮬레이션 — 실제 반응은 다를 수 있음.** Deliverable optional.

### Strategy-mode honesty rules

- Opportunities/strategies are **hypotheses**; the data shows *what people said*,
  not market truth. Recommend the cheapest real-world validation step for each.
- Never let the simulation (S5) be treated as the person's actual view — it's a
  planning aid. Remind the user.
- Deliverables default into `<corpus>/_strategy/` (create if missing) so they
  accumulate next to the data that produced them.
