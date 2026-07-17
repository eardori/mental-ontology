# Mental Ontology 🧠

> **회의 녹음만 넣으면, 참석자들의 사고방식(멘탈모델)을 인물·관계·시간축의 지도로 만들고 — 그 데이터에 질문을 던지고, 사업과 전략까지 뽑아내는 도구.**
>
> **Turn meeting recordings into a living map of how people think — then query it, and turn it into business ideas and strategy.**

사람마다 세상을 보는 **프레임(멘탈모델)** 이 있습니다. 회의 녹취를 이 도구에 넣으면 각자의 사고방식을 **객체와 관계의 그래프**로 뽑아냅니다. 그리고 그 데이터는 화면으로 보는 데서 끝나지 않습니다 — **DB로 쌓이고, 질문에 답하고, 전략의 재료가 됩니다.**

리더가 얻는 것: *누구에게 어떤 일을 어떻게 맡길지 · 파트너/투자자와 어떻게 소통할지 · 다음 베팅을 어디에 걸지.*

---

## 🎁 이 리포에 든 것 / What's inside

| 파일 | 용도 |
|---|---|
| `skills/mental-ontology/` | **Claude Code 스킬** — 파이프라인 전체(수집→전사→화자→코퍼스→온톨로지→DB→질문→전략) |
| `INSTALL.md` | Claude가 직접 실행하는 설치 가이드 (한 줄 요청으로 설치) |
| `skills/.../assets/PLAYBOOK.md` | **질문·전략 워크북** — SQL 레시피 + 사업구상/전략 워크플로우 5종 |
| `skills/.../assets/viewer.html` | 시각화 뷰어 — `objects.json` 더블클릭/드래그로 열림 (서버·인터넷 불필요) |
| `skills/.../scripts/` | `build_db.py`(SQLite DB + 화자 별칭 조인 + 접촉 기록) · `build_dossiers.py`(인물 도시에) · `validate.py`(무결성·정직성·인용 접지 검증) · `prepare_synthesis.py`+`merge_ontology.py`(배치 재추출 파이프라인) · `purge_person.py`(인물 일괄 삭제/익명화) · `build_index.py` · `whisper_transcribe.py` · `migrate_objects.py`(v1→v2) |
| `examples/sample-objects.json` | 완성 예시(가상 Acme) — 뷰어로 바로 열어 결과 형태 확인 |
| `tests/run_tests.py` | 자체 테스트 스위트 — 가상 데이터로 파이프라인 전체 검증 (`python3 tests/run_tests.py`) |

---

## 🚀 설치 (2분) / Install

**Claude Code에게 이 한 줄만 말하세요 / Just tell Claude Code:**

> "https://github.com/eardori/mental-ontology 클론해서 INSTALL.md 따라 설치해줘"
>
> "Clone https://github.com/eardori/mental-ontology and follow INSTALL.md to install it."

