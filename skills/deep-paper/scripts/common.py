"""Shared helpers for deep-paper: config, paths, HTTP, arXiv identifiers, JSON I/O."""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import time
from pathlib import Path

import requests
import yaml

SKILL_DIR = Path(__file__).resolve().parent.parent
UA = "Mozilla/5.0 (deep-paper skill; +https://github.com/)"

DEFAULTS = {
    # Prose language of the write-up. "ko": Korean sentences with English technical terms.
    "language": "en",
    # Where finished write-ups go: "html" (static site in data_dir), "notion", or "both".
    "backend": "html",
    # Working files for every paper, and the static site when backend includes html.
    "data_dir": "~/deep-papers",
    "html": {"title": "Deep Papers"},
    "notion": {
        "data_source_id": None,      # Notion data source (database) that receives one row per paper
        "token_file": None,          # optional integration token, only for uploading local figures
    },
    # Category is one broad area; tags are method/topic keywords. With Notion, only options that
    # already exist in the database are used unless allow_new_options is true.
    "taxonomy": {
        "categories": [
            "LLM", "Reasoning", "Agents", "Vision-Language", "Computer Vision", "Generative Models",
            "Video", "3D", "Robotics", "Reinforcement Learning", "Efficient ML", "Theory",
            "Benchmark", "Survey",
        ],
        "allow_new_options": True,
    },
    "figures": {"min_main": 6, "max_main": 8},
    # Official accepted-paper lists checked for the venue. "auto" picks recent major venues
    # from the paper's submission year; a list overrides it (see references/venue.md).
    "venues": "auto",
    "check": {"max_prose_ratio": 0.30, "min_compression": 0.12},
}


def _merge(base, over):
    if not isinstance(base, dict) or not isinstance(over, dict):
        return over if over is not None else base
    out = dict(base)
    for k, v in over.items():
        out[k] = _merge(base.get(k), v) if k in base else v
    return out


def config_path() -> Path:
    env = os.environ.get("DEEP_PAPER_CONFIG")
    return Path(env).expanduser() if env else Path.home() / ".config" / "deep-paper" / "config.yaml"


class NotConfigured(SystemExit):
    pass


def load_config(required: bool = True) -> dict:
    p = config_path()
    if not p.exists():
        if required:
            raise NotConfigured(f"deep-paper is not set up (no {p}). Run: python3 "
                                f"{SKILL_DIR}/scripts/setup.py init --answers FILE")
        user = {}
    else:
        user = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    cfg = _merge(DEFAULTS, user)
    cfg["data_dir"] = Path(os.path.expanduser(cfg["data_dir"]))
    return cfg


def cache_dir() -> Path:
    d = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "deep-paper"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------------------------------------------------------------- JSON


def read_json(path: Path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def write_json(path: Path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def out(obj):
    print(json.dumps(obj, ensure_ascii=False, indent=2))


# ---------------------------------------------------------------- HTTP

_session = None


def session() -> requests.Session:
    global _session
    if _session is None:
        _session = requests.Session()
        _session.headers["User-Agent"] = UA
    return _session


def http_get(url, *, params=None, timeout=60, retries=3, backoff=5, **kw) -> requests.Response:
    """GET with retries on network errors, 429 and 5xx."""
    last = None
    for attempt in range(retries + 1):
        try:
            r = session().get(url, params=params, timeout=timeout, **kw)
            if r.status_code == 429 or r.status_code >= 500:
                last = f"HTTP {r.status_code}"
            else:
                return r
        except requests.RequestException as e:
            last = str(e)
        if attempt < retries:
            time.sleep(backoff * (attempt + 1))
    raise RuntimeError(f"GET {url} failed after {retries + 1} attempts: {last}")


# ---------------------------------------------------------------- arXiv ids and paper folders

ARXIV_NEW = re.compile(r"(?<![\d.])(\d{4}\.\d{4,5})(v\d+)?(?![\d])")
ARXIV_OLD = re.compile(r"\b([a-z\-]+(?:\.[A-Z]{2})?/\d{7})(v\d+)?\b")


def parse_arxiv_id(text: str) -> str | None:
    """arXiv id (without version) from an id, abs/pdf/html URL, or text; None if absent."""
    text = text.strip()
    m = ARXIV_NEW.search(text) or ARXIV_OLD.search(text)
    return m.group(1) if m else None


def slug(paper_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", paper_id)


def paper_dir(cfg, paper_id: str) -> Path:
    return cfg["data_dir"] / "papers" / slug(paper_id)


def norm_title(t: str) -> str:
    """Lowercase alphanumerics only, for title matching."""
    return re.sub(r"[^a-z0-9]+", "", (t or "").lower())


def title_tokens(t: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", (t or "").lower()))


def today() -> str:
    return dt.date.today().isoformat()
