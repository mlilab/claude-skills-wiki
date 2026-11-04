# Experiment Notebook

한국어 | [English](README.md)

연구 질문·방법·관측·결과·해석을 근거와 함께 기록하고, HTML 보고서와 연구 계보를 로컬 서버에서 읽는 Claude Code·Codex 스킬입니다. 계산 실험, 실험실 측정, 현장 관측, 정성 연구, 문헌 기반 분석 등에서 사용할 수 있습니다. 기록 하나는 실험이나 하나의 일관된 연구 단위를 나타냅니다.

핵심은 **Git 연결과 실행 버전 기록, 실험 모니터링, 실험 상속 모식도, 목적·가설·이전 실험과의 차이·결과·필요한 수정 사항을 담은 보고서**입니다.
Slack을 설정하면 실험 시작·진행·완료·중단·실패도 채널이나 DM으로 알립니다.

특정 프로젝트의 역할, 채점 공식, 모델, 예산, 실험 절차를 전제로 하지 않습니다. 코드를 사용하는 연구는 소스 Git 저장소를 연결하고, 코드가 없는 연구는 실제 프로토콜·데이터 버전으로 출처를 기록할 수 있습니다. AI 서비스, 에이전트 로그, 수치 지표, 반복 최적화는 선택 사항입니다.

## 기능

| 기능 | 내용 |
| --- | --- |
| Git 연결 | 로컬 소스 저장소를 연결하고 전체 commit·branch·미커밋 변경·변경 경로·인증값을 제거한 remote를 기록합니다. 준비·실행·보고서 작성 시점의 버전을 구분합니다. |
| 실험 모니터링 | 실험을 수정하지 않고 상태·단계·진행률·경과 시간·Linux 프로세스 신원을 관측합니다. 실시간 관측이 미연결된 기록은 분명히 표시합니다. |
| Slack 알림 | 별도 monitor 프로세스가 설정한 채널·DM으로 상태 변화를 보냅니다. 전송 원장을 재시작 후에도 보존하고, 진행 알림 빈도와 전달 불명확 상태를 관리합니다. |
| 실험 상속 모식도 | 부모→자식 분기 관계를 SVG로 그리고 실험 보고서를 연결합니다. 참조 자료·재시작·시간 순서는 상속 관계와 구분합니다. |
| 보고서 주요 항목 | 실제 실행 commit, 목적·가설, 부모 실험과의 차이, 결과, 분석, 필요한 수정과 이유·검증 상태를 담습니다. |
| 기타 재현 정보 | 연구에 맞는 프로토콜, 장비, 자료 출처, 시료 식별자, 분석 버전을 기록합니다. |
| 자원·비용 | 장비 사용 시간, 재료, 참여자 시간, 계산 자원 등 연구에 맞는 항목을 자유롭게 기록합니다. |
| 반복 기록 | 반복 측정·분석 수정이 있을 때 차수별 질문·변경점·근거·결과를 연결합니다. |
| 근거 보기 | JSON 필드 토글과 텍스트 보기를 제공합니다. 원본은 수정하지 않습니다. 에이전트 trajectory는 선택 기능입니다. |
| 대시보드 | 검색, 최신 순 정렬, 실시간 진행률·상태 표시, 상속 모식도의 텍스트 보기를 제공합니다. |
| 언어 | 한국어·영어 UI와 사용자 지정 시간대를 지원합니다. 보고서 본문은 연구에서 사용하는 언어로 작성할 수 있습니다. |
| 검토 의견 | 필요한 경우 검토 결론과 후속 결정을 기록합니다. 모든 연구에 사용자 판정을 요구하지 않습니다. |

## 설치

Python 3.10 이상이 필요합니다. 외부 Python 패키지는 필요 없습니다. Git 연결 기능에는 로컬 Git 실행 파일이 필요하며, 로컬 저장소 조회에 API 토큰은 필요하지 않습니다.

이 레포를 clone한 뒤 스킬을 연결합니다.

```bash
mkdir -p "$HOME/.claude/skills" "$HOME/.codex/skills"
ln -s /path/to/claude-skills-wiki/skills/experiment-notebook "$HOME/.claude/skills/experiment-notebook"
ln -s /path/to/claude-skills-wiki/skills/experiment-notebook "$HOME/.codex/skills/experiment-notebook"
```

