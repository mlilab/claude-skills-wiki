# 도시락 주문 Slack 봇 (Lunchbox Order Bot)

A Slack bot that runs a team's daily lunchbox (도시락) order. Every working evening it
posts an order message, collects orders from emoji reactions (🍚 rice / 🥗 salad) **and**
a shared Google Sheet, reminds people before the deadline, and confirms or cancels the
order. Weekends and Korean public holidays are skipped automatically.

| Time (KST) | What happens |
|---|---|
| 20:00 | Order message for tomorrow + tomorrow's menu image (whole week on the first lunch day) |
| 20:00–22:55 | Every 5 min: sync emoji reactions ↔ sheet (no Slack message) |
| 22:00 | Reminder with the current count, rice/salad listed separately |
| 23:00 | Confirm if ≥ 3 people, otherwise cancel (and clear that day in the sheet) |
| Fri 21:00 | Create next week's sheet tab and delete old menu images in `menu_images/` |
| 15:00, last working day of the week | Settlement reminder: mentions everyone who ordered + account |

---

## Using it as a Claude Code / Codex skill

This folder is also a skill (`SKILL.md`). Link it into your skills folder, then ask
Claude things like "도시락 봇 dry-run 돌려줘" or "시트 동기화가 안 돼":

```bash
ln -s "$HOME/claude-skills-wiki/skills/hangyul-lunchbot" "$HOME/.claude/skills/hangyul-lunchbot"
```

Your private files (`lunchbot_config.py`, `service_account.json`) then live in that
folder; they are git-ignored, so they are never committed.

---

## 준비할 것

**Private한 정보가 담긴 파일 두 개**가 필요합니다. 둘 다 이 저장소에는 들어 있지 않고, git에서도 제외(ignore)되어 있습니다.

### 1. `service_account.json` (Google Sheets 접근용)

1. Google Cloud Console에서 프로젝트를 만들고 **Google Sheets API**를 활성화합니다.
2. **서비스 계정**(service account)을 만든 뒤 JSON 키를 다운로드합니다.
3. 키 파일을 저장소 루트에 `service_account.json`이라는 이름으로 저장합니다.
4. 사용할 스프레드시트를 열고, JSON 파일에 있는 **`client_email`에 편집자(Editor) 권한으로 공유**합니다.
   봇이 탭을 만들고 주문을 기록하기 때문에 보기 권한만으로는 동작하지 않습니다.

### 2. `lunchbot_config.py` (Slack, 시트, 계좌 설정)

```bash
cp lunchbot_config.example.py lunchbot_config.py
chmod 600 lunchbot_config.py
```

그다음 아래 값을 채워 넣습니다.

| 설정 | 설명 | 확인하는 곳 |
|---|---|---|
| `SLACK_BOT_TOKEN` | 봇 토큰 (`xoxb-...`) | Slack 앱 → OAuth & Permissions → *Bot User OAuth Token* |
| `SLACK_CHANNEL_ID` | 메시지를 보낼 채널 (`C...`) | Slack 채널 → 채널 세부정보 → About 탭 맨 아래 |
| `SHEET_ID` | 사용할 Google 시트 | 시트 URL에서 `/d/`와 `/edit` 사이 부분 |
| `SETTLE_ACCOUNT` | 정산 알림에 표시할 계좌 | 본인 계좌, 예: `"은행 000-000-000000 예금주"` |
| `INCLUDE_FRIDAY` *(선택)* | 월–목만 도시락을 주문하려면 `False` | 기본값 `True` |

같은 이름의 환경 변수가 있으면 파일보다 우선 적용됩니다. 서버에서 운영할 때 편리합니다.

### 3. Slack 앱 설정

- **필수 bot scope:** `chat:write`, `reactions:read`, `reactions:write`, `files:write`
- **권장:** `users:read`(표시 이름 조회), 그리고 멤버 확인용으로 공개 채널이면 `channels:read`,
  비공개 채널이면 `groups:read`
- scope를 바꾼 뒤에는 앱을 워크스페이스에 다시 설치하고, **봇을 채널에 초대**해야 합니다.

권장 scope가 없어도 주문은 정상적으로 받을 수 있습니다. 다만 이름과 Slack ID를 시트의 `명단` 탭에서만
가져오므로, 명단을 직접 관리해야 합니다.

### 4. Python 환경

Python 3.10 이상이 필요합니다.

```bash
pip install -r requirements.txt
```

EasyOCR을 처음 실행할 때 모델 파일을 내려받기 때문에 몇 분 정도 걸립니다.

---

## Running

```bash
# Safe local test: nothing is posted and the sheet is not modified
python lunch_bot.py --dry-run --test --delay 5

# Production option A: built-in scheduler (keep it running, e.g. with systemd/tmux)
python lunch_bot.py --run

# Production option B: cron, one job per run
python lunch_bot.py --once first      # 20:00
python lunch_bot.py --once sync       # every 5 min, 20:00–22:55
python lunch_bot.py --once final      # 22:00
python lunch_bot.py --once midnight   # 23:00 confirm/cancel
python lunch_bot.py --once prep       # Fri 21:00 (also clears menu_images/)
python lunch_bot.py --once settle     # 15:00 Mon–Fri (posts only on the week's last working day)
```

Extra flags:
- `--force` ignores the holiday and weekend checks, for testing.
- `--friday` / `--no-friday` overrides `INCLUDE_FRIDAY` for a single run.

---

## Code structure

```
lunch_bot.py               Main entry point: Slack messages, scheduling, holiday logic, tallying
sheet_sync.py              Google Sheet read/write: weekly tabs, orders, roster (명단)
menu_fetch.py              Scrapes the caterer's menu image and crops the needed day/week (OCR)
lunchbot_config.example.py Template for your private lunchbot_config.py
requirements.txt           Python dependencies
SKILL.md                   Instructions for Claude Code / Codex when used as a skill
references/architecture.md Detailed design notes (sheet layout, identity, menu OCR)

# created at runtime (git-ignored)
lunchbot_config.py         your private settings
service_account.json       your Google key
state.json                 today's order-message ID, shared between jobs
menu_images/               downloaded and cropped menu images
```

`lunch_bot.py` uses the other two modules. Sheet and menu errors **never stop the
reminders**: they print a warning and the Slack messages still go out.

### How the Google Sheet is organized

- **`명단` tab:** the master roster (`이름 | Slack ID`). Week tabs list people in this
  order. New people who react on Slack are added automatically.
- **Weekly tabs** are named `YYYYMMDD-YYYYMMDD` and laid out as
  `인원 | Mon … Fri | Total | 가격`. The bot creates each one from the roster.
- An order cell contains `밥`, `샐러드`, or `error` (for unclear input). People can order
  either by typing in the sheet or by reacting on Slack; both are merged.
- The bot only clears cells **it wrote itself**, so manual entries are never deleted.

### Customizing

Message texts, the minimum headcount (`MIN_ORDER`), the meal price
(`PRICE_PER_MEAL` in `sheet_sync.py`) and the schedule times are constants near the top
of `lunch_bot.py` / `sheet_sync.py`. The menu scraper in `menu_fetch.py` targets one
specific caterer's website, so you will need to adapt it for a different caterer.
