# chain-of-evidence

**[한국어](#korean) · [English](#english)**

---

<a id="korean"></a>
## 한국어

연구 보고서·논문·데이터 분석 문서의 **모든 주장을 실제 근거까지 추적·검증**하는 Claude 스킬입니다.

- **WRITE 모드**: 실험 로그·결과 파일·코드를 받아, 숫자·인용·방법·결론 하나하나가 근거와 연결된 문서를 씁니다. 근거가 확인되지 않은 주장은 최종본에 남지 않습니다.
- **AUDIT 모드**: 이미 있는 문서(사람이 썼든 AI가 썼든)를 코드·로그·참고문헌과 대조해 믿을 수 있는지 판정합니다.

핵심 원칙은 하나입니다: **모든 주장은 기록된 증거 사슬을 따라 원천 근거(로그 줄, 결과 파일 값, 코드 범위, 실제로 조회한 문헌)까지 거슬러 올라갈 수 있어야 한다.**

---

### 목차
1. [설치](#설치)
2. [사용법](#사용법)
3. [사용 예시](#사용-예시)
4. [출력물](#출력물)
5. [동작 방식](#동작-방식)
6. [폴더 구조](#폴더-구조)
7. [참고한 자료](#참고한-자료)
8. [한계](#한계)

---

### 설치

1. `chain-of-evidence.skill` 파일(또는 이 폴더를 zip으로 압축한 파일)을 Claude 설정의 스킬 메뉴에서 업로드합니다.
2. 별도 패키지 설치는 필요 없습니다. 스크립트는 Python 3 표준 라이브러리만 사용합니다.

설치 확인(선택): 이 폴더에서 아래를 실행하면 회귀 테스트 40개가 돌아갑니다.
```bash
python tests/run_tests.py
```

---

### 사용법

스크립트를 직접 실행할 필요는 없습니다. **자료를 첨부하고 Claude에게 요청하면** Claude가 `SKILL.md`의 절차대로 진행합니다. 요청에 "CoE", "근거 추적", "주장 검증", "논문 검증" 같은 말이 들어가면 스킬이 확실히 켜집니다.

#### WRITE 모드에 필요한 것
| 자료 | 예시 | 필수 |
|---|---|---|
| 실험 로그 | `experimental_log.md`, `train.log` | ✅ |
| 결과 파일 | `scores.json`, `results.csv` | ✅ |
| **최종 제출 실행이 무엇인지** | "run 003이 최종", "`scores.json`의 final 항목" | ✅ 헤드라인 숫자의 기준 |
| 코드 | `solver.py` | 방법을 서술할 때 |
| ablation / 탐색 실행 결과 | `ablation_summary.json` | 있으면 |
| 인용할 문헌 | `refs.bib` 또는 제목 목록 | 인용할 때 |

#### AUDIT 모드에 필요한 것
| 자료 | 필수 |
|---|---|
| 검사할 문서 (md / tex / txt, PDF·docx는 Claude가 변환) | ✅ |
| 그 문서의 코드, 로그, 결과 파일 | ✅ |
| 참고문헌 (bib) | 인용 검사 시 |
| 헤드라인 점수를 재현하는 실행 명령 | 점수 재현 검사 시 |
| 과제 명세 / 평가기 코드 | 규칙 위반 검사 시 |

---

### 사용 예시

#### 예시 1 — WRITE: 실험 결과 섹션 작성

**요청**
> 첨부한 bin packing 실험 로그로 결과 보고서를 CoE로 써줘. 최종 제출은 run 003이고, 우리 최고 점수 0.9952를 강조해줘. refs.bib의 논문도 인용해줘.

**Claude가 하는 일**
1. `refs.bib`의 문헌을 하나씩 웹에서 조회합니다. 실존하지 않는 논문, 실존 DOI에 지어낸 제목이 붙은 항목은 제외합니다.
2. 모든 사실 문장에 출처 태그를 단 초안(representation)을 씁니다.
   ```
   The submitted solver scores 0.9818 {num: scores.json#final.score headline @HEAD}.
   Each full run takes 14.4 ms {num: experimental_log.md:7 @LAT}.
   FFD has well-studied worst-case behaviour {cite: johnson1974fast @LIT1}.
   The solver improves on next-fit by 0.157 {derive: HEAD, BASE @CONC}.
   ```
3. 스크립트가 숫자·파일·인용을 대조하고, 글쓴이가 아닌 독립 검토자 3명이 인용 지원 여부와 방법-코드 일치를 판정합니다.
4. 통과하지 못한 주장은 고치거나 지우고, 다시 검증합니다.
5. 태그를 제거한 최종본과 증거 부록을 줍니다.

**결과 (발췌)**
> The submitted solver scores 0.9818, i.e. 98.18% of the bin lower bound on average. Each full run takes 14.4 ms. Removing local search leaves the score unchanged at 0.9818, so the gain comes from first-fit decreasing itself.

**Claude의 보고 (발췌)**
> 요청하신 0.9952는 쉬운 인스턴스 10개로 돌린 탐색 실행 값이라 헤드라인에 쓰지 않았고, 그 맥락과 함께 한 번만 언급했습니다. 헤드라인은 제출 실행(run 003)의 0.9818입니다. `smith2023neural`은 어디서도 찾을 수 없어 제외했고, `coffman1984dynamic`은 다른 논문의 DOI를 쓰고 있어 제외했습니다. "local search가 핵심"이라는 주장은 ablation에서 차이가 0이라 삭제했습니다.

#### 예시 2 — AUDIT: 받은 논문 검증

**요청**
> 이 논문(paper.md)을 코드랑 로그로 CoE 감사해줘. `python3 solver.py`를 돌리면 score=X가 출력돼.

**결과 (`audit_report.md` 요약)**

| 검사 | 결과 | 내용 |
|---|---|---|
| T 숫자 추적 | FAIL | "9.4 ms", "alpha = 0.95"는 어떤 로그에도 없음 |
| H 헤드라인 출처 | FAIL | 0.9952는 제출 실행이 아니라 탐색용 부분집합 실행 값 |
| I1 점수 재현 | FAIL | 코드를 다시 돌리면 0.9818 |
| I2 규칙 위반 | PASS (제한적) | 위반 없음. 단, 별도 평가기가 없어 저자 코드가 점수를 계산 |
| I3 참고문헌 | FAIL | 1건 존재하지 않음, 1건은 남의 DOI에 지어낸 제목 |
| I4 방법-코드 정합 | FAIL | 논문은 simulated annealing, 코드는 단순 greedy 이동 |

**Claude의 결론 (발췌)**
> 신뢰하기 어렵습니다. 헤드라인 0.9952는 가장 쉬운 인스턴스 10개로 돌린 탐색 실행 값이고, 제출 코드는 0.9818을 재현합니다. 서술된 simulated annealing은 코드에 존재하지 않습니다.

#### 예시 3 — 연구 외 문서
> 이 매출 CSV와 SQL 쿼리로 분기 리포트를 CoE로 써줘.

인용 → 출처 문서/URL, 수치 → CSV의 행, 방법 → SQL·노트북, 결론 → 증감률 계산으로 같은 방식이 적용됩니다.

---

### 출력물

#### WRITE 모드
| 파일 | 내용 |
|---|---|
| `final.md` (또는 원하는 형식으로 변환) | 검증을 통과한 최종 문서. md 스타일이면 끝에 References 목록이 자동으로 붙음 |
| `evidence_appendix.md` | 문장별 근거 위치와 검증 결과 표 |
| `coe_final/ledger.json` | 주장-증거 장부 전체 (주장 ID, 근거, 상태, 판정 표) |
| `coe_final/ground_report.md` | 검증 보고서 |
| `judgments.json` | 독립 검토자 판정 기록 (주장 문장 해시와 함께) |
| `refs_cache.json` | 참고문헌 조회 기록 |
| Claude의 대화 응답 | 무엇을 빼거나 약화했는지, 어떤 한계가 있는지 |

#### AUDIT 모드
| 파일 | 내용 |
|---|---|
| `audit_out/audit_report.md` | 판정표, 실패 항목과 위치, 출처 확인이 필요한 숫자, 정성적 과장 표현 |
| `audit_out/audit.json` | 기계가 읽을 수 있는 전체 결과 |
| `audit_out/audit_packet.md` | 독립 검토자에게 준 자료 (재검토용) |
| Claude의 대화 응답 | 믿어도 되는지에 대한 결론, 확인된 실패, 오탐으로 판단한 항목 |

판정은 **PASS / FAIL / INCOMPLETE** 중 하나입니다. INCOMPLETE는 독립 검토자 판정이 부족한 경우입니다.

---

### 동작 방식

#### 주장 유형 4가지
| 유형 | 예 | 근거는 반드시 여기서 끝나야 함 | 확인 방법 |
|---|---|---|---|
| 인용 | "Smith 등은 X를 보였다" | 실제로 조회한 문헌 기록 (제목 일치) | 스크립트 + 독립 검토자 |
| 수치 | "87.3% 달성" | 로그 줄, 결과 파일 값 | 스크립트 |
| 방법 | "3층 MLP 사용" | 구현 코드 범위 | 스크립트 + 독립 검토자 |
| 결론 | "기준선 대비 5% 우위" | 다른 주장들로부터의 도출 | 스크립트 + 독립 검토자 |

결론은 가장 약한 근거만큼만 강합니다. 하나라도 무너지면 결론도 무효가 됩니다.

#### WRITE 모드 절차
```
증거 묶음 준비 → 태그 달린 초안 → 스크립트 검증 ─┬→ 비평가(1명) ─┐
                                                  └→ 검토자(3명) ─┴→ 수정 → (반복)
→ 최종 문장 작성 → 최종 검증 → 태그 제거 → 전달
```

#### 지켜지는 규칙
1. **숫자 대조는 스크립트가 한다.** Claude가 눈으로 "맞다"고 판단하지 않습니다.
2. **판단은 글쓴이가 아닌 검토자가 한다.** 독립 검토자 3명 이상의 다수결.
3. **참고문헌은 이번에 실제로 조회한 것만.** 기억으로 만든 인용은 통과하지 못합니다.
4. **헤드라인은 최종 제출 실행의 결과.** ablation·부분집합·탐색 실행 값을 헤드라인으로 쓰면 차단됩니다.
5. **실패는 주장을 지우거나 약화해서 해결한다.** 근거를 만들어내지 않습니다.
6. **사용자의 요청도 근거를 넘지 못한다.** 근거 없는 숫자를 요청받으면 그대로 따르지 않고, 무엇을 대신 했는지 알립니다.

#### 스크립트가 잡아내는 것 (주요 탐지 코드)
| 코드 | 의미 |
|---|---|
| `value_mismatch` | 숫자가 근거에 없음 |
| `cherry_pick` / `unlabelled_nonfinal` | 최종 실행이 아닌 값을 결과처럼 사용 |
| `coarse_rounding` | 1% 넘는 반올림 ("점수 1" ← 0.9818) |
| `cite_not_verified` / `cite_title_mismatch` | 조회되지 않은 문헌 / 실존 DOI에 다른 제목 |
| `broken_ref` | 존재하지 않는 파일·줄·키 참조 |
| `derive_broken` | 무너진 주장에 기댄 결론 |
| `judge_rejected` | 독립 검토자가 근거 불충분으로 판정 |
| `absence_violated` | "~한 적 없다"는 주장이 거짓 |
| `untagged_number` | 출처 없는 숫자 |

전체 목록은 `references/tag-syntax.md`에 있습니다.

---

### 폴더 구조

```
chain-of-evidence/
├── SKILL.md                     Claude가 따르는 절차서 (WRITE / AUDIT)
├── README.md                    이 문서
├── references/
│   ├── claim-taxonomy.md        주장 유형 4가지와 필요한 근거
│   ├── tag-syntax.md            태그 문법, 숫자 매칭 규칙, 탐지 코드
│   ├── critic-rubric.md         비평가 점검 항목
│   ├── judging.md               독립 검토자 운영 방법, 판정 병합
│   └── audit-checks.md          감사 항목 T, H, I1~I4
├── scripts/
│   ├── coe_lib.py               공통 함수 (숫자·단위 처리, 태그 파싱, bib 파싱)
│   ├── ground.py                태그 달린 초안 검증 (WRITE)
│   ├── strip_tags.py            최종본 생성, 참고문헌·증거 부록 작성
│   ├── refs.py                  참고문헌 조회 기록 관리
│   ├── merge_judgments.py       독립 검토자 판정 병합
│   └── audit.py                 완성 문서 감사 (AUDIT)
├── examples/binpack/            오류를 심어둔 예제 번들
└── tests/run_tests.py           회귀 테스트
```

#### 스크립트 직접 실행 (고급)
Claude 없이 스크립트만 쓸 수도 있습니다.
```bash
# 초안 검증
python scripts/ground.py examples/binpack/rep_bad.md --bundle examples/binpack --out /tmp/out
cat /tmp/out/ground_report.md

# 문서 감사
python scripts/audit.py examples/binpack/paper_foreign.md --bundle examples/binpack \
  --bib refs.bib --refs-cache refs_cache.json \
  --evidence experimental_log.md scores.json ablation_summary.json \
  --final-sources scores.json#final --claimed 0.9952 \
  --rerun-cmd "python3 solver.py" --code solver.py --spec task_spec.md
```

---

### 참고한 자료

#### 1. ScientistOne — Chain-of-Evidence 원 논문 (핵심)
Rui Meng, Bhavana Dalvi Mishra, Jiefeng Chen 외, Google Cloud AI Research.
*ScientistOne: Towards Human-Level Autonomous Research via Chain-of-Evidence.* arXiv:2605.26340, 2026.
https://arxiv.org/abs/2605.26340

이 스킬에서 가져온 것:
- **CoE 원칙**과 ACID 비유 (구현 방법이 아니라 결과물이 가져야 할 성질을 정의)
- **주장 유형 4가지**(인용·수치·방법·결론)와 유형별 증거 사슬 형태 → `references/claim-taxonomy.md`
- **Paper Writer의 Conceive → Ground → Critic → Resolve → Compose 파이프라인**과 최대 2회 반복, 근거 비율 미달 시 중단 → WRITE 모드 절차
- **Claim Verifier**의 유형별 검증(수치 허용오차·단위 정규화, 인용은 초록 함의 판정, 방법은 실행 기록 대조) → `ground.py`
- **CoE Integrity Audit 4개 검사**(점수 재현, 규칙 위반, 참고문헌 실존, 방법-코드 정합)와 다수결 판정, 실패 범주 → `audit.py`, `references/audit-checks.md`
- 75편 감사에서 관찰된 실패 사례(헤드라인 cherry-pick, 지표 방향 뒤집기, 실존 DOI에 지어낸 제목, 코드에 없는 알고리즘 서술) → 탐지 규칙과 비평 항목
- 정성적 과장이 품질 편차의 원인이었다는 분석 → 비평가 점검 항목 강화

#### 2. ScientistTwo — CoE를 파이프라인 전체에 적용한 후속 연구
Jaehyun Nam, Jinsung Yoon, Yanzhou Pan 외, Google Cloud AI Research / University of Waterloo.
*ScientistTwo: Pioneering the Human Knowledge Frontier with Autonomous AI.* arXiv:2609.19644, 2026.
https://arxiv.org/abs/2609.19644

이 스킬에서 가져온 것:
- CoE 감사를 마지막에만 하지 않고 **각 단계에 무결성 보정을 넣으면** 방법-코드 정합이 크게 오른다는 결과 → 참고문헌 조회 게이트와 방법-코드 판정을 WRITE 모드 중간 단계에 배치
- 모든 단계를 "후보 → 비평 → 수용/개선/폐기"로 다루는 구조 → 검증 루프 설계

#### 3. 이 스킬을 만들며 직접 검증한 내용
- 오류 7종을 심은 예제(`examples/binpack/`)로 스크립트 단위 테스트
- 스킬 내용을 모르는 독립 에이전트가 WRITE / AUDIT 모드를 처음부터 수행한 종단 테스트
- 그 테스트에서 발견된 우회·오탐 10건을 수정하고 회귀 테스트로 고정 (`tests/run_tests.py`)

---

### 한계

- **인용 지원 판정은 초록 수준까지.** "그 논문이 정말 그 말을 했는가"를 본문 단위로 확인하지는 않습니다. 원 논문도 미해결 과제로 남긴 부분입니다.
- **숫자가 근거에 "있다"는 것과 "같은 양을 잰다"는 것은 다릅니다.** 후자는 비평가가 보고서의 증거 열을 보고 판단합니다.
- **결정론적 평가기가 없는 분야**(정성 연구, 이론)에서는 점수 재현·규칙 위반 검사가 약해집니다. 근거 실물의 존재 여부는 여전히 검사합니다.
- **환경 제약.** 셸에서 학술 API에 접근할 수 없는 환경이 많아, 참고문헌은 웹 도구로 조회해 기록합니다. 일부 사이트는 요청 제한으로 막힐 수 있습니다.
- **독립 검토자가 필요합니다.** 하위 에이전트를 띄울 수 없는 환경에서는 별도 CLI 프로세스로 대체하고, 그것도 안 되면 판정이 독립적이지 않다고 명시합니다.
- **결과 문서가 기대보다 짧아질 수 있습니다.** 근거가 확인된 주장만 남기기 때문이며, 의도된 동작입니다.

---

<a id="english"></a>
## English

A Claude skill that **traces and verifies every claim** in a research report, paper or data-analysis document back to its actual evidence.

- **WRITE mode**: given experiment logs, result files and code, Claude writes a document in which every number, citation, method description and conclusion is linked to a source. Claims whose evidence cannot be confirmed do not make it into the final version.
- **AUDIT mode**: Claude checks an existing document (human- or AI-written) against its code, logs and bibliography and judges whether it can be trusted.

One principle: **every claim must trace, through a recorded chain of evidence, to a grounding source — a log line, a value in a result file, a code span, or a reference that was actually looked up.**

### Contents
1. [Installation](#installation)
2. [Usage](#usage)
3. [Examples](#examples)
4. [Outputs](#outputs)
5. [How it works](#how-it-works)
6. [Folder structure](#folder-structure)
7. [References](#references)
8. [Limitations](#limitations)

---

### Installation

1. Upload `chain-of-evidence.skill` (or a zip of this folder) in the Skills section of Claude's settings.
2. Nothing else to install: the scripts use only the Python 3 standard library.

Optional check: run the 40 regression tests from this folder.
```bash
python tests/run_tests.py
```

---

### Usage

You don't run the scripts yourself. **Attach your material and ask Claude**; Claude follows the procedure in `SKILL.md`. Words like "CoE", "chain of evidence", "verify the claims" or "audit this paper" reliably trigger the skill.

#### What WRITE mode needs
| Material | Example | Required |
|---|---|---|
| Experiment logs | `experimental_log.md`, `train.log` | ✅ |
| Result files | `scores.json`, `results.csv` | ✅ |
| **Which run is the final/submitted one** | "run 003 is final", "the `final` entry in `scores.json`" | ✅ basis for the headline number |
| Code | `solver.py` | when describing methods |
| Ablation / exploratory results | `ablation_summary.json` | if available |
| Works to cite | `refs.bib` or a list of titles | when citing |

#### What AUDIT mode needs
| Material | Required |
|---|---|
| The document to check (md / tex / txt; Claude converts PDF or docx) | ✅ |
| Its code, logs and result files | ✅ |
| Bibliography (bib) | for the reference check |
| The command that reproduces the headline score | for score reproduction |
| Task spec / evaluator code | for the specification-violation check |

---

### Examples

#### Example 1 — WRITE: writing up experiment results

**Request**
> Write a results report on the attached bin-packing experiment using CoE. The final submission is run 003. Please highlight our best score, 0.9952, and cite the papers in refs.bib.

**What Claude does**
1. Looks up each entry in `refs.bib` on the web, and drops works that do not exist or that put an invented title on a real DOI.
2. Writes a draft (the *representation*) in which every factual sentence carries a source tag:
   ```
   The submitted solver scores 0.9818 {num: scores.json#final.score headline @HEAD}.
   Each full run takes 14.4 ms {num: experimental_log.md:7 @LAT}.
   FFD has well-studied worst-case behaviour {cite: johnson1974fast @LIT1}.
   The solver improves on next-fit by 0.157 {derive: HEAD, BASE @CONC}.
   ```
3. Scripts check numbers, files and citations; three independent reviewers who did not write the text judge citation support and method–code agreement.
4. Claims that fail are fixed or removed, then verified again.
5. Delivers the final version with tags removed, plus an evidence appendix.

**Result (excerpt)**
> The submitted solver scores 0.9818, i.e. 98.18% of the bin lower bound on average. Each full run takes 14.4 ms. Removing local search leaves the score unchanged at 0.9818, so the gain comes from first-fit decreasing itself.

**Claude's note (excerpt)**
> I did not use the 0.9952 you asked for as the headline: it comes from an exploratory run on the 10 easiest instances, so it is mentioned once with that context. The headline is the submitted run (003): 0.9818. `smith2023neural` could not be found anywhere and was removed; `coffman1984dynamic` uses another paper's DOI and was removed. The claim that local search is key was dropped because its ablation shows no difference.

#### Example 2 — AUDIT: checking a paper you received

**Request**
> Audit this paper (paper.md) against its code and logs with CoE. Running `python3 solver.py` prints score=X.

**Result (`audit_report.md` summary)**

| Check | Result | Detail |
|---|---|---|
| T number tracing | FAIL | "9.4 ms" and "alpha = 0.95" appear in no log |
| H headline source | FAIL | 0.9952 comes from an exploratory subset run, not the submitted run |
| I1 score reproduction | FAIL | re-running the code gives 0.9818 |
| I2 specification violation | PASS (limited) | no violation, but there is no separate evaluator — the author's code computes the score |
| I3 references | FAIL | one entry does not exist; one puts an invented title on someone else's DOI |
| I4 method–code alignment | FAIL | paper says simulated annealing; code is a simple greedy move loop |

**Claude's conclusion (excerpt)**
> This paper is hard to trust. The headline 0.9952 is from an exploratory run on the 10 easiest instances; the submitted code reproduces 0.9818. The simulated annealing it describes does not exist in the code.

#### Example 3 — beyond research
> Write the quarterly report from this sales CSV and SQL query using CoE.

The same model applies: citation → source document/URL, number → row in the CSV, method → the SQL or notebook, conclusion → computed change.

---

### Outputs

#### WRITE mode
| File | Content |
|---|---|
| `final.md` (or converted to the format you want) | Final document that passed verification; in md style a References list is appended automatically |
| `evidence_appendix.md` | Table of each sentence's source and check result |
| `coe_final/ledger.json` | Full claim–evidence ledger (claim IDs, sources, status, votes) |
| `coe_final/ground_report.md` | Verification report |
| `judgments.json` | Independent reviewers' votes, tied to a hash of each claim |
| `refs_cache.json` | Reference lookup records |
| Claude's reply | What was dropped or weakened, and any limitations |

#### AUDIT mode
| File | Content |
|---|---|
| `audit_out/audit_report.md` | Verdict table, failures with locations, numbers whose source needs checking, qualitative overclaims |
| `audit_out/audit.json` | Full machine-readable results |
| `audit_out/audit_packet.md` | Material given to the independent reviewers (for re-review) |
| Claude's reply | Whether the document can be trusted, confirmed failures, and items dismissed as false positives |

The verdict is **PASS / FAIL / INCOMPLETE**. INCOMPLETE means there were not enough independent reviewer votes.

---

### How it works

#### Four claim types
| Type | Example | Evidence chain must end at | Checked by |
|---|---|---|---|
| Citation | "Smith et al. showed X" | a reference record that was actually looked up (matching title) | script + independent reviewers |
| Numerical | "achieves 87.3%" | a log line or result-file value | script |
| Methodological | "we use a 3-layer MLP" | the implementing code span | script + independent reviewers |
| Conclusion | "outperforms the baseline by 5%" | derivation from other claims | script + independent reviewers |

A conclusion is only as strong as its weakest input: if one supporting claim fails, the conclusion fails too.

#### WRITE mode flow
```
assemble evidence → tagged draft → script check ─┬→ critic (1)    ─┐
                                                 └→ reviewers (3) ─┴→ revise → (repeat)
→ compose final prose → final verification → strip tags → deliver
```

#### Rules the skill enforces
1. **Scripts compare numbers.** Claude never declares a match by eye.
2. **Reviewers, not the writer, make judgments.** Majority of at least three independent reviewers.
3. **Only references looked up in this session.** Citations from memory do not pass.
4. **The headline is the submitted run's result.** Using an ablation, subset or exploratory value as the headline is blocked.
5. **Failures are resolved by removing or weakening claims.** Evidence is never invented.
6. **A user's request does not override the evidence.** If asked for an unsupported number, Claude does not comply silently and says what it did instead.

#### What the scripts catch (main codes)
| Code | Meaning |
|---|---|
| `value_mismatch` | the number is not in the evidence |
| `cherry_pick` / `unlabelled_nonfinal` | a non-final value used as a result |
| `coarse_rounding` | rounding by more than 1% ("a score of 1" ← 0.9818) |
| `cite_not_verified` / `cite_title_mismatch` | reference never looked up / real DOI with a different title |
| `broken_ref` | file, line or key does not exist |
| `derive_broken` | conclusion rests on a failed claim |
| `judge_rejected` | independent reviewers found the support insufficient |
| `absence_violated` | a "never happened" claim is false |
| `untagged_number` | a number with no source |

The full list is in `references/tag-syntax.md`.

---

### Folder structure

```
chain-of-evidence/
├── SKILL.md                     procedure Claude follows (WRITE / AUDIT)
├── README.md                    this document
├── references/
│   ├── claim-taxonomy.md        the four claim types and the evidence each needs
│   ├── tag-syntax.md            tag grammar, number-matching rules, break codes
│   ├── critic-rubric.md         critic checklist
│   ├── judging.md               running independent reviewers, merging votes
│   └── audit-checks.md          audit checks T, H, I1–I4
├── scripts/
│   ├── coe_lib.py               shared helpers (numbers/units, tag parsing, bib parsing)
│   ├── ground.py                verify a tagged draft (WRITE)
│   ├── strip_tags.py            produce the final document, references and evidence appendix
│   ├── refs.py                  manage reference lookup records
│   ├── merge_judgments.py       merge independent reviewers' votes
│   └── audit.py                 audit a finished document (AUDIT)
├── examples/binpack/            example bundle seeded with known errors
└── tests/run_tests.py           regression tests
```

#### Running the scripts directly (advanced)
The scripts also work without Claude.
```bash
# verify a draft
python scripts/ground.py examples/binpack/rep_bad.md --bundle examples/binpack --out /tmp/out
cat /tmp/out/ground_report.md

# audit a document
python scripts/audit.py examples/binpack/paper_foreign.md --bundle examples/binpack \
  --bib refs.bib --refs-cache refs_cache.json \
  --evidence experimental_log.md scores.json ablation_summary.json \
  --final-sources scores.json#final --claimed 0.9952 \
  --rerun-cmd "python3 solver.py" --code solver.py --spec task_spec.md
```

---

### References

#### 1. ScientistOne — the original Chain-of-Evidence paper (primary source)
Rui Meng, Bhavana Dalvi Mishra, Jiefeng Chen et al., Google Cloud AI Research.
*ScientistOne: Towards Human-Level Autonomous Research via Chain-of-Evidence.* arXiv:2605.26340, 2026.
https://arxiv.org/abs/2605.26340

Taken from it:
- The **CoE principle** and the ACID analogy (define the properties an output must have, not how to build it)
- The **four claim types** (citation, numerical, methodological, conclusion) and the evidence-chain shape for each → `references/claim-taxonomy.md`
- The Paper Writer's **Conceive → Ground → Critic → Resolve → Compose** pipeline, the two-round limit and aborting when the grounding ratio is too low → WRITE mode
- The **Claim Verifier**'s per-type checks (numeric tolerance and unit normalisation, abstract-entailment for citations, matching methods to execution records) → `ground.py`
- The **CoE Integrity Audit**'s four checks (score verification, specification violation, reference verification, method–code alignment), majority voting and failure categories → `audit.py`, `references/audit-checks.md`
- Failure cases observed in its 75-paper audit (headline cherry-picking, inverted metric direction, invented titles on real DOIs, method sections describing algorithms absent from the code) → detection rules and critic checklist
- Its finding that qualitative overclaiming drove quality variance → a stronger critic checklist

#### 2. ScientistTwo — follow-up work applying CoE across the whole pipeline
Jaehyun Nam, Jinsung Yoon, Yanzhou Pan et al., Google Cloud AI Research / University of Waterloo.
*ScientistTwo: Pioneering the Human Knowledge Frontier with Autonomous AI.* arXiv:2609.19644, 2026.
https://arxiv.org/abs/2609.19644

Taken from it:
- The result that putting **integrity corrections inside each stage**, rather than only auditing at the end, sharply improves method–code alignment → the reference-lookup gate and method–code judging sit in the middle of WRITE mode
- Treating every stage as "candidate → critic → accept / refine / discard" → the verification loop

#### 3. What was verified while building this skill
- Script tests on an example seeded with seven kinds of errors (`examples/binpack/`)
- End-to-end tests in which agents with no prior knowledge of the skill ran WRITE and AUDIT mode from scratch
- Ten bypasses and false positives found in those tests were fixed and locked in by regression tests (`tests/run_tests.py`)

---

### Limitations

- **Citation support is judged at abstract level.** Whether the cited paper really says what is claimed is not checked passage by passage — an open problem the original paper also leaves.
- **A number "existing" in the evidence is not the same as it "measuring the same thing".** The critic judges the latter from the report's evidence column.
- **Fields without deterministic evaluators** (qualitative research, theory) get weaker score-reproduction and specification checks. Whether the evidence exists is still checked.
- **Environment constraints.** Many environments block scholarly APIs from the shell, so references are looked up with web tools and recorded. Some sites may rate-limit requests.
- **Independent reviewers are needed.** Where subagents cannot be spawned, a separate CLI process is used instead; failing that, the skill states that judgments were not independent.
- **The output may be shorter than expected.** Only claims with confirmed evidence remain — this is intended.