같은 이름의 스킬이 이미 있으면 기존 설치를 먼저 확인하세요. 개인 설정·연구 데이터·로그·인증 정보는 공유 스킬 디렉터리 밖에 보관하세요.

## 사용

에이전트에게 다음과 같이 요청합니다.

- “이 소스 저장소를 Git으로 연결하고, 실험을 모니터링하면서 부모·자식 분기와 보고서를 보여줘.”
- “실행 commit, 가설, 이전 실험과 달라진 점, 결과, 다음에 고쳐야 할 점을 보고서에 적어줘.”
- “이 측정 연구의 보고서와 대시보드를 만들어줘. 원본 디렉터리는 읽기 전용으로 두자.”
- “현장 관측의 절차, 관측 내용, 한계를 기록해줘.”
- “시뮬레이션 결과를 비교하고 각 해석을 실제 결과 파일에 연결해줘.”
- “이 문헌 검토는 질문·자료 선정·분석·발견·한계 순서로 구성해줘.”
- “이 디렉터리에 연결된 Codex 대화가 있으면 보조 근거로 확인해줘.”

직접 시작할 수도 있습니다.

```bash
python3 /path/to/skill/scripts/notebook.py init --root /path/to/private-notebook --title "나의 연구" --language ko --timezone Asia/Seoul
python3 /path/to/skill/scripts/notebook.py connect-git --root /path/to/private-notebook --repository /path/to/source
python3 /path/to/skill/scripts/notebook.py new --root /path/to/private-notebook --slug pilot-study --title "예비 연구" --parent none
python3 /path/to/skill/scripts/notebook.py capture-git --root /path/to/private-notebook --experiment 001-pilot-study --stage preparation --phase prepared
```

코드를 사용하지 않는 연구에서는 Git 연결과 capture를 생략합니다. 생성된 `experiments/001-pilot-study/report.json`을 실제 근거로 채웁니다. 실제 실험 시작·재개 시에는 해당 소스 checkout을 확인하고, 노트북 상태가 `running`일 때 실행 버전을 기록합니다.

```bash
python3 /path/to/skill/scripts/notebook.py capture-git --root /path/to/private-notebook --experiment 001-pilot-study --stage execution --phase initial-run
```

이 명령은 실험을 시작하지 않습니다. 이미 끝난 과거 실험은 당시 실행 근거에서 commit을 확인해야 합니다. 실시간 모니터링을 위해 `watch`에 실제 상태 파일 또는 프로세스 신원을 연결한 뒤 실행합니다.

```bash
python3 /path/to/skill/scripts/notebook.py check --root /path/to/private-notebook
python3 /path/to/skill/scripts/notebook.py build --root /path/to/private-notebook
python3 /path/to/skill/scripts/notebook.py serve --root /path/to/private-notebook --port 8782
```

`http://127.0.0.1:8782/`에서 엽니다. 원격 서버라면 해당 포트를 전달하세요. 서버는 manifest에 등록된 HTML·CSS·JS만 제공하며, 원본 데이터나 노트북 JSON은 제공하지 않습니다.

## 연구에 맞게 조정하기

`notebook.json`에서 연결한 `repository`, `language`(`en`/`ko`), `timezone`, `sections`, `request_feedback`, 근거 파일 크기 제한을 설정합니다. 기본값은 영어·UTC·일반적인 여섯 섹션·필수 검토 없음입니다. `sections`의 섹션을 추가·삭제·이름 변경·재정렬할 수 있고, 개별 보고서의 추가 섹션도 보존합니다. 프로젝트의 작성 규칙은 `GUIDE.md`에 둡니다.

`hypotheses`, `comparisons`, `follow_up`으로 가설·판단 기준, 이전/이번 조건과 변경 이유, 필요한 수정과 구현·검증 상태를 최상위 보고서에 표시합니다. 준비·실제 실행·보고서 작성 commit은 구분하고, 나중에 바뀐 코드 버전으로 과거 실행 버전을 덮어쓰지 않습니다.

`configuration`, `execution`, `quality`에는 해당 연구에 실제로 존재하는 재현 정보와 검사를 기록합니다. 실험실 프로토콜은 Git commit 없이 버전만 기록할 수 있고, 정성 연구는 수치 지표 없이 발견과 해석을 기록할 수 있습니다. 자원 집계가 필요 없으면 `usage`를 비워둡니다. API·구독·과금 항목은 기본으로 만들지 않습니다.

