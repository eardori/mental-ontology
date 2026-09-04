# 설치 가이드 / Install

> **이미 Claude Code를 쓰고 계시다면 두 줄이면 끝납니다:**
>
> ```bash
> claude plugin marketplace add eardori/mental-ontology
> claude plugin install mental-ontology@eardori
> ```
>
> 그리고 Claude Code를 **재시작**하세요. 나머지(Plaud 연결·캘린더·로컬 전사)는 아래에서
> 하나씩. 전부 Claude Code에게 **"INSTALL.md 따라 설치해줘"** 라고 시켜도 됩니다.

---

## 0. 무엇이 필요한가

|                                                                      | 필요한 이유                              | 없으면                                     |
| -------------------------------------------------------------------- | ---------------------------------------- | ------------------------------------------ |
| **Claude 구독** (Pro / Max / Team / Enterprise, 또는 Console 크레딧) | Claude Code 사용에 계정이 필요           | 아무것도 안 됩니다                         |
| **Claude Code** (터미널 앱)                                          | 이 도구는 Claude Code **플러그인**입니다 | 아무것도 안 됩니다                         |
| **Python 3**                                                         | 인덱스·DB·브리핑 스크립트                | 아무것도 안 됩니다 (macOS엔 기본 설치)     |
| **Plaud 계정 + 기기**                                                | 녹음을 자동으로 가져옴                   | 오디오 파일을 직접 넣는 방식으로 사용 가능 |
| **Node 20+**                                                         | Plaud 연결(MCP)이 `npx`로 실행됨         | Plaud 자동 수집만 불가                     |
| 캘린더 (선택)                                                        | 참석자 명단·자리 성격(TPO)               | 화자 질문이 조금 늘어남                    |

확인:

```bash
claude --version   # 없으면 1단계
python3 -V         # 3.x 나오면 OK
node -v            # v20 이상이면 Plaud 연결 가능
```

## 1. Claude Code 설치 (이미 있으면 건너뛰기)

```bash
# macOS / Linux / WSL
curl -fsSL https://claude.ai/install.sh | bash

# 또는 Homebrew
brew install --cask claude-code

# Windows (PowerShell)
irm https://claude.ai/install.ps1 | iex
```

