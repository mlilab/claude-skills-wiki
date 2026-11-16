#!/usr/bin/env python3
"""Check Markdown before posting it as an OpenReview comment.

    python3 check_openreview_md.py reply.md [--limit N]
    python3 check_openreview_md.py --diff draft.md reply.md

The first form prints the length and warns about source that OpenReview will
display differently from what it looks like. Venues set different length
limits, so the length is checked only against a --limit you give. The second
lists every word that differs between a draft and its formatted version,
ignoring Markdown markup.
"""
import argparse
import difflib
import re
import sys

PUNCT = re.escape("!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~")
HTML_TAGS = ("a|b|br|center|code|details|div|em|font|h[1-6]|hr|i|img|li|mark|ol|p|pre|small|span|"
             "strong|sub|summary|sup|table|td|th|tr|u|ul")


def js_length(text):
    """Length as OpenReview counts it (UTF-16 code units)."""
    return len(text.encode("utf-16-le")) // 2


def check_math(span, line, warn):
    """Markdown runs before MathJax, so simulate its backslash escapes on one $...$ span."""
    seen, lost, i = [], set(), 0
    while i < len(span):
        if span[i] == "\\" and i + 1 < len(span) and re.match(f"[{PUNCT}]", span[i + 1]):
            if span[i + 1] not in "\\_*":  # \_ and \* are meant to reach MathJax as _ and *
                lost.add("\\" + span[i + 1])
            seen.append(span[i + 1])
            i += 2
        else:
            seen.append(span[i])
            i += 1
    seen = "".join(seen)
    if lost:
        doubled = ", ".join("\\" + s for s in sorted(lost))
        warn(line, f"math loses {', '.join(sorted(lost))}: write {doubled}")
    if re.search(r"(?<!\\)\\\s", seen):
        warn(line, r"math line break \\ arrives as \ : write \\\\")
    if re.search(r"(?<!\\)\*", span):
        warn(line, r"'*' in math can turn into italics: write \* or \ast")


def check(path, limit):
    text = open(path, encoding="utf-8").read()
    lines = text.split("\n")
    problems = []
    warn = lambda n, msg: problems.append((n, msg))

    in_fence = False
    for n, line in enumerate(lines, 1):
        prev = lines[n - 2] if n > 1 else ""
        nxt = lines[n] if n < len(lines) else ""
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if re.fullmatch(r"\s*(-{3,}|={3,})\s*", line) and prev.strip() and not prev.lstrip().startswith("|"):
            warn(n, "'---' right under text turns that text into a heading: add a blank line above")
        if line.startswith("|") and prev.startswith(">"):
            warn(n, "table right after a quote line is drawn inside the quote: add a blank line above")
        if line.startswith("|") and not nxt.startswith("|"):
            after = next((l for l in lines[n:] if l.strip()), "")
            if after.startswith("**Table"):
                warn(n, "caption is below the table: this format puts it above")
        if line.startswith(">") and line[1:].strip() and nxt.strip():
            if not nxt.startswith(">"):
                warn(n + 1, "line has no '>' but continues the quote, so it joins the line above")
            elif nxt[1:].strip() and not (line.endswith("\\") or line.endswith("  ")):
                warn(n, "quote lines run together: end this line with '\\'")
        if re.match(r"#{4,}\s", line):
            warn(n, "'####' and smaller headings are smaller than normal text")
        plain = re.sub(r"`[^`]*`", "", line)
        if re.search(r"!\[[^\]]*\]\([^)]*\)", plain):
            warn(n, "images show as literal text: link to the PDF page instead")
        if re.search(rf"</?({HTML_TAGS})(\s[^<>]*)?/?>", plain, re.I):
            warn(n, "raw HTML shows as literal text")

    plain = re.sub(r"```.*?```|`[^`\n]*`", lambda m: re.sub(r"[^\n]", " ", m.group()), text, flags=re.S)
    for m in re.finditer(r"\$\$(.+?)\$\$|(?<![\\$])\$([^$\n]+?)\$", plain, re.S):
        span = m.group(1) if m.group(1) is not None else m.group(2)
        check_math(span, plain.count("\n", 0, m.start()) + 1, warn)

    length = js_length(text.strip())
    over = limit is not None and length > limit
    print(f"{path}: {length:,} characters" + (f" (limit {limit:,})" if limit is not None else ""))
    if over:
        print(f"  over the limit by {length - limit:,}")
    for n, msg in sorted(problems):
        print(f"  line {n}: {msg}")
    if not problems:
        print("  no rendering problems found")
    return not over and not problems


def words(path):
    """Words of a file with Markdown markup removed, so only wording is compared."""
    out = []
    for line in open(path, encoding="utf-8").read().split("\n"):
        while m := re.match(r"\s*(>|#{1,6}(?=\s|$)|[*+-](?=\s|$))", line):
            line = line[m.end():]  # quote, heading and bullet markers count only where a line starts
        if re.fullmatch(r"[\s|:-]*-[\s|:-]*|\s*([*_])(\s*\1){2,}\s*", line):
            continue  # table rules and ---, *** or ___ lines
        if line.lstrip().startswith("|"):
            line = re.sub(r"(?<!\\)\|", " ", line)  # table cell borders
        line = re.sub(rf"\\([{PUNCT}])", r"\1", line)  # Markdown drops the backslash of an escape
        for token in line.split():
            token = (re.sub(r"[*`]", "", token) or token.strip("`")).rstrip("\\")  # bold, italics and red; a lone * stays
            if token:
                out.append(token)
    return out


def diff(old_path, new_path):
    old, new = words(old_path), words(new_path)
    removed, added, moved = [], [], []  # (changed text, the three words before it)
    for op, a0, a1, b0, b1 in difflib.SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
        if op in ("delete", "replace"):
            removed.append((" ".join(old[a0:a1]), " ".join(old[max(0, a0 - 3):a0])))
        if op in ("insert", "replace"):
            added.append((" ".join(new[b0:b1]), " ".join(new[max(0, b0 - 3):b0])))
    for gone in list(removed):  # the same text removed in one place and added in another
        match = next((a for a in added if a[0] == gone[0]), None)
        if match:
            removed.remove(gone)
            added.remove(match)
            moved.append(match)
    for label, items in (("moved", moved), ("removed", removed), ("added", added)):
        for t, before in items:
            print(f'{label}: {t}' + (f'   (after "{before}")' if before else ""))
    if not (moved or removed or added):
        print("no word changes")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # a cp1252 stdout garbles dashes and fails on symbols like α or ≤
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+")
    ap.add_argument("--limit", type=int, help="the venue's comment length limit, if you want it checked")
    ap.add_argument("--diff", action="store_true", help="compare the wording of two files")
    args = ap.parse_args()
    if args.diff:
        if len(args.files) != 2:
            ap.error("--diff takes a draft and its formatted version")
        diff(*args.files)
    else:
        ok = all([check(f, args.limit) for f in args.files])
        sys.exit(0 if ok else 1)
