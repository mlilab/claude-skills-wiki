#!/usr/bin/env python3
"""Offline tests for scripts/gpu_sheet.py: no network, no Google account, no ssh.

    python3 tests/run_tests.py

The test grid copies the layout of the lab sheet's "info" tab with made-up values.
Standard library only. Exits 1 if any test fails.
"""
import argparse
import importlib.util
import io
import os
import shutil
import subprocess
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("gpu_sheet", SKILL / "scripts" / "gpu_sheet.py")
gs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gs)

PROXIES = ["10.0.0.25", "10.0.0.34"]
HEAD = (["Rack", "Server name", "GPU Version", "# of GPUs", "Domain", "Domain 2", "Server IP", "PORT", "Priority"]
        + [f"GPU {i}" for i in range(8)] + ["Memo"])
G0 = 9   # column of GPU 0


def grid():
    pad = [""] * 8
    return [
        pad + ["Proxy Servers IP"],
        pad + [PROXIES[0]],
        pad + [PROXIES[1]],
        [],
        HEAD,
        # old layout: same server, other port -> ignored
        ["", "GPU server 39", "RTX 3090", "8", "s39.example", "", "172.16.0.1", "22", ""] + [""] * 8 + [""],
        ["C3", "GPU server 39", "RTX 3090", "8", "s39.example", "", "192.168.0.204", "10039", "alice(0-3)",
         "alice", "bob", "", "-", "carol", "carol", "dave", "", "ProxyJump error, use 192.168.0.83"],
        ["B4", "GPU server 08", "RTX 3090", "4", "s08.example", "", "192.168.0.191", "10008", "",
         "erin", "", "", "", "-", "-", "-", "-", ""],
    ]


def probe_text(rows, apps=()):
    """nvidia-smi output in the probe's format: rows are (index, mem MiB, util %) per sample."""
    out = ["HOST gpu39"]
    for sample in rows:
        out.append("SAMPLE")
        out += [f"{i}, GPU-{i}, {mem}, 81920, {util}" for i, mem, util in sample]
    out.append("APPS")
    out += [f"GPU-{i}, 1234, 20000" for i in apps]
    return "\n".join(out)


def test_proxies_come_from_the_label_not_memos():
    assert gs.proxy_hosts(grid()) == PROXIES, gs.proxy_hosts(grid())


def test_find_servers_takes_current_rows_only():
    rows = gs.find_servers(gs.Sheet("info", grid(), []))
    assert [(r.server, r.row) for r in rows] == [(39, 6), (8, 7)], rows
    assert rows[0].hosts == PROXIES and rows[0].gpu_cols == {i: G0 + i for i in range(8)}


def test_find_servers_without_port_column():
    g = [["Proxy servers"], ["10.1.1.1"], ["Server", "GPU 0", "GPU 1"], ["server 24", "x", "y"], ["Server 40", "", ""]]
    rows = gs.find_servers(gs.Sheet("t", g, []))
    assert [(r.server, r.hosts) for r in rows] == [(24, ["10.1.1.1"]), (40, ["10.1.1.1"])], rows


def test_ssh_command_pattern():
    cmd = gs.ssh_base("1.2.3.4", 8)
    assert Path(cmd[0]).stem.lower() == "ssh" and cmd[1:3] == ["-p", "10008"], cmd
    assert cmd[-1] == "server08@1.2.3.4", cmd
    assert "IdentitiesOnly yes" in cmd and "BatchMode=yes" in cmd
    assert "BatchMode=yes" not in gs.ssh_base("1.2.3.4", 39, batch=False)


def test_idle_rule():
    text = probe_text(
        [[(0, 4, 0), (1, 20000, 99), (2, 3000, 0), (3, 1, 0), (4, 2, 0)],
         [(0, 4, 0), (1, 20000, 98), (2, 3000, 0), (3, 1, 60), (4, 2, 0)]],
        apps=[1]).replace("4, GPU-4, 2,", "4, GPU-4, [N/A],")
    p = gs.parse_probe(text)
    assert p.ok and p.hostname == "gpu39"
    state = {i: g.idle for i, g in p.gpus.items()}
    # 0 idle; 1 process; 2 memory held; 3 utilization spike in one sample; 4 missing reading
    assert state == {0: True, 1: False, 2: False, 3: False, 4: False}, state


