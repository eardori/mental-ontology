# INSTALL — Claude가 직접 실행하는 설치 가이드 / Self-install guide for Claude

> **가장 빠른 길 / Fastest path** — 터미널에 두 줄:
>
> ```bash
> claude plugin marketplace add eardori/mental-ontology
> claude plugin install mental-ontology@eardori
> ```
>
> 아래 가이드는 Plaud·Whisper·캘린더까지 포함한 전체 설치입니다. Claude Code에게
> **"INSTALL.md 따라 설치해줘"** 라고 시키면 순서대로 진행합니다.

---

## Claude: follow these steps in order / Claude는 아래를 순서대로 실행

### 0. Prerequisites check / 사전 확인

```bash
node -v        # need v20+  (Plaud MCP requirement)
claude -v      # Claude Code CLI
python3 -V     # for index/whisper scripts
```

- Node가 v20 미만이거나 없으면: 사용자에게 Node 20+ 설치를 안내 (e.g. `brew install node`).
- If Node < 20 or missing: guide the user to install Node 20+ first.

### 1. Clone (if not already cloned) / 클론

```bash
git clone https://github.com/eardori/mental-ontology.git /tmp/mental-ontology-install
```

이미 클론된 폴더에서 실행 중이면 이 단계는 건너뛴다. / Skip if already inside the cloned repo.

### 2. Install the skill / 스킬 설치

**방법 A — 플러그인 (권장, 클론 불필요)**

```bash
claude plugin marketplace add eardori/mental-ontology
claude plugin install mental-ontology@eardori
claude plugin details mental-ontology@eardori   # Skills (1) mental-ontology 확인
```

이후 업데이트는 `claude plugin update mental-ontology@eardori` 한 줄. 1단계(클론)도 필요 없다.

**방법 B — 수동 복사 (포크해서 고쳐 쓰는 경우)**

```bash
mkdir -p ~/.claude/skills
cp -R <repo>/skills/mental-ontology ~/.claude/skills/mental-ontology
ls ~/.claude/skills/mental-ontology   # SKILL.md, stages/, assets/, scripts/ 확인
```

이미 존재하면 사용자에게 덮어쓸지 확인 후 진행. / If it already exists, ask the user before overwriting.

> ⚠️ **둘 다 하지 말 것.** 플러그인과 `~/.claude/skills/` 복사본이 함께 있으면 같은 스킬이
> 두 번 로드된다. 방법 A로 옮길 때는 `rm -rf ~/.claude/skills/mental-ontology` 를 먼저.

### 3. Register the Plaud MCP server / Plaud MCP 등록

```bash
claude mcp add plaud -s user -- npx -y @plaud-ai/mcp@latest
claude mcp list   # → "plaud: ... ✔ Connected" 확인
```

### 4. Restart & login / 재시작과 로그인

새 MCP 툴은 **세션 재시작 후** 로드된다. 사용자에게 안내하라:
New MCP tools load only after a session restart. Tell the user:

1. 현재 세션을 재시작: `claude --continue` (맥락 유지 재개) / restart with `claude --continue`
2. 재시작 후 **"Plaud 로그인해줘" / "Log me into Plaud"** 라고 말하면 브라우저 인증이 열림 —
   **Authorize는 사용자가 직접 클릭** (Claude는 자격증명을 다루지 않는다).

### 4b. (Optional) Calendar MCP / 캘린더 연동 (선택, 강력 추천)

캘린더를 붙이면 **참석자 명단이 화자 추정의 정답지**가 되고, 그 자리의 성격(TPO)이
근거 등급 판단에 들어간다. 사용자의 캘린더 MCP(예: Google Calendar 커넥터)가 이미
붙어 있으면 스킬이 알아서 쓴다 — 없으면 이 단계는 건너뛴다(캘린더는 선택이며,
없다고 파이프라인이 막히지 않는다).

첫 사용 시 스킬이 한 번만 묻는다: 어떤 캘린더인지, 그리고 **내 이메일 도메인**
(내부/외부 참석자를 가르는 기준). 답은 `~/.mental-ontology.json`에 저장된다.
일정은 `<corpus>/_meta/calendar/`에 로컬 캐시로만 저장된다.

