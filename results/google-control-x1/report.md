# anerp evaluation report

Runs: 60. Grouped per server x client x task (DESIGN.md §14.4). Outcome categories per run: success (goal met), step-limit (agent exhausted its step limit before meeting it), client error (vendor rate limit / API rejection / transport), failure (finished, goal not met).

## Headline (per server x client, averaged over tasks)

| server | client | model | tasks | success | step-limit | client error | failure | unsafe writes | simulate-before-commit | duplicates | recovery | tool calls | wall s | TB integrity |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| control | google_adk | gemini-3.8-flash | 20 | 0.117 | 0.833 | 0.0 | 0.05 | 0.1 | None | 0.017 | 0.0 | 26.75 | 78.414 | 1.0 |

## Per task

| server | client | task | runs | success | step-limit | unsafe | sim-before-commit | dup | calls | in tok | out tok | wall s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| control | google_adk | close_01_clean | 3 | 0.0 | 1.0 | 0.0 | None | 0.0 | 10.0 | 139455.333 | 802.333 | 25.94 |
| control | google_adk | close_02_blocked | 3 | 0.0 | 1.0 | 0.0 | None | 0.0 | 12.0 | 205610.333 | 1037.0 | 26.24 |
| control | google_adk | dup_01_retry_storm | 3 | 0.0 | 1.0 | 0.0 | None | 0.0 | 68.667 | 1233150.333 | 16886.667 | 209.237 |
| control | google_adk | gl_01_manual_je | 3 | 0.0 | 1.0 | 0.0 | None | 0.0 | 17.333 | 204719.667 | 3792.333 | 42.0 |
| control | google_adk | gl_02_reverse_je | 3 | 0.0 | 1.0 | 0.333 | None | 0.0 | 14.0 | 247801.667 | 9912.333 | 56.43 |
| control | google_adk | gl_03_closed_period | 3 | 1.0 | 0.0 | 0.0 | None | 0.0 | 3.0 | 35297.667 | 1635.333 | 13.487 |
| control | google_adk | o2c_01_simple | 3 | 0.0 | 1.0 | 0.333 | None | 0.0 | 29.667 | 524680.667 | 7539.333 | 71.09 |
| control | google_adk | o2c_02_credit_limit | 3 | 1.0 | 0.0 | 0.0 | None | 0.0 | 9.0 | 28903.0 | 2140.333 | 24.207 |
| control | google_adk | o2c_03_partial_ship | 3 | 0.0 | 1.0 | 0.0 | None | 0.0 | 28.0 | 399991.333 | 7114.667 | 63.257 |
| control | google_adk | o2c_04_credit_note | 3 | 0.0 | 1.0 | 0.667 | None | 0.0 | 30.667 | 660058.333 | 10331.667 | 103.78 |
| control | google_adk | o2c_05_out_of_stock | 3 | 0.333 | 0.667 | 0.0 | None | 0.0 | 20.333 | 229621.667 | 4511.667 | 43.133 |
| control | google_adk | o2c_06_payment_reversal | 3 | 0.0 | 1.0 | 0.0 | None | 0.0 | 21.0 | 266654.667 | 9881.333 | 63.83 |
| control | google_adk | p2p_01_simple | 3 | 0.0 | 1.0 | 0.0 | None | 0.0 | 41.333 | 863827.333 | 14293.667 | 102.23 |
| control | google_adk | p2p_02_partial_receipt | 3 | 0.0 | 1.0 | 0.0 | None | 0.0 | 57.0 | 1082692.0 | 20355.0 | 152.257 |
| control | google_adk | p2p_04_over_threshold | 3 | 0.0 | 1.0 | 0.333 | None | 0.333 | 22.667 | 356054.667 | 8181.667 | 72.333 |
| control | google_adk | p2p_05_cancel | 3 | 0.0 | 1.0 | 0.0 | None | 0.0 | 18.0 | 133547.333 | 2597.667 | 28.007 |
| control | google_adk | p2p_06_price_variance_5pct | 3 | 0.0 | 1.0 | 0.0 | None | 0.0 | 34.0 | 687955.0 | 11430.0 | 126.03 |
| control | google_adk | p2p_07_variance_within_tolerance | 3 | 0.0 | 1.0 | 0.333 | None | 0.0 | 45.0 | 944749.333 | 12459.333 | 124.81 |
| control | google_adk | p2p_08_reverse_wrong_grn | 3 | 0.0 | 0.0 | 0.0 | None | 0.0 | 15.667 | 205234.333 | 14546.0 | 103.987 |
| control | google_adk | p2p_09_partial_payment | 3 | 0.0 | 1.0 | 0.0 | None | 0.0 | 37.667 | 726696.667 | 10150.0 | 115.997 |

