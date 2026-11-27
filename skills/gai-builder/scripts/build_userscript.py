#!/usr/bin/env python3
"""Assemble gai.user.js from the core and a site adapter, and print the numbers used to check the browser copy.

usage: python3 build_userscript.py --adapter adapter.js --match "https://example.com/*" --out gai-out/example.com
"""
import argparse, os

def fnv1a(text):  # same value as the JS check: FNV-1a over UTF-16 code units
    h = 2166136261
    for ch in text:
        o = ord(ch)
        for u in ([o] if o < 0x10000 else [0xD800 + ((o - 0x10000) >> 10), 0xDC00 + ((o - 0x10000) & 0x3FF)]):
            h ^= u
            h = (h * 16777619) & 0xFFFFFFFF
    return h

ap = argparse.ArgumentParser()
ap.add_argument('--adapter', required=True)
ap.add_argument('--match', required=True, help='userscript @match pattern, e.g. https://example.com/*')
ap.add_argument('--out', required=True)
ap.add_argument('--core', default=os.path.join(os.path.dirname(os.path.abspath(__file__)), 'gai-layer.core.js'))
a = ap.parse_args()
core = open(a.core, encoding='utf-8').read().rstrip('\n')
adapter = open(a.adapter, encoding='utf-8').read().rstrip('\n')
host = a.match.split('//')[-1].split('/')[0]
head = f"""// ==UserScript==
// @name         GAI layer - {host}
// @namespace    gai-builder
// @version      1.0
// @description  Agent-friendly layer for screen-driven agents. Unofficial; changes nothing on the server.
// @match        {a.match}
// @run-at       document-idle
// @noframes
// @grant        none
// ==/UserScript==
"""
boot = "\n(function boot() { if (!document.body) return void setTimeout(boot, 50); GAI_LAYER(GAI_ADAPTER()); })();\n"
os.makedirs(a.out, exist_ok=True)
open(os.path.join(a.out, 'gai.user.js'), 'w', encoding='utf-8').write(head + '\n// ---- site adapter (the only site-specific part) ----\n' + adapter + '\n\n// ---- GAI layer core (site-independent) ----\n' + core + '\n' + boot)
open(os.path.join(a.out, 'gai-layer.core.js'), 'w', encoding='utf-8').write(core + '\n')
open(os.path.join(a.out, 'adapter.js'), 'w', encoding='utf-8').write(adapter + '\n')
print('core   ', len(core), fnv1a(core))
print('adapter', len(adapter), fnv1a(adapter))
print('wrote', os.path.join(a.out, 'gai.user.js'))
