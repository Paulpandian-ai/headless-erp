# anerp evaluation report

Runs: 360. Grouped per server x client x task (DESIGN.md §14.4). Outcome categories per run: success (goal met), step-limit (agent exhausted its step limit before meeting it), vendor unavailable (the vendor could not serve the run after every retry - 503/overloaded; a dropout, so success is also given over completed runs), client error (rate limit / API rejection / transport), failure (finished, goal not met). Step limits in this run: 50-120 per round.

## Headline (per server x client, averaged over tasks)

| server | client | model | tasks | success (all runs) | success (completed runs) | step-limit | vendor unavailable | client error | failure | unsafe writes | simulate-before-commit | duplicates | recovery | tool calls | wall s | TB integrity |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| control | claude_agent_sdk | claude-sonnet-5 | 20 | 0.65 | 0.65 | 0.0 | 0.0 | 0.0 | 0.35 | 0.033 | None | 0.0 | 0.667 | 27.633 | 76.63 | 1.0 |
| control | google_adk | gemini-3.8-flash | 20 | 0.6 | 0.6 | 0.0 | 0.0 | 0.0 | 0.4 | 0.0 | None | 0.0 | 0.333 | 52.133 | 297.626 | 1.0 |
| control | openai_agents_sdk | gpt-5.6-terra | 20 | 0.417 | 0.417 | 0.0 | 0.0 | 0.0 | 0.583 | 0.0 | None | 0.0 | 0.111 | 18.383 | 20.466 | 1.0 |
| treatment | claude_agent_sdk | claude-sonnet-5 | 20 | 0.95 | 0.95 | 0.0 | 0.0 | 0.0 | 0.05 | 0.0 | 1.0 | 0.05 | 1.0 | 9.283 | 38.446 | 1.0 |
| treatment | google_adk | gemini-3.8-flash | 20 | 0.933 | 0.933 | 0.0 | 0.0 | 0.0 | 0.067 | 0.0 | 1.0 | 0.033 | 0.778 | 16.55 | 86.432 | 1.0 |
| treatment | openai_agents_sdk | gpt-5.6-terra | 20 | 0.95 | 0.95 | 0.0 | 0.0 | 0.0 | 0.05 | 0.0 | 0.995 | 0.05 | 1.0 | 7.65 | 18.369 | 1.0 |

## Per task

