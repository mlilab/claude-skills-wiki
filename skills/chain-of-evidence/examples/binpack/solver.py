"""Bin packing solver: first-fit decreasing + swap-based local search."""
import json
import random

CAP = 100


def load(path="instances.json"):
    with open(path) as f:
        return json.load(f)


def first_fit_decreasing(items):
    bins = []
    for it in sorted(items, reverse=True):
        for b in bins:
            if sum(b) + it <= CAP:
                b.append(it)
                break
        else:
            bins.append([it])
    return bins


def local_search(bins, iters=200, seed=0):
    rng = random.Random(seed)
    for _ in range(iters):
        if len(bins) < 2:
            break
        a, b = rng.sample(range(len(bins)), 2)
        # try to move the smallest item of the emptiest bin into another bin
        src = min((a, b), key=lambda i: sum(bins[i]))
        dst = b if src == a else a
        it = min(bins[src])
        if sum(bins[dst]) + it <= CAP:
            bins[src].remove(it)
            bins[dst].append(it)
            if not bins[src]:
                bins.pop(src)
    return bins


def score(instances):
    ratios = []
    for items in instances:
        lb = -(-sum(items) // CAP)
        bins = local_search(first_fit_decreasing(items))
        ratios.append(lb / len(bins))
    return sum(ratios) / len(ratios)


if __name__ == "__main__":
    print(f"score={score(load()):.4f}")
