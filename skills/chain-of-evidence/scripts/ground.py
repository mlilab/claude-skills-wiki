#!/usr/bin/env python3
"""Ground / Verify a tagged CoE representation or composed draft.

Usage:
  python ground.py DRAFT.md --bundle BUNDLE_DIR [--out OUT_DIR]
                   [--judgments judgments.json] [--require-reviews]

Writes OUT_DIR/ledger.json, OUT_DIR/ground_report.md, OUT_DIR/review_packet.md
Exit code 0 = no blocking issues, 1 = blocking issues, 2 = usage error.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from coe_lib import (decimals_of, TAG_RE, SENT_END_RE, Num, find_numbers, numbers_match, parse_tag,
                     strip_tags, split_sentences, read_lines, parse_location, json_lookup, numeric_leaves,
                     unit_from_key, parse_bib, load_cache, title_similarity, overclaim_hits,
                     load_config, to_json)

REVIEW_TYPES = {"cite": "citation_entailment", "code": "method_code_alignment",
                "log": "method_log_alignment"}


# ---------------------------------------------------------------------------
# Parsing the draft into claims
# ---------------------------------------------------------------------------
def split_paragraphs(text: str):
    """Yield (start_line, paragraph_text). Skips fenced code and headings."""
    buf, start, fence = [], None, False
    for i, line in enumerate(text.splitlines(), 1):
        if line.strip().startswith("```"):
            fence = not fence
            if buf:
                yield start, "\n".join(buf)
                buf, start = [], None
            continue
        if fence or line.lstrip().startswith("#"):
            if buf:
                yield start, "\n".join(buf)
                buf, start = [], None
            continue
        if not line.strip():
            if buf:
                yield start, "\n".join(buf)
                buf, start = [], None
            continue
        if start is None:
            start = i
        buf.append(line)
    if buf:
        yield start, "\n".join(buf)


def sentence_bounds(par: str, pos: int) -> tuple[int, int]:
    """Start/end offsets of the sentence containing pos (tags are treated as part of text)."""
    clean = par
    s = 0
    for m in SENT_END_RE.finditer(clean[:pos]):
        # a sentence end must not sit inside a tag
        if not _inside_tag(par, m.start()):
            s = m.end()
    e = len(par)
    for m in SENT_END_RE.finditer(clean, pos):
        if not _inside_tag(par, m.start()):
            e = m.end()
            break
    return s, e


def _inside_tag(par: str, idx: int) -> bool:
    for m in TAG_RE.finditer(par):
        if m.start() <= idx < m.end():
            return True
    return False


def extract_claims(text: str):
    claims, untagged = [], []
    auto = 0
    for pline, par in split_paragraphs(text):
        tags = [parse_tag(m) for m in TAG_RE.finditer(par)]
        prev_end = 0
        for t in tags:
            ss, se = sentence_bounds(par, t.start)
            seg_start = max(ss, prev_end)
            segment = strip_tags(par[seg_start:t.start])
            sentence = strip_tags(par[ss:se]).strip()
            prev_end = t.end
            if t.type == "context":
                continue
            auto += 1
            cid = t.id or f"C{auto}"
            claims.append({
                "id": cid, "type": t.type, "targets": t.targets, "flags": t.flags,
                "sentence": sentence, "segment": segment.strip(), "line": pline + par[:t.start].count("\n"),
                "tag": t.raw,
            })
        # untagged sentences containing numbers
        cursor = 0
        bounds = []
        for m in SENT_END_RE.finditer(par):
            if _inside_tag(par, m.start()):
                continue
            bounds.append((cursor, m.end()))
            cursor = m.end()
        if cursor < len(par):
            bounds.append((cursor, len(par)))
        for a, b in bounds:
            raw = par[a:b]
            if TAG_RE.search(raw):
                continue
            visible = re.sub(r"`[^`]*`", "", raw)
            visible = re.sub(r"^\s*(?:[-*]|\d+[.)])\s+", "", visible, flags=re.M)  # list markers
            visible = re.sub(r"\[[^\]]*\]\([^)]*\)", "", visible)  # links
            nums = [n for n in find_numbers(visible)]
            if nums and visible.strip():
                untagged.append({"line": pline + par[:a].count("\n"), "sentence": raw.strip(),
                                 "numbers": [n.raw for n in nums]})
    return claims, untagged


# ---------------------------------------------------------------------------
# Verification per claim type
# ---------------------------------------------------------------------------
def claim_number(seg: str) -> Num | None:
    nums = find_numbers(seg)
    return nums[-1] if nums else None


def evidence_numbers(bundle: str, target: str, cfg: dict):
    """Return (numbers, snippet, error)."""
    path, kind, loc = parse_location(target)
    full = os.path.join(bundle, path)
    if kind == "json":
        try:
            obj = json.load(open(full, encoding="utf-8"))
        except FileNotFoundError:
            return None, None, f"file not found: {path}"
        except json.JSONDecodeError as e:
            return None, None, f"invalid JSON in {path}: {e}"
        try:
            val = json_lookup(obj, loc)
        except KeyError:
            return None, None, f"key not found: {path}#{loc}"
        nums = []
        for k, v in numeric_leaves(val, loc, strings=isinstance(val, str)):
            n = Num(float(v), unit_from_key(k or loc), decimals_of(v), str(v))
            nums.append((n, f"{path}#{k or loc}"))
        return nums, f"{path}#{loc} = {json.dumps(val, ensure_ascii=False)[:300]}", None
    lines = read_lines(full)
    if lines is None:
        return None, None, f"file not found: {path}"
    if kind == "file":
        return None, None, f"numeric claim needs a line or key locator: {target}"
    if kind == "line":
        if not (1 <= loc <= len(lines)):
            return None, None, f"line {loc} out of range ({len(lines)} lines) in {path}"
        w = cfg.get("num_line_window", 0)
        a, b = max(1, loc - w), min(len(lines), loc + w)
    else:
        a, b = loc
        if not (1 <= a <= b <= len(lines)):
            return None, None, f"range {a}-{b} out of range ({len(lines)} lines) in {path}"
    nums, snippet = [], []
    for i in range(a, b + 1):
        nums += [(n, f"{path}:{i}") for n in find_numbers(lines[i - 1])]
        snippet.append(f"{i:>5}: {lines[i - 1]}")
    return nums, "\n".join(snippet), None


def verify_num(c, bundle, cfg):
    cn = claim_number(c["segment"])
    if cn is None:
        return "unsupported", "no_number_in_claim", "tag is not preceded by a number in its sentence", None
    if not c["targets"]:
        return "unsupported", "malformed_tag", "num tag has no evidence locator", None
    approx = bool(APPROX_RE.search(c["segment"][:cn.start]))
    mrr = None if approx else cfg.get("max_round_rel", 0.01)
    snippets = []
    for t in c["targets"]:
        nums, snip, err = evidence_numbers(bundle, t, cfg)
        if err:
            return "unsupported", "broken_ref", err, None
        snippets.append(snip)
        for e, where in nums:
            if numbers_match(cn, e, cfg["rel_tol"], mrr):
                c["claim_value"] = cn.raw
                ctx = ""
                m_ = re.search(r":(\d+)$", where)
                if m_ and snip:
                    for ln in snip.splitlines():
                        if ln.strip().startswith(m_.group(1) + ":"):
                            ctx = " — line: " + ln.split(":", 1)[1].strip()[:80]
                return "supported", None, f"{cn.raw} matched {e.raw} at {where}{ctx}", "\n".join(snippets)
    c["claim_value"] = cn.raw
    if any(numbers_match(cn, e, cfg["rel_tol"]) for t in c["targets"]
           for e, _ in (evidence_numbers(bundle, t, cfg)[0] or [])):
        return ("unsupported", "coarse_rounding",
                f"{cn.raw} only matches after rounding by more than {mrr:.0%}; state the precise value "
                f"or mark it approximate ('about', '~')", "\n".join(snippets))
    return ("unsupported", "value_mismatch",
            f"claimed {cn.raw} not found (tol {cfg['rel_tol']:.0%}) in {', '.join(c['targets'])}",
            "\n".join(snippets))


APPROX_RE = re.compile(r"(?:~|≈|\babout|\bapproximately|\bapprox\.?|\broughly|\baround|\bnearly|약|대략)\s*$", re.I)
RESULT_WORDS = re.compile(r"\b(?:our|ours|we (?:achieve|obtain|reach|get)|achiev\w*|reach\w*|best|outperform\w*|"
                          r"state[- ]of[- ]the[- ]art|sota)\b|우리|달성|최고", re.I)


def verify_nonfinal(c, cfg):
    """A result-sounding sentence that cites a non-final source must say so explicitly."""
    srcs = cfg.get("final_result_sources") or []
    if not srcs or "headline" in c["flags"] or "nonfinal" in c["flags"]:
        return None
    if all(any(t == s or t.startswith(s) for s in srcs) for t in c["targets"]):
        return None
    if RESULT_WORDS.search(c["sentence"]):
        return ("unsupported", "unlabelled_nonfinal",
                "result-sounding sentence cites a non-final source; use the final run's value, or add the "
                "'nonfinal' flag AND state the context (ablation / subset / exploratory) in the sentence")
    return None


def verify_absent(c, bundle):
    path = next((t for t in c["targets"] if not t.startswith("re=")), None)
    pat = next((t[3:] for t in c["targets"] if t.startswith("re=")), None)
    if not path or not pat:
        return "unsupported", "malformed_tag", "absent tag needs a file and re=PATTERN", None
    lines = read_lines(os.path.join(bundle, path))
    if lines is None:
        return "unsupported", "broken_ref", f"file not found: {path}", None
    try:
        rx = re.compile(pat, re.I)
    except re.error as e:
        return "unsupported", "malformed_tag", f"bad regex {pat}: {e}", None
    hits = [f"{i}: {l}" for i, l in enumerate(lines, 1) if rx.search(l)]
    if hits:
        return ("unsupported", "absence_violated", f"pattern /{pat}/ occurs in {path}: {hits[0][:100]}",
                "\n".join(hits[:5]))
    return "supported", None, f"pattern /{pat}/ does not occur in {path} ({len(lines)} lines)", None


def verify_headline(c, cfg):
    srcs = cfg.get("final_result_sources") or []
    if "headline" not in c["flags"] or not srcs:
        return None
    for t in c["targets"]:
        if not any(t == s or t.startswith(s) for s in srcs):
            return ("unsupported", "cherry_pick",
                    f"headline evidence {t} is not one of final_result_sources {srcs}")
    return None


def verify_cite(c, bib, cache, cfg):
    if not c["targets"]:
        return "unsupported", "malformed_tag", "cite tag has no key", None
    snippets = []
    for key in c["targets"]:
        if key not in bib:
            return "unsupported", "cite_not_in_bib", f"key '{key}' not in bibliography", None
        rec = cache.get(key)
        if not rec or rec.get("status") != "verified":
            st = rec.get("status") if rec else "absent"
            return ("unsupported", "cite_not_verified",
                    f"'{key}' has no verified retrieval record (cache status: {st})", None)
        sim = title_similarity(bib[key].get("title", ""), rec.get("title", ""))
        if sim < cfg["title_match_threshold"]:
            return ("unsupported", "cite_title_mismatch",
                    f"bib title vs retrieved title similarity {sim:.2f} for '{key}'", None)
        abst = rec.get("abstract") or "(no abstract cached — judge from title/source only)"
        snippets.append(f"[{key}] {rec.get('title')}\nsource: {rec.get('source', '')}\n{abst[:1500]}")
    return "supported", None, "keys resolved to verified records", "\n\n".join(snippets)


def verify_span(c, bundle, cfg):
    if not c["targets"]:
        return "unsupported", "malformed_tag", f"{c['type']} tag has no locator", None
    snippets = []
    for t in c["targets"]:
        path, kind, loc = parse_location(t)
        lines = read_lines(os.path.join(bundle, path))
        if lines is None:
            return "unsupported", "broken_ref", f"file not found: {path}", None
        if kind == "line":
            if not (1 <= loc <= len(lines)):
                return "unsupported", "broken_ref", f"line {loc} out of range in {path}", None
            w = cfg["line_window"]
            a, b = max(1, loc - w), min(len(lines), loc + w)
            if c["type"] == "code":
                a, b = enclosing_block(lines, loc, a, b)
        elif kind == "range":
            a, b = loc
            if not (1 <= a <= b <= len(lines)):
                return "unsupported", "broken_ref", f"range {a}-{b} out of range in {path}", None
        elif kind == "file":
            a, b = 1, min(len(lines), 200)
        else:
            return "unsupported", "malformed_tag", f"unsupported locator for {c['type']}: {t}", None
        snippets.append(f"--- {path}:{a}-{b}\n" + "\n".join(f"{i:>5}: {lines[i - 1]}" for i in range(a, b + 1)))
    return "supported", None, "span exists", "\n".join(snippets)


def arith_hint(c, by_id) -> str:
    """Try simple relations between supporting values and the number stated in the conclusion."""
    target = claim_number(c["sentence"])
    vals = []
    for d in c["targets"]:
        v = by_id[d].get("claim_value")
        if v:
            n = find_numbers(v)
            if n:
                vals.append(n[0].value / (100 if n[0].unit == "%" else 1))
    if target is None or len(vals) < 2:
        return "arith: n/a"
    a, b = vals[0], vals[1]
    cands = {"a-b": a - b, "b-a": b - a, "a/b": a / b if b else None, "b/a": b / a if a else None,
             "(a-b)/b %": (a - b) / b * 100 if b else None, "(b-a)/a %": (b - a) / a * 100 if a else None,
             "(a-b)/a %": (a - b) / a * 100 if a else None, "(b-a)/b %": (b - a) / b * 100 if b else None}
    for name, v in cands.items():
        if v is not None and numbers_match(target, Num(v, "", 6, str(v)), 0.01):
            return f"arith: {target.raw} ~ {name} of {vals[:2]}"
    return f"arith: no simple relation found for {target.raw} from {vals[:2]} — judge must check"


def enclosing_block(lines, loc, a, b):
    """Expand a single code line to its enclosing def/class block (indentation based)."""
    indent = lambda l: len(l) - len(l.lstrip())
    for i in range(loc, 0, -1):
        l = lines[i - 1]
        if re.match(r"\s*(?:async\s+)?(?:def|class|function|fn|func)\b", l) and (i == loc or indent(l) < indent(lines[loc - 1]) or not lines[loc - 1].strip()):
            base = indent(l)
            end = i
            for j in range(i + 1, len(lines) + 1):
                lj = lines[j - 1]
                if lj.strip() and indent(lj) <= base:
                    break
                end = j
            return i, max(end, b) if end - i < 200 else b
    return a, b


def claim_hash(c) -> str:
    h = hashlib.sha1(json.dumps([c["type"], c["sentence"], c["targets"], c.get("evidence_snippet")],
                                ensure_ascii=False).encode()).hexdigest()
    return h[:10]


def resolve_derived(claims_by_id, only_reset=False):
    for c in claims_by_id.values():
        if c["type"] == "derive":
            c.update(status=None, reason=None, detail=None)
            c.pop("review", None)
    state = {}

    def visit(cid, stack):
        c = claims_by_id[cid]
        if c["type"] != "derive":
            return c["status"]
        if cid in state:
            return state[cid]
        if cid in stack:
            c.update(status="unsupported", reason="derive_cycle", detail="cyclic derive reference")
            state[cid] = "unsupported"
            return "unsupported"
        stack.add(cid)
        statuses = []
        for dep in c["targets"]:
            if dep not in claims_by_id:
                c.update(status="unsupported", reason="derive_missing", detail=f"unknown claim id {dep}")
                state[cid] = "unsupported"
                return "unsupported"
            statuses.append((dep, visit(dep, stack)))
        stack.discard(cid)
        bad = [d for d, s in statuses if s == "unsupported"]
        if not c["targets"]:
            c.update(status="unsupported", reason="malformed_tag", detail="derive tag lists no claims")
        elif bad:
            c.update(status="unsupported", reason="derive_broken", detail=f"depends on unsupported {bad}")
        elif any(s == "partial" for _, s in statuses):
            c.update(status="partial", reason="derive_pending", detail="depends on partial claims")
        else:
            c.update(status="supported", reason=None,
                     detail=f"derived from {c['targets']}; {arith_hint(c, claims_by_id)}")
            c["review"] = "pending"
            c["review_kind"] = "derivation_check"
        state[cid] = c["status"]
        return c["status"]

    for cid in claims_by_id:
        visit(cid, set())


def apply_judgments(claims, judgments, min_votes=1):
    for c in claims:
        j = judgments.get(c["id"])
        if j is None or c.get("review") != "pending":
            continue
        votes = j if isinstance(j, list) else [j]
        fresh = [v for v in votes if not v.get("hash") or v.get("hash") == c["hash"]]
        if len(fresh) < len(votes):
            c["stale_votes"] = len(votes) - len(fresh)
        votes = fresh
        if len(votes) < min_votes:
            c["review_votes"] = dict(Counter(v.get("verdict") for v in votes))
            continue
        tally = Counter(v.get("verdict") for v in votes)
        verdict, n = tally.most_common(1)[0]
        c["review_votes"] = dict(tally)
        reasons = "; ".join(v.get("reason", "") for v in votes if v.get("reason"))
        if verdict == "supported" and n > len(votes) / 2:
            c["review"] = "pass"
        elif verdict == "unsupported" and n > len(votes) / 2:
            c["review"] = "fail"
            c.update(status="unsupported", reason="judge_rejected", detail=reasons[:500])
        else:
            c["review"] = "fail"
            c.update(status="partial", reason="judge_partial", detail=reasons[:500])


# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("draft")
    ap.add_argument("--bundle", default=None, help="evidence directory (default: draft's folder)")
    ap.add_argument("--config", default=None)
    ap.add_argument("--out", default=None, help="output dir (default: BUNDLE/coe_out)")
    ap.add_argument("--judgments", default=None, help="JSON of LLM-judge verdicts keyed by claim id")
    ap.add_argument("--min-votes", type=int, default=3,
                    help="judge votes (matching the current claim hash) needed to decide a review")
    ap.add_argument("--require-reviews", action="store_true",
                    help="final verify: pending reviews count as blocking")
    a = ap.parse_args()

    bundle = os.path.abspath(a.bundle or os.path.dirname(os.path.abspath(a.draft)))
    cfg = load_config(bundle, a.config)
    out = a.out or os.path.join(bundle, "coe_out")
    os.makedirs(out, exist_ok=True)
    text = open(a.draft, encoding="utf-8").read()
    bib = parse_bib(os.path.join(bundle, cfg["bib"]))
    cache = load_cache(os.path.join(bundle, cfg["refs_cache"]))

    claims, untagged = extract_claims(text)
    ids = Counter(c["id"] for c in claims)
    dup = [k for k, v in ids.items() if v > 1]

    for c in claims:
        c.update(status=None, reason=None, detail=None, evidence_snippet=None)
        if c["type"] == "unsourced":
            c.update(status="unsupported", reason="unsourced", detail="explicitly unsourced — drop or source it")
        elif c["type"] == "num":
            s, r, d, snip = verify_num(c, bundle, cfg)
            c.update(status=s, reason=r, detail=d, evidence_snippet=snip)
            h = verify_headline(c, cfg)
            if h:
                c.update(status=h[0], reason=h[1], detail=h[2])
        elif c["type"] == "cite":
            s, r, d, snip = verify_cite(c, bib, cache, cfg)
            c.update(status=s, reason=r, detail=d, evidence_snippet=snip)
        elif c["type"] in ("code", "log"):
            s, r, d, snip = verify_span(c, bundle, cfg)
            c.update(status=s, reason=r, detail=d, evidence_snippet=snip)
        elif c["type"] == "absent":
            s, r, d, snip = verify_absent(c, bundle)
            c.update(status=s, reason=r, detail=d, evidence_snippet=snip)
        if c["type"] == "num" and c["status"] == "supported":
            nf = verify_nonfinal(c, cfg)
            if nf:
                c.update(status=nf[0], reason=nf[1], detail=nf[2])
        if c["status"] == "supported" and c["type"] in REVIEW_TYPES:
            c["review"] = "pending"
            c["review_kind"] = REVIEW_TYPES[c["type"]]
        if c["id"] in dup:
            c.update(status="unsupported", reason="duplicate_id", detail=f"claim id {c['id']} used more than once")

    for c in claims:
        c["hash"] = claim_hash(c)
    by_id = {c["id"]: c for c in claims}
    resolve_derived(by_id)

    if a.judgments:
        judg = json.load(open(a.judgments, encoding="utf-8"))
        apply_judgments([c for c in claims if c["type"] != "derive"], judg, a.min_votes)
        resolve_derived(by_id)  # propagate judge rejections into conclusions
        apply_judgments([c for c in claims if c["type"] == "derive"], judg, a.min_votes)

    # overclaim hints (non-blocking, for the critic)
    overclaims = []
    plain = strip_tags(text)
    for _, par in split_paragraphs(plain):
        for sent in split_sentences(par):
            hits = overclaim_hits(sent)
            if hits:
                overclaims.append({"sentence": sent.strip(), "terms": hits})

    total = len(claims)
    sup = sum(c["status"] == "supported" for c in claims)
    ratio = sup / total if total else 0.0
    pending = [c for c in claims if c.get("review") == "pending"]
    headline_missing = bool(cfg.get("final_result_sources")) and not any(
        "headline" in c["flags"] for c in claims)

    blocking = []
    for c in claims:
        if c["status"] == "unsupported":
            blocking.append(f"{c['id']} [{c['reason']}] {c['detail']}")
    if cfg["untagged_numbers_blocking"]:
        for u in untagged:
            blocking.append(f"line {u['line']} [untagged_number] {u['numbers']} in: {u['sentence'][:120]}")
    if ratio < cfg["min_grounding_ratio"]:
        blocking.append(f"[low_grounding_ratio] {ratio:.2f} < {cfg['min_grounding_ratio']}")
    if a.require_reviews and pending:
        blocking.append(f"[reviews_pending] {len(pending)} claims still need an LLM-judge verdict: "
                        + ", ".join(c["id"] for c in pending))
    if headline_missing:
        blocking.append("[no_headline] final_result_sources is configured but no claim carries the 'headline' flag")

    summary = {"total_claims": total, "supported": sup,
               "partial": sum(c["status"] == "partial" for c in claims),
               "unsupported": sum(c["status"] == "unsupported" for c in claims),
               "grounding_ratio": round(ratio, 4), "untagged_numeric_sentences": len(untagged),
               "reviews_pending": len(pending), "overclaim_hints": len(overclaims),
               "blocking": len(blocking), "pass": not blocking}
    ledger = {"draft": os.path.abspath(a.draft), "bundle": bundle, "config": cfg,
              "summary": summary, "claims": claims, "untagged": untagged,
              "overclaim_hints": overclaims, "blocking": blocking}
    with open(os.path.join(out, "ledger.json"), "w", encoding="utf-8") as f:
        f.write(to_json(ledger))

    # ---- human-readable report
    L = [f"# CoE Ground report\n", f"- draft: `{a.draft}`",
         f"- result: **{'PASS' if summary['pass'] else 'BLOCKED'}**",
         f"- claims: {total} (supported {sup}, partial {summary['partial']}, unsupported {summary['unsupported']})",
         f"- grounding ratio: {ratio:.2f} (min {cfg['min_grounding_ratio']})",
         f"- untagged numeric sentences: {len(untagged)}",
         f"- LLM reviews pending: {len(pending)}\n"]
    if blocking:
        L.append("## Blocking issues\n")
        L += [f"- {b}" for b in blocking]
        L.append("")
    L.append("## Claims\n")
    L.append("Check the *evidence* column: a value can match a number that measures something else.\n")
    L.append("| id | type | status | reason | review | claim | evidence |")
    L.append("|---|---|---|---|---|---|---|")
    for c in claims:
        L.append(f"| {c['id']} | {c['type']} | {c['status']} | {c['reason'] or ''} | {c.get('review', '')} | "
                 f"{c['sentence'][:90].replace('|', '/')} | {(c['detail'] or '')[:110].replace('|', '/')} |")
    if overclaims:
        L.append("\n## Overclaim hints (for the critic, non-blocking)\n")
        L += [f"- {o['terms']}: {o['sentence'][:140]}" for o in overclaims]
    open(os.path.join(out, "ground_report.md"), "w", encoding="utf-8").write("\n".join(L) + "\n")

    # ---- review packet for LLM judges
    P = ["# CoE review packet\n",
         "Judge each item ONLY from the evidence shown. Answer with JSON: "
         '{"<id>": {"verdict": "supported|partial|unsupported", "reason": "...", "hash": "<hash shown in the heading>"}}\n',
         "- citation_entailment: does the cited work (title/abstract) support the specific assertion?",
         "- method_code_alignment: does the code implement what the sentence says? Omitted detail is fine; "
         "a different algorithm, a missing component, or a hidden switch is not.",
         "- method_log_alignment: does the log region substantively describe the stated procedure?",
         "- derivation_check: does the conclusion follow from the listed supporting claims "
         "(arithmetic, direction of improvement, scope)?\n"]
    for c in pending:
        P.append(f"## {c['id']} — {c['review_kind']}  (hash {c['hash']})\n")
        P.append(f"**Claim:** {c['sentence']}\n")
        if c["type"] == "derive":
            for d in c["targets"]:
                dc = by_id.get(d)
                if dc:
                    P.append(f"- supporting {d}: {dc['sentence']}  (status {dc['status']})")
            P.append("")
        if c.get("evidence_snippet"):
            P.append("```\n" + c["evidence_snippet"] + "\n```\n")
    open(os.path.join(out, "review_packet.md"), "w", encoding="utf-8").write("\n".join(P) + "\n")

    print(json.dumps(summary, ensure_ascii=False))
    for b in blocking:
        print("BLOCK:", b)
    sys.exit(0 if summary["pass"] else 1)


if __name__ == "__main__":
    main()
