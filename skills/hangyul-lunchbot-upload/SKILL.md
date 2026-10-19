---
name: hangyul-lunchbot
description: >
  Set up, run, test, schedule, debug and customize the lunchbox (도시락) order Slack bot,
  which posts a 20:00 KST order message, syncs 🍚/🥗 emoji reactions with a Google Sheet,
  sends a 22:00 reminder, confirms or cancels at 23:00, and posts a weekly settlement
  reminder, skipping weekends and Korean holidays. Use for requests such as "도시락 봇",
  "점심 주문 봇", "lunchbot", "도시락 알림 설정", "주문 메시지 지금 보내줘", "시트 동기화 안 돼",
  "명단 이름이 Slack ID로 바뀌었어", "다음 주 탭 만들어줘", "정산 알림", or running a job with
  `--once` / `--dry-run`. Not for general Slack messaging or unrelated spreadsheets.
---

# Lunchbox Order Bot (도시락 봇)

A Slack bot for a team's daily lunchbox order. Orders come from emoji reactions on the
20:00 message (🍚 `:rice:` = 밥, 🥗 `:green_salad:` = 샐러드) **and** from direct entries
in a shared Google Sheet; the bot merges both.

The skill directory is `<skill_dir>` (the folder containing this file). Run scripts by
absolute path, because the shell's working directory can reset between commands. `$PY`
below means a Python 3.10+ interpreter with `requirements.txt` installed. The system
`python3` usually lacks the packages, so ask the user which environment to use, or create
one with `pip install -r <skill_dir>/requirements.txt`.

For module internals (sheet layout, identity matching, menu OCR), read
`references/architecture.md` before changing code or debugging sheet behavior.

## Schedule (KST)

| Time | Job (`--once`) | What happens |
|---|---|---|
| 20:00 | `first` | Order message for **tomorrow** + menu image (whole week on the week's first lunch day, otherwise tomorrow's column); seeds both emoji; ensures tomorrow's sheet column |
| 20:00–22:55, every 5 min | `sync` | Merge sheet ↔ reactions; posts nothing |
| 22:00 | `final` | Tally reminder, rice and salad listed separately |
| 23:00 | `midnight` | Confirm if ≥ `MIN_ORDER` (3) people, else post a cancel and clear that day in the sheet |
| Fri 21:00 | `prep` | Create next week's tab, empty `menu_images/`; posts nothing |
| 15:00 Mon–Fri | `settle` | Posts only on the week's last working day: mentions everyone who ordered + account |

"Lunch day" is always posting date + 1. Weekends and Korean public holidays are skipped.
Friday lunch is on by default (`INCLUDE_FRIDAY`).

## Start here: setup check

Before any live run, check these four things and tell the user what is missing:

1. **`<skill_dir>/lunchbot_config.py` exists** (git-ignored). If not:
   `cp lunchbot_config.example.py lunchbot_config.py && chmod 600 lunchbot_config.py`,
   then have the user fill in `SLACK_BOT_TOKEN`, `SLACK_CHANNEL_ID`, `SHEET_ID`,
   `SETTLE_ACCOUNT`. Environment variables with the same names override the file.
2. **`<skill_dir>/service_account.json` exists** (git-ignored), and the spreadsheet is
   shared with its `client_email` as **Editor**.
3. **Slack scopes:** required `chat:write`, `reactions:read`, `reactions:write`,
   `files:write`; recommended `users:read` and `channels:read` (public) or `groups:read`
   (private). The bot must be invited to the channel; reinstall the app after scope changes.
4. **`SHEET_ID` points at the intended sheet** (test vs production). The sheet is usually
   live and shared, so confirm before any non-dry run.

Never print, echo or commit the token, the service-account key, or the account number.
If a token appears in chat, logs or a committed file, tell the user to rotate it.

## Commands

```bash
# Safe full cycle: nothing posted, sheet untouched (menu lookup may still use the network)
$PY <skill_dir>/lunch_bot.py --dry-run --test --delay 5

# One job (cron entry points)
$PY <skill_dir>/lunch_bot.py --once first|sync|final|midnight|prep|settle

# Built-in scheduler (keep it supervised: systemd, tmux, ...)
$PY <skill_dir>/lunch_bot.py --run

# Menu scraper alone (+ OCR the chosen image)
$PY <skill_dir>/menu_fetch.py [--ocr]
```

Flags: `--force` bypasses holiday/weekend checks (for `first`, `final`, `sync`, `settle`
tests); `--friday` / `--no-friday` overrides `INCLUDE_FRIDAY` for one run.

**Ask before any non-dry run.** `--once first|final|midnight|settle` posts to a real Slack
channel, and `midnight` with too few orders cancels the day and clears its sheet column.
Prefer `--dry-run` for testing.

### Scheduling

The repository installs no scheduler. Offer either `--run` under a supervisor, or a cron
setup like this (server timezone must be KST, or convert the times):

```cron
0 20 * * *      cd <skill_dir> && $PY lunch_bot.py --once first
*/5 20-22 * * * cd <skill_dir> && $PY lunch_bot.py --once sync
0 22 * * *      cd <skill_dir> && $PY lunch_bot.py --once final
0 23 * * *      cd <skill_dir> && $PY lunch_bot.py --once midnight
0 21 * * 5      cd <skill_dir> && $PY lunch_bot.py --once prep
0 15 * * 1-5    cd <skill_dir> && $PY lunch_bot.py --once settle
```

`--run` never replays slots that passed before it started (beyond the minute it started
in). To run a missed slot, call it explicitly with `--once <job>`.

## Operating rules

- **`state.json` is the handoff between jobs.** `first` writes today's message `ts`;
  `sync`, `final` and `midnight` only work on the same day after `first` succeeded. If
  they report no state, `first` failed or was not run today.
- **Sheet and menu failures are non-fatal.** A missing key, gspread error, scraper breakage
  or missing Slack scope only prints a warning; reminders still post. Read the warnings
  in the output when diagnosing.
- **Cell ownership:** the bot only clears cells it wrote itself (tracked in `state.json`
  `synced`); manual entries are never deleted. Order cells hold exactly `밥`, `샐러드` or
  `error`.
- **`명단` tab** (`이름 | Slack ID`) is the master roster and sets the week-tab order. New
  Slack members are inserted at the end of the first (regular) section. A Slack ID must
  never be written into a name cell; if names turned into `U...` IDs, `users:read` is
  probably missing.
- **Week tabs** are named `YYYYMMDD-YYYYMMDD`, one per week, laid out
  `인원 | Mon … Fri | Total | 가격`. Human-made tabs are used as-is.
- Change Friday handling only through `lunch_bot.set_include_friday` so the skip logic and
  sheet column count stay consistent.

## Testing sheet logic without Slack

Drive `sheet_sync` directly, for example:

```bash
cd <skill_dir> && $PY -c "import datetime as dt, sheet_sync as S; print(S.week_orders(dt.date.today(), members=S.load_roster()))"
```

This reads the real sheet. If a test creates tabs, delete the throwaway tabs afterwards
and re-check the tab list.

## Customizing

- Message texts, `MIN_ORDER`, schedule times: constants at the top of `lunch_bot.py`.
- Meal price: `PRICE_PER_MEAL` in `sheet_sync.py` (feeds the `가격` formula).
- Menu source: `menu_fetch.py` targets one specific caterer's Imweb site (browser
  User-Agent required). For another caterer, the scraper and the header-band detection
  need to be adapted.
- No automated test suite; verify changes with `--dry-run` and targeted function calls.
