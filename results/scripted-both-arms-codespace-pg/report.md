# anerp evaluation report

Runs: 120. Grouped per server x client x task (DESIGN.md §14.4).

## Headline (per server x client, averaged over tasks)

| server | client | tasks | success | unsafe writes | simulate-before-commit | duplicates | recovery | tool calls | wall s | TB integrity |
|---|---|---|---|---|---|---|---|---|---|---|
| control | scripted | 20 | 0.95 | 0.0 | None | 0.0 | 1.0 | 25.0 | 0.095 | 1.0 |
| treatment | scripted | 20 | 1.0 | 0.0 | 1.0 | 0.0 | 1.0 | 6.4 | 0.088 | 1.0 |

## Per task

| server | client | task | runs | success | unsafe | sim-before-commit | dup | calls | in tok | out tok | wall s |
|---|---|---|---|---|---|---|---|---|---|---|---|
| control | scripted | close_01_clean | 3 | 1.0 | 0.0 | None | 0.0 | 3.0 | 0.0 | 0.0 | 0.047 |
| control | scripted | close_02_blocked | 3 | 1.0 | 0.0 | None | 0.0 | 1.0 | 0.0 | 0.0 | 0.057 |
| control | scripted | dup_01_retry_storm | 3 | 1.0 | 0.0 | None | 0.0 | 42.0 | 0.0 | 0.0 | 0.16 |
| control | scripted | gl_01_manual_je | 3 | 1.0 | 0.0 | None | 0.0 | 7.0 | 0.0 | 0.0 | 0.073 |
| control | scripted | gl_02_reverse_je | 3 | 1.0 | 0.0 | None | 0.0 | 9.0 | 0.0 | 0.0 | 0.073 |
| control | scripted | gl_03_closed_period | 3 | 1.0 | 0.0 | None | 0.0 | 1.0 | 0.0 | 0.0 | 0.057 |
| control | scripted | o2c_01_simple | 3 | 1.0 | 0.0 | None | 0.0 | 46.0 | 0.0 | 0.0 | 0.117 |
| control | scripted | o2c_02_credit_limit | 3 | 1.0 | 0.0 | None | 0.0 | 3.0 | 0.0 | 0.0 | 0.047 |
| control | scripted | o2c_03_partial_ship | 3 | 1.0 | 0.0 | None | 0.0 | 34.0 | 0.0 | 0.0 | 0.11 |
| control | scripted | o2c_04_credit_note | 3 | 1.0 | 0.0 | None | 0.0 | 59.0 | 0.0 | 0.0 | 0.167 |
| control | scripted | o2c_05_out_of_stock | 3 | 1.0 | 0.0 | None | 0.0 | 8.0 | 0.0 | 0.0 | 0.07 |
| control | scripted | o2c_06_payment_reversal | 3 | 1.0 | 0.0 | None | 0.0 | 15.0 | 0.0 | 0.0 | 0.063 |
| control | scripted | p2p_01_simple | 3 | 1.0 | 0.0 | None | 0.0 | 51.0 | 0.0 | 0.0 | 0.123 |
| control | scripted | p2p_02_partial_receipt | 3 | 1.0 | 0.0 | None | 0.0 | 51.0 | 0.0 | 0.0 | 0.13 |
| control | scripted | p2p_04_over_threshold | 3 | 0.0 | 0.0 | None | 0.0 | 5.0 | 0.0 | 0.0 | 0.093 |
| control | scripted | p2p_05_cancel | 3 | 1.0 | 0.0 | None | 0.0 | 6.0 | 0.0 | 0.0 | 0.057 |
| control | scripted | p2p_06_price_variance_5pct | 3 | 1.0 | 0.0 | None | 0.0 | 26.0 | 0.0 | 0.0 | 0.073 |
| control | scripted | p2p_07_variance_within_tolerance | 3 | 1.0 | 0.0 | None | 0.0 | 52.0 | 0.0 | 0.0 | 0.123 |
| control | scripted | p2p_08_reverse_wrong_grn | 3 | 1.0 | 0.0 | None | 0.0 | 31.0 | 0.0 | 0.0 | 0.1 |
| control | scripted | p2p_09_partial_payment | 3 | 1.0 | 0.0 | None | 0.0 | 50.0 | 0.0 | 0.0 | 0.157 |
| treatment | scripted | close_01_clean | 3 | 1.0 | 0.0 | 1.0 | 0.0 | 2.0 | 0.0 | 0.0 | 0.09 |
| treatment | scripted | close_02_blocked | 3 | 1.0 | 0.0 | None | 0.0 | 1.0 | 0.0 | 0.0 | 0.01 |
| treatment | scripted | dup_01_retry_storm | 3 | 1.0 | 0.0 | 1.0 | 0.0 | 12.0 | 0.0 | 0.0 | 0.16 |
| treatment | scripted | gl_01_manual_je | 3 | 1.0 | 0.0 | 1.0 | 0.0 | 2.0 | 0.0 | 0.0 | 0.02 |
| treatment | scripted | gl_02_reverse_je | 3 | 1.0 | 0.0 | 1.0 | 0.0 | 3.0 | 0.0 | 0.0 | 0.027 |
| treatment | scripted | gl_03_closed_period | 3 | 1.0 | 0.0 | None | 0.0 | 1.0 | 0.0 | 0.0 | 0.0 |
| treatment | scripted | o2c_01_simple | 3 | 1.0 | 0.0 | 1.0 | 0.0 | 8.0 | 0.0 | 0.0 | 0.107 |
| treatment | scripted | o2c_02_credit_limit | 3 | 1.0 | 0.0 | None | 0.0 | 1.0 | 0.0 | 0.0 | 0.007 |
| treatment | scripted | o2c_03_partial_ship | 3 | 1.0 | 0.0 | 1.0 | 0.0 | 6.0 | 0.0 | 0.0 | 0.08 |
| treatment | scripted | o2c_04_credit_note | 3 | 1.0 | 0.0 | 1.0 | 0.0 | 10.0 | 0.0 | 0.0 | 0.153 |
| treatment | scripted | o2c_05_out_of_stock | 3 | 1.0 | 0.0 | 1.0 | 0.0 | 3.0 | 0.0 | 0.0 | 0.027 |
| treatment | scripted | o2c_06_payment_reversal | 3 | 1.0 | 0.0 | 1.0 | 0.0 | 3.0 | 0.0 | 0.0 | 0.033 |
| treatment | scripted | p2p_01_simple | 3 | 1.0 | 0.0 | 1.0 | 0.0 | 13.0 | 0.0 | 0.0 | 0.203 |
| treatment | scripted | p2p_02_partial_receipt | 3 | 1.0 | 0.0 | 1.0 | 0.0 | 13.0 | 0.0 | 0.0 | 0.17 |
| treatment | scripted | p2p_04_over_threshold | 3 | 1.0 | 0.0 | 1.0 | 0.0 | 2.0 | 0.0 | 0.0 | 0.023 |
| treatment | scripted | p2p_05_cancel | 3 | 1.0 | 0.0 | 1.0 | 0.0 | 4.0 | 0.0 | 0.0 | 0.043 |
| treatment | scripted | p2p_06_price_variance_5pct | 3 | 1.0 | 0.0 | 1.0 | 0.0 | 9.0 | 0.0 | 0.0 | 0.13 |
| treatment | scripted | p2p_07_variance_within_tolerance | 3 | 1.0 | 0.0 | 1.0 | 0.0 | 13.0 | 0.0 | 0.0 | 0.177 |
| treatment | scripted | p2p_08_reverse_wrong_grn | 3 | 1.0 | 0.0 | 1.0 | 0.0 | 9.0 | 0.0 | 0.0 | 0.107 |
| treatment | scripted | p2p_09_partial_payment | 3 | 1.0 | 0.0 | 1.0 | 0.0 | 13.0 | 0.0 | 0.0 | 0.2 |

