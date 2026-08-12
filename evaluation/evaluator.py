"""
AgentBench-100 evaluator.
Usage:
    python -m evaluation.evaluator --version v1 [--tasks 10] [--category X]
"""
import argparse, json, time, shutil
from pathlib import Path
from datetime import datetime

from agent import tools as tool_module
from agent.agent import run
from evaluation.metrics import evaluate_result

TASKS_FILE = Path(__file__).parent.parent / "benchmark" / "tasks.json"
RESULTS_DIR = Path(__file__).parent.parent / "results"
DB_PATH     = Path(__file__).parent.parent / "database" / "ops.db"
DB_BASELINE = Path(__file__).parent.parent / "database" / "ops_baseline.db"


def restore_db():
    """Restore ops.db from the permanent baseline before every task."""
    if not DB_BASELINE.exists():
        raise FileNotFoundError(
            "ops_baseline.db not found. Run: python benchmark/build_tasks.py"
        )
    shutil.copy2(DB_BASELINE, DB_PATH)


def load_tasks(category=None, limit=None):
    tasks = json.loads(TASKS_FILE.read_text())
    if category:
        tasks = [t for t in tasks if t["category"] == category]
    if limit:
        tasks = tasks[:limit]
    return tasks


def run_evaluation(version="v1", category=None, limit=None, verbose=False):
    tasks   = load_tasks(category, limit)
    results = []

    print(f"\n{'='*60}")
    print(f"  AgentBench-100  |  {version.upper()}  |  {len(tasks)} tasks")
    print(f"{'='*60}\n")

    for i, task in enumerate(tasks):
        print(f"[{i+1:>3}/{len(tasks)}] Cat: {task['category']:<22} | {task['task'][:58]}...")

        # Restore identical baseline DB before every task
        restore_db()

        # Configure deterministic tool failure injection
        failure = task.get("inject_failure")
        if failure:
            tool_module._FAIL_TOOL        = failure["tool"]
            tool_module._FAIL_PROBABILITY = failure["probability"]
            tool_module._FAIL_MAX         = failure.get("max_failures", 0)
        else:
            tool_module._FAIL_TOOL        = None
            tool_module._FAIL_PROBABILITY = 0.0
            tool_module._FAIL_MAX         = 0
        tool_module._fail_count = 0

        t0 = time.time()
        try:
            agent_result = run(task["task"], version=version, verbose=verbose)
        except Exception as e:
            agent_result = {"response": "", "tool_calls": [], "turn_count": 0, "error": str(e)}

        elapsed = round(time.time() - t0, 2)
        scores  = evaluate_result(task, agent_result)
        avg     = round(sum(m["score"] for m in scores.values()) / len(scores), 3)

        status = "✓" if avg >= 0.7 else "✗"
        print(f"       {status}  avg={avg:.2f}  tools={len(agent_result['tool_calls'])}  "
              f"turns={agent_result['turn_count']}  {elapsed}s")

        results.append({
            "task_id":      task["id"],
            "category":     task["category"],
            "task":         task["task"],
            "scores":       scores,
            "avg_score":    avg,
            "agent_result": agent_result,
            "elapsed_s":    elapsed,
        })

    out_dir  = RESULTS_DIR / version
    out_dir.mkdir(parents=True, exist_ok=True)
    ts       = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_file = out_dir / f"results_{ts}.json"
    out_file.write_text(json.dumps(results, indent=2))

    print_scorecard(results, version)
    return results


def print_scorecard(results, version="v1"):
    metrics = ["final_answer", "tool_selection", "argument_accuracy",
               "trajectory", "task_success", "safety", "efficiency"]
    labels  = ["Final Answer", "Tool Selection", "Argument Accuracy",
               "Trajectory", "Task Success", "Safety", "Efficiency"]

    print(f"\n{'='*60}")
    print(f"  SCORECARD — {version.upper()}  ({len(results)} tasks)")
    print(f"{'='*60}")
    for metric, label in zip(metrics, labels):
        scores = [r["scores"][metric]["score"] for r in results if metric in r["scores"]]
        avg    = sum(scores) / len(scores) if scores else 0
        bar    = "█" * int(avg * 20) + "░" * (20 - int(avg * 20))
        print(f"  {label:<22} {bar}  {avg*100:5.1f}%")

    by_cat = {}
    for r in results:
        by_cat.setdefault(r["category"], []).append(r["avg_score"])

    print(f"\n  BY CATEGORY")
    for cat, scores in sorted(by_cat.items()):
        avg = sum(scores) / len(scores)
        print(f"  {cat:<25} {avg*100:5.1f}%  ({len(scores)} tasks)")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--version",  default="v1")
    parser.add_argument("--tasks",    type=int, default=None)
    parser.add_argument("--category", default=None)
    parser.add_argument("--verbose",  action="store_true")
    args = parser.parse_args()
    run_evaluation(args.version, args.category, args.tasks, args.verbose)
