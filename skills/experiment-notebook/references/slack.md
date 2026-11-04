# Slack experiment notifications

The notifier is a separate process. It reads experiment records and live observations, writes
its own private outbox, and sends concise lifecycle messages to one configured channel or DM.
The HTTP server and its GET endpoints never send messages. Browser activity is not required.

## Configure once

Install a Slack app with a bot token in the intended workspace. Grant `chat:write`, and invite
the bot to a target channel. For a DM target selected by user ID, also grant `im:write`.
The relevant methods are [chat.postMessage](https://docs.slack.dev/reference/methods/chat.postMessage/)
and [conversations.open](https://docs.slack.dev/reference/methods/conversations.open/).

Set `SLACK_BOT_TOKEN` in the notifier's environment through your secret manager or a hidden
terminal prompt. Do not paste the value into an agent prompt, command argument, notebook JSON,
or the shared skill. This terminal example does not place the value in shell history:

```bash
read -r -s -p "Slack bot token: " SLACK_BOT_TOKEN
export SLACK_BOT_TOKEN
```

Select one destination:

```bash
python3 <skill>/scripts/notebook.py configure-slack --root <book> --channel C0123456789 --token-env SLACK_BOT_TOKEN
```

Or use `--user U0123456789` for one person's DM. These IDs are examples, not defaults.
Configuration itself makes no Slack request. It records only the target and secret reference.
An existing private token file can be selected with `--token-file /path/to/private/slack-token`
instead. On POSIX, that file must have private permissions such as 0600. The skill never writes
the token file. It does not reuse GitHub credentials or another project's Slack settings.

The configuration in `notebook.json` is:

```json
{
  "notifications": {
    "slack": {
      "enabled": true,
      "channel": "C0123456789",
      "token_env": "SLACK_BOT_TOKEN",
      "progress_interval_seconds": 1800,
      "max_attempts": 3,
      "events": ["started", "attached", "resumed", "progress", "completed", "stopped", "failed", "attention"]
    }
  }
}
```

Use exactly one of `channel` or `user`. A channel can also be an existing DM conversation ID.
Notifications are disabled when this configuration is absent. Set `enabled` to false to stop
notifications. `events` can select a subset. Set the progress interval to 0 to disable periodic
progress notices. Otherwise changed phase or progress can produce at most one progress notice
per interval. The default is 30 minutes. State transitions do not wait for that interval.

## Run independently of the browser

Connect each experiment's `watch` source as described in [server.md](server.md). Start the
notifier before the real experiment so it can observe the planned-to-running transition.

```bash
python3 <skill>/scripts/notebook.py monitor --root <book> --once --dry-run
python3 <skill>/scripts/notebook.py monitor --root <book>
```

Dry-run previews new event text without a Slack call or state writes. The normal monitor polls
every 20 seconds and stays in the foreground. Use the environment's background-process support
or an existing supervisor to keep it running. Installing a recurring service is a separate task.
Keep the same private notebook/outbox across restarts. One monitor can run per notebook.

`--once` without dry-run samples observations and attempts at most one eligible message.
Other events remain queued. Continuous mode drains them across subsequent ticks. Use
`--interval` to choose a polling interval from one to 60 seconds. Notification failure does not
stop, restart, or change an experiment.

| Event | Behavior |
| --- | --- |
| Started | A recorded non-running experiment becomes running. |
| Monitoring attached | The first observation already shows an active experiment. This is not a new-start claim. |
| Resumed | Activity resumes after interruption or a terminal state. |
| Progress | Observed phase or counters changed and the configured interval elapsed. |
| Completed / stopped / failed | The actual observed terminal state changed. A process still cleaning up does not trigger a premature terminal alert. |
| Needs attention | The source cannot establish normal activity, such as a missing recorded PID. This does not claim a proven failure. |

Existing completed/stopped/failed experiments do not produce historical notifications on first
attachment. A planned experiment is not announced as running. Inactivity alone is not a failure.
Each message contains experiment ID, short title, event, available counters, and event time.
No raw logs, error bodies, credentials, source paths, or artifact contents are included.

## Delivery state and recovery

```bash
python3 <skill>/scripts/notebook.py notification-status --root <book>
```

The dashboard also shows delivery counts. Private files `.notifications.sqlite3` and
`.notifications-lock.sqlite3` remain outside the served site. They hold observation history,
event keys, attempts, receipts, and manual resolutions. They do not hold the bot token.
Known successes are not resent after monitor restart. Pending progress is coalesced, and a
terminal/attention event supersedes obsolete pending progress. Ordered lifecycle events for
one experiment do not overtake an earlier pending delivery.

Posts are paced locally. HTTP 429 responses defer queued sends until `Retry-After`, following
Slack's [rate-limit guidance](https://docs.slack.dev/apis/web-api/rate-limits/).
Each event has at most three automatic delivery attempts by default. A known rejection such as
invalid authentication is recorded as failed. Missing credentials block delivery without
consuming attempts. A changed destination does not reroute an existing queued message.

A response loss, ambiguous server error, or interrupted in-flight delivery remains `uncertain`.
It is not automatically resent. Slack documents that `internal_error` and `fatal_error` can
follow partial success in [chat.postMessage errors](https://docs.slack.dev/reference/methods/chat.postMessage/#errors).
This design reduces duplicates but does not promise exactly-once delivery.

After checking the actual Slack conversation, stop only the notification monitor and record a
resolution. Keep the research process running:

```bash
python3 <skill>/scripts/notebook.py resolve-notification --root <book> --event <event-id> --outcome sent --note "Verified in Slack"
```

Use `--outcome not-sent` only when non-delivery is established and another attempt is intended.
That requeues the same event while retaining prior attempts and the resolution note. The same
command can requeue a known failed event after its configuration problem is fixed. It does not
change the event's original destination. Restart the monitor afterward.