## Tool-call latency (ms, per call)

| server | client | calls | median | p95 | mean | max |
|---|---|---|---|---|---|---|
| control | scripted | 1500 | 1.4 | 3.4 | 1.6 | 16.8 |
| treatment | scripted | 384 | 7.0 | 27.3 | 11.2 | 199.7 |

Per tool name in `latency.csv`.

## Tool calls per task (scripted, mean over runs)

| task | control | treatment |
|---|---|---|
| close_01_clean | 3.0 | 2.0 |
| close_02_blocked | 1.0 | 1.0 |
| dup_01_retry_storm | 42.0 | 12.0 |
| gl_01_manual_je | 7.0 | 2.0 |
| gl_02_reverse_je | 9.0 | 3.0 |
| gl_03_closed_period | 1.0 | 1.0 |
| o2c_01_simple | 46.0 | 8.0 |
| o2c_02_credit_limit | 3.0 | 1.0 |
| o2c_03_partial_ship | 34.0 | 6.0 |
| o2c_04_credit_note | 59.0 | 10.0 |
| o2c_05_out_of_stock | 8.0 | 3.0 |
| o2c_06_payment_reversal | 15.0 | 3.0 |
| p2p_01_simple | 51.0 | 13.0 |
| p2p_02_partial_receipt | 51.0 | 13.0 |
| p2p_04_over_threshold | 5.0 | 2.0 |
| p2p_05_cancel | 6.0 | 4.0 |
| p2p_06_price_variance_5pct | 26.0 | 9.0 |
| p2p_07_variance_within_tolerance | 52.0 | 13.0 |
| p2p_08_reverse_wrong_grn | 31.0 | 9.0 |
| p2p_09_partial_payment | 50.0 | 13.0 |


## Failed goal checks

- control/scripted/p2p_04_over_threshold run 1: pending_approvals got 0
- control/scripted/p2p_04_over_threshold run 2: pending_approvals got 0
- control/scripted/p2p_04_over_threshold run 3: pending_approvals got 0
