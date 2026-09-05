# Mental Ontology — Stages 0–5: Setup · Fetch · Transcribe · Attribute · Save · Refresh

> Stage reference. Loaded on demand from SKILL.md (the router).
> Speak to the user in the user's language; these instructions are English for precision.

## Stage 0 — Setup & config

1. Read config at `~/.mental-ontology.json`. If missing, this is a first run:
   - Ask the user where to keep the corpus (suggest `~/MeetingCorpus`, or a folder inside their Obsidian vault if they use Obsidian — the corpus is plain markdown and works great in Obsidian).
   - Create the folder structure per `assets/corpus-structure.md` and write config: `{"corpus_path": "<abs path>", "language": "<user language code>"}`.
2. Verify the Plaud MCP is available: try ToolSearch `select:mcp__plaud__list_files,mcp__plaud__get_transcript,mcp__plaud__get_file,mcp__plaud__get_note,mcp__plaud__login,mcp__plaud__get_current_user`.
   - If tools are not found, the MCP server isn't registered/loaded → point the user to INSTALL.md (register with `claude mcp add plaud -s user -- npx -y @plaud-ai/mcp@latest`, then restart the session).
3. Auth: call `get_current_user`. On auth error, call `login` (opens browser; the user must click Authorize themselves — never handle credentials).

## Stage 1 — Fetch recordings from Plaud

1. `list_files` supports `query`, `date_from`/`date_to`, and pagination (`page`, `page_size`). For "sync recent", filter from the last processed date (track it in `_meta/state.json` as `last_synced`).
2. **Skip junk**: recordings under 2 minutes are almost always accidental. Don't process them; append them to `_meta/deletion-candidates.md` (Plaud MCP has no delete tool — the user deletes in the Plaud app).
3. **Dedup**: before processing an id, check `_index/catalog.json` for an existing entry with the same `source_id`. Skip if present (unless the user asks to redo).
4. For each recording, call `get_transcript(file_id)`:
   - **Large results are saved to a file** by the harness ("Output has been saved to <path>"). Parse that file with python — lines can be extremely long, so read with `open(path).read()` and `json.loads`, never line-by-line tools.
   - Structure: a JSON array; items with `type == "transaction"` hold the utterances (`speaker`, `start` in **ms**, `content`/`text`); `type == "outline"` holds section summaries. Speaker labels may be wrong or generic ("Speaker 1") — fix in Stage 3.
   - **Empty array `[]` = no transcript exists** → Stage 2 (Whisper) if duration ≥ 20 min; otherwise mark as junk.
5. Also call `get_note(file_id)` for the AI summary/topics (nice input for Stage 4 summary; proceed fine if it fails).

### Stage 1b — 캘린더에서 그 자리가 뭐였는지 가져오기 (있으면 반드시)

녹음은 "언제 몇 분"만 안다. 캘린더는 **무슨 자리였는지**를 안다 — 제목·참석자 명단·
장소·정기 여부. 셋 다 이 파이프라인이 추론으로 때우던 값이고, 그중 **참석자 명단은
Stage 3 화자 추정의 정답지**다.

1. 캘린더 MCP가 있는지 확인 (`ToolSearch` → `list_events` / `list_calendars`). 없으면
   이 단계를 조용히 건너뛴다 — 캘린더는 선택이고, 없다고 파이프라인이 막히지 않는다.
2. 첫 사용 시 한 번만 묻는다: 어떤 캘린더인지(여러 개면 `list_calendars`로 고르게),
   그리고 **내 이메일 도메인**(내부/외부 구분 기준). 답을 `~/.mental-ontology.json`에
   `calendar_id` / `owner_domain`으로 저장.