| server | client | task | runs | success | step-limit | unsafe | sim-before-commit | dup | calls | in tok | out tok | wall s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| control | claude_agent_sdk | close_01_clean | 3 | 1.0 | 0.0 | 0.0 | None | 0.0 | 17.333 | 60506.333 | 3402.667 | 37.863 |
| control | claude_agent_sdk | close_02_blocked | 3 | 1.0 | 0.0 | 0.0 | None | 0.0 | 12.0 | 30138.667 | 3008.333 | 34.203 |
| control | claude_agent_sdk | dup_01_retry_storm | 3 | 1.0 | 0.0 | 0.0 | None | 0.0 | 50.333 | 259834.667 | 11938.0 | 119.383 |
| control | claude_agent_sdk | gl_01_manual_je | 3 | 1.0 | 0.0 | 0.0 | None | 0.0 | 10.667 | 63572.667 | 2361.667 | 25.903 |
| control | claude_agent_sdk | gl_02_reverse_je | 3 | 0.667 | 0.0 | 0.0 | None | 0.0 | 13.0 | 71869.0 | 4617.333 | 49.86 |
| control | claude_agent_sdk | gl_03_closed_period | 3 | 1.0 | 0.0 | 0.0 | None | 0.0 | 1.667 | 6256.333 | 619.333 | 8.697 |
| control | claude_agent_sdk | o2c_01_simple | 3 | 0.0 | 0.0 | 0.0 | None | 0.0 | 48.333 | 300677.333 | 10556.333 | 102.763 |
| control | claude_agent_sdk | o2c_02_credit_limit | 3 | 1.0 | 0.0 | 0.0 | None | 0.0 | 5.333 | 14137.667 | 1506.0 | 17.897 |
| control | claude_agent_sdk | o2c_03_partial_ship | 3 | 0.0 | 0.0 | 0.0 | None | 0.0 | 41.333 | 233705.667 | 10053.333 | 99.173 |
| control | claude_agent_sdk | o2c_04_credit_note | 3 | 1.0 | 0.0 | 0.0 | None | 0.0 | 56.667 | 397688.333 | 13604.0 | 131.31 |
| control | claude_agent_sdk | o2c_05_out_of_stock | 3 | 1.0 | 0.0 | 0.0 | None | 0.0 | 7.667 | 32227.667 | 1714.333 | 21.923 |
| control | claude_agent_sdk | o2c_06_payment_reversal | 3 | 0.333 | 0.0 | 0.0 | None | 0.0 | 20.333 | 89923.667 | 4016.333 | 42.947 |
| control | claude_agent_sdk | p2p_01_simple | 3 | 0.0 | 0.0 | 0.0 | None | 0.0 | 47.0 | 302667.0 | 11335.333 | 108.487 |
| control | claude_agent_sdk | p2p_02_partial_receipt | 3 | 0.0 | 0.0 | 0.0 | None | 0.0 | 50.333 | 345089.0 | 21126.0 | 217.233 |
| control | claude_agent_sdk | p2p_04_over_threshold | 3 | 0.0 | 0.0 | 0.667 | None | 0.0 | 9.0 | 39141.333 | 2921.0 | 34.543 |
| control | claude_agent_sdk | p2p_05_cancel | 3 | 1.0 | 0.0 | 0.0 | None | 0.0 | 9.0 | 39603.667 | 2155.0 | 26.233 |
| control | claude_agent_sdk | p2p_06_price_variance_5pct | 3 | 1.0 | 0.0 | 0.0 | None | 0.0 | 24.667 | 162310.0 | 9202.667 | 96.017 |
| control | claude_agent_sdk | p2p_07_variance_within_tolerance | 3 | 1.0 | 0.0 | 0.0 | None | 0.0 | 49.0 | 331574.667 | 11286.0 | 109.797 |
| control | claude_agent_sdk | p2p_08_reverse_wrong_grn | 3 | 1.0 | 0.0 | 0.0 | None | 0.0 | 34.667 | 250029.0 | 13096.0 | 140.157 |
| control | claude_agent_sdk | p2p_09_partial_payment | 3 | 0.0 | 0.0 | 0.0 | None | 0.0 | 44.333 | 301264.333 | 10871.667 | 108.217 |
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
| control | openai_agents_sdk | close_01_clean | 3 | 1.0 | 0.0 | 0.0 | None | 0.0 | 15.333 | 18403.667 | 576.667 | 10.203 |
| control | openai_agents_sdk | close_02_blocked | 3 | 1.0 | 0.0 | 0.0 | None | 0.0 | 14.667 | 11387.0 | 475.0 | 7.927 |
| control | openai_agents_sdk | dup_01_retry_storm | 3 | 1.0 | 0.0 | 0.0 | None | 0.0 | 35.0 | 89766.0 | 2456.333 | 41.843 |
| control | openai_agents_sdk | gl_01_manual_je | 3 | 1.0 | 0.0 | 0.0 | None | 0.0 | 10.667 | 43471.667 | 745.333 | 14.263 |
| control | openai_agents_sdk | gl_02_reverse_je | 3 | 0.0 | 0.0 | 0.0 | None | 0.0 | 10.0 | 22533.667 | 681.0 | 11.937 |
| control | openai_agents_sdk | gl_03_closed_period | 3 | 1.0 | 0.0 | 0.0 | None | 0.0 | 1.0 | 2794.333 | 98.0 | 3.003 |
| control | openai_agents_sdk | o2c_01_simple | 3 | 0.0 | 0.0 | 0.0 | None | 0.0 | 26.0 | 94339.333 | 1775.0 | 31.493 |
| control | openai_agents_sdk | o2c_02_credit_limit | 3 | 1.0 | 0.0 | 0.0 | None | 0.0 | 4.667 | 3075.667 | 201.0 | 3.933 |
| control | openai_agents_sdk | o2c_03_partial_ship | 3 | 0.0 | 0.0 | 0.0 | None | 0.0 | 22.333 | 49566.0 | 1576.0 | 22.157 |
| control | openai_agents_sdk | o2c_04_credit_note | 3 | 0.333 | 0.0 | 0.0 | None | 0.0 | 29.0 | 108806.333 | 2146.667 | 38.76 |
| control | openai_agents_sdk | o2c_05_out_of_stock | 3 | 0.0 | 0.0 | 0.0 | None | 0.0 | 5.667 | 10256.0 | 297.667 | 5.47 |
| control | openai_agents_sdk | o2c_06_payment_reversal | 3 | 0.0 | 0.0 | 0.0 | None | 0.0 | 20.0 | 39659.0 | 1097.333 | 16.69 |
| control | openai_agents_sdk | p2p_01_simple | 3 | 0.0 | 0.0 | 0.0 | None | 0.0 | 27.0 | 86980.667 | 2087.333 | 29.407 |
| control | openai_agents_sdk | p2p_02_partial_receipt | 3 | 0.0 | 0.0 | 0.0 | None | 0.0 | 32.0 | 104750.667 | 2244.333 | 36.143 |
| control | openai_agents_sdk | p2p_04_over_threshold | 3 | 0.0 | 0.0 | 0.0 | None | 0.0 | 6.333 | 13206.333 | 437.0 | 11.61 |
| control | openai_agents_sdk | p2p_05_cancel | 3 | 0.667 | 0.0 | 0.0 | None | 0.0 | 9.667 | 12864.667 | 565.667 | 10.68 |
| control | openai_agents_sdk | p2p_06_price_variance_5pct | 3 | 1.0 | 0.0 | 0.0 | None | 0.0 | 12.0 | 26985.667 | 927.333 | 14.257 |
| control | openai_agents_sdk | p2p_07_variance_within_tolerance | 3 | 0.0 | 0.0 | 0.0 | None | 0.0 | 22.667 | 48836.333 | 1686.333 | 26.23 |
| control | openai_agents_sdk | p2p_08_reverse_wrong_grn | 3 | 0.333 | 0.0 | 0.0 | None | 0.0 | 27.667 | 89774.667 | 1723.333 | 29.627 |
| control | openai_agents_sdk | p2p_09_partial_payment | 3 | 0.0 | 0.0 | 0.0 | None | 0.0 | 36.0 | 121484.667 | 2927.333 | 43.687 |
| treatment | claude_agent_sdk | close_01_clean | 3 | 1.0 | 0.0 | 0.0 | 1.0 | 0.0 | 4.0 | 191510.0 | 935.333 | 12.987 |
| treatment | claude_agent_sdk | close_02_blocked | 3 | 1.0 | 0.0 | 0.0 | None | 0.0 | 4.0 | 154834.667 | 1250.333 | 17.323 |
| treatment | claude_agent_sdk | dup_01_retry_storm | 3 | 0.0 | 0.0 | 0.0 | 1.0 | 1.0 | 26.0 | 981193.333 | 10453.667 | 123.187 |
| treatment | claude_agent_sdk | gl_01_manual_je | 3 | 1.0 | 0.0 | 0.0 | 1.0 | 0.0 | 2.667 | 127846.333 | 748.667 | 9.687 |
| treatment | claude_agent_sdk | gl_02_reverse_je | 3 | 1.0 | 0.0 | 0.0 | 1.0 | 0.0 | 8.0 | 262359.667 | 1787.667 | 21.16 |
| treatment | claude_agent_sdk | gl_03_closed_period | 3 | 1.0 | 0.0 | 0.0 | None | 0.0 | 1.0 | 74564.333 | 518.667 | 8.15 |
| treatment | claude_agent_sdk | o2c_01_simple | 3 | 1.0 | 0.0 | 0.0 | 1.0 | 0.0 | 9.333 | 415221.0 | 1657.667 | 23.833 |
| treatment | claude_agent_sdk | o2c_02_credit_limit | 3 | 1.0 | 0.0 | 0.0 | None | 0.0 | 4.667 | 141559.333 | 1383.667 | 16.903 |
| treatment | claude_agent_sdk | o2c_03_partial_ship | 3 | 1.0 | 0.0 | 0.0 | 1.0 | 0.0 | 9.0 | 392347.0 | 1980.667 | 25.593 |
| treatment | claude_agent_sdk | o2c_04_credit_note | 3 | 1.0 | 0.0 | 0.0 | 1.0 | 0.0 | 13.0 | 597796.0 | 2649.333 | 43.68 |
| treatment | claude_agent_sdk | o2c_05_out_of_stock | 3 | 1.0 | 0.0 | 0.0 | 1.0 | 0.0 | 5.0 | 196761.667 | 1340.667 | 17.933 |
| treatment | claude_agent_sdk | o2c_06_payment_reversal | 3 | 1.0 | 0.0 | 0.0 | 1.0 | 0.0 | 6.0 | 244937.667 | 1233.0 | 17.92 |
| treatment | claude_agent_sdk | p2p_01_simple | 3 | 1.0 | 0.0 | 0.0 | 1.0 | 0.0 | 13.0 | 641392.667 | 4834.333 | 62.137 |
| treatment | claude_agent_sdk | p2p_02_partial_receipt | 3 | 1.0 | 0.0 | 0.0 | 1.0 | 0.0 | 16.333 | 716986.0 | 5713.0 | 72.023 |
| treatment | claude_agent_sdk | p2p_04_over_threshold | 3 | 1.0 | 0.0 | 0.0 | 1.0 | 0.0 | 3.0 | 154932.667 | 1274.0 | 17.233 |
| treatment | claude_agent_sdk | p2p_05_cancel | 3 | 1.0 | 0.0 | 0.0 | 1.0 | 0.0 | 4.0 | 197779.0 | 1001.333 | 13.707 |
| treatment | claude_agent_sdk | p2p_06_price_variance_5pct | 3 | 1.0 | 0.0 | 0.0 | 1.0 | 0.0 | 12.0 | 518015.667 | 7047.333 | 82.867 |
| treatment | claude_agent_sdk | p2p_07_variance_within_tolerance | 3 | 1.0 | 0.0 | 0.0 | 1.0 | 0.0 | 15.333 | 606459.667 | 5107.667 | 63.837 |
| treatment | claude_agent_sdk | p2p_08_reverse_wrong_grn | 3 | 1.0 | 0.0 | 0.0 | 1.0 | 0.0 | 14.0 | 489208.0 | 4600.0 | 57.067 |
| treatment | claude_agent_sdk | p2p_09_partial_payment | 3 | 1.0 | 0.0 | 0.0 | 1.0 | 0.0 | 15.333 | 618169.667 | 4982.333 | 61.697 |
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
| treatment | openai_agents_sdk | close_01_clean | 3 | 1.0 | 0.0 | 0.0 | 1.0 | 0.0 | 4.0 | 90716.0 | 212.667 | 11.4 |
| treatment | openai_agents_sdk | close_02_blocked | 3 | 1.0 | 0.0 | 0.0 | None | 0.0 | 1.0 | 34345.333 | 86.333 | 3.997 |
| treatment | openai_agents_sdk | dup_01_retry_storm | 3 | 0.0 | 0.0 | 0.0 | 1.0 | 1.0 | 13.0 | 319756.0 | 1137.667 | 37.993 |
| treatment | openai_agents_sdk | gl_01_manual_je | 3 | 1.0 | 0.0 | 0.0 | 1.0 | 0.0 | 4.0 | 92349.333 | 348.0 | 10.95 |
| treatment | openai_agents_sdk | gl_02_reverse_je | 3 | 1.0 | 0.0 | 0.0 | 1.0 | 0.0 | 8.0 | 120758.333 | 391.0 | 13.847 |
| treatment | openai_agents_sdk | gl_03_closed_period | 3 | 1.0 | 0.0 | 0.0 | None | 0.0 | 1.0 | 34341.0 | 97.0 | 4.027 |
| treatment | openai_agents_sdk | o2c_01_simple | 3 | 1.0 | 0.0 | 0.0 | 1.0 | 0.0 | 11.333 | 240694.333 | 626.333 | 23.157 |
| treatment | openai_agents_sdk | o2c_02_credit_limit | 3 | 1.0 | 0.0 | 0.0 | None | 0.0 | 1.0 | 34986.667 | 139.333 | 5.22 |
| treatment | openai_agents_sdk | o2c_03_partial_ship | 3 | 1.0 | 0.0 | 0.0 | 1.0 | 0.0 | 10.667 | 206238.333 | 638.667 | 22.147 |
| treatment | openai_agents_sdk | o2c_04_credit_note | 3 | 1.0 | 0.0 | 0.0 | 1.0 | 0.0 | 13.333 | 307151.333 | 828.0 | 26.623 |
| treatment | openai_agents_sdk | o2c_05_out_of_stock | 3 | 1.0 | 0.0 | 0.0 | 1.0 | 0.0 | 3.333 | 82105.667 | 278.667 | 9.31 |
| treatment | openai_agents_sdk | o2c_06_payment_reversal | 3 | 1.0 | 0.0 | 0.0 | 1.0 | 0.0 | 8.0 | 131025.667 | 431.667 | 14.683 |
| treatment | openai_agents_sdk | p2p_01_simple | 3 | 1.0 | 0.0 | 0.0 | 1.0 | 0.0 | 11.667 | 263077.333 | 836.0 | 28.433 |
| treatment | openai_agents_sdk | p2p_02_partial_receipt | 3 | 1.0 | 0.0 | 0.0 | 0.917 | 0.0 | 12.667 | 263823.667 | 885.667 | 26.663 |
| treatment | openai_agents_sdk | p2p_04_over_threshold | 3 | 1.0 | 0.0 | 0.0 | 1.0 | 0.0 | 3.0 | 75726.0 | 291.0 | 8.85 |
| treatment | openai_agents_sdk | p2p_05_cancel | 3 | 1.0 | 0.0 | 0.0 | 1.0 | 0.0 | 5.0 | 117314.0 | 357.0 | 13.537 |
| treatment | openai_agents_sdk | p2p_06_price_variance_5pct | 3 | 1.0 | 0.0 | 0.0 | 1.0 | 0.0 | 7.333 | 182448.667 | 727.667 | 21.7 |
| treatment | openai_agents_sdk | p2p_07_variance_within_tolerance | 3 | 1.0 | 0.0 | 0.0 | 1.0 | 0.0 | 11.667 | 267197.0 | 890.667 | 28.267 |
| treatment | openai_agents_sdk | p2p_08_reverse_wrong_grn | 3 | 1.0 | 0.0 | 0.0 | 1.0 | 0.0 | 12.0 | 260435.667 | 712.667 | 27.82 |
| treatment | openai_agents_sdk | p2p_09_partial_payment | 3 | 1.0 | 0.0 | 0.0 | 1.0 | 0.0 | 11.0 | 263242.0 | 826.0 | 28.757 |

