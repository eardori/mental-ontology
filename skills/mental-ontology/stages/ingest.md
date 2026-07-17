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

## Stage 2 — Whisper transcription (raw audio)

Only for recordings with no Plaud transcript.

1. **Critical: presigned URLs expire within seconds–minutes.** Call `get_file(file_id)` to obtain `presigned_url`, then **immediately** run the download in the very next tool call. Never batch-fetch URLs first.
2. Use the bundled script (handles download, validation, and transcription):
   ```bash
   python3 <skill_dir>/scripts/whisper_transcribe.py --url "<presigned_url>" --id <file_id> --out <corpus>/_whisper [--lang ko]
   ```
   - It validates the download (≥1MB, not an XML `ExpiredToken` error), picks `mlx_whisper` on Apple Silicon or `openai-whisper` elsewhere, and writes `<corpus>/_whisper/<id>.json` (`{id, text, segments:[{start,text}]}`).
   - If neither whisper package is installed, the script prints install hints (`pip3 install mlx-whisper` on Apple Silicon, else `pip3 install openai-whisper`). Offer to install for the user.
3. Long audio takes real time (roughly 5–7× realtime on Apple Silicon). For multiple files, run sequentially in the background and continue other work; warn the user that closing the laptop lid pauses transcription (finished files are skipped on rerun — safe to resume).
4. Whisper output has **no speaker separation** — note `transcribed_by: whisper` in the frontmatter and still attempt Stage 3 from context clues (self-introductions, names being addressed).

## Stage 3 — Speaker attribution (interactive, learning)

Goal: replace "Speaker 1/2" and misattributed labels with real names, learning over time.

1. Load `_meta/speakers.json` — this is the **person registry**, not just an STT map: `[{name, role, org, aliases[], traits, meetings:[dates], tier, first_met_context, intro_by, personal[]}]`. Create if missing.
   - `tier`: `core` (deep mental-model analysis) / `acquaintance` (light dossier) / `contact` (name + meetings only). New confirmed speakers default to `acquaintance`; promote to `core` when the user starts asking about how they think.
   - `first_met_context` ("스타트업얼라이언스 행사에서"), `intro_by` (who introduced them) — capture when the transcript or the user reveals it; this is네트워커의 핵심 자산.
   - `personal[]`: dated personal-context notes (`{"date","note"}`) — see the privacy policy below for when to record these.
2. For each distinct speaker label in the transcript, infer candidates from:
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

**Token economy rule: format the transcript body with a python script — never have the LLM rewrite or re-emit the transcript.** The LLM decides only: title, category, summary, speaker mapping, light global fixes (recurring proper-noun STT errors as find→replace pairs), and whether to split.

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
   transcribed_by: plaud | whisper
   part: "1/2"            # only when split
   ---

   # <title>

   ## 요약 / Summary
   <3–6 lines; use get_note if available>

   ## 액션아이템 / Action items
   - [ ] (요청자→담당자) 내용 (기한: YYYY-MM-DD)     # 화살표·기한은 알 수 있을 때만

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

## Stage 5 — Index & refresh

Run after every batch of new files (all three are cheap local scripts):

```bash
python3 <skill_dir>/scripts/build_index.py <corpus_path>      # catalog + INDEX.md
python3 <skill_dir>/scripts/build_db.py <corpus_path>         # DB incl. person_meetings
python3 <skill_dir>/scripts/build_dossiers.py <corpus_path>   # people/ dossiers + INDEX
```

Update `_meta/state.json.last_synced`. This keeps the daily loop rewarding: every
sync immediately refreshes each person's 접촉 이력 and the contacts/승격 후보 list —
no Stage 6 required.
