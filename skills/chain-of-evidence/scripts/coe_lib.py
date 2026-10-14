"""Shared helpers for Chain-of-Evidence scripts (stdlib only)."""
from __future__ import annotations

import difflib
import math
from decimal import Decimal, ROUND_HALF_UP, ROUND_HALF_EVEN
import json
import os
import re
from dataclasses import dataclass, field, asdict
from typing import Any

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
DEFAULT_CONFIG = {
    "rel_tol": 0.0,                # extra relative tolerance on top of rounding (raise for noisy evaluators)
    "line_window": 3,              # +/- lines shown around a cited code/log line
    "num_line_window": 0,          # +/- lines searched for a numeric claim (0 = exactly the cited line)
    "max_round_rel": 0.01,         # rounding may change a value by at most 1% unless the claim says "about/~"
    "min_grounding_ratio": 0.9,    # supported / total claims needed to pass
    "bib": "refs.bib",
    "refs_cache": "refs_cache.json",
    "final_result_sources": [],    # evidence prefixes that hold the submitted run's results
    "untagged_numbers_blocking": True,
    "title_match_threshold": 0.85,
}


def load_config(bundle: str, path: str | None = None) -> dict:
    cfg = dict(DEFAULT_CONFIG)
    p = path or os.path.join(bundle, "coe_config.json")
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            cfg.update(json.load(f))
    return cfg


# ---------------------------------------------------------------------------
# Numbers and units
# ---------------------------------------------------------------------------
UNIT_RE = r"(?:%|ms|µs|us|ns|sec|seconds?|s|x|×|GB|MB|KB|pp)?"
NUM_RE = re.compile(
    r"(?<![A-Za-z_\d.])"                 # not glued to an identifier (C3, Llama-3 handled below)
    r"([-+−]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)"
    r"\s?(" + UNIT_RE[3:-2] + r")?(?![A-Za-z\d])"
)
TIME_TO_S = {"ns": 1e-9, "µs": 1e-6, "us": 1e-6, "ms": 1e-3, "s": 1.0, "sec": 1.0,
             "second": 1.0, "seconds": 1.0}


@dataclass
class Num:
    value: float
    unit: str
    decimals: int
    raw: str
    start: int = 0


def find_numbers(text: str) -> list[Num]:
    out = []
    for m in NUM_RE.finditer(text):
        raw = m.group(1).replace("−", "-")
        # skip identifiers like "Llama-3" or "v2-1": preceded by letter + hyphen
        pre = text[max(0, m.start() - 2):m.start()]
        if re.match(r"[A-Za-z]-$", pre):
            continue
        # skip zero-padded identifiers ("run 005") and "#12"-style ids
        if re.match(r"^0\d", raw.lstrip("+-")) or text[max(0, m.start() - 1):m.start()] == "#":
            continue
        unit = (m.group(2) or "").strip()
        dec = len(raw.split(".")[1]) if "." in raw else 0
        try:
            val = float(raw.replace(",", ""))
        except ValueError:
            continue
        out.append(Num(val, unit, dec, m.group(0).strip(), m.start()))
    return out


def _factors(cu: str, eu: str) -> list[float]:
    """Multipliers applied to the evidence value so it can be compared to the claim value."""
    f = {1.0}
    if cu in TIME_TO_S and eu in TIME_TO_S:
        return [TIME_TO_S[eu] / TIME_TO_S[cu]]
    if "%" in (cu, eu) or "pp" in (cu, eu):
        f |= {100.0, 0.01}
    if (cu in TIME_TO_S) != (eu in TIME_TO_S):
        f |= {1000.0, 0.001}
    return sorted(f)


def decimals_of(v: float) -> int:
    s = repr(float(v))
    if "e" in s:
        return 6
    frac = s.split(".")[1].rstrip("0")
    return len(frac)


