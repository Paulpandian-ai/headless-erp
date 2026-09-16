# anerp evaluation report

Runs: 60. Grouped per server x client x task (DESIGN.md §14.4). Outcome categories per run: success (goal met), step-limit (agent exhausted its step limit before meeting it), vendor unavailable (the vendor could not serve the run after every retry - 503/overloaded; a dropout, so success is also given over completed runs), client error (rate limit / API rejection / transport), failure (finished, goal not met). Step limits in this run: 50-120 per round.

## Headline (per server x client, averaged over tasks)

| server | client | model | tasks | success (all runs) | success (completed runs) | step-limit | vendor unavailable | client error | failure | unsafe writes | simulate-before-commit | duplicates | recovery | tool calls | wall s | TB integrity |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| control | google_adk | gemini-3.8-flash | 20 | 0.6 | 0.6 | 0.0 | 0.0 | 0.0 | 0.4 | 0.0 | None | 0.0 | 0.333 | 52.133 | 297.626 | 1.0 |

## Per task

| server | client | task | runs | success | step-limit | unsafe | sim-before-commit | dup | calls | in tok | out tok | wall s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| control | google_adk | close_01_clean | 3 | 1.0 | 0.0 | 0.0 | None | 0.0 | 24.667 | 557533.333 | 5009.667 | 94.043 |
| control | google_adk | close_02_blocked | 3 | 1.0 | 0.0 | 0.0 | None | 0.0 | 20.0 | 428298.333 | 5069.0 | 82.573 |
| control | google_adk | dup_01_retry_storm | 3 | 1.0 | 0.0 | 0.0 | None | 0.0 | 92.667 | 2947130.333 | 35475.667 | 272.897 |
| control | google_adk | gl_01_manual_je | 3 | 1.0 | 0.0 | 0.0 | None | 0.0 | 29.0 | 730391.667 | 14277.333 | 106.373 |
| control | google_adk | gl_02_reverse_je | 3 | 0.0 | 0.0 | 0.0 | None | 0.0 | 43.333 | 1957355.0 | 45223.667 | 269.453 |
| control | google_adk | gl_03_closed_period | 3 | 1.0 | 0.0 | 0.0 | None | 0.0 | 4.333 | 53708.333 | 1933.333 | 20.083 |
| control | google_adk | o2c_01_simple | 3 | 0.0 | 0.0 | 0.0 | None | 0.0 | 78.333 | 2964922.333 | 32115.667 | 245.443 |
| control | google_adk | o2c_02_credit_limit | 3 | 1.0 | 0.0 | 0.0 | None | 0.0 | 10.667 | 31867.667 | 2400.667 | 25.777 |
| control | google_adk | o2c_03_partial_ship | 3 | 0.0 | 0.0 | 0.0 | None | 0.0 | 70.667 | 2369861.667 | 21344.667 | 181.043 |
| control | google_adk | o2c_04_credit_note | 3 | 1.0 | 0.0 | 0.0 | None | 0.0 | 84.333 | 3354129.667 | 29842.333 | 261.003 |
| control | google_adk | o2c_05_out_of_stock | 3 | 1.0 | 0.0 | 0.0 | None | 0.0 | 20.0 | 242172.667 | 4653.333 | 43.993 |
| control | google_adk | o2c_06_payment_reversal | 3 | 1.0 | 0.0 | 0.0 | None | 0.0 | 50.0 | 2119475.0 | 54452.0 | 373.983 |
| control | google_adk | p2p_01_simple | 3 | 0.0 | 0.0 | 0.0 | None | 0.0 | 88.333 | 3651167.667 | 32398.667 | 394.093 |
| control | google_adk | p2p_02_partial_receipt | 3 | 0.0 | 0.0 | 0.0 | None | 0.0 | 107.0 | 4120187.333 | 45664.667 | 609.75 |
| control | google_adk | p2p_04_over_threshold | 3 | 0.0 | 0.0 | 0.0 | None | 0.0 | 32.333 | 713995.0 | 14379.667 | 347.223 |
| control | google_adk | p2p_05_cancel | 3 | 1.0 | 0.0 | 0.0 | None | 0.0 | 33.333 | 576912.0 | 9751.0 | 423.53 |
| control | google_adk | p2p_06_price_variance_5pct | 3 | 1.0 | 0.0 | 0.0 | None | 0.0 | 61.667 | 2432825.0 | 28071.333 | 478.917 |
| control | google_adk | p2p_07_variance_within_tolerance | 3 | 1.0 | 0.0 | 0.0 | None | 0.0 | 86.333 | 3635539.667 | 27949.0 | 659.28 |
| control | google_adk | p2p_08_reverse_wrong_grn | 3 | 0.0 | 0.0 | 0.0 | None | 0.0 | 18.0 | 313477.667 | 14138.0 | 255.713 |
| control | google_adk | p2p_09_partial_payment | 3 | 0.0 | 0.0 | 0.0 | None | 0.0 | 87.667 | 4220408.333 | 33580.333 | 807.357 |

