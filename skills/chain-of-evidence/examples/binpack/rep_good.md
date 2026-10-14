# Representation: FFD bin packing (fixed)

## Problem
One-dimensional bin packing asks for the fewest bins of capacity 100 {num: solver.py:5 @CAP} that hold all items. First-fit decreasing has well-studied worst-case behaviour {cite: johnson1974fast @LIT1}.

## Approach
Items are first packed with first-fit decreasing {code: solver.py:L13-22 @M1}. A local search then repeatedly tries to move the smallest item of the emptier of two random bins into the other bin {code: solver.py:L25-40 @M2}.

## Results
We evaluated 30 {num: experimental_log.md:6 @N} instances. The next-fit baseline scores 0.8248 {num: scores.json#baseline_next_fit.score @BASE}. The submitted solver scores 0.9818 {num: scores.json#final.score headline @HEAD}, i.e. 98.18% {num: scores.json#final.score @PCT} of the bin lower bound on average. Each full run takes 14.4 ms {num: experimental_log.md:7 @LAT}. The solver improves on next-fit by 0.157 {derive: HEAD, BASE @CONC}. Removing local search leaves the score unchanged at 0.9818 {num: ablation_summary.json#no_local_search.score @ABL}, so the gain comes from first-fit decreasing itself {derive: ABL, HEAD @CONC2}.