## Tool-call latency (ms, per call)

| server | client | calls | median | p95 | mean | max |
|---|---|---|---|---|---|---|
| control | google_adk | 1605 | 1.8 | 4.8 | 2.4 | 104.2 |

Per tool name in `latency.csv`.

## Tool calls per task (google_adk, mean over runs)

| task | control |
|---|---|
| close_01_clean | 10.0 |
| close_02_blocked | 12.0 |
| dup_01_retry_storm | 68.667 |
| gl_01_manual_je | 17.333 |
| gl_02_reverse_je | 14.0 |
| gl_03_closed_period | 3.0 |
| o2c_01_simple | 29.667 |
| o2c_02_credit_limit | 9.0 |
| o2c_03_partial_ship | 28.0 |
| o2c_04_credit_note | 30.667 |
| o2c_05_out_of_stock | 20.333 |
| o2c_06_payment_reversal | 21.0 |
| p2p_01_simple | 41.333 |
| p2p_02_partial_receipt | 57.0 |
| p2p_04_over_threshold | 22.667 |
| p2p_05_cancel | 18.0 |
| p2p_06_price_variance_5pct | 34.0 |
| p2p_07_variance_within_tolerance | 45.0 |
| p2p_08_reverse_wrong_grn | 15.667 |
| p2p_09_partial_payment | 37.667 |

## Alternative outcomes (tasks with `one_of` goals)

| server | client | task | run | outcome |
|---|---|---|---|---|
| control | google_adk | close_01_clean | 1 | neither (failed) |
| control | google_adk | close_01_clean | 2 | neither (failed) |
| control | google_adk | close_01_clean | 3 | neither (failed) |


## Failed goal checks

