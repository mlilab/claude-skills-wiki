# MLI Lab Claude Skills Wiki

팀에서 배포하고 사용하는 Claude Code·Codex 스킬을 모아 둔 저장소입니다. **스킬 하나는 `skills/<skill-name>/` 디렉토리 하나**에 넣고, 그 디렉토리의 루트에 `SKILL.md`를 둡니다. 스킬에 필요한 코드, 참고 문서, 예제 설정도 같은 디렉토리에 보관합니다. 실제 사용자 설정, 생성 데이터, 토큰과 비밀번호는 올리지 않습니다.

| 스킬 | 설명 | 원본 |
| --- | --- | --- |
| [Daily Papers](skills/daily-papers/README.md) | 관심 분야 논문을 수집·요약하고 영어·한국어 digest를 만드는 스킬 | [claude-skills-daily-papers](https://github.com/mlilab/claude-skills-daily-papers) ([가져온 버전](https://github.com/mlilab/claude-skills-daily-papers/tree/0e8aa0550e064492e7fb1ac442395b6c9a2d9823)) |
| [Chain-of-Evidence](skills/chain-of-evidence/README.md) | 논문·보고서의 모든 주장(수치·인용·방법·결론)을 근거에 연결해 작성(WRITE)하거나, 완성된 문서를 코드·로그·참고문헌과 대조해 검증(AUDIT)하는 스킬 | — |

## 설치

저장소를 clone한 뒤 사용할 스킬 디렉토리를 Claude Code나 Codex의 skills 경로에 연결합니다. 예를 들어 Daily Papers를 두 도구에서 모두 쓰려면:

```bash
git clone https://github.com/mlilab/claude-skills-wiki.git "$HOME/claude-skills-wiki"
mkdir -p "$HOME/.claude/skills" "$HOME/.codex/skills"
ln -s "$HOME/claude-skills-wiki/skills/daily-papers" "$HOME/.claude/skills/daily-papers"
ln -s "$HOME/claude-skills-wiki/skills/daily-papers" "$HOME/.codex/skills/daily-papers"
```

스킬별 의존성과 설정 방법은 각 디렉토리의 README를 확인하세요. 이미 같은 이름의 설치 디렉토리가 있다면 기존 설정을 확인한 뒤 연결하세요.

## Duty 기준

**계정 1개당 2주에 2 duty, 한 달에 4 duty**를 기준으로 합니다.

| 활동 | 인정 duty |
| --- | ---: |
| 스킬 최초 배포 | 1 |
| 스킬에 대한 feedback 제출 | 0.5 |
| feedback을 반영한 스킬 재배포 | 변경 규모에 따라 0.5 또는 1 |

## 배포 및 feedback 규칙

1. 스킬은 이 저장소의 `skills/<skill-name>/`에 올립니다. 스킬마다 독립된 디렉토리를 사용합니다.
2. 스킬에 대한 feedback은 [이 저장소의 Issues](https://github.com/mlilab/claude-skills-wiki/issues)에 올립니다. 어떤 스킬에 관한 의견인지와 필요한 변경 내용을 적습니다.
3. feedback을 반영한 재배포는 **그 스킬을 최초 배포한 사람**이 담당합니다. 재배포 시기는 담당자가 정합니다.
4. 재배포할 때 관련 채널에 **변경·업데이트 내용**과 **이번 재배포에 적용할 duty(0.5 또는 1)**를 공지합니다.
