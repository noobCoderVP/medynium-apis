# Timing and cost

Generated 2026-10-03 06:36 UTC at the service layer as the demo doctor (no HTTP, so add roughly 50 to 100 ms through the API).
Credits: 2.22 before, 2.24 after, **0.02 spent by this run**. The resource monitor cap is 100. Snowflake updates the monitor with a delay, so treat this as a lower bound.
Assistant route timings (lookup, changed, hero) include the router call, whose own p50 is the row above. The plan targets are 1 s after routing for cheap routes and 20 s p50 for the hero.

| Measure | Runs | Failed | First (cold) s | p50 s | p95 s | Max s | p50 target s | Within target |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Dashboard data | 20 | 0 | 1.59 | 1.16 | 1.98 | 1.98 | 3 | yes |
| Patient overview | 20 | 0 | 1.25 | 0.92 | 1.61 | 1.61 | 3 | yes |
| Router decision only | 10 | 0 | 1.94 | 0.86 | 1.94 | 1.94 | 2 | yes |
| lookup route (current medicines) | 20 | 0 | 3.36 | 3.53 | 15.06 | 15.06 | 1 | **no** |
| changed route (what changed) | 20 | 0 | 2.64 | 3.05 | 5.91 | 5.91 | 1 | **no** |
| Safety review through the assistant (hero) | 8 | 0 | 27.14 | 24.14 | 39.19 | 39.19 | 20 | **no** |
