# INSTALL — Claude가 직접 실행하는 설치 가이드 / Self-install guide for Claude

> **사용자님께**: Claude Code에서 이렇게 말하면 끝입니다 —
> **"https://github.com/eardori/mental-ontology 클론해서 INSTALL.md 따라 설치해줘"**
>
> **To the user**: In Claude Code, just say —
> **"Clone https://github.com/eardori/mental-ontology and follow INSTALL.md to install it."**

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

```bash
mkdir -p ~/.claude/skills
cp -R <repo>/skills/mental-ontology ~/.claude/skills/mental-ontology
ls ~/.claude/skills/mental-ontology   # SKILL.md, assets/, scripts/ 확인
```

이미 존재하면 사용자에게 덮어쓸지 확인 후 진행. / If it already exists, ask the user before overwriting.

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

### 6. Verify / 검증

재시작된 세션에서 사용자에게 이렇게 시켜보라고 안내:
In the restarted session, have the user try:

> "최근 Plaud 녹음 목록 보여줘" / "List my recent Plaud recordings"

첫 실행 시 스킬이 코퍼스 저장 위치를 묻는다(기본 `~/MeetingCorpus`, Obsidian 볼트 추천).
On first run the skill asks where to keep the corpus (default `~/MeetingCorpus`; an Obsidian vault works great).

---

## Uninstall / 제거

```bash
rm -rf ~/.claude/skills/mental-ontology
claude mcp remove plaud -s user
rm ~/.mental-ontology.json          # config (선택)
# corpus 폴더는 사용자 데이터 — 직접 판단해 보관/삭제
```