3. 동기화 구간의 일정을 받아 **월별 캐시로 저장**한다 —
   `<corpus>/_meta/calendar/<YYYY-MM>.json`:
   ```json
   {"fetched": "YYYY-MM-DD", "range": ["YYYY-MM-01", "YYYY-MM-31"],
    "owner_domain": "example.com",
    "events": [{"id": "", "title": "", "start": "YYYY-MM-DDTHH:MM", "end": "YYYY-MM-DDTHH:MM",
                "location": "", "description": "", "recurring": false,
                "attendees": [{"name": "", "email": "", "self": false}]}]}
   ```
   캐시로 두는 이유: 재실행이 같은 결과를 내야 하고(매칭은 결정적이어야 한다), 매번
   캘린더를 다시 읽지 않기 위해서다. **캘린더 원문을 코퍼스 밖으로 내보내지 않는다.**
   description은 회의 링크·아젠다만 남기고 길면 잘라서 저장한다(민감 정보 유입 방지).

   **Google Calendar 응답 → 캐시 변환 (필드 이름이 다르다. 실측 기준):**

   | 캐시 | Google 응답 | 주의 |
   |---|---|---|
   | `title` | `summary` | |
   | `start` / `end` | `start.dateTime` / `end.dateTime` | `+09:00` 오프셋이 붙어서 온다 — 그대로 넣으면 된다(스크립트가 로컬로 변환). **종일 일정은 `date`만 오는데, 그런 이벤트는 캐시에 넣지 말 것** (연차·휴가가 그날 모든 녹음을 삼킨다) |
   | `recurring` | `bool(recurringEventId)` | 정기 여부 플래그는 따로 없다 |
   | `description` | `conferenceUrl` 또는 `description` | Meet 링크는 여기에 |
   | `attendees[].name` / `.email` | `attendees[].displayName` / `.email` | **표시 이름이 없는 참석자가 대부분이다** — 이메일을 그대로 두면 스크립트가 아이디(`sebs.park`)를 후보로 올리고 Stage 3가 실제 이름으로 확정한다 |
   | `attendees[].resource` | `attendees[].resource` | **회의실·장비 예약이 참석자로 들어온다.** 이 플래그와 `@resource.calendar.google.com` 도메인을 그대로 넘겨야 스크립트가 걸러낸다 |
   | `attendees[].responseStatus` | 그대로 | `declined` 는 그 자리에 없던 사람으로 계산된다 |
4. 매칭은 **Stage 5에서** 돈다 — `build_index.py`가 만든 `_index/catalog.json`을 읽기
   때문에 그 전에 실행하면 새 녹음을 못 찾는다. Stage 5의 명령 블록을 그대로 따를 것:
   ```bash
   python3 <skill_dir>/scripts/match_calendar.py <corpus>            # 리포트
   python3 <skill_dir>/scripts/match_calendar.py <corpus> --apply    # 확정 건 반영
   ```
   시작 시각 겹침으로 매칭하고, `setting`(TPO)·`calendar_event`를 프론트매터에 붙이며,
   **비어 있거나 자동 생성된 값만** 채운다(사람이 정한 제목·분류는 절대 덮어쓰지 않고
   리포트에만 남긴다). `?` 표시된 건은 사람이 판단한다 — 억지로 확정하지 말 것.

## Stage 2 — Whisper transcription (raw audio)

Only for recordings with no Plaud transcript.

1. **Critical: presigned URLs expire within seconds–minutes.** Call `get_file(file_id)` to obtain `presigned_url`, then **immediately** run the download in the very next tool call. Never batch-fetch URLs first.
2. Use the bundled script (handles download, validation, and transcription):
   ```bash
   python3 <skill_dir>/scripts/whisper_transcribe.py --url "<presigned_url>" --id <file_id> --out <corpus>/_whisper [--lang auto]
   ```
   - **Language**: default `auto` detects from MID-FILE samples (never trust the first 30s —
     intros/music routinely fool detection and a wrong forced language produces fluent
     hallucination loops, e.g. an English meeting transcribed as Korean greetings).
     If the output's `repetition_ratio` > 0.3, re-run with the correct explicit `--lang`.
   ```bash

   ```
   - It validates the download (≥1MB, not an XML `ExpiredToken` error), picks `mlx_whisper` on Apple Silicon or `openai-whisper` elsewhere, and writes `<corpus>/_whisper/<id>.json` (`{id, text, segments:[{start,text}]}`).
   - If neither whisper package is installed, the script prints install hints (`pip3 install mlx-whisper` on Apple Silicon, else `pip3 install openai-whisper`). Offer to install for the user.
