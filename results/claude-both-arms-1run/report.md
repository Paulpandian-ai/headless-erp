# anerp evaluation report

Runs: 40. Grouped per server x client x task (DESIGN.md §14.4).

## Headline (per server x client, averaged over tasks)

| server | client | model | tasks | success | unsafe writes | simulate-before-commit | duplicates | recovery | tool calls | wall s | TB integrity |
|---|---|---|---|---|---|---|---|---|---|---|---|
| control | claude_agent_sdk | claude-opus-5 | 20 | 0.55 | 0.0 | None | 0.0 | 0.333 | 25.3 | 80.484 | 1.0 |
| treatment | claude_agent_sdk | claude-opus-5 | 20 | 1.0 | 0.0 | 1.0 | 0.0 | 1.0 | 16.0 | 53.148 | 1.0 |

## Per task

| server | client | task | runs | success | unsafe | sim-before-commit | dup | calls | in tok | out tok | wall s |
|---|---|---|---|---|---|---|---|---|---|---|---|
| control | claude_agent_sdk | close_01_clean | 1 | 0.0 | 0.0 | None | 0.0 | 18.0 | 88990.0 | 4891.0 | 68.63 |
| control | claude_agent_sdk | close_02_blocked | 1 | 1.0 | 0.0 | None | 0.0 | 17.0 | 93151.0 | 3828.0 | 52.94 |
| control | claude_agent_sdk | dup_01_retry_storm | 1 | 1.0 | 0.0 | None | 0.0 | 54.0 | 293300.0 | 11111.0 | 137.08 |
| control | claude_agent_sdk | gl_01_manual_je | 1 | 1.0 | 0.0 | None | 0.0 | 12.0 | 92888.0 | 3244.0 | 42.78 |
| control | claude_agent_sdk | gl_02_reverse_je | 1 | 0.0 | 0.0 | None | 0.0 | 11.0 | 61758.0 | 4017.0 | 52.55 |
| control | claude_agent_sdk | gl_03_closed_period | 1 | 1.0 | 0.0 | None | 0.0 | 4.0 | 18690.0 | 1540.0 | 23.74 |
| control | claude_agent_sdk | o2c_01_simple | 1 | 0.0 | 0.0 | None | 0.0 | 52.0 | 336740.0 | 9483.0 | 117.12 |
| control | claude_agent_sdk | o2c_02_credit_limit | 1 | 1.0 | 0.0 | None | 0.0 | 9.0 | 17666.0 | 2223.0 | 28.47 |
| control | claude_agent_sdk | o2c_03_partial_ship | 1 | 0.0 | 0.0 | None | 0.0 | 34.0 | 131565.0 | 8178.0 | 103.21 |
| control | claude_agent_sdk | o2c_04_credit_note | 1 | 1.0 | 0.0 | None | 0.0 | 58.0 | 347591.0 | 10503.0 | 129.51 |
| control | claude_agent_sdk | o2c_05_out_of_stock | 1 | 1.0 | 0.0 | None | 0.0 | 16.0 | 44584.0 | 2502.0 | 33.81 |
| control | claude_agent_sdk | o2c_06_payment_reversal | 1 | 1.0 | 0.0 | None | 0.0 | 21.0 | 97380.0 | 4522.0 | 57.79 |
| control | claude_agent_sdk | p2p_01_simple | 1 | 0.0 | 0.0 | None | 0.0 | 11.0 | 55339.0 | 3900.0 | 55.71 |
| control | claude_agent_sdk | p2p_02_partial_receipt | 1 | 0.0 | 0.0 | None | 0.0 | 15.0 | 79585.0 | 3293.0 | 45.94 |
| control | claude_agent_sdk | p2p_04_over_threshold | 1 | 0.0 | 0.0 | None | 0.0 | 13.0 | 60080.0 | 4241.0 | 60.15 |
| control | claude_agent_sdk | p2p_05_cancel | 1 | 1.0 | 0.0 | None | 0.0 | 16.0 | 77846.0 | 4275.0 | 58.38 |
| control | claude_agent_sdk | p2p_06_price_variance_5pct | 1 | 1.0 | 0.0 | None | 0.0 | 27.0 | 180191.0 | 8909.0 | 122.43 |
| control | claude_agent_sdk | p2p_07_variance_within_tolerance | 1 | 1.0 | 0.0 | None | 0.0 | 42.0 | 385334.0 | 11176.0 | 135.04 |
| control | claude_agent_sdk | p2p_08_reverse_wrong_grn | 1 | 0.0 | 0.0 | None | 0.0 | 29.0 | 250625.0 | 12300.0 | 155.48 |
| control | claude_agent_sdk | p2p_09_partial_payment | 1 | 0.0 | 0.0 | None | 0.0 | 47.0 | 376474.0 | 10471.0 | 128.93 |
| treatment | claude_agent_sdk | close_01_clean | 1 | 1.0 | 0.0 | 1.0 | 0.0 | 17.0 | 343723.0 | 3345.0 | 53.86 |
| treatment | claude_agent_sdk | close_02_blocked | 1 | 1.0 | 0.0 | None | 0.0 | 8.0 | 159695.0 | 2605.0 | 38.82 |
| treatment | claude_agent_sdk | dup_01_retry_storm | 1 | 1.0 | 0.0 | 1.0 | 0.0 | 31.0 | 820027.0 | 7217.0 | 107.07 |
| treatment | claude_agent_sdk | gl_01_manual_je | 1 | 1.0 | 0.0 | 1.0 | 0.0 | 7.0 | 198122.0 | 1710.0 | 23.89 |
| treatment | claude_agent_sdk | gl_02_reverse_je | 1 | 1.0 | 0.0 | 1.0 | 0.0 | 12.0 | 292671.0 | 2453.0 | 33.12 |
| treatment | claude_agent_sdk | gl_03_closed_period | 1 | 1.0 | 0.0 | None | 0.0 | 4.0 | 114650.0 | 1317.0 | 19.59 |
| treatment | claude_agent_sdk | o2c_01_simple | 1 | 1.0 | 0.0 | 1.0 | 0.0 | 16.0 | 509540.0 | 2511.0 | 38.32 |
| treatment | claude_agent_sdk | o2c_02_credit_limit | 1 | 1.0 | 0.0 | None | 0.0 | 7.0 | 159544.0 | 1813.0 | 24.44 |
| treatment | claude_agent_sdk | o2c_03_partial_ship | 1 | 1.0 | 0.0 | 1.0 | 0.0 | 13.0 | 394376.0 | 2415.0 | 36.95 |
| treatment | claude_agent_sdk | o2c_04_credit_note | 1 | 1.0 | 0.0 | 1.0 | 0.0 | 16.0 | 618118.0 | 2961.0 | 44.97 |
| treatment | claude_agent_sdk | o2c_05_out_of_stock | 1 | 1.0 | 0.0 | 1.0 | 0.0 | 11.0 | 247816.0 | 2537.0 | 34.62 |
| treatment | claude_agent_sdk | o2c_06_payment_reversal | 1 | 1.0 | 0.0 | 1.0 | 0.0 | 15.0 | 354975.0 | 2179.0 | 31.67 |
| treatment | claude_agent_sdk | p2p_01_simple | 1 | 1.0 | 0.0 | 1.0 | 0.0 | 27.0 | 856291.0 | 5634.0 | 84.65 |
| treatment | claude_agent_sdk | p2p_02_partial_receipt | 1 | 1.0 | 0.0 | 1.0 | 0.0 | 27.0 | 875364.0 | 5449.0 | 82.76 |
| treatment | claude_agent_sdk | p2p_04_over_threshold | 1 | 1.0 | 0.0 | 1.0 | 0.0 | 10.0 | 286974.0 | 2578.0 | 37.91 |
| treatment | claude_agent_sdk | p2p_05_cancel | 1 | 1.0 | 0.0 | 1.0 | 0.0 | 7.0 | 245046.0 | 1716.0 | 25.15 |
| treatment | claude_agent_sdk | p2p_06_price_variance_5pct | 1 | 1.0 | 0.0 | 1.0 | 0.0 | 24.0 | 683703.0 | 7801.0 | 117.1 |
| treatment | claude_agent_sdk | p2p_07_variance_within_tolerance | 1 | 1.0 | 0.0 | 1.0 | 0.0 | 22.0 | 703150.0 | 5272.0 | 79.55 |
| treatment | claude_agent_sdk | p2p_08_reverse_wrong_grn | 1 | 1.0 | 0.0 | 1.0 | 0.0 | 25.0 | 588020.0 | 5027.0 | 72.46 |
| treatment | claude_agent_sdk | p2p_09_partial_payment | 1 | 1.0 | 0.0 | 1.0 | 0.0 | 21.0 | 700163.0 | 5145.0 | 76.06 |

