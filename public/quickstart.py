"""Two-minute sandbox quickstart (brief P08): fetch tasks, submit a trivial answer, print the score.
Standard library only, so nothing needs installing:

    python3 scripts/quickstart.py https://<your-deployment>.vercel.app

The trivial answer refuses every task, so expect a low score: traps refused for the right reason
score well, everything else is penalised. Swap in your own agent's answers to score it.
"""

import json
import sys
import time
import urllib.request

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8001").rstrip("/")


def call(method: str, path: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())


# Free hosting can cold-start: wait for /api/health instead of concluding the sandbox is broken.
for attempt in range(12):
    try:
        print("health:", call("GET", "/api/health"))
        break
    except Exception as exc:
        print(f"waiting for the sandbox to wake up ({exc.__class__.__name__}); retry {attempt + 1}/12")
        time.sleep(5)

batch = call("GET", "/api/tasks?tier=2,3&n=5&seed=42")
print(f"run {batch['run_id'][:16]}... | rule set {batch['ruleset_version']} | seed {batch['seed']} | tiers {batch['tier_mix']} | {batch['n_tasks']} tasks")
print("first task:", batch["tasks"][0]["prompt"][-1]["content"].split("---")[-1].strip()[:300], "...")

trivial = {"decision": "refuse", "reason_code": "MISSING_INPUT", "lines": None, "explanation": "trivial quickstart answer"}
result = call("POST", "/api/submit", {"run_id": batch["run_id"], "answers": [{"id": t["id"], "answer": trivial} for t in batch["tasks"]]})
print(f"mean reward: {result['mean_reward']}")
for t in result["per_task"]:
    print(f"  task {t['id']} (tier {t['tier']}): score {t['score']:+.2f}  clause {t['clause']}  breakdown {t['breakdown']}")