def test_probe_failures():
    assert gs.parse_probe("HOST x\nNO_NVIDIA_SMI").error == "nvidia-smi not found"
    bad = gs.parse_probe("HOST x\nSAMPLE\nNVIDIA-SMI has failed because it couldn't communicate with the NVIDIA driver.")
    assert not bad.ok and "NVIDIA driver" in bad.error, bad
    assert gs.ssh_error("server39@h: Permission denied (publickey,password).").startswith("key not accepted")
    assert gs.ssh_error("ssh: connect to host h port 10039: Connection timed out").startswith("unreachable")
    assert gs.ssh_error("kex_exchange_identification: Connection closed by remote host").startswith("unreachable")


def test_ssh_tries_the_next_proxy_only_when_unreachable():
    calls = []
    answers = {}

    def fake_run(cmd, **kw):
        host = cmd[-2].split("@")[1]
        calls.append(host)
        code, err = answers[host]
        return subprocess.CompletedProcess(cmd, code, "out", err)

    orig, orig_proxies = gs.subprocess.run, gs.PROXIES
    gs.subprocess.run = fake_run
    gs.PROXIES = gs.Proxies(interval=0)
    try:
        answers.update({"a": (255, "Connection closed by a port 10039"), "b": (0, "")})
        p, err, host = gs.ssh_try(["a", "b"], 39, "true", 5)
        assert p is not None and host == "b" and calls == ["a", "b"], (calls, err)
        calls.clear()
        answers.update({"a": (255, "server39@a: Permission denied (publickey,password).")})
        p, err, host = gs.ssh_try(["a", "b"], 39, "true", 5)
        assert p is None and err.startswith("key not accepted") and calls == ["a"], (calls, err)
    finally:
        gs.subprocess.run, gs.PROXIES = orig, orig_proxies


def run_with_servers(alive, blocking=False):
    """A fake ssh: servers in `alive` answer through any proxy; the rest are down. With
    blocking=True the proxies refuse everything. Returns (fake run, list of (proxy, server))."""
    calls = []

    def fake_run(cmd, **kw):
        host = cmd[-2].split("@")[1]
        num = int(cmd[cmd.index("-p") + 1]) - 10000
        calls.append((host, num))
        if not blocking and num in alive:
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return subprocess.CompletedProcess(cmd, 255, "", "kex_exchange_identification: Connection closed by remote host")

    return fake_run, calls


def test_servers_that_are_down_do_not_stop_a_proxy():
    fake_run, calls = run_with_servers(alive={8, 99})
    orig, orig_proxies = gs.subprocess.run, gs.PROXIES
    gs.subprocess.run = fake_run
    gs.PROXIES = gs.Proxies(interval=0, max_refusals=3)
    try:
        assert gs.ssh_try(["a"], 8, "true", 5)[0] is not None
        for num in (40, 41, 42):   # three servers in a row are down
            assert gs.ssh_try(["a"], num, "true", 5)[0] is None
        assert ("a", 8) in calls[1:], calls      # after the third refusal, server08 was asked again...
        assert gs.PROXIES.usable("a")            # ...answered, so the proxy is still used
        assert gs.ssh_try(["a"], 99, "true", 5)[0] is not None
    finally:
        gs.subprocess.run, gs.PROXIES = orig, orig_proxies


def test_a_blocking_proxy_is_left_alone():
    """When even a server that answered earlier is refused, the proxy is not used again in the run."""
    fake_run, calls = run_with_servers(alive={8})
    orig, orig_proxies = gs.subprocess.run, gs.PROXIES
    gs.subprocess.run = fake_run
    gs.PROXIES = gs.Proxies(interval=0, max_refusals=3)
    try:
        gs.ssh_try(["a"], 8, "true", 5)
        fake_blocking, _ = run_with_servers(alive={8}, blocking=True)
        gs.subprocess.run = lambda cmd, **kw: (calls.append(("x", 0)), fake_blocking(cmd, **kw))[1]
        for num in (20, 21, 22):
            gs.ssh_try(["a"], num, "true", 5)
        n = len(calls)
        p, err, _ = gs.ssh_try(["a"], 23, "true", 5)
        assert p is None and err == gs.THROTTLED and len(calls) == n, (calls, err)
    finally:
        gs.subprocess.run, gs.PROXIES = orig, orig_proxies


def test_pacing_is_shared_by_all_proxies():
    pr = gs.Proxies(interval=0.15)
    t0 = gs.time.monotonic()
    for host in ("a", "b", "a", "b"):
        pr.wait_turn(host)
    elapsed = gs.time.monotonic() - t0
    assert 0.4 <= elapsed < 0.8, elapsed   # three gaps of 0.15 s, whichever proxy