### 5. (Optional) Whisper for raw audio / 미전사 녹음용 Whisper (선택)

Plaud가 전사하지 못한 원본 오디오를 로컬 전사하려면 (Apple Silicon Mac 권장):

```bash
# Apple Silicon Mac:
pip3 install mlx-whisper
# Other platforms:
pip3 install openai-whisper
# both need ffmpeg:
brew install ffmpeg   # macOS  /  apt install ffmpeg  # Linux
```

지금 설치하지 않아도 된다 — 필요해지면 스킬이 안내한다. / Can be deferred; the skill will prompt when needed.

### 5b. (Optional) 화자 분리 + 목소리 지문 / Diarization + voiceprints (선택)

여러 사람이 나오는 **오디오 파일**을 자주 넣는다면(식사·통화·잡담 녹음), 로컬 화자 분리와
목소리 지문을 켜두는 게 좋다 — 한 번 확인한 사람은 이후 녹음에서 자동으로 이름이 붙는다.

```bash
pip3 install sherpa-onnx soundfile numpy scikit-learn
# 모델 2개를 아래 디렉터리에 배치 (env DIAR_MODELS 로 위치 변경 가능):
#   ~/.cache/mental-ontology/diar-models/sherpa-onnx-pyannote-segmentation-3-0/model.onnx
#   ~/.cache/mental-ontology/diar-models/campplus.onnx
```

Plaud처럼 화자 라벨이 이미 붙어 오는 소스만 쓴다면 필요 없다.
목소리 데이터는 생체정보라 `<corpus>/_meta/voiceprints.json`에만 저장되고,
`purge_person.py` 또는 `voiceprint.py <corpus> forget --name X --apply`로 지운다.

### 6. Verify / 검증

스크립트 파이프라인 자체 점검 (선택, 가상 데이터만 사용):
Optional self-check of the script pipeline (fictional data only):

```bash
python3 <repo>/tests/run_tests.py   # PASS: N passed, 0 failed 확인
```

재시작된 세션에서 사용자에게 이렇게 시켜보라고 안내:
In the restarted session, have the user try:

> "최근 Plaud 녹음 목록 보여줘" / "List my recent Plaud recordings"

첫 실행 시 스킬이 코퍼스 저장 위치를 묻는다(기본 `~/MeetingCorpus`, Obsidian 볼트 추천).
On first run the skill asks where to keep the corpus (default `~/MeetingCorpus`; an Obsidian vault works great).

온톨로지까지 만든 뒤에는 데이터에 바로 질문할 수 있다 (DB는 자동 생성 — sqlite3는 파이썬 내장이라 추가 설치 없음):
Once the ontology exists you can query it directly (the DB is built automatically — sqlite3 ships with Python):

> "X는 어떻게 생각하는 사람이야?" / "회의 데이터에서 사업 아이디어 찾아줘"

---

## Uninstall / 제거

```bash
claude plugin uninstall mental-ontology@eardori   # 플러그인으로 설치한 경우
rm -rf ~/.claude/skills/mental-ontology           # 수동 복사한 경우
claude mcp remove plaud -s user
rm ~/.mental-ontology.json          # config (선택)
# corpus 폴더는 사용자 데이터 — 직접 판단해 보관/삭제
#   (특히 _meta/voiceprints.json 은 생체정보, _meta/calendar/ 는 일정 캐시)
```

## Upgrade / 업그레이드

**플러그인으로 설치했다면** 한 줄이다:

```bash
claude plugin update mental-ontology@eardori
```

**수동 복사로 설치했다면** 리포를 당겨받은 뒤 다시 복사해야 반영된다:

```bash
git -C <repo> pull
rm -rf ~/.claude/skills/mental-ontology
cp -R <repo>/skills/mental-ontology ~/.claude/skills/mental-ontology
python3 <repo>/tests/run_tests.py     # PASS 확인
```

**업그레이드 후 기존 코퍼스에서 한 번은 반드시**: `build_index.py` → `build_db.py` →
`build_dossiers.py`. DB는 파생물이라 새 스키마(예: v2.0의 대화 의도·TPO 컬럼)를 담으려면
다시 만들어야 한다. 변경 내역은 [CHANGELOG.md](./CHANGELOG.md).