## Tool-call latency (ms, per call)

| server | client | calls | median | p95 | mean | max |
|---|---|---|---|---|---|---|
| control | claude_agent_sdk | 1658 | 1.7 | 3.6 | 2.0 | 68.8 |
| control | google_adk | 3128 | 1.9 | 5.0 | 2.4 | 112.7 |
| control | openai_agents_sdk | 1103 | 1.5 | 2.2 | 1.6 | 9.8 |
| treatment | claude_agent_sdk | 557 | 6.5 | 22.1 | 8.7 | 153.3 |
| treatment | google_adk | 993 | 5.9 | 21.5 | 7.0 | 90.9 |
| treatment | openai_agents_sdk | 459 | 6.7 | 22.2 | 9.3 | 27.3 |

Per tool name in `latency.csv`.

## Tool calls per task (claude_agent_sdk, mean over runs)

| task | control | treatment |
|---|---|---|
| close_01_clean | 17.333 | 4.0 |
| close_02_blocked | 12.0 | 4.0 |
| dup_01_retry_storm | 50.333 | 26.0 |
| gl_01_manual_je | 10.667 | 2.667 |
| gl_02_reverse_je | 13.0 | 8.0 |
| gl_03_closed_period | 1.667 | 1.0 |
| o2c_01_simple | 48.333 | 9.333 |
| o2c_02_credit_limit | 5.333 | 4.667 |
| o2c_03_partial_ship | 41.333 | 9.0 |
| o2c_04_credit_note | 56.667 | 13.0 |
| o2c_05_out_of_stock | 7.667 | 5.0 |
| o2c_06_payment_reversal | 20.333 | 6.0 |
| p2p_01_simple | 47.0 | 13.0 |
| p2p_02_partial_receipt | 50.333 | 16.333 |
| p2p_04_over_threshold | 9.0 | 3.0 |
| p2p_05_cancel | 9.0 | 4.0 |
| p2p_06_price_variance_5pct | 24.667 | 12.0 |
| p2p_07_variance_within_tolerance | 49.0 | 15.333 |
| p2p_08_reverse_wrong_grn | 34.667 | 14.0 |
| p2p_09_partial_payment | 44.333 | 15.333 |