## Tool-call latency (ms, per call)

| server | client | calls | median | p95 | mean | max |
|---|---|---|---|---|---|---|
| control | google_adk | 3128 | 1.9 | 5.0 | 2.4 | 112.7 |

Per tool name in `latency.csv`.

## Tool calls per task (google_adk, mean over runs)

| task | control |
|---|---|
| close_01_clean | 24.667 |
| close_02_blocked | 20.0 |
| dup_01_retry_storm | 92.667 |
| gl_01_manual_je | 29.0 |
| gl_02_reverse_je | 43.333 |
| gl_03_closed_period | 4.333 |
| o2c_01_simple | 78.333 |
| o2c_02_credit_limit | 10.667 |
| o2c_03_partial_ship | 70.667 |
| o2c_04_credit_note | 84.333 |
| o2c_05_out_of_stock | 20.0 |
| o2c_06_payment_reversal | 50.0 |
| p2p_01_simple | 88.333 |
| p2p_02_partial_receipt | 107.0 |
| p2p_04_over_threshold | 32.333 |
| p2p_05_cancel | 33.333 |
| p2p_06_price_variance_5pct | 61.667 |
| p2p_07_variance_within_tolerance | 86.333 |
| p2p_08_reverse_wrong_grn | 18.0 |
| p2p_09_partial_payment | 87.667 |

## Alternative outcomes (tasks with `one_of` goals)

| server | client | task | run | outcome |
|---|---|---|---|---|
| control | google_adk | close_01_clean | 1 | closed |
| control | google_adk | close_01_clean | 2 | closed |
| control | google_adk | close_01_clean | 3 | closed |


## Failed goal checks

- control/google_adk/gl_02_reverse_je run 1: count got 0
- control/google_adk/gl_02_reverse_je run 2: count got 0
- control/google_adk/gl_02_reverse_je run 3: count got 0
- control/google_adk/o2c_01_simple run 1: count got 0
- control/google_adk/o2c_01_simple run 2: count got 0
- control/google_adk/o2c_01_simple run 3: count got 0
- control/google_adk/o2c_03_partial_ship run 1: count got 0
- control/google_adk/o2c_03_partial_ship run 2: count got 0; open_items got 0
- control/google_adk/o2c_03_partial_ship run 3: count got 0
- control/google_adk/p2p_01_simple run 1: count got 0
- control/google_adk/p2p_01_simple run 2: count got 0
- control/google_adk/p2p_01_simple run 3: count got 0
- control/google_adk/p2p_02_partial_receipt run 1: count got 0
- control/google_adk/p2p_02_partial_receipt run 2: count got 0
- control/google_adk/p2p_02_partial_receipt run 3: count got 0
- control/google_adk/p2p_04_over_threshold run 1: pending_approvals got 0
- control/google_adk/p2p_04_over_threshold run 2: pending_approvals got 0
- control/google_adk/p2p_04_over_threshold run 3: pending_approvals got 0
- control/google_adk/p2p_08_reverse_wrong_grn run 1: count got 0
- control/google_adk/p2p_08_reverse_wrong_grn run 2: count got 0
- control/google_adk/p2p_08_reverse_wrong_grn run 3: count got 0
- control/google_adk/p2p_09_partial_payment run 1: open_items got 0
- control/google_adk/p2p_09_partial_payment run 2: open_items got 0
- control/google_adk/p2p_09_partial_payment run 3: open_items got 0