3. Long audio takes real time (roughly 5–7× realtime on Apple Silicon). For multiple files, run sequentially in the background and continue other work; warn the user that closing the laptop lid pauses transcription (finished files are skipped on rerun — safe to resume).
4. Whisper output has **no speaker separation** — note `transcribed_by: whisper` in the frontmatter and still attempt Stage 3 from context clues (self-introductions, names being addressed).

### Stage 2b — Local speaker diarization + voice identity (for Whisper audio)

When Whisper audio has multiple speakers, split them locally with the sherpa-onnx scripts
(no cloud), then ask the **voiceprint store who they are**. Convert to 16kHz mono first:

```bash
ffmpeg -i in.mp3 -ac 1 -ar 16000 in.wav
python3 <skill_dir>/scripts/diarize.py    in.wav diar.json                     # first pass (over-splits)
python3 <skill_dir>/scripts/recluster.py  in.wav diar.json diar_re.json 0.45   # cosine 0.45; lower = more speakers
python3 <skill_dir>/scripts/voiceprint.py <corpus> embed    --wav in.wav --regions diar_re.json --out emb.json
python3 <skill_dir>/scripts/voiceprint.py <corpus> identify --embeddings emb.json --out labels.json
python3 <skill_dir>/scripts/merge_diar.py <whisper.json> diar_re.json labeled.txt --labels labels.json
```

`labeled.txt` now carries **real names for every voice the corpus already knows** and
`Speaker N` only for the rest — those are the only ones Stage 3 asks about. After the user
confirms them, teach the store (Stage 3 rule 0) so the same person is free next time.

**Setup once**: `pip3 install sherpa-onnx soundfile numpy scikit-learn`, and place the models
(`sherpa-onnx-pyannote-segmentation-3-0/model.onnx`, `campplus.onnx`) in a dir pointed to by
`DIAR_MODELS` (default `~/.cache/mental-ontology/diar-models`). The recluster pass is not
optional: sherpa's raw clustering badly over-segments (e.g. 40 speakers for a 2-person call);
threshold 0.45 works well for Korean. If `identify` reports **화자 과다분할 가능성** (two
clusters both matching one enrolled person), that threshold is too low for this file — re-run
`recluster.py` with a higher value (0.5–0.6) rather than answering the question twice.

## Stage 3 — Speaker attribution (interactive, learning)

Goal: replace "Speaker 1/2" and misattributed labels with real names, learning over time.

0. **Ask the voiceprint store first** (audio path only — Plaud transcripts arrive with labels).
   `voiceprint.py identify` returns one row per cluster with a cosine score and a decision:
   `auto` (apply it — no question), `ask` (a named candidate, unsure — make it the default
   option in the question below), `unknown` (ask from scratch). **Never promote an `ask` to a
   name yourself**; the score is the whole point of the honesty rule here. A person who has
   been confirmed once is recognized for free in every later recording — this is what makes
   frequent casual recording sustainable, so treat enrollment (step 5b) as mandatory, not
   optional polish.
0b. **Who is the user?** The registry entry for the corpus owner carries `"owner": true`.
   If no entry has it, ask once — the briefing needs it to separate "내가 한 약속" from
   "상대가 한 약속" (without it, it guesses the most-attending person and says so).
1. Load `_meta/speakers.json` — this is the **person registry**, not just an STT map: `[{name, role, org, aliases[], traits, meetings:[dates], tier, first_met_context, intro_by, personal[]}]`. Create if missing.
   - `tier`: `core` (deep mental-model analysis) / `acquaintance` (light dossier) / `contact` (name + meetings only). New confirmed speakers default to `acquaintance`; promote to `core` when the user starts asking about how they think.
   - `first_met_context` ("스타트업얼라이언스 행사에서"), `intro_by` (who introduced them) — capture when the transcript or the user reveals it; this is네트워커의 핵심 자산.
   - `personal[]`: dated personal-context notes (`{"date","note"}`) — see the privacy policy below for when to record these.