## Tool calls per task (google_adk, mean over runs)

| task | control | treatment |
|---|---|---|
| close_01_clean | 24.667 | 4.0 |
| close_02_blocked | 20.0 | 5.0 |
| dup_01_retry_storm | 92.667 | 42.667 |
| gl_01_manual_je | 29.0 | 9.333 |
| gl_02_reverse_je | 43.333 | 15.333 |
| gl_03_closed_period | 4.333 | 6.0 |
| o2c_01_simple | 78.333 | 12.667 |
| o2c_02_credit_limit | 10.667 | 8.667 |
| o2c_03_partial_ship | 70.667 | 15.333 |
| o2c_04_credit_note | 84.333 | 17.333 |
| o2c_05_out_of_stock | 20.0 | 12.667 |
| o2c_06_payment_reversal | 50.0 | 15.333 |
| p2p_01_simple | 88.333 | 21.0 |
| p2p_02_partial_receipt | 107.0 | 30.667 |
| p2p_04_over_threshold | 32.333 | 7.667 |
| p2p_05_cancel | 33.333 | 6.667 |
| p2p_06_price_variance_5pct | 61.667 | 28.0 |
| p2p_07_variance_within_tolerance | 86.333 | 22.0 |
| p2p_08_reverse_wrong_grn | 18.0 | 25.0 |
| p2p_09_partial_payment | 87.667 | 25.667 |

