"""Slack uses fake transports only. Test files stay in tests/.tmp/."""

from contextlib import contextmanager, redirect_stdout
from functools import partial
import http.client
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.error

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / "scripts"))
import notebook
import notifications as notify

TEMP = SKILL / "tests/.tmp"


class FakeClient:
    def __init__(self, calls, failure=None):
        self.calls, self.failure = calls, failure

    def send(self, cfg, message):
        self.calls.append((notify.destination(cfg), message))
        if self.failure:
            raise self.failure
        return "123.456"


class Response(io.BytesIO):
    def __init__(self, data, headers=None):
        super().__init__(json.dumps(data).encode())
        self.headers = headers or {}


class NotificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        TEMP.mkdir(exist_ok=True)

    @classmethod
    def tearDownClass(cls):
        TEMP.rmdir()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=TEMP)
        self.root = Path(self.temp.name)
        self.calls = []
        self.cfg = {"language": "ko", "timezone": "UTC", "notifications": {"slack": {
            "enabled": True, "channel": "C0123456789", "token_env": "NOTEBOOK_TEST_SLACK_TOKEN",
            "progress_interval_seconds": 60,
        }}}
        self.slack = notify.settings(self.cfg)
        self.record = notebook.blank_record("001-measurement", 1, "Synthetic measurement", "none")
        self.network = patch("notifications.urllib.request.urlopen", side_effect=AssertionError("Live network is forbidden in tests"))
        self.network.start()

    def tearDown(self):
        self.network.stop()
        self.temp.cleanup()

    @contextmanager
    def ledger(self):
        with notify.monitor_lock(self.root):
            ledger = notify.Ledger(self.root)
            try:
                yield ledger
            finally:
                ledger.close()

    def factory(self, cfg):
        return FakeClient(self.calls)

    def observation(self, status, completed=0):
        return {"observed_status": status, "phase": "measurement", "completed": completed, "total": 8}

    def cli(self, *arguments):
        with patch.object(sys, "argv", ["notebook.py", *arguments, "--root", str(self.root)]), redirect_stdout(io.StringIO()) as output:
            code = notebook.main()
        self.assertEqual(code, 0, output.getvalue())
        return json.loads(output.getvalue())

    def test_start_and_stop_survive_monitor_restart_without_duplicates(self):
        with self.ledger() as ledger:
            ledger.ingest([(self.record, self.observation("planned"))], self.cfg, 0)
            ledger.ingest([(self.record, self.observation("running"))], self.cfg, 1)
            self.assertEqual(ledger.deliver_one(self.slack, 1, self.factory)["delivery"], "sent")
        with self.ledger() as ledger:
            self.assertEqual(ledger.ingest([(self.record, self.observation("running"))], self.cfg, 2), 0)
            ledger.ingest([(self.record, self.observation("stopped"))], self.cfg, 3)
            ledger.deliver_one(self.slack, 3, self.factory)
            self.assertEqual(ledger.ingest([(self.record, self.observation("stopped"))], self.cfg, 4), 0)
        self.assertEqual(len(self.calls), 2)
        self.assertIn("시작", self.calls[0][1])
        self.assertIn("중단", self.calls[1][1])
        self.assertEqual(notify.status(self.root)["counts"], {"sent": 2})

    def test_attach_does_not_replay_past_completions_or_fake_start(self):
        past = dict(self.record, id="002-old-study", status="completed")
        with self.ledger() as ledger:
            self.assertEqual(ledger.ingest([(past, self.observation("completed")), (self.record, self.observation("running"))], self.cfg, 0), 1)
            ledger.deliver_one(self.slack, 0, self.factory)
        self.assertEqual(len(self.calls), 1)
        self.assertIn("진행 중 · 감시 시작", self.calls[0][1])
        self.assertNotIn("002-old-study", self.calls[0][1])

    def test_progress_is_throttled_and_pending_progress_is_coalesced(self):
        with self.ledger() as ledger:
            ledger.ingest([(self.record, self.observation("running"))], self.cfg, 0)
            ledger.deliver_one(self.slack, 0, self.factory)
            self.assertEqual(ledger.ingest([(self.record, self.observation("running", 3))], self.cfg, 10), 0)
            self.assertEqual(ledger.ingest([(self.record, self.observation("running", 4))], self.cfg, 61), 1)
            self.assertEqual(ledger.ingest([(self.record, self.observation("running", 6))], self.cfg, 122), 1)
            self.assertEqual(notify.status(self.root)["counts"]["superseded"], 1)
            ledger.ingest([(self.record, self.observation("completed", 8))], self.cfg, 123)
            ledger.deliver_one(self.slack, 124, self.factory)
        self.assertEqual(len(self.calls), 2)
        self.assertIn("완료", self.calls[-1][1])
        self.assertIn("8/8", self.calls[-1][1])

    def test_resume_and_new_execution_are_distinct_observed_events(self):
        with self.ledger() as ledger:
            ledger.ingest([(self.record, self.observation("running"))], self.cfg, 0)
            ledger.ingest([(self.record, self.observation("failed"))], self.cfg, 1)
            ledger.ingest([(self.record, self.observation("running"))], self.cfg, 2)
            rows = ledger.db.execute("SELECT kind,generation FROM events ORDER BY rowid").fetchall()
            self.assertEqual([(r[0], r[1]) for r in rows], [("attached", 0), ("failed", 0), ("resumed", 1)])

    def test_attention_does_not_claim_definite_failure(self):
        with self.ledger() as ledger:
            ledger.ingest([(self.record, self.observation("running"))], self.cfg, 0)
            ledger.ingest([(self.record, self.observation("attention"))], self.cfg, 1)
            row = ledger.db.execute("SELECT kind,message FROM events WHERE kind='attention'").fetchone()
            self.assertIsNotNone(row)
            self.assertNotIn("실패", row[1])

    def test_retry_after_and_bounded_rate_limit_retries(self):
        failure = lambda cfg: FakeClient(self.calls, notify.DeliveryError("retry", "rate_limited", 30))
        with self.ledger() as ledger:
            ledger.ingest([(self.record, self.observation("running"))], self.cfg, 0)
            self.assertEqual(ledger.deliver_one(self.slack, 0, failure)["delivery"], "pending")
            self.assertEqual(ledger.deliver_one(self.slack, 29, failure)["delivery"], "waiting")
            ledger.deliver_one(self.slack, 30, failure)
            self.assertEqual(ledger.deliver_one(self.slack, 60, failure)["delivery"], "failed")
            self.assertEqual(ledger.deliver_one(self.slack, 90, self.factory)["delivery"], "idle")
            self.assertEqual(ledger.db.execute("SELECT count(*) FROM attempts").fetchone()[0], 3)
        self.assertEqual(len(self.calls), 3)

    def test_uncertain_delivery_needs_explicit_resolution_before_retry(self):
        failure = lambda cfg: FakeClient(self.calls, notify.DeliveryError("uncertain", "transport_error"))
        with self.ledger() as ledger:
            ledger.ingest([(self.record, self.observation("running"))], self.cfg, 0)
            event = ledger.deliver_one(self.slack, 0, failure)["event"]
        with self.ledger() as ledger:
            self.assertEqual(ledger.deliver_one(self.slack, 100, self.factory)["delivery"], "idle")
        notify.resolve(self.root, event, "not-sent", "Checked the recipient conversation.", 110)
        with self.ledger() as ledger:
            self.assertEqual(ledger.deliver_one(self.slack, 111, self.factory)["delivery"], "sent")
            self.assertEqual(ledger.db.execute("SELECT count(*) FROM resolutions").fetchone()[0], 1)
        self.assertEqual(len(self.calls), 2)

    def test_interrupted_inflight_request_becomes_uncertain(self):
        with self.ledger() as ledger:
            ledger.ingest([(self.record, self.observation("running"))], self.cfg, 0)
            with ledger.db:
                ledger.db.execute("UPDATE events SET status='sending',attempts=1")
                ledger.db.execute("INSERT INTO attempts SELECT id,0,'sending',NULL FROM events")
        with self.ledger() as ledger:
            self.assertEqual(notify.status(self.root)["counts"], {"uncertain": 1})
            self.assertEqual(ledger.deliver_one(self.slack, 100, self.factory)["delivery"], "idle")

    def test_only_one_monitor_and_one_post_per_cooldown(self):
        with self.ledger() as ledger:
            with self.assertRaises(ValueError):
                with notify.monitor_lock(self.root):
                    self.fail("A second monitor acquired the lock")
            other = dict(self.record, id="002-other-study")
            ledger.ingest([(self.record, self.observation("running")), (other, self.observation("running"))], self.cfg, 0)
            ledger.deliver_one(self.slack, 0, self.factory)
            self.assertEqual(ledger.deliver_one(self.slack, 0.5, self.factory)["delivery"], "waiting")
            ledger.deliver_one(self.slack, 1.2, self.factory)
        self.assertEqual(len(self.calls), 2)

    def test_missing_token_and_changed_destination_never_send(self):
        with self.ledger() as ledger, patch.dict("os.environ", {"NOTEBOOK_TEST_SLACK_TOKEN": ""}):
            ledger.ingest([(self.record, self.observation("running"))], self.cfg, 0)
            self.assertEqual(ledger.deliver_one(self.slack, 0)["delivery"], "blocked")
            self.assertEqual(ledger.db.execute("SELECT attempts FROM events").fetchone()[0], 0)
            changed = dict(self.slack, channel="C9876543210")
            self.assertEqual(ledger.deliver_one(changed, 1, self.factory)["error"], "destination_changed")
        self.assertEqual(self.calls, [])

    def test_lifecycle_delivery_does_not_overtake_a_pending_start(self):
        retry = lambda cfg: FakeClient(self.calls, notify.DeliveryError("retry", "transport_error", 30))
        with self.ledger() as ledger:
            ledger.ingest([(self.record, self.observation("running"))], self.cfg, 0)
            ledger.deliver_one(self.slack, 0, retry)
            ledger.ingest([(self.record, self.observation("completed", 8))], self.cfg, 1)
            self.assertEqual(ledger.deliver_one(self.slack, 2, self.factory)["delivery"], "idle")
            self.assertEqual(ledger.deliver_one(self.slack, 30, self.factory)["delivery"], "sent")
            self.assertEqual(ledger.deliver_one(self.slack, 32, self.factory)["delivery"], "sent")
        self.assertIn("완료", self.calls[-1][1])

    def test_dry_run_and_disabled_monitor_write_nothing(self):
        load_config = lambda root: self.cfg
        load_records = lambda root: [(root, self.record)]
        observe = lambda *args: self.observation("running")
        before = list(self.root.iterdir())
        result = notify.run_monitor(self.root, load_config, load_records, observe, dry_run=True)
        self.assertEqual(result["messages"][0]["kind"], "attached")
        self.assertEqual(before, list(self.root.iterdir()))
        disabled = {"notifications": {"slack": {"enabled": False}}}
        result = notify.run_monitor(self.root, lambda root: disabled, load_records, observe, once=True)
        self.assertEqual(result["delivery"], "disabled")
        self.assertEqual(before, list(self.root.iterdir()))

    def test_cli_configuration_stores_references_and_status_is_read_only(self):
        self.cli("init")
        self.cli("configure-slack", "--user", "U0123456789", "--token-env", "NOTEBOOK_TEST_SLACK_TOKEN", "--progress-interval", "600")
        config = json.loads((self.root / "notebook.json").read_text())
        self.assertEqual(config["notifications"]["slack"]["user"], "U0123456789")
        self.assertNotIn("xoxb-", (self.root / "notebook.json").read_text())
        self.assertEqual(self.cli("notification-status")["counts"], {})
        self.assertFalse((self.root / notify.DATABASE).exists())
        with self.assertRaises(ValueError):
            notify.settings({"notifications": {"slack": {"token": "forbidden-literal"}}})

    def test_http_notification_status_does_not_send_or_initialize_ledger(self):
        self.cli("init")
        self.cli("configure-slack", "--channel", "C0123456789", "--token-env", "NOTEBOOK_TEST_SLACK_TOKEN")
        self.cli("build")
        server = notebook.ThreadingHTTPServer(("127.0.0.1", 0), partial(notebook.Handler, root=self.root))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
            connection.request("GET", "/api/notifications")
            response = connection.getresponse()
            data = json.loads(response.read())
            connection.close()
            self.assertEqual(response.status, 200)
            self.assertTrue(data["enabled"])
            self.assertEqual(data["counts"], {})
            self.assertNotIn("C0123456789", json.dumps(data))
            self.assertNotIn("NOTEBOOK_TEST_SLACK_TOKEN", json.dumps(data))
            self.assertFalse((self.root / notify.DATABASE).exists())
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)

    def test_message_masks_known_secrets_and_escapes_mentions(self):
        secret = "xoxb-" + "synthetic-sensitive-value"
        record = dict(self.record, title=secret + "\n<@U0123456789>")
        with self.ledger() as ledger:
            ledger.ingest([(record, self.observation("running"))], self.cfg, 0)
            ledger.deliver_one(self.slack, 0, self.factory)
        self.assertNotIn(secret, self.calls[0][1])
        self.assertNotIn("<@", self.calls[0][1])
        self.assertNotIn(secret.encode(), (self.root / notify.DATABASE).read_bytes())

    def test_http_transport_handles_dm_and_uncertain_response(self):
        secret = "xoxb-" + "synthetic-bot-token"
        cfg = dict(self.slack, user="U0123456789")
        cfg.pop("channel")
        with patch.dict("os.environ", {cfg["token_env"]: secret}), patch("notifications.urllib.request.urlopen", side_effect=[Response({"ok": True, "channel": {"id": "D0123456789"}}), Response({"ok": True, "ts": "123.456"})]) as request:
            self.assertEqual(notify.SlackClient(cfg).send(cfg, "Synthetic notice"), "123.456")
            first = request.call_args_list[0].args[0]
            second = request.call_args_list[1].args[0]
            self.assertTrue(first.full_url.endswith("/conversations.open"))
            self.assertEqual(json.loads(second.data)["channel"], "D0123456789")
            self.assertFalse(json.loads(second.data)["mrkdwn"])
        with patch.dict("os.environ", {self.slack["token_env"]: secret}), patch("notifications.urllib.request.urlopen", side_effect=TimeoutError):
            with self.assertRaises(notify.DeliveryError) as caught:
                notify.SlackClient(self.slack).send(self.slack, "Synthetic notice")
            self.assertEqual(caught.exception.outcome, "uncertain")
            self.assertNotIn(secret, str(caught.exception))

    def test_http_429_reads_retry_after_and_internal_error_is_uncertain(self):
        secret = "xoxb-" + "synthetic-bot-token"
        error = urllib.error.HTTPError("https://slack.com/api/chat.postMessage", 429, "rate limited", {"Retry-After": "45"}, None)
        with patch.dict("os.environ", {self.slack["token_env"]: secret}), patch("notifications.urllib.request.urlopen", side_effect=error):
            with self.assertRaises(notify.DeliveryError) as caught:
                notify.SlackClient(self.slack).send(self.slack, "Synthetic notice")
            self.assertEqual((caught.exception.outcome, caught.exception.retry_after), ("retry", 45))
        with patch.dict("os.environ", {self.slack["token_env"]: secret}), patch("notifications.urllib.request.urlopen", return_value=Response({"ok": False, "error": "internal_error"})):
            with self.assertRaises(notify.DeliveryError) as caught:
                notify.SlackClient(self.slack).send(self.slack, "Synthetic notice")
            self.assertEqual(caught.exception.outcome, "uncertain")


if __name__ == "__main__":
    unittest.main()
