---
name: meeting-summary-bot
description: >
  Set up, run, test, debug and customize the lab's Slack bot that writes the weekly
  3-line pre-meeting summary (교수님 양식 미팅 3줄 요약). Students DM the bot their past
  feedback notes (.md/.txt) or say it is a new topic, then send this week's slides (PDF),
  and Claude Sonnet writes the summary through the Anthropic API. Use for requests such as
  "미팅 요약 봇 실행해줘", "3줄 요약 봇 설정", "meeting summary bot", "봇이 응답을 안 해",
  "요약 규칙(prompt) 고쳐줘", "요약이 너무 길어", "Slack 토큰 넣었어", "봇 재시작", or
  testing a summary on local files. Not for general Slack messaging or unrelated summaries.
---

# Meeting Summary Bot (미팅 3줄 요약 봇)

A Slack bot (Socket Mode, no public URL needed) that guides a student through two steps in
a DM — feedback notes or a new-topic declaration, then this week's material — and replies
with the professor's 3-line summary card. One Anthropic Messages API call per summary
(`claude-sonnet-5-5`, structured output). See `README.md` for the user-facing flow.

The skill directory is `<skill_dir>` (the folder containing this file). Run commands with
absolute paths or `cd <skill_dir>` first, because the shell's working directory can reset.
`$PY` means a Python 3.10+ interpreter with this package installed
(`pip install -e <skill_dir>`, or `pip install -e "<skill_dir>[dev]"` for tests). The
system `python3` usually lacks the packages, so ask which environment to use or create a
venv.

## Start here: setup check

Before running anything live, check these and tell the user what is missing:

1. **`<skill_dir>/.env` exists** (git-ignored). If not:
   `cp .env.example .env && chmod 600 .env`, then the user fills in `ANTHROPIC_API_KEY`,
   `SLACK_BOT_TOKEN` (`xoxb-`) and `SLACK_APP_TOKEN` (`xapp-`). Check that they are set
   without printing them, e.g. print only whether each value is non-empty and has the
   right prefix.
2. **The Slack app was created from `slack_manifest.yaml`** and installed to the
   workspace. The manifest carries the scopes (`app_mentions:read`, `chat:write`,
   `files:read`, `im:history`), events (`app_mention`, `app_home_opened`, `message.im`),
   interactivity (buttons) and Socket Mode. After changing the manifest, reinstall the app.
3. **The API key is an Anthropic Console key.** Never run this bot on a personal Claude
   Pro/Max login: it serves other people, which Anthropic's terms do not allow for
   subscription credentials.
4. **No other instance is running** with the same Slack tokens (see Operating rules).

Never print, echo, log or commit the tokens or the API key. If one appears in chat, logs
or a committed file, tell the user to rotate it.

## Commands

```bash
cd <skill_dir>
$PY -m pytest                         # offline tests: fake Slack, mocked API; no key needed
$PY -m meeting_bot summarize slides.pdf notes.md [--note "..."] [--new-topic]
                                      # one real summary from local files, printed to stdout
$PY -m meeting_bot                    # run the bot (Socket Mode); keep it under tmux/systemd
```

`summarize` and every DM summary call the paid API (about $0.1 for a 20-page PDF). Ask
before running `summarize` on the user's behalf, and prefer the offline tests for code
changes.

To keep the bot running: `tmux new -d -s meeting-bot "cd <skill_dir> && $PY -m meeting_bot 2>&1 | tee -a logs/bot.log"`
(create `logs/` first). Check startup with the log line `⚡️ Bolt app is running!`.

## Operating rules

- **Run one instance per Slack app.** Socket Mode spreads events across all connections
  that use the same app token, so a second instance (another server, an old tmux window)
  splits a student's conversation between processes. Before starting, check `tmux ls`
  and `ps aux | grep meeting_bot`; stop the old one first.
- Conversation state (notes, material, memos) lives in process memory per
  (user, channel) for 2 hours and is cleared after each summary. Restarting the bot drops
  half-finished conversations; students just start again.
- Files are not written to disk. Logs hold user IDs, file counts, token usage and timing,
  never content. Material is sent to the Anthropic API for the summary.
- Who can use it: everyone in the workspace by default; `ALLOWED_USER_IDS` /
  `ALLOWED_CHANNEL_IDS` in `.env` restrict it. Usage is billed to the API key's owner.

## Customizing

- **Summary rules**: `meeting_bot/prompt.md` (reader and purpose, the role of each line,
  language rules, fictional examples). Keep each rule's reason next to it and keep the
  examples labeled fictional; a single example gets copied verbatim. Verify a change with
  `summarize` on two or three past meetings, then restart the bot.
- **Model and depth**: `SUMMARY_MODEL` (exact model ID; the API has no "latest" alias) and
  `SUMMARY_EFFORT` (`low`…`max`, default `medium`) in `.env`.
- **Bot texts, buttons, card layout**: `meeting_bot/formatting.py`. Slack renders `*bold*`
  only when the closing `*` is followed by a space or line end, so never put a Korean
  particle or `(` right after it; `tests/test_files_config_formatting.py` checks this.
- **Conversation flow**: `meeting_bot/slack_app.py` (`SummaryBot._advance` is the state
  machine). Add or update tests in `tests/test_slack_app.py` with any flow change.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| `config error: ... is not set` at startup | `.env` missing a value, or started from another directory without `.env` |
| Bot never answers | bot not running, or two instances running; check `tmux ls` and `logs/bot.log` |
| Buttons do nothing | interactivity off in the app settings; re-apply `slack_manifest.yaml` and reinstall |
| No greeting when reopening the DM | expected: it greets only an empty DM. Students type "처음부터" or press "새 요약 시작하기" |
| "files:read 권한" error | the app was installed without `files:read`; reinstall from the manifest |
| Literal `*asterisks*` in a bot message | a bold span touches a letter or `(`; see Customizing |
| `첨부한 자료를 처리하지 못했습니다: ...` | the API rejected the input (e.g. PDF too large or too many pages); the message carries the API's reason |