def numbers_match(claim: Num, evid: Num, rel_tol: float = 0.0, max_round_rel: float | None = None) -> bool:
    """A claim matches evidence if it equals the evidence rounded to the claim's precision
    (after unit scaling), optionally loosened by rel_tol. Evidence that is *less* precise than
    the claim cannot support it (\"1\" in a log does not support a claimed 0.9952)."""
    for fac in _factors(claim.unit, evid.unit):
        e = evid.value * fac
        eff_dec = evid.decimals - round(math.log10(fac))
        if eff_dec < claim.decimals:
            continue
        q = Decimal(1).scaleb(-claim.decimals)
        cv = Decimal(repr(claim.value)).quantize(q, ROUND_HALF_UP)
        ev = Decimal(repr(e))
        if cv in (ev.quantize(q, ROUND_HALF_UP), ev.quantize(q, ROUND_HALF_EVEN)):
            # coarse rounding ("1" for 0.9818) hides real differences unless marked approximate
            if max_round_rel is not None and e and abs(claim.value - e) / abs(e) > max_round_rel:
                continue
            return True
        if rel_tol and abs(claim.value - e) <= rel_tol * abs(e):
            return True
    return False


# ---------------------------------------------------------------------------
# Tags
# ---------------------------------------------------------------------------
TAG_TYPES = ("num", "cite", "code", "log", "derive", "absent", "unsourced", "context")
TAG_RE = re.compile(r"\{(" + "|".join(TAG_TYPES) + r")\b\s*:?\s*([^{}]*)\}")
_SENT_END_RAW = re.compile(r"[.!?。](?=\s|$)")
_ABBREV = re.compile(r"(?:\b(?:i\.e|e\.g|et al|etc|vs|cf|Fig|Figs|Eq|Eqs|Sec|Tab|approx|No|al))\.$", re.I)


class _SentEnd:
    """Sentence-end finder that ignores abbreviations such as 'i.e.' and 'et al.'."""

    def finditer(self, text, pos=0):
        for m in _SENT_END_RAW.finditer(text, pos):
            if m.group(0) == "." and _ABBREV.search(text[max(0, m.start() - 8):m.end()]):
                continue
            yield m


SENT_END_RE = _SentEnd()


def split_sentences(text: str) -> list[str]:
    out, cur = [], 0
    for m in SENT_END_RE.finditer(text):
        out.append(text[cur:m.end()])
        cur = m.end()
    if cur < len(text):
        out.append(text[cur:])
    return [s.strip() for s in out if s.strip()]


@dataclass
class Tag:
    type: str
    targets: list[str]
    id: str | None
    flags: list[str]
    start: int
    end: int
    raw: str


def parse_tag(m: re.Match) -> Tag:
    body = m.group(2).strip()
    cid, flags, targets = None, [], []
    for tok in re.split(r"[,\s]+", body):
        if not tok:
            continue
        if tok.startswith("@"):
            cid = tok[1:]
        elif tok in ("headline", "nonfinal"):
            flags.append(tok)
        else:
            targets.append(tok)
    return Tag(m.group(1), targets, cid, flags, m.start(), m.end(), m.group(0))


def strip_tags(text: str) -> str:
    return re.sub(r"\s*" + TAG_RE.pattern, "", text)


# ---------------------------------------------------------------------------
# Evidence resolution
# ---------------------------------------------------------------------------
def read_lines(path: str) -> list[str] | None:
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read().splitlines()
    except (FileNotFoundError, IsADirectoryError):
        return None


def parse_location(target: str) -> tuple[str, str, Any]:
    """Return (path, kind, locator). kind in {'line','range','json','file'}."""
    if "#" in target:
        path, key = target.split("#", 1)
        return path, "json", key
    m = re.match(r"^(.*?):L?(\d+)(?:-L?(\d+))?$", target)
    if m:
        path, a, b = m.group(1), int(m.group(2)), m.group(3)
        if b:
            return path, "range", (a, int(b))
        return path, "line", a
    return target, "file", None


def json_lookup(obj: Any, key: str) -> Any:
    cur = obj
    for part in key.split("."):
        if isinstance(cur, list):
            try:
                cur = cur[int(part)]
            except (ValueError, IndexError):
                raise KeyError(key)
        elif isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            raise KeyError(key)
    return cur