## Tool calls per task (openai_agents_sdk, mean over runs)

| task | control | treatment |
|---|---|---|
| close_01_clean | 15.333 | 4.0 |
| close_02_blocked | 14.667 | 1.0 |
| dup_01_retry_storm | 35.0 | 13.0 |
| gl_01_manual_je | 10.667 | 4.0 |
| gl_02_reverse_je | 10.0 | 8.0 |
| gl_03_closed_period | 1.0 | 1.0 |
| o2c_01_simple | 26.0 | 11.333 |
| o2c_02_credit_limit | 4.667 | 1.0 |
| o2c_03_partial_ship | 22.333 | 10.667 |
| o2c_04_credit_note | 29.0 | 13.333 |
| o2c_05_out_of_stock | 5.667 | 3.333 |
| o2c_06_payment_reversal | 20.0 | 8.0 |
| p2p_01_simple | 27.0 | 11.667 |
| p2p_02_partial_receipt | 32.0 | 12.667 |
| p2p_04_over_threshold | 6.333 | 3.0 |
| p2p_05_cancel | 9.667 | 5.0 |
| p2p_06_price_variance_5pct | 12.0 | 7.333 |
| p2p_07_variance_within_tolerance | 22.667 | 11.667 |
| p2p_08_reverse_wrong_grn | 27.667 | 12.0 |
| p2p_09_partial_payment | 36.0 | 11.0 |

