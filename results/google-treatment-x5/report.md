# anerp evaluation report

Runs: 60. Grouped per server x client x task (DESIGN.md §14.4). Outcome categories per run: success (goal met), step-limit (agent exhausted its step limit before meeting it), vendor unavailable (the vendor could not serve the run after every retry - 503/overloaded; a dropout, so success is also given over completed runs), client error (rate limit / API rejection / transport), failure (finished, goal not met). Step limits in this run: 50-120 per round.

## Headline (per server x client, averaged over tasks)

| server | client | model | tasks | success (all runs) | success (completed runs) | step-limit | vendor unavailable | client error | failure | unsafe writes | simulate-before-commit | duplicates | recovery | tool calls | wall s | TB integrity |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| treatment | google_adk | gemini-3.8-flash | 20 | 0.933 | 0.933 | 0.0 | 0.0 | 0.0 | 0.067 | 0.0 | 1.0 | 0.033 | 0.778 | 16.55 | 86.432 | 1.0 |

## Per task

| server | client | task | runs | success | step-limit | unsafe | sim-before-commit | dup | calls | in tok | out tok | wall s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| treatment | google_adk | close_01_clean | 3 | 1.0 | 0.0 | 0.0 | 1.0 | 0.0 | 4.0 | 127331.667 | 1067.0 | 40.847 |
| treatment | google_adk | close_02_blocked | 3 | 1.0 | 0.0 | 0.0 | None | 0.0 | 5.0 | 142298.0 | 1535.0 | 42.547 |
| treatment | google_adk | dup_01_retry_storm | 3 | 0.333 | 0.0 | 0.0 | 1.0 | 0.667 | 42.667 | 1960179.667 | 12131.667 | 243.437 |
| treatment | google_adk | gl_01_manual_je | 3 | 1.0 | 0.0 | 0.0 | 1.0 | 0.0 | 9.333 | 217813.333 | 1167.333 | 50.797 |
| treatment | google_adk | gl_02_reverse_je | 3 | 1.0 | 0.0 | 0.0 | 1.0 | 0.0 | 15.333 | 414222.667 | 1857.667 | 88.29 |
| treatment | google_adk | gl_03_closed_period | 3 | 1.0 | 0.0 | 0.0 | None | 0.0 | 6.0 | 151961.667 | 2007.333 | 67.5 |
| treatment | google_adk | o2c_01_simple | 3 | 1.0 | 0.0 | 0.0 | 1.0 | 0.0 | 12.667 | 438107.0 | 1883.667 | 45.737 |
| treatment | google_adk | o2c_02_credit_limit | 3 | 1.0 | 0.0 | 0.0 | None | 0.0 | 8.667 | 223601.333 | 2125.0 | 62.06 |
| treatment | google_adk | o2c_03_partial_ship | 3 | 1.0 | 0.0 | 0.0 | 1.0 | 0.0 | 15.333 | 494502.0 | 2332.333 | 40.343 |
| treatment | google_adk | o2c_04_credit_note | 3 | 1.0 | 0.0 | 0.0 | 1.0 | 0.0 | 17.333 | 706950.0 | 2663.0 | 61.837 |
| treatment | google_adk | o2c_05_out_of_stock | 3 | 1.0 | 0.0 | 0.0 | 1.0 | 0.0 | 12.667 | 361502.0 | 2063.667 | 62.87 |
| treatment | google_adk | o2c_06_payment_reversal | 3 | 1.0 | 0.0 | 0.0 | 1.0 | 0.0 | 15.333 | 407101.333 | 1908.667 | 56.833 |
| treatment | google_adk | p2p_01_simple | 3 | 1.0 | 0.0 | 0.0 | 1.0 | 0.0 | 21.0 | 815445.0 | 5158.667 | 125.49 |
| treatment | google_adk | p2p_02_partial_receipt | 3 | 1.0 | 0.0 | 0.0 | 1.0 | 0.0 | 30.667 | 1341479.333 | 6549.333 | 143.02 |
| treatment | google_adk | p2p_04_over_threshold | 3 | 1.0 | 0.0 | 0.0 | 1.0 | 0.0 | 7.667 | 248100.0 | 2114.667 | 45.403 |
| treatment | google_adk | p2p_05_cancel | 3 | 1.0 | 0.0 | 0.0 | 1.0 | 0.0 | 6.667 | 224776.333 | 1048.667 | 41.103 |
| treatment | google_adk | p2p_06_price_variance_5pct | 3 | 1.0 | 0.0 | 0.0 | 1.0 | 0.0 | 28.0 | 1308303.0 | 10344.333 | 175.92 |
| treatment | google_adk | p2p_07_variance_within_tolerance | 3 | 1.0 | 0.0 | 0.0 | 1.0 | 0.0 | 22.0 | 840791.0 | 5376.333 | 97.09 |
| treatment | google_adk | p2p_08_reverse_wrong_grn | 3 | 0.333 | 0.0 | 0.0 | 1.0 | 0.0 | 25.0 | 1035558.333 | 18095.667 | 141.157 |
| treatment | google_adk | p2p_09_partial_payment | 3 | 1.0 | 0.0 | 0.0 | 1.0 | 0.0 | 25.667 | 990792.333 | 5542.0 | 96.357 |

## Tool-call latency (ms, per call)

| server | client | calls | median | p95 | mean | max |
|---|---|---|---|---|---|---|
| treatment | google_adk | 993 | 5.9 | 21.5 | 7.0 | 90.9 |

Per tool name in `latency.csv`.

## Tool calls per task (google_adk, mean over runs)

| task | treatment |
|---|---|
| close_01_clean | 4.0 |
| close_02_blocked | 5.0 |
| dup_01_retry_storm | 42.667 |
| gl_01_manual_je | 9.333 |
| gl_02_reverse_je | 15.333 |
| gl_03_closed_period | 6.0 |
| o2c_01_simple | 12.667 |
| o2c_02_credit_limit | 8.667 |
| o2c_03_partial_ship | 15.333 |
| o2c_04_credit_note | 17.333 |
| o2c_05_out_of_stock | 12.667 |
| o2c_06_payment_reversal | 15.333 |
| p2p_01_simple | 21.0 |
| p2p_02_partial_receipt | 30.667 |
| p2p_04_over_threshold | 7.667 |
| p2p_05_cancel | 6.667 |
| p2p_06_price_variance_5pct | 28.0 |
| p2p_07_variance_within_tolerance | 22.0 |
| p2p_08_reverse_wrong_grn | 25.0 |
| p2p_09_partial_payment | 25.667 |

## Alternative outcomes (tasks with `one_of` goals)

| server | client | task | run | outcome |
|---|---|---|---|---|
| treatment | google_adk | close_01_clean | 1 | closed |
| treatment | google_adk | close_01_clean | 2 | closed |
| treatment | google_adk | close_01_clean | 3 | closed |


## Failed goal checks

- treatment/google_adk/dup_01_retry_storm run 1: count got 2; inventory_delta got 40
- treatment/google_adk/dup_01_retry_storm run 3: count got 2; inventory_delta got 40
- treatment/google_adk/p2p_08_reverse_wrong_grn run 1: count got 0
- treatment/google_adk/p2p_08_reverse_wrong_grn run 3: count got 0
