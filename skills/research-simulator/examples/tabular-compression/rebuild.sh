#!/usr/bin/env bash
# Rebuild the Tabular Dataset Compression example.
# research.json: status reconstructed from the project's 7 artifacts (2026-10-19 .. 11-05).
# pool.json: 55 OpenAlex papers gathered with the web-tool path, facets written per references/facets.md.
set -euo pipefail
cd "$(dirname "$0")"
S=../../scripts
python3 $S/sim.py init --papers pool.json --research research.json --hops 2 \
  --title "SSC Research Sim" \
  --status-source "reconstructed from 7 artifacts of the Tabular Dataset Compression project (2026-10-19 to 11-05)" \
  -o state.json > /dev/null
python3 $S/sim.py retag state.json hierarchy.json --reanchor
python3 $S/sim.py apply state.json s0_moves.json --node s0
python3 $S/sim.py validate state.json
python3 $S/sim.py build state.json --mode html -o simulator.html
