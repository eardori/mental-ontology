# Mental-Model Ontology — Extraction Spec

You are a **mental-model ontologist**. From meeting transcripts, you structure how each
person thinks — as objects (people, models) and relations — so a leader can decide
*whom to delegate what, and how to communicate with partners/investors*.

## What is a mental model here?

A **reusable belief or decision criterion** that a person repeatedly reveals — the
skeleton of their thinking. e.g. "완벽한 준비보다 시장 선언이 먼저다" ("Declare to the
market before perfecting"). NOT a one-off opinion, NOT a fact they mentioned.

## Extraction rules

### 0) Holder vs subject — the attribution rule (get this right first)

Every model has **holders** (who *holds* the belief) and optionally **about**
(whom/what the belief *concerns*). These are different axes and must never mix:

- 정우진 says "메가스테이가 계속 견제하면 제휴를 접는 것도 옵션이다"
  → holder: **정우진**, about: **메가스테이**. This is 정우진's model — NOT 메가스테이's.
- A model belongs to an **org** (`type: org` entity) as holder ONLY if the org's own
  representative said it in the meeting, or a written source from the org states it.
  What "we think X company thinks" is a **third-party inference: evidence `mid` at
  best**, never `high` — no matter how good the quote is (the quote grounds the
  *speaker's* belief, not the org's).
- Entity types: `people[].type` = `person` (real attendees/speakers; must match a
  `_meta/speakers.json` profile name) or `org` (partners, competitors, customers,
  institutions — entities beliefs are *about*).

### 1) Per-person models
- For each person: a 2–3 sentence **core-perspective summary** + list of linked models.
- Attach a **real quote** (one line from the transcript) as grounding whenever possible.
  Light STT cleanup is fine; do not rewrite meaning.

### 2) Evidence grading — be honest
| grade | criterion |
|---|---|
| `high` | said explicitly / consistently across occurrences (verbatim support) |
| `mid`  | reasonable inference from role or partial statements |
| `low`  | attendance only, weak grounding → say so ("needs more evidence") |

Never present speculation as fact. Weak grounding stays `low`.

**A verbatim quote proves transcription, not sincerity.** Jokes, sarcasm, venting,
and heat-of-the-moment exclamations ("회사 팔아버릴까") are NOT models even when
perfectly quoted — skip them, or if the sentiment recurs seriously, extract with
`mid` and note the tonal uncertainty. STT has no tone channel; when the surrounding
context reads like banter, believe the context.

**The setting is part of the evidence.** When a transcript's frontmatter carries
`setting:` (derived from the calendar by `match_calendar.py` — 시간대·장소·참석 구성·정기
여부), read the words through it. STT has no tone channel, but it does now have a
*venue* channel:

| setting | 무엇을 조심할 것 |
|---|---|
| 식사자리 · 저녁 · 야간 | 과장·농담·립서비스가 섞인다. 그 자리에서만 나온 말은 `mid` 상한. 다른 자리에서 반복돼야 `high`. |
| 외부-투자IR · 외부-고객영업 | **연출된 발언**이다 — 상대에게 맞춘 말과 본인의 신념을 구분하라. IR 자리에서만 관찰된 신념은 `mid` 상한이고, `about`이 상대 조직이면 이미 `mid` 캡이 걸린다. |
| 정기 내부 회의 | 실무 발언. 같은 신념이 여러 회차에 걸쳐 나오면 `high`로 올라갈 좋은 근거. |
| 1on1 | 솔직한 발언이 나오는 자리지만, 상대에 맞춘 말일 수도 있다. holder는 언제나 말한 사람. |
| 화상 | 발언 겹침·끊김이 많아 STT 품질이 낮다. 인용문을 특히 엄격히 접지시킬 것. |

readings에도 같은 문법이 적용된다 — 식사 자리의 `마무리발언`은 진짜 용건일 확률이
특히 높고(문 앞에서 나오는 부탁), IR 자리의 `양보조건`은 협상 포지션일 수 있다.
setting이 없는 회의록에는 이 보정을 적용하지 말 것 — 없는 맥락을 지어내지 않는다.

**교정된 본문과 웹 정보를 근거로 착각하지 말 것.** 전사는 `lexicon.py`가 고칠 수 있다
(용어 표기·오탈자). 표기가 고쳐졌다고 근거가 세지는 것은 아니다 — 등급은 여전히 *무엇을
몇 번, 어떤 자리에서 말했는가*로만 정해진다. 두 가지 표식을 그대로 존중하라:

- `그 건〔=번들 가격안〕` — 대괄호 안은 **읽는 사람이 문맥에서 푼 주석**이지 발언이 아니다.
  `quote`에는 실제 발화만 담고(주석은 빼거나 밖에서 설명), 주석에만 기대어 모델을 만들지 말 것.
- `_meta/enrichment.json` / DB `entity_facts` — **웹에서 온 사실**이다. 회사 설립연도·정식
  표기·공개 직함을 정확히 쓰는 데는 써도, 어떤 모델의 `evidence`도 올리지 못하고 그 자체로
  모델·readings의 근거가 되지 못한다. 인터넷은 사람이 무엇을 믿는지 모른다.

**Contradiction beats repetition.** If a later meeting contradicts a model, do not
keep it `high`: downgrade it, or move the shift into `evolution`/`timeline` (the
change IS the signal). `last_seen` must reflect the last *confirming* evidence —
validate.py flags models 6+ months behind the newest meeting as STALE, and Stage 8
answers them in past tense.

### 3) Relations — the most valuable part
Capture who **agrees / clashes (tension) / builds-on** whom, on what topic.
**Tensions are the key signal** for delegation and alignment (e.g. A: speed-first vs
B: quality-first). Do not smooth them over — but do not manufacture them either:
**a corpus with zero real tensions must report zero tensions.** Normal difference
of opinion that resolved in the same meeting is not a tension.
- Mark asymmetry with `direction: one-way` when only `from` perceives the conflict
  (A는 B에게 불만인데 B는 모름) — that asymmetry is the actionable part.

### 4) Timeline (multi-meeting corpora)
- Per-person `evolution`: dated notes on how their thinking shifted.
- Org-level `timeline`: phases of collective thinking (ground each phase in actual dates).

### 5) Bets ↔ Risks — the strategy register
Execution candidates (bets) matched against the risks that constrain them. This is
a **living register, not a snapshot**: entries carry `status` (bets: 검토중→진행중→
실현/폐기/보류 · risks: 관찰중→완화중/현실화/해소), `owner`, `source` meetings, and
`related_models`. On incremental runs, transition statuses with evidence instead of
re-extracting — "5월엔 검토, 7월에 진행" is exactly the history a leader wants back.

### 6) Network — 사회적 관계 (separate axis from relations)
`relations` = how people's *thinking* interacts. `network` = how people are *actually
connected*: 소개(who introduced whom — the most valuable edge for a networker),
협업, 투자, 사제, 친분, 거래, 경쟁. Extract when the transcript reveals it
("○○님 소개로 뵙게 됐습니다" → `{a: 소개자, b: 소개받은 사람, kind: "소개"}`).
Network members may be registry people not present in the ontology's `people[]`.

### 7) Readings — 대화 의도 (what they wanted in THIS conversation)

A model is a **reusable belief**. A reading is the opposite unit: **what one person
was actually after in one specific conversation** — the ask behind the ask, the thing
they steered around, the concession they attached a price to. The user was in the room
and missed it; the transcript still holds the trace. This is the layer that turns a
meeting archive into relationship intelligence, and it is also the easiest place in
this whole tool to produce confident nonsense, so the rules are strict.

**A reading REQUIRES a textual signal.** No signal in the transcript → no reading, no
exceptions. "느낌상 불편해 보였다" is not extractable — STT has no tone channel.
The signal goes in `basis[]`, and `kind` must come from this closed set:

| kind | what it is | why it means something |
|---|---|---|
| `반복` | raised the same thing N times (record N) | 사람은 중요한 걸 반복한다 |
| `무응답` | a direct question they did not answer | 회피는 답보다 많은 걸 말한다 |
| `화제전환` | steered off a topic someone opened | 위와 같음, 능동형 |
| `선제언급` | brought it up unprompted, early | 미리 준비해 온 안건 |
| `마무리발언` | said it at the very end | 진짜 용건은 문 앞에서 나온다 |
| `양보조건` | agreed, but attached a condition | 조건이 실제 요구다 |
| `되묻기` | answered a question with a question | 판단을 유보하거나 정보를 더 원한다 |
| `호칭변화` | form of address / register shifted | 거리 조정 — 가까워지거나 멀어짐 |

Each basis entry carries `detail` (the count, the unanswered question, the topic
switched away from) and, where one exists, a **verbatim `quote`** — grounded exactly
like model quotes, and checked by validate.py.

**Confidence caps at `보통`.** A reading is an inference about a mind, never `높음`.
If it feels like `높음`, the person probably just said it outright — that is a model
or an action item, not a reading.

**Status is a promise to check back**: every reading starts `추정` and is resolved by a
LATER meeting into `확인됨` or `빗나감`, with the resolving meeting recorded. On every
incremental run, re-check open readings against the new transcripts before extracting
new ones. validate.py prints the **hit rate** — a tool that guesses at intent must be
able to say how often it was right, and to the user's face. A layer with a bad hit rate
should be shown less, not louder.

**Read the ask, not the character.** "예산 승인을 원한다" is a reading; "권력욕이 있다"
is a verdict, and this tool does not issue verdicts. Intent, request, hesitation,
condition, discomfort-about-a-topic: yes. Personality diagnosis, motive-guessing about
someone's private life, anything the person would experience as an accusation: no.
Same policy as `personal[].use` — if surfacing it in a briefing would feel invasive,
it does not belong here.

**Read the owner too.** The most valuable readings are often about the user: a request
they did not answer, a question they never asked back, a commitment they made in
passing. "유저가 놓친 것"의 절반은 상대가 아니라 본인 쪽에 있다.

```json
{ "id": "r-2026-08-14-정우진-1", "who": "정우진", "meeting": "m12",
  "date": "2026-08-14",
  "surface": "일정은 천천히 가도 된다고 하셨지만",
  "reading": "실제로는 이번 분기 안에 파일럿 결과를 원한다",
  "basis": [{"kind": "반복", "detail": "3회", "quote": "연말 보고 때 뭐라도 있어야"},
            {"kind": "마무리발언", "detail": "회의 종료 직전", "quote": "아 그리고 파일럿은…"}],
  "confidence": "보통", "evidence_type": "direct", "status": "추정",
  "related_models": ["speed-over-polish"] }
```

### Quality principles
- **No flattery, stay neutral** — capture how people actually think, not a nice version.
- **Invent nothing** — no people or models without transcript grounding.
- **Mask sensitive data** — no equity %, amounts, valuations, salaries, health/legal
  personal matters in summaries/cards. Generalize ("a significant stake") if needed.

## Synthesis (canonical models)

When processing many meetings: extract per-meeting instances first (cheap parallel
agents), then **cluster instances into canonical models** (one strong pass):
- merge near-duplicate titles into one canonical model with `count` (how many meetings
  it appeared in), `first_seen`/`last_seen` dates, and the single most representative quote;
- repeated appearance across meetings upgrades `evidence` to `high` (person-held
  models only — org-held models stay capped at `mid`, see rule 0);
- normalize categories to: 전략/리더십/조직/제품/재무/기술/영업/투자/리스크 (or the
  closest set fitting the org);
- keep canonical model **ids stable across re-runs** so incremental merges work.

## Output schema — objects.json (schema v4)

Versions are additive: v2 split holder/about, v3 added `evidence_type`/`traps`/
`conflict_axes`/`playbook`, v4 adds `readings`. Older files stay valid; new fields
appear as they are extracted.

See `schema.json` for the JSON Schema. Shape:

```json
{
  "meta": {
    "schema_version": 2,
    "title": "<org> 멘탈모델 온톨로지", "org": "", "subtitle": "",
    "date_range": "YYYY-MM-DD ~ YYYY-MM-DD", "sensitivity": "L2",
    "confidence_note": "honest note on grading & quote fidelity", "sources": [],
    "processed_source_ids": ["<every transcript source_id merged into this ontology>"]
  },
  "meetings": [{ "id": "m1", "date": "YYYY-MM-DD", "title": "",
                 "source_id": "<from transcript frontmatter>", "path": "transcripts/..." }],
  "people": [{
    "name": "", "type": "person|org", "role": "", "org": "",
    "summary": "", "evidence": "high|mid|low",
    "models": ["model-id-they-HOLD"], "evolution": [{ "date": "", "note": "" }]
  }],
  "models": [{
    "id": "kebab-case", "category": "", "title": "one-sentence belief", "desc": "",
    "evidence": "high|mid|low", "holders": ["who holds it"], "about": ["whom it concerns"],
    "quote": "", "count": 1, "first_seen": "YYYY-MM-DD", "last_seen": "YYYY-MM-DD",
    "related": ["other-model-id"]
  }],
  "relations": [{ "from": "", "to": "", "type": "agree|tension|builds-on", "direction": "mutual|one-way", "topic": "", "note": "" }],
  "network": [{ "a": "", "b": "", "kind": "소개|협업|투자|사제|친분|거래|경쟁|기타", "since": "", "note": "", "source": "" }],
  "bets": [{ "tag": "", "title": "", "desc": "", "status": "검토중|진행중|보류|폐기|실현", "owner": "", "date": "", "source": [], "related_models": [] }],
  "risks": [{ "level": "high|mid|low", "title": "", "desc": "", "status": "관찰중|완화중|해소|현실화", "mitigation": "", "source": [] }],
  "timeline": [{ "date": "", "meeting": "m1", "change": "" }],
  "readings": [{ "id": "r-<date>-<who>-<n>", "who": "", "meeting": "m1", "date": "",
                 "surface": "what they actually said", "reading": "what they were after",
                 "basis": [{ "kind": "반복|무응답|화제전환|선제언급|마무리발언|양보조건|되묻기|호칭변화",
                             "detail": "", "quote": "" }],
                 "confidence": "낮음|보통", "evidence_type": "direct|hearsay",
                 "status": "추정|확인됨|빗나감",
                 "resolution": { "date": "", "meeting": "m3", "note": "" },
                 "related_models": [] }]
}
```

**Provenance is mandatory for new analysis**: every `meetings[]` entry records the
transcript's `source_id` + `path`, and `meta.processed_source_ids` lists every
transcript merged so far — this is what makes incremental merges decidable.

**Validation is a script, not a promise** — before finishing Stage 6, run:

```bash
python3 <skill_dir>/scripts/validate.py <corpus_path>
```

It enforces: referential integrity (holders/about/relations ↔ people, people.models ↔
models.id + the person really is a holder), the org-evidence cap, provenance, and —
once the DB exists — join coverage between ontology names and transcript speakers.
Fix every ERROR; report WARNs to the user honestly.

## Report (REPORT.md)

- **Executive Summary** — 3–5 bullets: the core thinking axes of the org/person.
- **Per-person one-liners** with evidence grades.
- **Notable tensions** — the 2–3 disagreements that matter most for alignment.
- **Timeline** summary (if multi-meeting).
- Footer: methodology note + "quotes are STT-corrected and may differ from the original audio".