설치 후 터미널에서 `claude` 를 실행하면 브라우저 로그인이 열립니다. Claude 구독 계정으로
로그인하세요. (자세히: <https://code.claude.com/docs/en/quickstart>)

## 2. 이 도구 설치

```bash
claude plugin marketplace add eardori/mental-ontology
claude plugin install mental-ontology@eardori
claude plugin details mental-ontology@eardori   # → Skills (1) mental-ontology 확인
```

**플러그인은 세션이 시작될 때 로드됩니다 — 설치 후 Claude Code를 재시작하세요.**
이후 업데이트는 `claude plugin update mental-ontology@eardori` 한 줄입니다.

<details>
<summary>포크해서 직접 고쳐 쓰려는 경우 (수동 복사)</summary>

```bash
git clone https://github.com/eardori/mental-ontology.git
mkdir -p ~/.claude/skills
cp -R mental-ontology/skills/mental-ontology ~/.claude/skills/mental-ontology
```

⚠️ **플러그인과 수동 복사를 함께 두지 마세요** — 같은 스킬이 두 번 로드됩니다.
플러그인으로 옮길 땐 `rm -rf ~/.claude/skills/mental-ontology` 를 먼저.
</details>

## 3. Plaud 연결 (녹음 자동 수집)

Plaud 앱에서 녹음이 **전사까지 끝난 상태**여야 가져올 수 있습니다(앱에서 동기화가 끝났는지
먼저 확인하세요). 그다음 터미널에서:

```bash
claude mcp add plaud -s user -- npx -y @plaud-ai/mcp@latest
claude mcp list        # → "plaud: ... ✔ Connected"
```

**등록 후 Claude Code를 재시작**하고(새 MCP 도구는 재시작 후 로드됩니다), 세션에서:

> **"Plaud 로그인해줘"**

브라우저 인증 창이 열립니다 — **Authorize 버튼은 본인이 직접 클릭**하세요(Claude는
자격증명을 다루지 않습니다). 한 번 로그인하면 이후로는 유지됩니다.

확인:

> **"최근 Plaud 녹음 목록 보여줘"**

Plaud 없이 쓰려면 이 단계를 건너뛰고, 오디오 파일을 직접 주면 됩니다(5단계 Whisper).

## 4. 캘린더 연결 (선택이지만 권장)

캘린더를 붙이면 **참석자 명단이 화자 추정의 정답지**가 되고("Speaker 2가 누구지"를 추측할
필요가 없어집니다), 그 자리의 성격(TPO: 저녁 식사 자리인지 임원 회의인지)이 발언의 근거
등급 판단에 들어갑니다.

**가장 쉬운 방법 — claude.ai 커넥터:**

1. <https://claude.ai> 로그인 (Claude Code와 **같은 계정**)
2. 설정(Settings) → **커넥터(Connectors)** → **Google Calendar** 연결
3. Claude Code 재시작 후 확인:

```bash
claude mcp list    # → "claude.ai Google Calendar: ... ✔ Connected"
```

다른 캘린더 MCP를 쓰셔도 됩니다 — 일정 목록을 조회할 수 있는 도구면 스킬이 사용합니다.
캘린더가 아예 없어도 파이프라인은 그대로 동작합니다(화자 질문이 조금 늘어날 뿐).

첫 사용 시 스킬이 한 번만 묻습니다: 어떤 캘린더인지, 그리고 **본인 이메일 도메인**
(내부/외부 참석자를 가르는 기준). 답은 `~/.mental-ontology.json`에 저장됩니다.
일정은 `<코퍼스>/_meta/calendar/`에 **로컬 캐시로만** 저장되고 외부로 나가지 않습니다.

## 5. 첫 실행

Claude Code를 아무 폴더에서 실행하고 이렇게 말하세요:

> **"최근 Plaud 녹음 가져와서 정리해줘"**

- 첫 실행 때 **코퍼스(회의록 저장소) 위치**를 묻습니다. 기본은 `~/MeetingCorpus`,
  Obsidian을 쓰신다면 볼트 안 폴더를 추천합니다(회의록이 위키처럼 연결됩니다).
- 녹음마다 **누가 말했는지** 확인하는 질문이 뜹니다. 처음엔 몇 번 물어보지만
  **쓸수록 조용해집니다**(이름·별칭·목소리를 기억합니다).
- 정리가 끝나면 **"놓친 것 브리핑"** 이 바로 나옵니다.

그다음 해볼 것:

> "온톨로지 분석해줘" — 사람들의 사고방식·의도·관계 지도를 만듭니다
> "〈이름〉은 어떤 사람이야?" — 실제 발언을 인용해 답합니다
> "내일 〈이름〉 만나" — 만나기 전 30초 브리핑
> "이번 주 정리해줘" — 미이행 약속·조용해진 관계

## 6. (선택) 전사 안 된 오디오 · 화자 분리

**Whisper — Plaud가 전사하지 못한 원본 오디오나 다른 기기 녹음:**

```bash
pip3 install mlx-whisper        # Apple Silicon Mac
pip3 install openai-whisper     # 그 외
brew install ffmpeg             # macOS  /  apt install ffmpeg  (Linux)
```

**화자 분리 + 목소리 지문 — 여러 명이 나오는 오디오 파일을 자주 넣는 경우:**

```bash
pip3 install sherpa-onnx soundfile numpy scikit-learn
# 모델 2개를 아래 위치에 (환경변수 DIAR_MODELS 로 변경 가능):
#   ~/.cache/mental-ontology/diar-models/sherpa-onnx-pyannote-segmentation-3-0/model.onnx
#   ~/.cache/mental-ontology/diar-models/campplus.onnx
```

한 번 확인한 목소리는 이후 녹음에서 자동으로 이름이 붙습니다. Plaud처럼 화자 라벨이
이미 붙어 오는 소스만 쓴다면 필요 없습니다. 목소리 데이터는 생체정보라
`<코퍼스>/_meta/voiceprints.json`에만 저장되고, `voiceprint.py <코퍼스> forget --name X --apply`
로 지울 수 있습니다.

지금 설치하지 않아도 됩니다 — 필요해지면 스킬이 안내합니다.

---

## 문제 해결

| 증상                         | 원인과 해결                                                                                                            |
| ---------------------------- | ---------------------------------------------------------------------------------------------------------------------- |
| 스킬이 반응하지 않음         | 플러그인은 **세션 시작 때** 로드됩니다. Claude Code를 재시작하세요. `claude plugin list` 로 `✔ enabled` 확인           |
| `claude mcp add plaud` 실패  | Node 20+ 필요 (`node -v`). `brew install node` 후 재시도                                                               |
| `plaud: ✘ Failed to connect` | 재시작했는지, 그리고 세션에서 **"Plaud 로그인해줘"** 로 인증했는지 확인                                                |
| 녹음 목록이 비어 있음        | Plaud 앱에서 **전사가 끝났는지** 확인(앱 동기화가 먼저)                                                                |
| 화자 질문이 너무 많음        | 정상입니다 — 초반뿐입니다. 사람 이름을 한 번 확정하면 별칭·목소리로 기억합니다. 밀린 건 **"화자 정리해줘"** 로 한 번에 |
| 캘린더가 안 잡힘             | 같은 계정으로 claude.ai에 로그인했는지, 커넥터를 연결했는지, 재시작했는지 (`claude mcp list`로 확인)                   |
| 결과가 빈약함                | 회의가 10건 미만이면 원래 얇습니다. 쌓일수록 좋아집니다                                                                |

## 업그레이드

```bash
claude plugin update mental-ontology@eardori
```

기존 코퍼스가 있다면 업그레이드 후 한 번은 Claude Code에서 **"인덱스랑 DB 다시 만들어줘"**
라고 하세요 — DB는 파생물이라 새 항목(대화 의도·TPO 등)을 담으려면 다시 만들어야 합니다.
변경 내역은 [CHANGELOG.md](./CHANGELOG.md).

## 제거

```bash
claude plugin uninstall mental-ontology@eardori
claude plugin marketplace remove eardori
claude mcp remove plaud -s user
rm ~/.mental-ontology.json          # 설정 (선택)
```

코퍼스 폴더는 **본인 데이터**라 자동으로 지우지 않습니다 — 직접 판단해 보관/삭제하세요
(특히 `_meta/voiceprints.json`은 생체정보, `_meta/calendar/`는 일정 캐시입니다).