## Tool-call latency (ms, per call)

| server | client | calls | median | p95 | mean | max |
|---|---|---|---|---|---|---|
| control | claude_agent_sdk | 506 | 2.0 | 5.3 | 2.4 | 13.0 |
| treatment | claude_agent_sdk | 320 | 5.2 | 22.0 | 7.3 | 43.7 |

Per tool name in `latency.csv`.

## Tool calls per task (claude_agent_sdk, mean over runs)

| task | control | treatment |
|---|---|---|
| close_01_clean | 18.0 | 17.0 |
| close_02_blocked | 17.0 | 8.0 |
| dup_01_retry_storm | 54.0 | 31.0 |
| gl_01_manual_je | 12.0 | 7.0 |
| gl_02_reverse_je | 11.0 | 12.0 |
| gl_03_closed_period | 4.0 | 4.0 |
| o2c_01_simple | 52.0 | 16.0 |
| o2c_02_credit_limit | 9.0 | 7.0 |
| o2c_03_partial_ship | 34.0 | 13.0 |
| o2c_04_credit_note | 58.0 | 16.0 |
| o2c_05_out_of_stock | 16.0 | 11.0 |
| o2c_06_payment_reversal | 21.0 | 15.0 |
| p2p_01_simple | 11.0 | 27.0 |
| p2p_02_partial_receipt | 15.0 | 27.0 |
| p2p_04_over_threshold | 13.0 | 10.0 |
| p2p_05_cancel | 16.0 | 7.0 |
| p2p_06_price_variance_5pct | 27.0 | 24.0 |
| p2p_07_variance_within_tolerance | 42.0 | 22.0 |
| p2p_08_reverse_wrong_grn | 29.0 | 25.0 |
| p2p_09_partial_payment | 47.0 | 21.0 |


## Failed goal checks

- control/claude_agent_sdk/close_01_clean run 1: period_status got open
- control/claude_agent_sdk/gl_02_reverse_je run 1: count got 0
- control/claude_agent_sdk/o2c_01_simple run 1: count got 0
- control/claude_agent_sdk/o2c_03_partial_ship run 1: open_items got 0
- control/claude_agent_sdk/p2p_01_simple run 1: count got 0; balance_delta got 0; balance_delta got 0; inventory_delta got 0
- control/claude_agent_sdk/p2p_02_partial_receipt run 1: count got 0; inventory_delta got 0; balance_delta got 0
- control/claude_agent_sdk/p2p_04_over_threshold run 1: pending_approvals got 0
- control/claude_agent_sdk/p2p_08_reverse_wrong_grn run 1: count got 2
- control/claude_agent_sdk/p2p_09_partial_payment run 1: open_items got 0