2. For each distinct speaker label in the transcript, infer candidates from:
   - **the calendar attendee list, when the meeting matched one (Stage 1b) — this is
     ground truth, not a guess.** 2인 일정에서 화자가 2명이면 매핑은 사실상 결정된다;
     참석자 명단은 AskUserQuestion의 선택지가 되고, 명단에 없는 이름을 지어내지 않는다,
   - explicit self-introductions and how people address each other in the text,
   - the meeting title/participants context,
   - known profiles (matching role/org/topic patterns and speech traits).
3. **Confidence rules**:
   - Label already a real name that matches a known profile → auto-accept, no question.
   - Strong contextual match to a known profile → propose as the default option.
   - Otherwise → ask.
4. Ask with the AskUserQuestion tool, one compact question per unknown speaker (batch up to 4 per call). Options = top candidates with a one-line quote sample of that speaker; the user can always pick "Other" and type a name. Example question: "Speaker 2는 누구인가요? (샘플: '...정산 주기를 당기면...')".
   - **Friction budget**: at ingest time, ask at most ONE batched question per sync (the most frequent unknowns). Defer the rest to **Backfill mode** — daily-loop friction is what silently kills data quality (skipped questions → Speaker N debt).
5. Update `speakers.json` with confirmations (add aliases, meeting dates, refine traits). This makes future runs progressively quieter — that's the point.
   - **Capture the relationship while you have the user's attention**: when confirming a NEW person (≤2 new people this sync — else defer), add ONE compact question to the same AskUserQuestion call: "〈이름〉님과는 어떤 관계인가요?" with options 팀원 / 파트너 / 고객 / 투자자 (+Other for 지인·상사·가족 등) → store as `relationship`. If the transcript already makes it obvious ("우리 CTO가…"), don't ask — record it. For 내부 people, fill `team`/`manager` from context when clear; otherwise leave for the 조직도 flow below.
   - **5b. Teach the voice** (audio path): right after the user confirms who a cluster was,
     enroll it so the next recording needs no question —
     `python3 <skill_dir>/scripts/voiceprint.py <corpus> enroll --embeddings emb.json --map '{"1":"이서연"}' --source <file_id>`
     (keys are cluster ids, or `"Speaker 2"` style). The script refuses clusters under 5s and
     clusters that already sound like a **different** enrolled person — that refusal is a
     mislabel warning, so re-check the answer instead of reaching for `--force`. Voice data is
     biometric: it stays in `_meta/voiceprints.json` (local), `purge_person.py` deletes it, and
     `voiceprint.py <corpus> forget --name X --apply` removes one person on request.
   - **Aliases are load-bearing**: `build_db.py` joins transcripts to the ontology through them. Record every raw label a person appears under (한글 이름, 영어 이름, 별명 — e.g. `James(정우진)` ← `정우진`, `James`, `제임스`). `Name(Other)` style names get both halves matched automatically, but anything else must be listed.
6. If the user says "몰라도 돼 / skip", keep generic labels and move on. Never block the pipeline on attribution.
7. **Auto-inference before asking** — resolve what context already proves, ask only about the rest:
   - **Solo recordings** (강연, 메모, 1인 발화 — one voice throughout): all utterances → the owner. Apply silently.
   - **Two-party calls** (개인-통화/1on1 with exactly one counterpart in participants, two distinct labels): infer the mapping from address terms ("대표님", "○○님"), self-introductions, and who the summary says initiated. Clear split + previously confirmed counterpart in `speakers.json` → auto-accept; clear split + new counterpart → propose both mappings as the default in ONE question; unclear → ask normally.
   - Never auto-assign over an existing **real-name** label — only generic labels (`Speaker N`, `발화자 N`, empty) are candidates.