Claude가 스킬 복사 → Plaud MCP 등록까지 자동 수행. 재시작 후 **"Plaud 로그인해줘"** 한 번이면 끝.
(요구사항: [Claude Code](https://claude.com/claude-code) · Node 20+ · [Plaud](https://www.plaud.ai) 계정 / Requires Claude Code, Node 20+, a Plaud account)

## 🏁 3분 퀵스타트 / Quickstart

설치 후 Claude Code에서 순서대로 말해보세요:

1. **"최근 Plaud 녹음 가져와서 정리해줘"** — 녹음을 가져와 화자를 확인하며 회의록 코퍼스를 만듭니다. (첫 실행 시 코퍼스 저장 위치를 물어봅니다 — Obsidian 볼트 추천)
2. **"온톨로지 분석해줘"** — 멘탈모델 지도 + 뷰어 + 리포트가 생성됩니다.
3. **"X는 어떻게 생각하는 사람이야?"** — 이제 데이터에 질문을 던지세요. 이게 이 도구의 진짜 시작입니다.

> 💡 **여러 회의를 넣을수록** 사람들의 사고가 어떻게 바뀌었는지 **시간축 변화**까지 쌓입니다.

---

## 📊 모은 데이터로 할 수 있는 3가지 / Three things you can do with the data

### ① 보기 (View) — 사고방식 지도

분석이 끝나면 **어떻게 볼지 스킬이 물어봅니다** — 원하는 형태로 골라 받으세요 (전부도 가능):

| 형식 | 파일 | 이럴 때 |
|---|---|---|
| **인터랙티브 HTML 뷰어** | `_ontology/index.html` | 더블클릭 한 번으로 전체 지도 탐색 (모델·관계 그래프·시간축) |
| **md 종합 리포트** | `_ontology/REPORT.md` | Obsidian/Notion에 넣고 읽는 내러티브 보고서 |
| **인물 도시에** | `people/이름.md` | 한 사람의 모든 것 — 접촉 이력·개인 맥락·사고방식·관계·수기 메모(재생성해도 보존). 1:1 전, 위임 전, 피칭 전에 |

### ② 묻기 (Ask) — 회의 전체가 검색 가능한 DB가 됩니다

온톨로지가 갱신될 때마다 **SQLite DB**(`_ontology/ontology.db`)가 만들어집니다 — 모든 회의·발화(전문 검색)·인물·모델·관계·시간축이 테이블로. Claude에게 자연어로 물으면 DB를 조회해 **날짜·실제 발언을 인용하며** 답합니다:

```
"정우진 대표는 어떤 사람이야? 뭘 중요하게 생각해?"
"이 프로젝트, 이서연 님한테 맡겨도 될까?"
"내일 ○○ 대표랑 미팅인데 준비 브리핑 만들어줘"
"우리 조직에서 지금 어디가 안 맞아?"
"'정산' 얘기가 나온 회의 전부 시간순으로 정리해줘"
"지난 분기 동안 내 생각은 어떻게 변했어?"
```

### ③ 구상하기 (Strategize) — 회의 데이터에서 사업과 전략을 뽑아냅니다

`PLAYBOOK.md`의 구조화된 워크플로우 5종 — 각각 **문서 산출물**을 만들어 `_strategy/` 폴더에 쌓습니다:

| 워크플로우 | 이렇게 말하세요 | 산출물 |
|---|---|---|
| **S1 기회 발굴** | "회의 데이터에서 사업 아이디어 찾아줘" | 반복된 pain point → 기회 후보 테이블 + 첫 검증 실험 |
| **S2 전략 옵션** | "유료화 전략 짜줘" | 본인의 실제 프레임에서 출발한 옵션 3개 비교 + pre-mortem |
| **S3 설득 전략** | "투자자 ○○를 설득해야 해" | 상대의 언어로 번역한 논거 + 예상 반론·응답 |
| **S4 정렬 리포트** | "조직 정렬 상태 점검해줘" | 대립(tension)별 상태·방치 비용·개입 제안 |
| **S5 결정 시뮬레이션** | "이 결정하면 리더들이 어떻게 반응할까?" | 인물별 예상 반응(각자의 모델 근거) |

> 전략 산출물에는 항상 정직성 각주가 붙습니다: *데이터는 "사람들이 말한 것"을 보여줄 뿐 시장의 진실이 아닙니다 — 아이디어마다 가장 싼 실전 검증 방법을 함께 제안합니다.*

---

## 🔄 일상 사용 루틴 / Daily routine

```
회의 후:   "새 녹음 정리해줘"            (1분 — 화자 질문은 쓸수록 줄어듭니다)
주 1회:    "온톨로지 업데이트해줘"        (증분 병합 — 시간축이 자랍니다)
필요할 때:  질문 · 미팅 준비 · 전략 워크플로우
월 1회:    "조직 정렬 상태 점검해줘"      (S4 — 대립의 조기 발견)
```

## 🔒 프라이버시 · 매너 / Privacy & etiquette

- **녹음의 적법성은 사용자 책임입니다** (법률 자문 아님): 관할마다 다릅니다 — 예컨대 한국은 본인이 참여한 대화의 녹음은 일반적으로 허용되지만 **제3자 간 대화 녹음은 불법**이고, 미국 일부 주(캘리포니아 등)는 **모든 당사자의 동의**를 요구합니다. 해외 미팅이 많다면 사용 전에 해당 관할의 규정을 확인하세요.
- **로컬 우선**: 코퍼스·DB·뷰어 모두 내 컴퓨터에만. 외부 전송 없음. 민감하면 Whisper 로컬 전사로 녹음도 밖에 안 나갑니다.
- **개인 신상 마스킹**: 지분율·금액·건강·법적 사안은 산출물에서 자동 제외.
- **분석 티 내지 않기**: 방법론 원안자의 조언 — 분석 대상에게 "분석당한다"는 인상을 주지 마세요. 이건 리더 본인의 사적 판단 보조 도구입니다.
- **정직한 근거**: 실제 발언(verbatim)이 있으면 근거 등급이 올라가고, 없으면 "추정"으로 표기합니다. 믿음의 **주체(holder)와 대상(about)을 구분**해서 — "A가 경쟁사 B에 대해 한 말"이 B의 견해로 둔갑하지 않습니다. 조직에 대한 제3자 추정은 등급 상한이 `mid`입니다.
- **검증 내장**: 온톨로지가 갱신될 때마다 `validate.py`가 참조 무결성·근거 규칙·화자 조인 커버리지를 검사하고, 빠진 데이터(파싱 실패·중복 녹음)를 숨기지 않고 보고합니다.

## 💡 팁 / Tips

- 회의록 요약본보다 **원문 녹취**를 넣을수록 정확해집니다.
- 정기 회의를 꾸준히 축적하면 팀 전원의 사고 지도 + 변화 추적이 가능해집니다.
- 투자자·파트너 미팅에도 그대로 — 상대 프레임을 미리 지도로 그려두면 소통이 쉬워집니다.
- 코퍼스를 **Obsidian 볼트**에 두면 회의록을 위키처럼 브라우징할 수 있습니다.

## ❓ FAQ

- **Plaud가 아닌 다른 녹음기여도 되나요?** — 네. 오디오 파일을 주면 Whisper로 로컬 전사합니다(`scripts/whisper_transcribe.py --audio`). Plaud MCP는 자동 수집이 편해질 뿐입니다.
- **영어 회의도 되나요?** — 됩니다. 전사 언어 옵션(`--lang en`)과 온톨로지 추출 모두 다국어.
- **DB는 뭘로 보나요?** — 그냥 Claude에게 물으면 됩니다. 직접 보려면 `sqlite3 ontology.db` 또는 아무 SQLite 뷰어.
- **팀원과 공유해도 되나요?** — 데이터는 민감합니다. 공유 전 반드시 내용 검토를 — 기본은 본인 전용.

## 크레딧 / Credits

- 멘탈모델 온톨로지 방법론 원안: **김태호 (Tab0)** — Mental-model ontology methodology inspired by **Taeho Kim (Tab0)**.
- Recording: [Plaud](https://www.plaud.ai) + [Plaud MCP](https://docs.plaud.ai/plaud-mcp-cli/mcp) · Local transcription: OpenAI Whisper / mlx-whisper.

## License

MIT — see [LICENSE](./LICENSE).