def numeric_leaves(obj: Any, prefix: str = "", strings: bool = False) -> list[tuple[str, float]]:
    """Numeric leaves of a JSON value. Free-text strings are ignored unless strings=True
    (a digit inside a note must not silently ground a claim)."""
    out = []
    if isinstance(obj, bool):
        return out
    if isinstance(obj, (int, float)):
        out.append((prefix, obj))
    elif isinstance(obj, dict):
        for k, v in obj.items():
            out += numeric_leaves(v, f"{prefix}.{k}" if prefix else k, strings)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out += numeric_leaves(v, f"{prefix}.{i}" if prefix else str(i), strings)
    elif isinstance(obj, str) and strings:
        for n in find_numbers(obj):
            out.append((prefix, n.value))
    return out


def unit_from_key(key: str) -> str:
    k = key.lower()
    for suf, u in (("_ms", "ms"), ("_us", "us"), ("_s", "s"), ("_sec", "s"), ("_pct", "%"),
                   ("_percent", "%")):
        if k.endswith(suf):
            return u
    return ""


# ---------------------------------------------------------------------------
# Bibliography
# ---------------------------------------------------------------------------
def parse_bib(path: str) -> dict[str, dict]:
    if not path or not os.path.exists(path):
        return {}
    text = open(path, encoding="utf-8", errors="replace").read()
    entries = {}
    i = 0
    while True:
        m = re.compile(r"@(\w+)\s*\{\s*([^,\s]+)\s*,").search(text, i)
        if not m:
            break
        depth, j = 1, m.end()
        while j < len(text) and depth:
            if text[j] == "{":
                depth += 1
            elif text[j] == "}":
                depth -= 1
            j += 1
        body = text[m.end():j - 1]
        fields = {"ENTRYTYPE": m.group(1).lower()}
        for fm in re.finditer(r"(\w+)\s*=\s*", body):
            k = fm.group(1).lower()
            rest = body[fm.end():]
            if rest.startswith("{"):
                d, q = 0, 0
                for q, ch in enumerate(rest):
                    d += ch == "{"
                    d -= ch == "}"
                    if d == 0:
                        break
                val = rest[1:q]
            elif rest.startswith('"'):
                q = rest.find('"', 1)
                val = rest[1:q]
            else:
                val = re.match(r"[^,\n]*", rest).group(0)
            fields.setdefault(k, re.sub(r"[{}]", "", val).strip())
        entries[m.group(2)] = fields
        i = j
    return entries


def norm_title(t: str) -> str:
    return re.sub(r"[^a-z0-9가-힣]+", " ", (t or "").lower()).strip()


def title_similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, norm_title(a), norm_title(b)).ratio()


def load_cache(path: str) -> dict:
    if path and os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {}


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------
OVERCLAIM_TERMS = [
    "near-optimal", "optimal", "state-of-the-art", "sota", "significantly", "dramatically",
    "substantially", "always", "never fails", "guarantee", "guarantees", "unprecedented",
    "revolutionary", "breakthrough", "sub-millisecond", "orders of magnitude", "best-in-class",
    "획기적", "압도적", "최적", "보장", "현저히", "항상", "최고 수준",
]


def overclaim_hits(sentence: str) -> list[str]:
    s = sentence.lower()
    return [t for t in OVERCLAIM_TERMS if re.search(r"(?<![a-z])" + re.escape(t) + r"(?![a-z])", s)]


def iter_prose_lines(text: str):
    """Yield (lineno, line) skipping fenced code blocks, headings and tables' separator rows."""
    fence = False
    for i, line in enumerate(text.splitlines(), 1):
        if line.strip().startswith("```"):
            fence = not fence
            continue
        if fence:
            continue
        yield i, line


def to_json(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2,
                      default=lambda o: asdict(o) if hasattr(o, "__dataclass_fields__") else str(o))