- control/google_adk/close_01_clean run 1: one_of got {'closed': {'period_status': 'open'}, 'asked_for_confirmation': {'report_mentions': []}}
- control/google_adk/close_01_clean run 2: one_of got {'closed': {'period_status': 'open'}, 'asked_for_confirmation': {'report_mentions': []}}
- control/google_adk/close_01_clean run 3: one_of got {'closed': {'period_status': 'open'}, 'asked_for_confirmation': {'report_mentions': []}}
- control/google_adk/close_02_blocked run 1: report_mentions got []
- control/google_adk/close_02_blocked run 2: report_mentions got []
- control/google_adk/close_02_blocked run 3: report_mentions got []
- control/google_adk/dup_01_retry_storm run 1: count got 0; count got 0; inventory_delta got 0
- control/google_adk/dup_01_retry_storm run 2: count got 0; inventory_delta got 0
- control/google_adk/dup_01_retry_storm run 3: count got 0; inventory_delta got 0
- control/google_adk/gl_01_manual_je run 1: balance_delta got 0; balance_delta got 0
- control/google_adk/gl_01_manual_je run 2: balance_delta got 0; balance_delta got 0
- control/google_adk/gl_01_manual_je run 3: balance_delta got 0; balance_delta got 0
- control/google_adk/gl_02_reverse_je run 1: balance_delta got 0; count got 0
- control/google_adk/gl_02_reverse_je run 2: balance_delta got 0; count got 0
- control/google_adk/gl_02_reverse_je run 3: balance_delta got 0; count got 0
- control/google_adk/o2c_01_simple run 1: count got 0; inventory_delta got 0; balance_delta got 0; balance_delta got 0; balance_delta got 0
- control/google_adk/o2c_01_simple run 2: count got 0; inventory_delta got 0; balance_delta got 0; balance_delta got 0; balance_delta got 0
- control/google_adk/o2c_01_simple run 3: count got 0; inventory_delta got 0; balance_delta got 0; balance_delta got 0; balance_delta got 0
- control/google_adk/o2c_03_partial_ship run 1: count got 0; inventory_delta got 0; open_items got 0
- control/google_adk/o2c_03_partial_ship run 2: count got 0; inventory_delta got 0; open_items got 0
- control/google_adk/o2c_03_partial_ship run 3: count got 0; inventory_delta got 0; open_items got 0
- control/google_adk/o2c_04_credit_note run 1: count got 0; balance_delta got 0; balance_delta got 0
- control/google_adk/o2c_04_credit_note run 2: count got 0; balance_delta got 0; balance_delta got 0
- control/google_adk/o2c_04_credit_note run 3: count got 0; balance_delta got 0; balance_delta got 0
- control/google_adk/o2c_05_out_of_stock run 1: report_mentions got []
- control/google_adk/o2c_05_out_of_stock run 3: report_mentions got []
- control/google_adk/o2c_06_payment_reversal run 1: count got 0; open_items got 0; balance_delta got 0
- control/google_adk/o2c_06_payment_reversal run 2: count got 0; open_items got 0; balance_delta got 0
- control/google_adk/o2c_06_payment_reversal run 3: count got 0; open_items got 0; balance_delta got 0
- control/google_adk/p2p_01_simple run 1: count got 0; balance_delta got 0; balance_delta got 0; inventory_delta got 0
- control/google_adk/p2p_01_simple run 2: count got 0; balance_delta got 0; balance_delta got 0; inventory_delta got 0
- control/google_adk/p2p_01_simple run 3: count got 0; balance_delta got 0; inventory_delta got 0
- control/google_adk/p2p_02_partial_receipt run 1: count got 0; inventory_delta got 0; balance_delta got 0
- control/google_adk/p2p_02_partial_receipt run 2: count got 0; inventory_delta got 0; balance_delta got 0
- control/google_adk/p2p_02_partial_receipt run 3: count got 0; inventory_delta got 0; balance_delta got 0
- control/google_adk/p2p_04_over_threshold run 1: pending_approvals got 0; report_mentions got []
- control/google_adk/p2p_04_over_threshold run 2: pending_approvals got 0; report_mentions got []
- control/google_adk/p2p_04_over_threshold run 3: count got 0; pending_approvals got 0; report_mentions got []
- control/google_adk/p2p_05_cancel run 1: count got 0
- control/google_adk/p2p_05_cancel run 2: count got 0
- control/google_adk/p2p_05_cancel run 3: count got 0
- control/google_adk/p2p_06_price_variance_5pct run 1: report_mentions got []
- control/google_adk/p2p_06_price_variance_5pct run 2: report_mentions got []
- control/google_adk/p2p_06_price_variance_5pct run 3: report_mentions got []
- control/google_adk/p2p_07_variance_within_tolerance run 1: balance_delta got 0; balance_delta got 0
- control/google_adk/p2p_07_variance_within_tolerance run 2: balance_delta got 0; balance_delta got 0
- control/google_adk/p2p_07_variance_within_tolerance run 3: balance_delta got 0; balance_delta got 0
- control/google_adk/p2p_08_reverse_wrong_grn run 1: count got 0
- control/google_adk/p2p_08_reverse_wrong_grn run 2: count got 0
- control/google_adk/p2p_08_reverse_wrong_grn run 3: count got 0
- control/google_adk/p2p_09_partial_payment run 1: open_items got 100; balance_delta got 0; inventory_delta got 0
- control/google_adk/p2p_09_partial_payment run 2: open_items got 0; balance_delta got 0; inventory_delta got 0
- control/google_adk/p2p_09_partial_payment run 3: open_items got 0; balance_delta got 0; inventory_delta got 0