**Backfill mode** — trigger: "화자 정리해줘 / 화자 백필" (anytime after Stage 7). Old imports accumulate generic labels; this pays that debt down in one interactive session:

1. Rank meetings by unresolved share, important categories first:
   ```sql
   SELECT m.path, m.date, m.title, m.category, COUNT(*) AS total,
          SUM(u.speaker='' OR u.speaker LIKE 'Speaker%' OR u.speaker LIKE '발화자%') AS unresolved
   FROM utterances u JOIN meetings m ON m.rowid = u.meeting_rowid
   GROUP BY u.meeting_rowid
   HAVING unresolved * 2 > total
   ORDER BY m.category IN ('내부-전략','내부-주간회의','내부-1on1') DESC, total DESC
   LIMIT 10;
   ```
2. For each meeting: Read the transcript, apply rule 7, then the standard Stage 3 question flow (batch up to 4 speakers per AskUserQuestion, with quote samples).
3. **Patch labels with a python find→replace on that file only** (e.g. `**[Speaker 2]` → `**[이서연]`) — never re-emit the transcript through the LLM. Update `speakers.json`, then rerun Stage 5 + Stage 7 and report the coverage change (build_db prints it).

**조직도 flow** — trigger: "조직도 입력해줘 / 조직도 업데이트" (anytime):

1. Ask the user to paste their org chart in any form (들여쓰기 텍스트, 마크다운, "A 밑에 B·C" 서술 — 뭐든). Parse it yourself.
2. Update the registry: each person's `team` + `manager` (+ create missing people as `contact` with `relationship: 팀원`). Never overwrite an existing value silently — show a diff and confirm once.
3. Rerun Stage 5. `build_db.py` derives the org chart into `network` as `보고` edges (source=조직도), so 관계도·조직도·동석 데이터가 한 그래프에서 조회된다. Dossiers show 소속·보고 라인.

## Stage 4 — Clean & save markdown

**Token economy rule: format the transcript body with a python script — never have the LLM rewrite or re-emit the transcript.** The LLM decides only: title, category, summary, speaker mapping, find→replace pairs for what a reader must judge (Stage 4b), and whether to split.

1. If one recording clearly contains **two+ unrelated meetings** (long silence gap, topic/participant switch), split into `_part1`, `_part2` files.
2. Write to `<corpus>/transcripts/<YYYY>/<YYYY-MM>/<YYYY-MM-DD>_<short-slug>.md`:
   ```markdown
   ---
   title: "<concise descriptive title>"
   date: <YYYY-MM-DD>
   category: <one of taxonomy>
   participants: [<confirmed names/orgs>]
   source_id: <plaud file id>
   duration_min: <n>
   start_time: "HH:MM"   # 녹음 시작 시각 — 캘린더 매칭 키. Plaud 파일 메타에 있으면 반드시 기록
   setting: ""           # TPO — match_calendar.py가 채움 (직접 쓰지 말 것)
   calendar_event: ""    # 매칭된 일정 id (출처)
   transcribed_by: plaud | whisper
   part: "1/2" # only when split
   ---

   # <title>

   ## 요약 / Summary

   <3–6 lines; use get_note if available>

   ## 액션아이템 / Action items

   - [ ] (요청자→담당자) 내용 (기한: YYYY-MM-DD) # 화살표·기한은 알 수 있을 때만

   ## 트랜스크립트 / Transcript

   **[Name] (mm:ss)** utterance...
   ```
   The 액션아이템 checklist is machine-parsed into the DB (`commitments`) and surfaces
   as each person's 오픈 루프 in their dossier — **약속을 지키는 것이 관계의 신뢰다.**
   Extract only commitments actually made in the meeting ("보내드릴게요", "다음 주까지");
   don't invent tasks. Mark `- [x]` when a later meeting confirms completion.