def test_a_down_server_is_not_retried_through_the_other_proxy():
    fake_run, calls = run_with_servers(alive={8})
    orig, orig_proxies = gs.subprocess.run, gs.PROXIES
    gs.subprocess.run = fake_run
    gs.PROXIES = gs.Proxies(interval=0, max_refusals=3)
    try:
        gs.ssh_try(["a", "b"], 8, "true", 5)          # proxy a works
        calls.clear()
        p, err, host = gs.ssh_try(["a", "b"], 40, "true", 5)
        assert p is None and err.startswith("unreachable") and calls == [("a", 40)], calls
    finally:
        gs.subprocess.run, gs.PROXIES = orig, orig_proxies


def test_one_password_for_all_servers():
    """The password is asked once, reused for every server, and may be retyped once if the
    first server rejects it."""
    used, prompts = [], []
    typed = iter(["typo", "right"])

    def fake_login(host, num, password, remote):
        used.append((num, password))
        if password == "right":
            return subprocess.CompletedProcess([], 0, "KEY_INSTALLED\n", "")
        return subprocess.CompletedProcess([], 255, "", f"server{num}@{host}: Permission denied (password).")

    import getpass
    orig = (gs.password_login, getpass.getpass, gs.PROXIES)
    gs.password_login = fake_login
    getpass.getpass = lambda prompt="": (prompts.append(prompt), next(typed))[1]
    gs.PROXIES = gs.Proxies(interval=0)
    try:
        with redirect_stdout(io.StringIO()):
            added = gs.add_keys([(17, ["a"]), (19, ["a"]), (21, ["b"])], "ssh-ed25519 AAAA test")
    finally:
        gs.password_login, getpass.getpass, gs.PROXIES = orig
    assert added == {17: "a", 19: "a", 21: "b"}, added
    assert len(prompts) == 2, prompts                         # asked once, retyped once after the typo
    assert used == [(17, "typo"), (17, "right"), (19, "right"), (21, "right")], used


def test_askpass_helper_prints_the_password_without_storing_it():
    with tempfile.TemporaryDirectory() as d:
        orig = gs.STATE_DIR
        gs.STATE_DIR = Path(d)
        try:
            helper = gs.askpass_helper()
            secret = "p@ss w%rd'\"!"
            assert secret not in helper.read_text(encoding="utf-8")
            if os.name != "nt" and not shutil.which("sh"):
                return
            cmd = [str(helper)] if os.name == "nt" else [shutil.which("sh"), str(helper)]
            out = subprocess.run(cmd, env=dict(os.environ, GPU_SHEET_SSH_PASS=secret, PYTHONIOENCODING="utf-8"),
                                 capture_output=True, text=True, encoding="utf-8").stdout
            assert out.rstrip("\r\n") == secret, repr(out)
        finally:
            gs.STATE_DIR = orig


def plan_for(g, merges, gpu_states, server_ok=True):
    sheet = gs.Sheet("info", g, merges)
    servers = gs.find_servers(sheet)
    gpus = {i: gs.Gpu(i, 4 if idle else 30000, 81920, 0, 0 if idle else 1, idle) for i, idle in gpu_states.items()}
    probes = {s.server: gs.Probe(server_ok, "" if server_ok else "unreachable", "h", gpus) for s in servers}
    return {(c.server, c.gpu): c for c in gs.plan(sheet, servers, probes)}


def test_plan_clears_only_idle_named_cells():
    states = {0: True, 1: False, 2: True, 3: True, 4: False, 5: False, 6: True}   # no GPU7 on these servers
    cells = plan_for(grid(), [], states)
    act = {k: c.action for k, c in cells.items() if k[0] == 39}
    assert act == {(39, 0): "clear", (39, 1): "keep", (39, 2): "none", (39, 3): "none",
                   (39, 4): "keep", (39, 5): "keep", (39, 6): "clear", (39, 7): "none"}, act
    assert cells[(39, 7)].status == "absent"
    assert cells[(8, 1)].action == "flag"   # busy GPU with an empty cell


def test_plan_leaves_unchecked_servers_alone():
    cells = plan_for(grid(), [], {i: True for i in range(8)}, server_ok=False)
    assert all(c.action == "none" and c.status == "unknown" for c in cells.values())


