We thank the reviewer for the careful reading and for noting that our method is *"simple to add to existing models"*. Below, we address each point.

---

### **`W1 – Comparison with a sliding window` – Sure, we now added this comparison.**

The reviewer asks how our method compares with a sliding window of the same cache size. **We ran this comparison on LongBench [1] and added the results in Appendix F.** **Our method keeps more accuracy at every budget, and the gap grows as the budget shrinks.**

**Table R1**: LongBench average score at each cache budget. Best in bold.
| Method | 20% | 10% | 5% |
|---|---:|---:|---:|
| Sliding window | 38.1 | 33.4 | 27.0 |
| Ours | **41.6** | **39.2** | **35.8** |

**In the revision, we will move this table to the main paper.**

---

### **`W2, Q1 – Why the eviction score uses the last 32 queries` – We chose 32 because the attention of the last queries is stable.**

The attention of the last queries changes little after about 30 tokens, as discussed in lines `214-226`, so 32 queries are enough. A single query is not enough, as the example below shows.

> **Input:** Who wrote the report that Alice cited?\
> **Sliding window output:** Bob. // `Wrong entity kept`, because the citation sentence fell out of the window.\
> **Our output:** Carol. // The citation sentence stays in the cache.

---

[1] Bai et al. LongBench: A Bilingual, Multitask Benchmark for Long Context Understanding. ACL 2024.
