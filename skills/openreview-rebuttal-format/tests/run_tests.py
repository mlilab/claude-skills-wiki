#!/usr/bin/env python3
"""Check scripts/check_openreview_md.py against examples/ and a file of known problems.

    python3 tests/run_tests.py

Standard library only. Exits 1 if any test fails.
"""
import os
import subprocess
import sys
import tempfile

SKILL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHECKER = os.path.join(SKILL, "scripts", "check_openreview_md.py")
DRAFT = os.path.join(SKILL, "examples", "draft.md")
REPLY = os.path.join(SKILL, "examples", "reply.md")

# Source with one of each rendering problem, and a phrase of the warning each should raise.
BAD = """Opening paragraph
---

> Quote line
| a | b |

#### Too small

<b>raw html</b> and ![fig](fig.png)

$a \\, b$ and $x * y * z$
"""
BAD_WARNINGS = [
    "'---' right under text",
    "drawn inside the quote",
    "'####' and smaller headings",
    "raw HTML",
    "images show as literal text",
    "math loses \\,",
    "'*' in math",
]


def run(*args):
    """Run the checker and return (exit code, stdout decoded as UTF-8)."""
    p = subprocess.run([sys.executable, CHECKER, *args], capture_output=True)
    return p.returncode, p.stdout.decode("utf-8") + p.stderr.decode("utf-8", "replace")


def write_temp(tmp, name, text):
    path = os.path.join(tmp, name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


def test_example_reply_renders_cleanly(tmp):
    code, out = run(REPLY)
    assert code == 0, out
    assert "no rendering problems found" in out, out


def test_known_problems_are_reported(tmp):
    code, out = run(write_temp(tmp, "bad.md", BAD))
    assert code == 1, out
    missing = [w for w in BAD_WARNINGS if w not in out]
    assert not missing, f"not reported: {missing}\n{out}"


def test_length_limit(tmp):
    code, out = run(REPLY, "--limit", "100")
    assert code == 1 and "over the limit" in out, out
    code, out = run(REPLY, "--limit", "100000")
    assert code == 0, out


def test_diff_lists_only_headings_and_markers(tmp):
    code, out = run("--diff", DRAFT, REPLY)
    assert code == 0, out
    assert "W1 –" in out, out  # the en dash survives a non-UTF-8 console
    assert "Sure, we now added this comparison." in out, out
    assert "Table R1:" in out, out
    for kept in ("keeps more accuracy", "Appendix F", "214-226", "fell out of the window"):
        assert kept not in out, f"{kept!r} reported as changed\n{out}"


def test_diff_handles_symbols(tmp):
    a = write_temp(tmp, "a.md", "hello world\n")
    b = write_temp(tmp, "b.md", "hello – α ≤ β world\n")
    code, out = run("--diff", a, b)
    assert code == 0, out
    assert "added: – α ≤ β" in out, out


def main():
    tests = [(n, f) for n, f in globals().items() if n.startswith("test_")]
    failed = 0
    with tempfile.TemporaryDirectory() as tmp:
        for name, fn in tests:
            try:
                fn(tmp)
                print(f"PASS {name}")
            except AssertionError as e:
                failed += 1
                print(f"FAIL {name}\n{e}")
    print(f"{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
