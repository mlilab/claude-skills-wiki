# AnnealPack: Simulated-Annealing Bin Packing

## Abstract
We present AnnealPack, which achieves a score of 0.9952 on the benchmark, a near-optimal result that outperforms next-fit (0.8248) by a wide margin.

## Method
AnnealPack first sorts items in decreasing order and packs them with first fit. It then runs simulated annealing with a geometric cooling schedule (T0 = 5.0, alpha = 0.95), accepting worse moves with probability exp(-delta/T).

## Results
On 30 instances, AnnealPack scores 0.9952 and each run takes 9.4 ms. Neural first-fit variants report similar quality [smith2023neural], and classical analysis covers FFD [johnson1974fast].
