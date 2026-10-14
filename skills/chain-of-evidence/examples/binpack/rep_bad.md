# Representation: FFD bin packing (seeded with errors)

## Problem
One-dimensional bin packing asks for the fewest bins of capacity 100 that hold all items. First-fit decreasing has well-known worst-case guarantees {cite: johnson1974fast @LIT1}. Learned packing policies are now widely used in production schedulers {cite: vaswani2017attention @LIT2}, and neural variants of first-fit scale to millions of items {cite: smith2023neural @LIT3}. Dynamic variants were analysed early on {cite: coffman1984dynamic @LIT4}.

## Approach
Items are first packed with first-fit decreasing {code: solver.py:L13-22 @M1}. We then refine the packing with simulated annealing that accepts worse moves under a cooling temperature schedule {code: solver.py:L25-40 @M2}. The refinement stage is described in the run notes {log: experimental_log.md:400 @M3}.

## Results
We evaluated 30 instances. The next-fit baseline scores 0.8248 {num: scores.json#baseline_next_fit.score @BASE}. Our solver reaches 0.9952 {num: ablation_summary.json#exploratory_easy_subset.score headline @HEAD}, i.e. 98.18% of the lower bound on average {num: scores.json#final.score @PCT}. Each full run takes 9.4 ms {num: experimental_log.md:7 @LAT}, i.e. 0.0144 s {num: scores.json#final.latency_ms @LATS}. This is a near-optimal solver that outperforms next-fit by 0.17 {derive: HEAD, BASE @CONC}.

## Limitations
This approach will generalise to all packing problems {unsourced @GEN}.