def test_merged_cells():
    g = grid()
    # carol's name spans GPU4-GPU5 of server39 as one merged cell; erin's spans GPU0-GPU1 of server08
    g[6][G0 + 4], g[6][G0 + 5] = "carol", ""
    g[7][G0], g[7][G0 + 1] = "erin", ""
    merges = [{"startRowIndex": 6, "endRowIndex": 7, "startColumnIndex": G0 + 4, "endColumnIndex": G0 + 6},
              {"startRowIndex": 7, "endRowIndex": 8, "startColumnIndex": G0, "endColumnIndex": G0 + 2}]
    states = {i: True for i in range(8)}
    states[5] = False
    cells = plan_for(g, merges, states)
    assert cells[(39, 4)].action == "keep" and cells[(39, 5)].action == "keep"   # GPU5 busy: keep carol
    assert cells[(8, 0)].action == "clear" and cells[(8, 1)].action == "none"    # both idle: clear once


def fake_args(**kw):
    base = dict(sheet_id="S", gid=1, servers=None, host=None, apply=True, mem_mib=500, util=5,
                samples=1, workers=2, json=None, no_password=True, details=False)
    base.update(kw)
    return argparse.Namespace(**base)


def test_apply_rereads_and_skips_changed_cells():
    first = gs.Sheet("info", grid(), [])
    second_grid = grid()
    second_grid[6][G0 + 6] = "frank"   # someone took server39 GPU6 while the check ran
    reads = [first, gs.Sheet("info", second_grid, [])]
    cleared = []
    idle = {i: gs.Gpu(i, 4, 81920, 0, 0, True) for i in range(8)}
    orig = (gs.read_sheet, gs.clear_cells, gs.probe)
    gs.read_sheet = lambda sid, gid: reads.pop(0)
    gs.clear_cells = lambda sid, title, cells: cleared.extend(cells)
    gs.probe = lambda hosts, num, *a: gs.Probe(True, "", "h", dict(idle), hosts[0])
    try:
        with redirect_stdout(io.StringIO()) as out:
            code = gs.cmd_check(fake_args())
    finally:
        gs.read_sheet, gs.clear_cells, gs.probe = orig
    assert code == 0
    # alice, bob, carol, carol (server39 GPU0, 1, 4, 5) and erin (server08 GPU0); not frank's new cell
    expected = [(6, G0), (6, G0 + 1), (6, G0 + 4), (6, G0 + 5), (7, G0)]
    assert sorted(cleared) == expected, (cleared, out.getvalue())
    assert "changed while checking: server39 GPU6" in out.getvalue(), out.getvalue()


def test_check_then_apply_clears_only_what_is_still_idle_and_unchanged():
    idle = {i: gs.Gpu(i, 4, 81920, 0, 0, True) for i in range(8)}
    orig = (gs.read_sheet, gs.clear_cells, gs.probe)
    cleared = []
    with tempfile.TemporaryDirectory() as d:
        plan_file = str(Path(d) / "plan.json")
        try:
            gs.read_sheet = lambda sid, gid: gs.Sheet("info", grid(), [])
            gs.clear_cells = lambda sid, title, cells: cleared.extend(cells)
            gs.probe = lambda hosts, num, *a: gs.Probe(True, "", "h", dict(idle), hosts[0])
            with redirect_stdout(io.StringIO()):
                gs.cmd_check(fake_args(apply=False, json=plan_file))
            assert cleared == [], cleared                     # the check alone writes nothing

            later = grid()
            later[7][G0] = "frank"                            # server08 GPU0 taken meanwhile
            gs.read_sheet = lambda sid, gid: gs.Sheet("info", later, [])
            busy_gpu1 = dict(idle)
            busy_gpu1[1] = gs.Gpu(1, 20000, 81920, 99, 1, False)
            gs.probe = lambda hosts, num, *a: gs.Probe(True, "", "h", busy_gpu1 if num == 39 else dict(idle), hosts[0])
            with redirect_stdout(io.StringIO()) as out:
                gs.cmd_apply(argparse.Namespace(plan=plan_file, sheet_id="S", gid=1, mem_mib=500, util=5,
                                                samples=1, workers=2))
        finally:
            gs.read_sheet, gs.clear_cells, gs.probe = orig
    # alice (GPU0), carol (GPU4, GPU5) and dave (GPU6) of server39; not bob (GPU1 now busy) or frank's cell
    assert sorted(cleared) == [(6, G0), (6, G0 + 4), (6, G0 + 5), (6, G0 + 6)], (cleared, out.getvalue())
    assert "server39 GPU1 (bob): no longer idle" in out.getvalue(), out.getvalue()
    assert "server08 GPU0 (erin): the cell changed to 'frank'" in out.getvalue(), out.getvalue()


