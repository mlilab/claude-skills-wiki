"""Synthetic evidence only. All test files stay under this skill's tests/.tmp/."""

from functools import partial
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import threading
import unittest
import xml.etree.ElementTree as ET
from urllib.error import HTTPError
from urllib.request import urlopen

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / "scripts"))
import notebook
import sessions
import views

TEMP = SKILL / "tests" / ".tmp"


class NotebookTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        TEMP.mkdir(exist_ok=True)

    @classmethod
    def tearDownClass(cls):
        TEMP.rmdir()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=TEMP)
        self.base = Path(self.temp.name)
        self.root = self.base / "book"
        self.cli("init", "--title", "테스트 노트북", "--language", "ko")

    def tearDown(self):
        self.temp.cleanup()

    def cli(self, command, *args, success=True):
        result = subprocess.run([sys.executable, "-B", str(SKILL / "scripts/notebook.py"), command, "--root", str(self.root), *args], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0 if success else 1, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def new(self, slug="baseline", parent="none"):
        result = self.cli("new", "--slug", slug, "--title", "기준 실험", "--parent", parent)
        path = Path(result["record"])
        return path, json.loads(path.read_text())

    def save(self, path, data):
        path.write_text(json.dumps(data, ensure_ascii=False))

    def test_full_report_and_source_immutability(self):
        path, record = self.new()
        source = self.base / "evidence.jsonl"
        secret = "sk-ant-" + "synthetic-test-secret"
        rows = [
            {"type": "assistant", "message": {"role": "assistant", "model": "test-model", "content": [
                {"type": "text", "text": "<script>alert(1)</script>"},
                {"type": "tool_use", "id": "tool-1", "name": "Bash", "input": {"command": "test", "api_key": secret}}]}},
            {"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "tool-1", "is_error": False, "content": "ok"}]}},
        ]
        source.write_text("\n".join(json.dumps(r) for r in rows))
        source.chmod(0o444)
        before = (source.read_bytes(), source.stat().st_mtime_ns)
        record.update(status="completed", research_outcome="가설 지지 안 됨", started_at="2026-01-01T10:00:00+09:00", ended_at="2026-01-01T10:10:00+09:00")
        record["execution"] = [{"phase": "run", "commit": "a" * 40, "dirty": False}]
        record["sections"] = {key: "근거 기반 설명" for key in notebook.SECTIONS}
        record["feedback"] = {"status": "received", "verdict": "추가 검토", "interpretation": None, "rules": ["다음 실행은 별도 결정"]}
        record["artifacts"] = [{"id": "attempt-1", "label": "실행 근거", "path": str(source), "kind": "trajectory"}]
        record["iterations"] = [{"group": "measurement series", "iteration": 1, "description": None, "document": None, "evidence": "attempt-1", "result": "미기록"}]
        self.save(path, record)
        record_before = path.read_bytes()
        self.assertEqual(self.cli("check")["errors"], [])
        self.cli("build")
        self.assertEqual(before, (source.read_bytes(), source.stat().st_mtime_ns))
        self.assertEqual(record_before, path.read_bytes())
        page = (self.root / "site/reports/001-baseline/artifact-attempt-1.html").read_text()
        self.assertIn("Tool · Bash · success", page)
        self.assertIn(hashlib.sha256(before[0]).hexdigest(), page)
        self.assertNotIn(secret, page)
        self.assertNotIn("<script>alert(1)</script>", page)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", page)
        report = (self.root / "site/reports/001-baseline/analysis.html").read_text()
        self.assertIn("질문 또는 변경점", report)
        self.assertIn("measurement series", report)
        self.assertIn("추가 검토", report)
        self.assertIn("a" * 40, report)

    def test_number_reservation_and_parent_are_independent(self):
        self.new()
        (self.root / "experiments/002-unfinished-reservation").mkdir()
        _, third = self.new("branch", "001-baseline")
        self.assertEqual(third["number"], 3)
        self.assertIsNone(third["started_at"])
        self.assertEqual(third["parent"], "001-baseline")
        self.cli("new", "--slug", "bad", "--title", "Bad", "--parent", "002-missing", success=False)
        self.assertFalse((self.root / ".reservation-lock").exists())

    def test_cycles_and_short_execution_hash_are_rejected(self):
        first_path, first = self.new()
        self.new("child", "001-baseline")
        first["parent"] = "002-child"
        first["execution"] = [{"phase": "run", "commit": "abcdef0", "dirty": None}]
        self.save(first_path, first)
        errors = self.cli("check", success=False)["errors"]
        self.assertTrue(any("cycle" in e for e in errors))
        self.assertTrue(any("40-character" in e for e in errors))

    def test_pending_feedback_warns_without_inventing_values(self):
        path, record = self.new()
        record["status"] = "stopped"
        record["feedback"]["status"] = "pending"
        self.save(path, record)
        result = self.cli("check")
        self.assertTrue(any("verdict pending" in w for w in result["warnings"]))
        self.assertEqual(json.loads(path.read_text())["usage"], {})

    def test_artifact_limits_and_credential_filename(self):
        path, record = self.new()
        auth = self.base / "auth.json"
        auth.write_text('{"password": "synthetic"}')
        record["artifacts"] = [{"id": "bad", "path": str(auth), "kind": "json"}]
        self.save(path, record)
        self.assertTrue(any("Credential-like" in e for e in self.cli("check", success=False)["errors"]))
        source = self.base / "large.txt"
        source.write_text("longer than limit")
        record["artifacts"] = [{"id": "large", "path": str(source), "kind": "text"}]
        self.save(path, record)
        cfg = json.loads((self.root / "notebook.json").read_text())
        cfg["max_artifact_bytes"] = 3
        self.save(self.root / "notebook.json", cfg)
        self.assertTrue(any("exceeds" in e for e in self.cli("check", success=False)["errors"]))

    def test_output_symlink_cannot_write_outside_notebook(self):
        self.new()
        elsewhere = self.base / "elsewhere"
        elsewhere.mkdir()
        (self.root / "site").symlink_to(elsewhere, target_is_directory=True)
        result = self.cli("build", success=False)
        self.assertIn("escapes", result["error"])
        self.assertEqual(list(elsewhere.iterdir()), [])

    def test_read_only_http_serves_only_manifest(self):
        record_path, record = self.new()
        state = self.base / "live-state.json"
        state.write_text(json.dumps({"state": "running", "phase": "measurement", "progress": {"completed": 3, "total": 8}}))
        record["watch"] = {"state_file": str(state)}
        self.save(record_path, record)
        record_before = record_path.read_bytes()
        self.cli("build")
        site = self.root / "site"
        (site / "leak.html").symlink_to(self.root / "GUIDE.md")
        manifest = json.loads((self.root / ".site-manifest.json").read_text())
        manifest["files"].append("leak.html")
        self.save(self.root / ".site-manifest.json", manifest)
        server = notebook.ThreadingHTTPServer(("127.0.0.1", 0), partial(notebook.Handler, root=self.root))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"
        try:
            with urlopen(base + "/", timeout=3) as response:
                self.assertEqual(response.status, 200)
                self.assertIn("frame-ancestors 'none'", response.headers["Content-Security-Policy"])
            with urlopen(base + "/api/status", timeout=3) as response:
                observation = json.load(response)["experiments"][0]
                self.assertEqual(observation["recorded_status"], "planned")
                self.assertEqual(observation["observed_status"], "running")
                self.assertEqual(observation["completed"], 3)
            state.write_text(json.dumps({"state": "running", "phase": "measurement", "progress": {"completed": 5, "total": 8}}))
            with urlopen(base + "/api/status", timeout=3) as response:
                self.assertEqual(json.load(response)["experiments"][0]["completed"], 5)
            self.assertEqual(record_before, record_path.read_bytes())
            for route in ("/notebook.json", "/GUIDE.md", "/%2e%2e/notebook.json", "/leak.html", "/reports/"):
                with self.assertRaises(HTTPError) as caught:
                    urlopen(base + route, timeout=3)
                self.assertEqual(caught.exception.code, 404, route)
                caught.exception.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)

    @unittest.skipUnless(Path("/proc/self/stat").exists(), "Linux process evidence")
    def test_process_identity_and_cleanup_observation(self):
        _, record = self.new()
        tick = Path("/proc/self/stat").read_text().rsplit(")", 1)[1].split()[19]
        record.update(status="completed", watch={"pid": os.getpid(), "pid_start_ticks": tick})
        self.assertEqual(notebook.observe(self.root, record)["observed_status"], "cleaning_up")
        record.update(status="running", watch={"pid": os.getpid(), "pid_start_ticks": "0"})
        self.assertEqual(notebook.observe(self.root, record)["observed_status"], "attention")
        record["watch"] = {"pid": os.getpid()}
        self.assertEqual(notebook.observe(self.root, record)["observed_status"], "attention")

    def test_tool_status_uses_returned_evidence(self):
        self.assertEqual(views.tool_status(None, True), "unknown")
        self.assertEqual(views.tool_status({}, True), "success")
        self.assertEqual(views.tool_status({"is_error": True}, True), "fail")
        self.assertEqual(views.tool_status({"is_error": "false"}, True), "unknown")
        self.assertEqual(views.tool_status({"output": '{"exit_code": 2}'}), "fail")
        self.assertEqual(views.tool_status({"output": "probably passed"}), "unknown")
        nested = json.dumps({"output": json.dumps({"api_key": "private-string"})})
        self.assertNotIn("private-string", views.redact(nested))

    def test_codex_calls_match_outputs_without_fabricated_success(self):
        rows = [
            {"type": "response_item", "payload": {"type": "function_call", "name": "exec", "call_id": "one", "arguments": '{"command":"test"}'}},
            {"type": "response_item", "payload": {"type": "function_call_output", "call_id": "one", "output": '{"exit_code":0,"output":"done"}'}},
            {"type": "response_item", "payload": {"type": "custom_tool_call", "name": "unknown", "call_id": "two", "input": "command"}},
        ]
        view = views.trajectory("\n".join(json.dumps(r) for r in rows))
        self.assertIn("Tool · exec · success", view)
        self.assertIn("Tool · unknown · unknown", view)
        self.assertIn("done", view)

    def test_wrong_feedback_or_description_types_fail_before_render(self):
        path, record = self.new()
        record["feedback"]["rules"] = "not a list"
        record["iterations"] = [{"group": "series", "iteration": 1, "description": 42, "result": "recorded"}]
        self.save(path, record)
        errors = self.cli("build", success=False)["errors"]
        self.assertTrue(any("rules" in e for e in errors))
        self.assertTrue(any("description" in e for e in errors))
        self.assertFalse((self.root / ".site-manifest.json").exists())

    def test_bound_sessions_use_metadata_and_response_messages(self):
        project = self.base / "project"
        project.mkdir()
        path = self.base / "rollout.jsonl"
        rows = [
            {"type": "session_meta", "payload": {"cwd": str(project), "id": "synthetic"}},
            {"type": "response_item", "timestamp": "test", "payload": {"role": "user", "content": [{"type": "input_text", "text": "report requirement"}]}},
            {"type": "response_item", "payload": {"role": "assistant", "phase": "analysis", "content": [{"type": "output_text", "text": "report hidden"}]}},
        ]
        path.write_text("\n".join(json.dumps(r) for r in rows))
        self.assertIsNotNone(sessions.metadata(path, project))
        read = sessions.messages(path, "codex", contains="report")
        self.assertEqual(read["matched"], 1)
        self.assertEqual(read["messages"][0]["line"], 2)
        unrelated = self.base / "unrelated.jsonl"
        unrelated.write_text(json.dumps({"type": "session_meta", "payload": {"cwd": "/unrelated"}}) + "\nTHIS BODY MUST NOT BE PARSED")
        self.assertIsNone(sessions.metadata(unrelated, project))

    def test_claude_candidates_encode_underscores_and_confirm_cwd(self):
        project = self.base / "research_project"
        project.mkdir()
        claude = self.base / "claude"
        folder = claude / re.sub(r"[^A-Za-z0-9]", "-", str(project))
        folder.mkdir(parents=True)
        path = folder / "session.jsonl"
        path.write_text(json.dumps({"type": "user", "cwd": str(project), "sessionId": "test", "message": {"role": "user", "content": "record experiment"}}))
        self.assertEqual(list(sessions.candidates(project, self.base / "empty", claude)), [(path, "claude")])
        self.assertIsNotNone(sessions.metadata(path, project, "claude"))
        self.assertEqual(sessions.messages(path, "claude")["matched"], 1)

    def test_nonsoftware_study_needs_no_git_ai_or_reviewer(self):
        path, record = self.new("lab-measurement")
        record.update(status="completed", started_at="2026-01-01T10:00:00+00:00", ended_at="2026-01-01T11:00:00+00:00")
        record["sections"] = {key: "Recorded methods and observations" for key in notebook.SECTIONS}
        record["execution"] = [{"phase": "measurement", "protocol_version": "v2", "instrument": "scale"}]
        record["quality"] = {"calibration": "verified against reference mass"}
        record["usage"] = {"instrument_hours": 1, "samples_measured": 12}
        self.save(path, record)
        checked = self.cli("check")
        self.assertEqual(checked["errors"], [])
        self.assertEqual(checked["warnings"], [])
        self.cli("build")
        report = (self.root / "site/reports/001-lab-measurement/analysis.html").read_text()
        self.assertIn("instrument_hours", report)
        self.assertNotIn("실행 commit", report)
        self.assertNotIn("검토 의견 대기", report)
        self.assertNotIn("api_estimated_cost", report)
        self.assertEqual(record["iterations"], [])
        self.assertEqual(record["feedback"]["status"], "not_applicable")

    def test_qualitative_study_custom_sections_and_english_interface(self):
        cfg_path = self.root / "notebook.json"
        cfg = json.loads(cfg_path.read_text())
        cfg.update(language="en", sections={"purpose": "Research question", "source_selection": "Source selection", "results": "Themes", "analysis": "Limitations"})
        self.save(cfg_path, cfg)
        path, record = self.new("interview-analysis")
        self.assertEqual(list(record["sections"]), list(cfg["sections"]))
        record["sections"] = {"purpose": "Explore participants' experiences.", "source_selection": "Recorded inclusion criteria.", "results": "Qualitative themes; no numerical metric.", "analysis": "Interpretation is limited to these sources.", "reflexivity": "Additional researcher reflections."}
        self.save(path, record)
        self.assertEqual(self.cli("build")["errors"], [])
        report = (self.root / "site/reports/001-interview-analysis/analysis.html").read_text()
        self.assertIn('<html lang="en">', report)
        self.assertLess(report.index("Research question"), report.index("Source selection"))
        self.assertIn("Additional researcher reflections.", report)
        self.assertNotIn("Proposer", report)
        self.assertNotIn("commit:", report)
        self.assertIn("Research lineage", (self.root / "site/index.html").read_text())

    def test_review_policy_is_opt_in(self):
        _, first = self.new()
        self.assertEqual(first["feedback"]["status"], "not_applicable")
        cfg_path = self.root / "notebook.json"
        cfg = json.loads(cfg_path.read_text())
        cfg["request_feedback"] = True
        self.save(cfg_path, cfg)
        _, second = self.new("reviewed-study")
        self.assertEqual(second["feedback"]["status"], "pending")

    def git_fixture(self):
        repository = self.base / "source"
        repository.mkdir()
        self.run_git(repository, "init", "--template=", "--initial-branch=main")
        (repository / "analysis.py").write_text("print('version one')\n")
        self.run_git(repository, "add", "analysis.py")
        self.run_git(repository, "commit", "-m", "Synthetic source")
        return repository

    def run_git(self, repository, *arguments):
        return subprocess.run(["git", "-c", "user.name=Test Fixture", "-c", "user.email=fixture@example.invalid", "-c", "commit.gpgSign=false", "-c", "core.hooksPath=/dev/null", "-C", str(repository), *arguments], check=True, capture_output=True, text=True).stdout.strip()

    def fingerprint(self, repository):
        return {str(p.relative_to(repository)): (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns)
                for p in repository.rglob("*") if p.is_file()}

    def test_git_connection_and_preparation_capture_are_read_only(self):
        repository = self.git_fixture()
        self.run_git(repository, "remote", "add", "origin", "https://fixture-user:fixture-password@example.invalid/team/study.git?private-query=1")
        path, record = self.new()
        source_before = self.fingerprint(repository)
        connected = self.cli("connect-git", "--repository", str(repository))
        self.assertEqual(connected["current_checkout"]["remotes"]["origin"], "https://example.invalid/team/study.git")
        self.assertNotIn("fixture-password", json.dumps(connected))
        captured = self.cli("capture-git", "--experiment", record["id"], "--phase", "prepared")
        self.assertEqual(captured["snapshot"]["stage"], "preparation")
        self.assertEqual(json.loads(path.read_text())["execution"], [])
        self.cli("git-status")
        self.assertEqual(source_before, self.fingerprint(repository))
        self.cli("capture-git", "--experiment", record["id"], "--stage", "execution", "--phase", "historical", success=False)
        saved = json.loads(path.read_text())
        saved.update(status="running", started_at="2026-01-01T10:00:00+00:00")
        self.save(path, saved)
        self.assertTrue(any("no recorded actual execution commit" in warning for warning in self.cli("check")["warnings"]))
        self.cli("build")
        report = (self.root / "site/reports/001-baseline/analysis.html").read_text()
        self.assertIn("실제 실행 commit 미기록", report)
        self.assertNotIn("fixture-password", (self.root / "site/index.html").read_text())
        self.assertEqual(source_before, self.fingerprint(repository))

    def test_git_capture_keeps_execution_commit_after_later_changes(self):
        repository = self.git_fixture()
        path, record = self.new()
        self.cli("connect-git", "--repository", str(repository))
        record.update(status="running", started_at="2026-01-01T10:00:00+00:00")
        self.save(path, record)
        first = self.cli("capture-git", "--experiment", record["id"], "--stage", "execution", "--phase", "initial run")["snapshot"]["commit"]
        (repository / "analysis.py").write_text("print('version two')\n")
        self.run_git(repository, "add", "analysis.py")
        self.run_git(repository, "commit", "-m", "Synthetic revision")
        report = self.cli("capture-git", "--experiment", record["id"], "--stage", "reporting", "--phase", "write report")
        self.assertNotEqual(first, report["snapshot"]["commit"])
        saved = json.loads(path.read_text())
        self.assertEqual(len(saved["execution"]), 1)
        self.assertEqual(saved["execution"][0]["commit"], first)
        self.cli("build")
        page = (self.root / "site/reports/001-baseline/analysis.html").read_text()
        self.assertIn(first, page)
        self.assertIn(report["snapshot"]["commit"], page)

    def test_lineage_diagram_has_only_explicit_parent_edges(self):
        self.new()
        self.new("independent")
        self.new("branch-a", "001-baseline")
        self.new("branch-b", "001-baseline")
        self.cli("build")
        page = (self.root / "site/index.html").read_text()
        svg = ET.fromstring(re.search(r"<svg\b.*?</svg>", page, re.S).group())
        edges = {(node.attrib["data-parent"], node.attrib["data-child"]) for node in svg.iter() if "data-parent" in node.attrib}
        self.assertEqual(edges, {("001-baseline", "003-branch-a"), ("001-baseline", "004-branch-b")})
        self.assertEqual(len([n for n in svg.iter() if "data-node" in n.attrib]), 4)
        self.assertIn("reports/003-branch-a/analysis.html", page)

    def test_monitor_reads_nested_progress_without_changing_source(self):
        _, record = self.new()
        state = self.base / "nested-state.json"
        state.write_text(json.dumps({"run": {"status": "working", "phase": "analysis", "done": 5, "count": 8, "heartbeat": "2026-01-01T00:00:00Z"}}))
        record["watch"] = {"state_file": str(state), "state_map": {"working": "running"}, "field_paths": {"state": "run.status", "phase": "run.phase", "completed": "run.done", "total": "run.count", "last_activity_at": "run.heartbeat"}}
        before = (state.read_bytes(), state.stat().st_mtime_ns)
        observation = notebook.observe(self.root, record)
        self.assertEqual(observation["observed_status"], "running")
        self.assertEqual((observation["completed"], observation["total"]), (5, 8))
        self.assertEqual(observation["phase"], "analysis")
        self.assertEqual(before, (state.read_bytes(), state.stat().st_mtime_ns))

    def test_report_keeps_hypotheses_parent_differences_and_required_fixes(self):
        path, record = self.new()
        record["sections"] = {key: "Recorded explanation" for key in notebook.SECTIONS}
        record["hypotheses"] = [{"statement": "Calibration reduces drift.", "criteria": "Compare drift with the reference condition."}]
        record["comparisons"] = [{"item": "Calibration interval", "before": "daily", "after": "hourly", "reason": "Test the source of drift."}]
        record["follow_up"] = [{"change": "Check the sensor mount.", "reason": "Residual drift remains.", "status": "needed", "evidence": "measurement log"}]
        self.save(path, record)
        self.cli("build")
        page = (self.root / "site/reports/001-baseline/analysis.html").read_text()
        for value in ("Calibration reduces drift.", "daily", "hourly", "Check the sensor mount.", "Residual drift remains."):
            self.assertIn(value, page)
        self.assertEqual(json.loads(path.read_text())["follow_up"][0]["status"], "needed")


if __name__ == "__main__":
    unittest.main()