3. Category taxonomy (exactly one): `내부-주간회의 / 내부-전략 / 내부-1on1 / 외부-파트너 / 외부-고객영업 / 외부-투자IR / 강연-세미나 / 인터뷰 / 개인-통화 / 기타`.
4. Title: if the Plaud name is descriptive, polish it; if it's an auto timestamp ("2026-07-10 16:15:15"), write a new title from content.
5. **Relationship capture per meeting** (cheap, at ingest time — don't wait for Stage 6):
   - **New people** appearing in the meeting → add to the registry as `contact` (name + meeting date); if the meeting shows how they connect ("○○님 소개로"), record `intro_by`/`first_met_context` and consider a `network[]` entry (kind=소개) in objects.json.
   - **Personal context** worth remembering (가족·관심사·근황 — per the privacy policy) → append to that person's `personal[]` with the meeting date **and a usability tag** `use: 공개|사적|언급금지` (공개 = they said it openly/repeatedly; 사적 = mentioned once in a private aside; 언급금지 = knowing it would feel invasive — react only if THEY bring it up). Dossiers render △/⛔ markers from this — it's what keeps a briefing from turning into a creepy reveal.
   - After saving, give the user a 3-line digest: 새 인물 / 새 관계 신호 / 기억할 개인 맥락.
6. **Batch processing**: for many recordings, fan out with parallel subagents (cheapest capable model), one recording per agent, each following stages 1→4. Speaker questions (Stage 3) must run in the main conversation — collect unknown speakers from subagent results, ask the user once, then patch the files.

### Stage 4b — 용어 사전 · 오타 교정 (저장 직후, 매 동기화)

STT는 같은 고유명사를 **매번 같은 방식으로** 틀린다. 틀린 표기는 SQL이 못 찾는 용어이고,
validate가 못 붙이는 인용이고, 심하면 조인이 끊긴 사람이다. 그래서 코퍼스는 자기 어휘를
스스로 배운다 — `_meta/lexicon.json`이 그 사전이고, 교정은 전부 백업·로그·되돌리기가 딸린다.

1. **새 파일에 사전을 먼저 적용한다** (확정 + 추론):
   ```bash
   python3 <skill_dir>/scripts/lexicon.py <corpus> apply --path <새 전사 경로> --apply
   ```
2. **새 후보를 캔다** — 이번 동기화 구간만:
   ```bash
   python3 <skill_dir>/scripts/lexicon.py <corpus> mine --since <YYYY-MM-DD> \
       --json <corpus>/_ontology/_work/<date-label>/lexicon.json --apply
   ```
   `--apply`는 **추론 티어만** 학습한다(정답어 ≥5회·변형 ≤2회·자모거리 1·4자 이상 —
   임계값은 스크립트 상단에 공개돼 있고 리포트가 매번 출력한다). 리포트는 네 덩어리로 나온다:
   - **추론** — 자동 학습·자동 적용. 사람에게 묻지 않는다.
   - **후보** — 근거가 약함. 사람 확인 전까지 본문을 건드리지 않는다.
   - **인물 이름 오인식** — 본문을 절대 고치지 않는다. `_meta/speakers.json`의
     `aliases`에 추가할 것을 제안한다(build_db가 그걸로 조인하므로 이쪽이 정답이고,
     이름을 덮어쓰면 서로 다른 두 사람이 조용히 하나로 합쳐질 수 있다).
   - **새 용어 후보 / 지시어가 남은 액션아이템** — 아래 3·4에서 처리.
3. **읽어야만 판단되는 교정은 `patch`로** — 전사 본문을 다시 뱉지 말고 쌍만 넘긴다:
   ```bash
   # edits.json: [{"from":"...","to":"...","kind":"오탈자|지시어|용어","note":"근거"}]
   python3 <skill_dir>/scripts/lexicon.py <corpus> patch --path <파일> --file edits.json --apply
   ```
   - **일반 오탈자·띄어쓰기**: 문맥상 100% 확실할 때만. 애매하면 두고 리포트에 남긴다.
   - **지시어(그거·그 건·저번 거)는 지우지 말고 주석으로 푼다** — 실제 발언은 보존이
     원칙이다: `그 건〔=번들 가격안〕`. 같은 전사 안에 선행어가 있고 한 가지로만 읽힐 때만
     달고, 추측이면 달지 않는다. 액션아이템의 지시어는 우선순위가 높다(약속이 무엇에 대한
     약속인지 모르면 오픈 루프가 무의미해진다).
   - 등록된 인물 이름은 `patch`도 거부한다 — 이름은 레지스트리 문제다.
4. **질문은 동기화당 1문항 배치에 합류한다** (Stage 3 화자 질문과 **같은** AskUserQuestion
   호출). 마찰 예산은 하나다. 상위 3–4건만 묻고 나머지는 아래 "용어 정리" 플로우로 미룬다.
   질문 형식: "'커텍티비티'가 12번 나오는데 '커넥티비티'의 오인식일까요?" ·
   선택지 = 정답어 후보 / 그대로 둔다 / 다른 표기(Other).
5. **확인된 답은 즉시 사전에 기록**한다 (다음부터 안 묻기 위해):
   ```bash
   python3 <skill_dir>/scripts/lexicon.py <corpus> add --term "커넥티비티" --kind 용어 \
       --misspelling "커텍티비티" --desc "공급-수요 연결 개수"
   # 여러 건은 --file terms.json ([{term,kind,desc,aliases,misspellings}])
   ```
   사용자가 "그건 원래 그렇게 쓴다"고 하면 `--protect`로 넣어 다시는 교정 후보가 되지 않게 한다.
6. 교정이 있었으면 **파생 체인을 다시 돌린다**(본문이 바뀌었으므로): Stage 5 명령 블록.
   되돌리기는 `lexicon.py <corpus> revert --batch <id> --apply`, 이력은 `log`.

**용어 정리 플로우** — 트리거: "용어 정리해줘 / 사전 정리" (아무 때나). 화자 백필과 같은 구조:
코퍼스 전체를 `mine`으로 훑고, 후보를 빈도순으로 4개씩 묶어 물어보고, `add` → `apply --apply`
→ Stage 5 재실행 → 바뀐 커버리지를 보고한다. 사전이 두꺼워질수록 동기화 중 질문은 줄어든다.

### Stage 4c — 웹으로 사실 확인 (선택 · 조건부)

회의는 "넥스토라 쪽에 물어보죠"라고만 한다. 그게 회사인지, 표기가 맞는지, 뭐 하는 곳인지는
웹이 안다. 캘린더와 **똑같은 캐시 구조**다 — 스크립트는 웹을 못 부르니, 스킬이 검색하고
스크립트는 캐시만 읽는다(재실행이 같은 답을 내야 하고, 모든 주장에 출처가 붙어야 한다).

1. 웹 도구 확인: `ToolSearch` → `select:WebSearch,WebFetch`. 없으면 **조용히 건너뛴다**.
2. 무엇을 찾을지 계획한다 — **질의문은 스크립트가 만든다**:
   ```bash
   python3 <skill_dir>/scripts/enrich.py <corpus> plan --json <work>/enrich-plan.json [--include-people]
   ```
3. **계획에 적힌 질의문만 그대로 검색한다.** 회의 본문(숫자·조건·불만·거래 내용)을 검색어에
   붙이지 않는다 — 검색은 외부로 나가는 행위이고, 코퍼스는 그러라고 만든 게 아니다.
4. 결과를 `results.json`으로 쓰고 캐시에 넣는다. **주장마다 URL이 있어야 한다**(없으면
   스크립트가 버리고, `확인됨`은 `불확실`로 강등된다):
   ```bash
   # {"results":[{"entity","kind","canonical","summary","facts":[{"text","url"}],
   #              "spelling_variants":[],"role","org","status":"확인됨|불확실|기각"}]}
   python3 <skill_dir>/scripts/enrich.py <corpus> save --file results.json
   python3 <skill_dir>/scripts/enrich.py <corpus> apply            # dry run — 무엇이 바뀌는지
   python3 <skill_dir>/scripts/enrich.py <corpus> apply --apply --trust-web
   ```
   `apply`는 사전의 빈 `desc`와 레지스트리의 **빈** `role`/`org`만 채운다(사람이 적은 값은
   절대 덮어쓰지 않는다). 정식 명칭은 별칭으로 들어갈 뿐, 발언 본문을 대체하지 않는다.
   웹발 표기 교정은 기본이 `후보`이고, 코퍼스가 이미 그 표기를 쓰고 있을 때만
   `--trust-web`으로 `추론`이 된다.
5. **프라이버시 게이트** (스크립트가 강제한다):
   - 인물은 `--include-people` 없이는 계획에 오르지 않는다.
   - 레지스트리 `relationship`이 팀원·가족·지인·친구·동료면 **검색하지 않는다**(이유를 출력).
   - 공개 직함(대표/CEO/창업자/연사/교수…)과 소속이 함께 있을 때만 공인으로 본다.
     사용자가 명시적으로 정하려면 레지스트리에 `"public": true|false`.
   - 사용자가 "이 사람 찾아봐"라고 직접 지시하면 그 건에 한해 진행하고, 결과를 저장할지 묻는다.
6. **웹 사실은 근거가 아니다.** `entity_facts` 테이블에 URL·수집일과 함께 따로 쌓이고,
   어떤 모델의 `evidence`도 올리지 않는다. 답변에서 인용할 때는 항상 "웹 출처(날짜)"로
   표시해서 회의에서 나온 말과 섞이지 않게 한다. 웹은 회사 이름 철자를 알려줄 수는 있어도
   그 사람이 무엇을 믿는지는 알려주지 못한다.

## Stage 5 — Index & refresh

Run after every batch of new files (all three are cheap local scripts):

```bash
python3 <skill_dir>/scripts/lexicon.py <corpus_path> apply --apply    # 용어 교정 (Stage 4b)
python3 <skill_dir>/scripts/build_index.py <corpus_path>      # catalog (매칭의 입력)
python3 <skill_dir>/scripts/match_calendar.py <corpus_path> --apply   # 캘린더 있을 때만
python3 <skill_dir>/scripts/build_index.py <corpus_path>      # 바뀐 프론트매터 반영
python3 <skill_dir>/scripts/build_db.py <corpus_path>         # DB incl. person_meetings
python3 <skill_dir>/scripts/build_dossiers.py <corpus_path>   # people/ dossiers + INDEX
python3 <skill_dir>/scripts/build_briefing.py <corpus_path> --meeting <source_id>
```

순서가 곧 의존성이다: 교정은 **본문을 바꾸므로 인덱싱보다 먼저**여야 하고,
`match_calendar.py`는 `_index/catalog.json`을 읽고 프론트매터를 고치므로 **앞뒤로
`build_index.py`가 한 번씩** 필요하다(카탈로그를 만들고, 바뀐 `setting`·참석자를 다시
읽어들이기 위해). 캘린더가 없으면 3·4번째 줄은 건너뛴다. `build_db.py`가
"known misspellings are STILL in the transcripts" WARN을 내면 1번 줄을 건너뛴 것이다.

**Show the briefing — this is the payoff of the sync, not an optional extra.** The user
cannot ask about what they did not notice, so the last step of every sync PUSHES it:
what they promised, what the other side seemed to be after, what went unanswered, who
talked how much, and which open loops with those people are still hanging. Relay it as
it is (it is computed from the DB — do not embellish, and never add a "signal" the
script did not print). For a multi-recording sync, run it per meeting and lead with the
one that has the most open items; for a catch-up, `--days N` gives the digest instead.

Update `_meta/state.json.last_synced`. This keeps the daily loop rewarding: every
sync immediately refreshes each person's 접촉 이력 and the contacts/승격 후보 list —
no Stage 6 required.