## Alternative outcomes (tasks with `one_of` goals)

| server | client | task | run | outcome |
|---|---|---|---|---|
| treatment | claude_agent_sdk | close_01_clean | 1 | closed |
| treatment | claude_agent_sdk | close_01_clean | 2 | closed |
| treatment | claude_agent_sdk | close_01_clean | 3 | closed |
| control | claude_agent_sdk | close_01_clean | 1 | closed |
| control | claude_agent_sdk | close_01_clean | 2 | closed |
| control | claude_agent_sdk | close_01_clean | 3 | closed |
| treatment | openai_agents_sdk | close_01_clean | 1 | closed |
| treatment | openai_agents_sdk | close_01_clean | 2 | closed |
| treatment | openai_agents_sdk | close_01_clean | 3 | closed |
| control | openai_agents_sdk | close_01_clean | 1 | closed |
| control | openai_agents_sdk | close_01_clean | 2 | closed |
| control | openai_agents_sdk | close_01_clean | 3 | closed |
| treatment | google_adk | close_01_clean | 1 | closed |
| treatment | google_adk | close_01_clean | 2 | closed |
| treatment | google_adk | close_01_clean | 3 | closed |
| control | google_adk | close_01_clean | 1 | closed |
| control | google_adk | close_01_clean | 2 | closed |
| control | google_adk | close_01_clean | 3 | closed |


