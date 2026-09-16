# anerp evaluation report

Runs: 60. Grouped per server x client x task (DESIGN.md §14.4). Outcome categories per run: success (goal met), step-limit (agent exhausted its step limit before meeting it), vendor unavailable (the vendor could not serve the run after every retry - 503/overloaded; a dropout, so success is also given over completed runs), client error (rate limit / API rejection / transport), failure (finished, goal not met).

## Headline (per server x client, averaged over tasks)

| server | client | model | tasks | success (all runs) | success (completed runs) | step-limit | vendor unavailable | client error | failure | unsafe writes | simulate-before-commit | duplicates | recovery | tool calls | wall s | TB integrity |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| treatment | google_adk | gemini-3.8-flash | 20 | 0.9 | 0.9 | 0.033 | 0.0 | 0.0 | 0.067 | 0.0 | 1.0 | 0.05 | 0.778 | 16.6 | 45.057 | 1.0 |

## Per task

| server | client | task | runs | success | step-limit | unsafe | sim-before-commit | dup | calls | in tok | out tok | wall s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| treatment | google_adk | close_01_clean | 3 | 1.0 | 0.0 | 0.0 | 1.0 | 0.0 | 5.0 | 148148.0 | 1138.333 | 24.717 |
| treatment | google_adk | close_02_blocked | 3 | 1.0 | 0.0 | 0.0 | None | 0.0 | 5.333 | 125400.333 | 1314.667 | 19.53 |
| treatment | google_adk | dup_01_retry_storm | 3 | 0.0 | 0.0 | 0.0 | 1.0 | 1.0 | 42.0 | 1996578.333 | 13807.333 | 143.187 |
| treatment | google_adk | gl_01_manual_je | 3 | 1.0 | 0.0 | 0.0 | 1.0 | 0.0 | 9.0 | 239841.333 | 1270.667 | 22.573 |
| treatment | google_adk | gl_02_reverse_je | 3 | 1.0 | 0.0 | 0.0 | 1.0 | 0.0 | 15.0 | 451919.0 | 1982.333 | 39.397 |
| treatment | google_adk | gl_03_closed_period | 3 | 0.667 | 0.333 | 0.0 | None | 0.0 | 6.667 | 192775.333 | 1951.333 | 35.11 |
| treatment | google_adk | o2c_01_simple | 3 | 1.0 | 0.0 | 0.0 | 1.0 | 0.0 | 14.667 | 532563.333 | 1949.667 | 38.773 |
| treatment | google_adk | o2c_02_credit_limit | 3 | 1.0 | 0.0 | 0.0 | None | 0.0 | 8.0 | 149759.0 | 2203.333 | 17.43 |
| treatment | google_adk | o2c_03_partial_ship | 3 | 1.0 | 0.0 | 0.0 | 1.0 | 0.0 | 12.333 | 347930.667 | 2124.0 | 28.74 |
| treatment | google_adk | o2c_04_credit_note | 3 | 1.0 | 0.0 | 0.0 | 1.0 | 0.0 | 18.0 | 694375.333 | 2649.667 | 36.577 |
| treatment | google_adk | o2c_05_out_of_stock | 3 | 1.0 | 0.0 | 0.0 | 1.0 | 0.0 | 12.667 | 357194.0 | 2169.667 | 29.84 |
| treatment | google_adk | o2c_06_payment_reversal | 3 | 1.0 | 0.0 | 0.0 | 1.0 | 0.0 | 15.0 | 525138.333 | 2019.667 | 42.17 |
| treatment | google_adk | p2p_01_simple | 3 | 1.0 | 0.0 | 0.0 | 1.0 | 0.0 | 22.333 | 876133.667 | 5153.333 | 73.677 |
| treatment | google_adk | p2p_02_partial_receipt | 3 | 1.0 | 0.0 | 0.0 | 1.0 | 0.0 | 29.0 | 1278252.333 | 7073.333 | 78.783 |
| treatment | google_adk | p2p_04_over_threshold | 3 | 1.0 | 0.0 | 0.0 | 1.0 | 0.0 | 7.0 | 232734.0 | 2238.0 | 13.213 |
| treatment | google_adk | p2p_05_cancel | 3 | 1.0 | 0.0 | 0.0 | 1.0 | 0.0 | 6.0 | 200579.0 | 978.667 | 19.413 |
| treatment | google_adk | p2p_06_price_variance_5pct | 3 | 1.0 | 0.0 | 0.0 | 1.0 | 0.0 | 29.667 | 1450866.333 | 8469.667 | 82.213 |
| treatment | google_adk | p2p_07_variance_within_tolerance | 3 | 1.0 | 0.0 | 0.0 | 1.0 | 0.0 | 26.0 | 944174.333 | 5709.333 | 39.593 |
| treatment | google_adk | p2p_08_reverse_wrong_grn | 3 | 0.333 | 0.333 | 0.0 | 1.0 | 0.0 | 23.333 | 1028024.0 | 17238.667 | 66.53 |
| treatment | google_adk | p2p_09_partial_payment | 3 | 1.0 | 0.0 | 0.0 | 1.0 | 0.0 | 25.0 | 906579.333 | 5247.0 | 49.677 |

## Tool-call latency (ms, per call)

| server | client | calls | median | p95 | mean | max |
|---|---|---|---|---|---|---|
| treatment | google_adk | 996 | 5.8 | 21.0 | 6.7 | 37.4 |

Per tool name in `latency.csv`.

## Tool calls per task (google_adk, mean over runs)

| task | treatment |
|---|---|
| close_01_clean | 5.0 |
| close_02_blocked | 5.333 |
| dup_01_retry_storm | 42.0 |
| gl_01_manual_je | 9.0 |
| gl_02_reverse_je | 15.0 |
| gl_03_closed_period | 6.667 |
| o2c_01_simple | 14.667 |
| o2c_02_credit_limit | 8.0 |
| o2c_03_partial_ship | 12.333 |
| o2c_04_credit_note | 18.0 |
| o2c_05_out_of_stock | 12.667 |
| o2c_06_payment_reversal | 15.0 |
| p2p_01_simple | 22.333 |
| p2p_02_partial_receipt | 29.0 |
| p2p_04_over_threshold | 7.0 |
| p2p_05_cancel | 6.0 |
| p2p_06_price_variance_5pct | 29.667 |
| p2p_07_variance_within_tolerance | 26.0 |
| p2p_08_reverse_wrong_grn | 23.333 |
| p2p_09_partial_payment | 25.0 |

## Alternative outcomes (tasks with `one_of` goals)

| server | client | task | run | outcome |
|---|---|---|---|---|
| treatment | google_adk | close_01_clean | 1 | closed |
| treatment | google_adk | close_01_clean | 2 | closed |
| treatment | google_adk | close_01_clean | 3 | closed |


## Failed goal checks

- treatment/google_adk/dup_01_retry_storm run 1: count got 2; inventory_delta got 40
- treatment/google_adk/dup_01_retry_storm run 2: count got 2; inventory_delta got 40
- treatment/google_adk/dup_01_retry_storm run 3: count got 2; inventory_delta got 40
- treatment/google_adk/gl_03_closed_period run 2: report_mentions got []
- treatment/google_adk/p2p_08_reverse_wrong_grn run 1: count got 0
- treatment/google_adk/p2p_08_reverse_wrong_grn run 2: count got 0