def test_report_ranks_servers_by_free_gpus():
    def gpus(states):
        return {i: gs.Gpu(i, 4 if idle else 30000, 81920, 0, 0 if idle else 1, idle) for i, idle in enumerate(states)}

    servers = [gs.ServerRow(n, 0, ["h"], {}) for n in (8, 24, 31, 37, 20)]
    probes = {8: gs.Probe(True, "", "h8", gpus([False] * 4)),
              24: gs.Probe(True, "", "h24", gpus([True] * 4)),
              31: gs.Probe(True, "", "h31", gpus([True, False] * 4)),
              37: gs.Probe(True, "", "h37", gpus([True] * 6)),
              20: gs.Probe(False, "unreachable (connection closed)")}
    cells = [gs.Cell(24, i, 0, i, "Long", "idle", "clear") for i in range(4)]
    cells += [gs.Cell(31, i, 0, i, "", "busy", "flag") for i in (1, 3, 5, 7)]
    with redirect_stdout(io.StringIO()) as out:
        gs.report(servers, probes, cells)
    lines = out.getvalue().splitlines()
    ranked = [l.split()[0] for l in lines[1:6]]
    assert ranked == ["server37", "server24", "server31", "server08", "Skipped:"], lines
    assert "4/4 idle   name to clear: GPU0-3 'Long'" in lines[2], lines[2]
    assert "busy, no name: GPU1, GPU3, GPU5, GPU7" in lines[3], lines[3]
    assert "server20  unreachable" in out.getvalue()
    assert "14/22 GPUs idle on 4 checked servers (1 skipped)" in out.getvalue(), out.getvalue()
    assert gs.gpu_ranges([0, 1, 2, 3, 6]) == "GPU0-3, GPU6"


def test_lab_account_required():
    names = ("signed_in_account", "access_token", "ensure_project", "gws_account")
    orig = {n: getattr(gs, n) for n in names}
    cases = [  # (skill sign-in, token works, gws's own account, expected account or None)
        ("someone@mli.kaist.ac.kr", True, None, "someone@mli.kaist.ac.kr"),
        ("someone@gmail.com", True, "someone@mli.kaist.ac.kr", None),          # wrong sign-in: stop
        ("someone@mli.kaist.ac.kr", False, None, None),                        # expired sign-in
        (None, False, "someone@mli.kaist.ac.kr", "someone@mli.kaist.ac.kr"),   # gws's own lab sign-in
        (None, False, "someone@kaist.ac.kr", None),
        (None, False, None, None),
    ]
    try:
        for account, token_ok, gws_acct, expected in cases:
            gs._AUTH = None
            gs.signed_in_account = lambda a=account: a
            gs.access_token = lambda t=token_ok: "TOKEN" if t else None
            gs.ensure_project = lambda a: "gpu-sheet-sync-test"
            gs.gws_account = lambda a=gws_acct: a
            try:
                auth = gs.lab_auth()
                assert auth.account == expected, (account, gws_acct, auth)
                if auth.via == "login":
                    assert auth.env == {"GOOGLE_WORKSPACE_CLI_TOKEN": "TOKEN",
                                        "GOOGLE_WORKSPACE_PROJECT_ID": "gpu-sheet-sync-test"}, auth.env
            except gs.AccountError as e:
                assert expected is None, (account, gws_acct, str(e))
                assert "@mli.kaist.ac.kr" in str(e)
    finally:
        for n, f in orig.items():
            setattr(gs, n, f)
        gs._AUTH = None


def test_install_key_command_is_idempotent():
    sh = shutil.which("sh")
    if not sh:
        print("  (skipped: no sh)")
        return
    key = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAITestKey user@laptop"
    with tempfile.TemporaryDirectory() as home:
        ssh = Path(home) / ".ssh"
        ssh.mkdir()
        (ssh / "authorized_keys").write_text("ssh-rsa OLDKEY other@host", encoding="utf-8")   # no final newline
        env = dict(os.environ, HOME=home)
        for _ in range(2):
            p = subprocess.run([sh, "-c", gs.install_key_command(key)], env=env, capture_output=True, text=True)
            assert p.returncode == 0 and "KEY_INSTALLED" in p.stdout, p.stderr
        lines = (ssh / "authorized_keys").read_text(encoding="utf-8").splitlines()
        assert lines == ["ssh-rsa OLDKEY other@host", key], lines


def main():
    tests = [(n, f) for n, f in globals().items() if n.startswith("test_")]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"PASS {name}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL {name}\n  {e}")
    print(f"{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