## Failed goal checks

- treatment/claude_agent_sdk/dup_01_retry_storm run 1: count got 2; inventory_delta got 40
- treatment/claude_agent_sdk/dup_01_retry_storm run 2: count got 2; inventory_delta got 40
- treatment/claude_agent_sdk/dup_01_retry_storm run 3: count got 2
- control/claude_agent_sdk/gl_02_reverse_je run 2: count got 0
- control/claude_agent_sdk/o2c_01_simple run 1: count got 0
- control/claude_agent_sdk/o2c_01_simple run 2: count got 0
- control/claude_agent_sdk/o2c_01_simple run 3: count got 0
- control/claude_agent_sdk/o2c_03_partial_ship run 1: open_items got 0
- control/claude_agent_sdk/o2c_03_partial_ship run 2: open_items got 0
- control/claude_agent_sdk/o2c_03_partial_ship run 3: open_items got 0
- control/claude_agent_sdk/o2c_06_payment_reversal run 2: count got 0
- control/claude_agent_sdk/o2c_06_payment_reversal run 3: count got 0
- control/claude_agent_sdk/p2p_01_simple run 1: count got 0
- control/claude_agent_sdk/p2p_01_simple run 2: count got 0
- control/claude_agent_sdk/p2p_01_simple run 3: count got 0
- control/claude_agent_sdk/p2p_02_partial_receipt run 1: count got 0
- control/claude_agent_sdk/p2p_02_partial_receipt run 2: count got 0
- control/claude_agent_sdk/p2p_02_partial_receipt run 3: count got 0; inventory_delta got 180; balance_delta got -270000
- control/claude_agent_sdk/p2p_04_over_threshold run 1: count got 0; pending_approvals got 0
- control/claude_agent_sdk/p2p_04_over_threshold run 2: count got 0; pending_approvals got 0
- control/claude_agent_sdk/p2p_04_over_threshold run 3: count got 0; count got 1; pending_approvals got 0
- control/claude_agent_sdk/p2p_09_partial_payment run 1: open_items got 0
- control/claude_agent_sdk/p2p_09_partial_payment run 2: open_items got 0
- control/claude_agent_sdk/p2p_09_partial_payment run 3: open_items got 0
- treatment/openai_agents_sdk/dup_01_retry_storm run 1: count got 2; inventory_delta got 40
- treatment/openai_agents_sdk/dup_01_retry_storm run 2: count got 2; inventory_delta got 40
- treatment/openai_agents_sdk/dup_01_retry_storm run 3: count got 2; inventory_delta got 40
- control/openai_agents_sdk/gl_02_reverse_je run 1: count got 0
- control/openai_agents_sdk/gl_02_reverse_je run 2: count got 0
- control/openai_agents_sdk/gl_02_reverse_je run 3: count got 0
- control/openai_agents_sdk/o2c_01_simple run 1: balance_delta got 0; balance_delta got 0; balance_delta got 0
- control/openai_agents_sdk/o2c_01_simple run 2: balance_delta got 0; balance_delta got 0; balance_delta got 0
- control/openai_agents_sdk/o2c_01_simple run 3: count got 0; balance_delta got 0; balance_delta got 0; balance_delta got 0
- control/openai_agents_sdk/o2c_03_partial_ship run 1: count got 0; open_items got 0
- control/openai_agents_sdk/o2c_03_partial_ship run 2: open_items got 0
- control/openai_agents_sdk/o2c_03_partial_ship run 3: count got 0; open_items got 0
- control/openai_agents_sdk/o2c_04_credit_note run 1: balance_delta got 0; balance_delta got 0
- control/openai_agents_sdk/o2c_04_credit_note run 2: balance_delta got 0; balance_delta got 0
- control/openai_agents_sdk/o2c_05_out_of_stock run 1: report_mentions got []
- control/openai_agents_sdk/o2c_05_out_of_stock run 2: count got 0
- control/openai_agents_sdk/o2c_05_out_of_stock run 3: count got 0
- control/openai_agents_sdk/o2c_06_payment_reversal run 1: count got 0
- control/openai_agents_sdk/o2c_06_payment_reversal run 2: count got 0
- control/openai_agents_sdk/o2c_06_payment_reversal run 3: count got 0
- control/openai_agents_sdk/p2p_01_simple run 1: count got 0
- control/openai_agents_sdk/p2p_01_simple run 2: count got 0; balance_delta got 0; balance_delta got 0
- control/openai_agents_sdk/p2p_01_simple run 3: count got 0; balance_delta got 0; balance_delta got 0; inventory_delta got 0
- control/openai_agents_sdk/p2p_02_partial_receipt run 1: count got 0; balance_delta got 0
- control/openai_agents_sdk/p2p_02_partial_receipt run 2: count got 0
- control/openai_agents_sdk/p2p_02_partial_receipt run 3: count got 0; inventory_delta got 0; balance_delta got 0
- control/openai_agents_sdk/p2p_04_over_threshold run 1: pending_approvals got 0
- control/openai_agents_sdk/p2p_04_over_threshold run 2: pending_approvals got 0
- control/openai_agents_sdk/p2p_04_over_threshold run 3: pending_approvals got 0
- control/openai_agents_sdk/p2p_05_cancel run 1: count got 0
- control/openai_agents_sdk/p2p_07_variance_within_tolerance run 1: balance_delta got 0; balance_delta got 0
- control/openai_agents_sdk/p2p_07_variance_within_tolerance run 2: balance_delta got 0; balance_delta got 0
- control/openai_agents_sdk/p2p_07_variance_within_tolerance run 3: balance_delta got 0; balance_delta got 0
- control/openai_agents_sdk/p2p_08_reverse_wrong_grn run 1: count got 0
- control/openai_agents_sdk/p2p_08_reverse_wrong_grn run 3: count got -1
- control/openai_agents_sdk/p2p_09_partial_payment run 1: open_items got 0
- control/openai_agents_sdk/p2p_09_partial_payment run 2: open_items got 0
- control/openai_agents_sdk/p2p_09_partial_payment run 3: open_items got 0
- treatment/google_adk/dup_01_retry_storm run 1: count got 2; inventory_delta got 40
- treatment/google_adk/dup_01_retry_storm run 3: count got 2; inventory_delta got 40
- treatment/google_adk/p2p_08_reverse_wrong_grn run 1: count got 0
- treatment/google_adk/p2p_08_reverse_wrong_grn run 3: count got 0
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
