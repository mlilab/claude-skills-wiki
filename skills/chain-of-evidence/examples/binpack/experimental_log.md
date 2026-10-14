# Experimental log — bin packing solver
run 001  config=next_fit                     instances=30
run 001  score=0.8248  latency_ms=3.1
run 002  config=ffd                          instances=30
run 002  score=0.9818  latency_ms=12.9
run 003  config=ffd+local_search(iters=200)  instances=30
run 003  score=0.9818  latency_ms=14.4
note: local search moved items in 0 of 30 instances; FFD packing already at lower bound for most.
run 004  config=ffd+local_search(iters=5000,seed=3)  instances=30
run 004  score=0.9818  latency_ms=41.7
run 005  config=best_fit_decreasing          instances=30
run 005  score=0.9818  latency_ms=13.6
decision: submit run 003 configuration (solver.py) as final.
