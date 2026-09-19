import json, logging, os, sys
logging.disable(logging.CRITICAL)
from anerp.eval.resilience.commit_failure import run
r = run(os.environ.get("ANERP_EVAL_DATABASE_URL"))
for t in r["trials"]:
    if not t["applicable"]: print(f"{t['tool']:24} {t['stage']:12} n/a (stage not reached)"); continue
    ok = t["all_or_nothing"] and t["tb_balanced_after"] and t["retry_same_key"]=="applied" and t["second_retry"]=="replayed"
    print(f"{t['tool']:24} {t['stage']:12} {t['response']:26} leaked={t['leaked_rows']} tb={t['tb_balanced_after']} retry={t['retry_same_key']} again={t['second_retry']} {'' if ok else '<-- PROBLEM'}")
print("backend", r["trials"][0]["backend"], "all_pass", r["all_pass"])
json.dump(r, open(sys.argv[1], "w"), indent=1)