반복 기록·근거 파일이 필요 없으면 `iterations`, `artifacts`를 비워둡니다. 진행 중인 실험은 가용한 상태 파일이나 PID를 `watch`에 연결합니다. 연결할 실시간 근거가 없으면 대시보드에 저장된 상태만 표시한다고 명시합니다. 연구마다 검토가 필요한 프로젝트에서만 `request_feedback: true`를 설정하세요. 특정 기록만 검토받을 때는 그 기록의 feedback을 `pending`으로 지정할 수 있습니다. 관측 결과와 검토자의 결론은 구분합니다.

자세한 내용은 [Git 연결·실행 버전](references/git.md), [데이터 형식](references/schema.md), [작성 기준](references/report-guide.md), [근거·대화 기록](references/evidence.md), [서버 운영](references/server.md)을 참고하세요.

## Slack 알림

Slack 앱에 Bot token과 `chat:write` 권한을 설정하고 대상 채널에 봇을 초대합니다. 사용자 ID를 지정한 DM에는 `im:write` 권한도 필요합니다. 토큰은 `SLACK_BOT_TOKEN` 환경 변수 또는 기존 비공개 토큰 파일로 제공합니다. 설정 파일에는 토큰 값 대신 그 참조만 저장합니다.

```bash
python3 /path/to/skill/scripts/notebook.py configure-slack --root /path/to/private-notebook --channel C0123456789 --token-env SLACK_BOT_TOKEN
python3 /path/to/skill/scripts/notebook.py monitor --root /path/to/private-notebook --once --dry-run
python3 /path/to/skill/scripts/notebook.py monitor --root /path/to/private-notebook
```

채널 ID는 본인의 대상으로 바꿉니다. DM은 `--channel` 대신 `--user U0123456789`를 사용합니다. 실험 전에 환경의 백그라운드 실행 기능이나 기존 supervisor로 monitor를 가동하세요. 웹페이지만 켜두는 것으로는 메시지를 보내지 않습니다. 별도 서비스 설치는 따로 요청하는 작업입니다. 모니터는 대시보드와 같은 `watch` 근거를 읽습니다.

실제 관측된 시작·재개·완료·중단·실패·활동 확인 필요 이벤트를 알립니다. 이미 진행 중인 실험에 연결하면 새 시작이라고 쓰지 않고 “감시 시작”으로 알립니다. 처음 연결할 때 과거 종료 실험을 일괄 전송하지 않습니다. 진행 상황이 바뀐 경우의 알림은 기본 최대 30분마다 한 번이며, `--progress-interval`로 간격을 바꾸거나 0으로 끌 수 있습니다.

`notification-status --root /path/to/private-notebook`으로 전송 상태를 확인합니다. 대기 메시지는 재시작 후에도 남고, 성공한 메시지는 다시 보내지 않습니다. 전달 여부가 불명확하면 Slack에서 확인하고 해당 이벤트를 명시적으로 판정한 뒤에만 다시 시도합니다. Slack 전송 실패로 실험을 중단하지 않습니다. 비밀 값 관리·설정·전송 제한·복구 명령은 [Slack 설정 및 복구](references/slack.md)에 있습니다. 설정 전에는 알림이 비활성화됩니다.

## 범위와 한계

기존 연구와 연구 계획을 기록하고, 명시적으로 설정한 Slack 모니터링에서 상태 알림을 보내는 스킬입니다. 실험 실행·분석 재실행·원본 프로젝트 변경·노트북 외부 게시·반복 작업 설치는 수행하지 않습니다. Linux PID 관측에는 기록된 프로세스 시작 tick이 필요합니다. 절차 완료 여부와 연구 주장이 뒷받침되는지는 별도로 기록합니다.

선택 기능인 trajectory viewer는 Claude 도구 메시지, Codex response item, 기본 ATIF steps를 지원합니다. 알 수 없는 레코드는 접힌 원본 보기로 남깁니다. 자동 마스킹은 모든 비밀 값을 탐지하지 못하므로 공유 전에 입력을 검토하세요. 서버는 로컬 전용이며 공개 호스팅용 인증 서버가 아닙니다.

레포 루트에서 검증합니다.

```bash
python3 -B -m unittest discover -s skills/experiment-notebook/tests -v
```

테스트는 이 스킬의 `tests/.tmp/` 안에만 합성 파일을 만들고 정리합니다. 기존 연구 프로젝트나 실행 중인 서비스를 사용하지 않습니다.
