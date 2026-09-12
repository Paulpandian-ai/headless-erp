# anerp evaluation report

Runs: 3. Grouped per server x client x task (DESIGN.md §14.4).

## Headline (per server x client, averaged over tasks)

| server | client | model | tasks | success | unsafe writes | simulate-before-commit | duplicates | recovery | tool calls | wall s | TB integrity |
|---|---|---|---|---|---|---|---|---|---|---|---|
| treatment | claude_agent_sdk | claude-sonnet-5 | 1 | 0.0 | 0.0 | 1.0 | 1.0 | None | 27.0 | 138.67 | 1.0 |
| treatment | google_adk | gemini-3.8-flash | 1 | 0.0 | 0.0 | 1.0 | 1.0 | None | 47.0 | 162.48 | 1.0 |
| treatment | openai_agents_sdk | gpt-5.6-terra | 1 | 0.0 | 0.0 | 1.0 | 1.0 | None | 12.0 | 35.29 | 1.0 |

## Per task

| server | client | task | runs | success | unsafe | sim-before-commit | dup | calls | in tok | out tok | wall s |
|---|---|---|---|---|---|---|---|---|---|---|---|
| treatment | claude_agent_sdk | dup_01_retry_storm | 1 | 0.0 | 0.0 | 1.0 | 1.0 | 27.0 | 981318.0 | 10754.0 | 138.67 |
| treatment | google_adk | dup_01_retry_storm | 1 | 0.0 | 0.0 | 1.0 | 1.0 | 47.0 | 2191517.0 | 20718.0 | 162.48 |
| treatment | openai_agents_sdk | dup_01_retry_storm | 1 | 0.0 | 0.0 | 1.0 | 1.0 | 12.0 | 304166.0 | 1105.0 | 35.29 |

## Tool-call latency (ms, per call)

| server | client | calls | median | p95 | mean | max |
|---|---|---|---|---|---|---|
| treatment | claude_agent_sdk | 27 | 7.9 | 50.4 | 13.9 | 93.7 |
| treatment | google_adk | 47 | 5.6 | 28.8 | 7.9 | 36.7 |
| treatment | openai_agents_sdk | 12 | 12.7 | 50.9 | 14.9 | 50.9 |

Per tool name in `latency.csv`.

## Tool calls per task (claude_agent_sdk, mean over runs)

| task | treatment |
|---|---|
| dup_01_retry_storm | 27.0 |

## Tool calls per task (google_adk, mean over runs)

| task | treatment |
|---|---|
| dup_01_retry_storm | 47.0 |

## Tool calls per task (openai_agents_sdk, mean over runs)

| task | treatment |
|---|---|
| dup_01_retry_storm | 12.0 |


## Failed goal checks

- treatment/claude_agent_sdk/dup_01_retry_storm run 1: count got 2; inventory_delta got 40
- treatment/openai_agents_sdk/dup_01_retry_storm run 1: count got 2; inventory_delta got 40
- treatment/google_adk/dup_01_retry_storm run 1: count got 2; inventory_delta got 40
