# Mental Ontology 🧠

**회의 녹음만 쌓으면, 함께 일하는 사람들의 '사고방식 지도'가 만들어집니다.**
**Turn your meeting recordings into a living map of how the people around you think.**

Plaud 녹음 → 전사 → 화자 확인 → 정제된 회의록 코퍼스 → **멘탈모델 온톨로지** (누가 어떤 믿음과 판단 기준으로 움직이는지, 누가 누구와 어디서 부딪히는지, 시간에 따라 생각이 어떻게 변하는지)를 Claude Code 스킬 하나로.

A single Claude Code skill that takes you from Plaud voice recordings to a **mental-model ontology**: each person's beliefs and decision criteria, where people agree and clash, and how thinking evolves over time.

---

## 왜 이게 유용한가 / Why

사람마다 세상을 보는 **프레임(멘탈모델)** 이 있습니다. 리더가 그것을 알면 —
- **위임이 정확해집니다**: 사람의 사고방식에 맞는 일을 맡기면 성공이 빨라집니다.
- **정렬 포인트가 보입니다**: 회의 속 대립(tension)이야말로 조직 정렬의 핵심 신호입니다.
- **파트너·투자자 소통이 쉬워집니다**: 상대의 프레임을 미리 지도로 그려두면 됩니다.

Everyone operates on **frames (mental models)**. When a leader can see them: delegation fits the person, the real alignment gaps (tensions) surface, and partner/investor conversations start from the other side's frame.

## 무엇이 만들어지나 / What you get

| 산출물 / Output | 설명 / Description |
|---|---|
| `transcripts/` | 정제된 회의록 md 코퍼스 (프론트매터·요약·화자별 타임스탬프) / clean meeting markdown corpus |
| `_index/` | 카테고리·월별 인덱스 + 기계용 카탈로그 / human & machine index |
| `_meta/speakers.json` | **화자 프로필 누적 학습** — 쓸수록 질문이 줄어듭니다 / learning speaker profiles |
| `_ontology/objects.json` | 인물·멘탈모델·관계·시간축 데이터 / people, models, relations, timeline |
| `_ontology/index.html` | 더블클릭으로 열리는 시각화 뷰어 (서버·인터넷 불필요) / self-contained viewer |
| `_ontology/REPORT.md` | 경영자용 내러티브 리포트 / executive narrative report |

## 설치 / Install (2 minutes)

**Claude Code에게 이 한 줄만 말하세요 / Just tell Claude Code:**

> "https://github.com/eardori/mental-ontology 클론해서 INSTALL.md 따라 설치해줘"
>
> "Clone https://github.com/eardori/mental-ontology and follow INSTALL.md to install it."

Claude가 스킬 복사 → Plaud MCP 등록까지 알아서 합니다. 재시작 후 "Plaud 로그인해줘"라고 하면 브라우저 인증 한 번으로 끝. (요구사항: [Claude Code](https://claude.com/claude-code), Node 20+, [Plaud](https://www.plaud.ai) 계정)

Claude copies the skill and registers the Plaud MCP for you. After a restart, say "Log me into Plaud" — one browser authorization and you're done. (Requires Claude Code, Node 20+, a Plaud account.)

## 사용법 / Usage

설치 후 Claude Code에서 자연어로 / After install, just talk to Claude Code:

```
"최근 Plaud 녹음 가져와서 정리해줘"          # fetch & clean recent recordings
"이번 달 회의 다 코퍼스에 추가해줘"            # sync this month into the corpus
"온톨로지 분석해줘"                         # build/update the ontology
"우리 팀 리더들 사고방식 어떻게 달라?"        # ask questions over the ontology
```

파이프라인 / The pipeline:

```
Plaud 녹음 → ① 전사 가져오기 (없으면 ② 로컬 Whisper 전사)
          → ③ 화자 확인 (맥락으로 후보 추론 → 사용자 선택 → 프로필 학습)
          → ④ 정제 md 저장 → ⑤ 인덱스 → ⑥ 멘탈모델 온톨로지 + 뷰어 + 리포트
```

- **화자 학습**: 처음엔 "Speaker 2가 누구인가요?"를 몇 번 묻지만, `speakers.json`에 프로필이 쌓이면 점점 조용해집니다.
- **증분 분석**: 회의를 더 넣을수록 온톨로지가 풍부해지고 시간축(생각의 변화)이 쌓입니다.
- **Speaker learning**: a few questions at first; the profile makes future runs quieter.
- **Incremental**: more meetings → richer ontology and a longer thinking-evolution timeline.

## 프라이버시 / Privacy

- **모든 데이터는 로컬**에 저장됩니다 (코퍼스 폴더 또는 Obsidian 볼트). 외부 전송 없음.
- 지분·금액·개인 신상 등 민감 정보는 온톨로지 산출물에서 **자동 마스킹**합니다.
- 이 도구는 리더 본인의 **사적인 판단 보조 도구**입니다 — 분석 대상에게 "분석당한다"는 인상을 주지 않도록 산출물 공유에 주의하세요.
- All data stays **local** (your corpus folder / Obsidian vault). Sensitive details (equity, amounts, personal matters) are **masked** in ontology outputs. Treat results as a private judgment aid — be discreet.

## 크레딧 / Credits

- 멘탈모델 온톨로지 방법론 원안: **김태호 (Tab0)** — 회의록·문서·대화에서 사람들의 사고방식을 객체와 관계의 그래프로 추출한다는 아이디어.
- Mental-model ontology methodology inspired by **Taeho Kim (Tab0)**.
- Recording & transcription: [Plaud](https://www.plaud.ai) + [Plaud MCP](https://docs.plaud.ai/plaud-mcp-cli/mcp). Local transcription: OpenAI Whisper / mlx-whisper.

## License

MIT — see [LICENSE](./LICENSE).
