# results/

Evaluation outputs land here as `results/<run_id>/raw.jsonl`, `summary.csv` and `report.md`
(DESIGN.md §14.4). Everything except this file is gitignored; `eval.yml` uploads runs as workflow
artifacts and can commit a `summary.csv` on request.
