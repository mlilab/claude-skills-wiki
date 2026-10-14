#!/usr/bin/env python3
"""Serve the deep-paper site locally.

usage: serve.py [--port 8010] [--host 127.0.0.1]

Serves <data_dir> over HTTP so the PDF viewer and figures load the same way as on a host.
For a remote machine, forward the port: ssh -L 8010:localhost:8010 <server>.
"""
from __future__ import annotations

import argparse
import functools
import http.server

from common import load_config


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8010)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()
    root = load_config()["data_dir"]
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
    print(f"serving {root} at http://{args.host}:{args.port}/", flush=True)
    http.server.ThreadingHTTPServer((args.host, args.port), handler).serve_forever()


if __name__ == "__main__":
    main()
