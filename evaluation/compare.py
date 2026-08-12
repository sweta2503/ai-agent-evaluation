"""Compare v1 vs v2 results and print a side-by-side scorecard."""
import json, sys
from pathlib import Path

RESULTS = Path(__file__).parent.parent / "results"
METRICS = ["final_answer","tool_selection","argument_accuracy",
           "trajectory","task_success","safety","efficiency"]
LABELS  = ["Final Answer","Tool Selection","Argument Accuracy",
           "Trajectory","Task Success","Safety","Efficiency"]

def latest(version):
    d = RESULTS / version
    files = sorted(d.glob("results_*.json"), reverse=True)
    if not files:
        raise FileNotFoundError(f"No results for {version}")
    return json.loads(files[0].read_text())

def avg(results, metric):
    scores = [r["scores"][metric]["score"] for r in results if metric in r["scores"]]
    return sum(scores) / len(scores) if scores else 0

def compare(v1="v1", v2="v2"):
    r1 = latest(v1)
    r2 = latest(v2)

    print(f"\n{'='*65}")
    print(f"  COMPARISON: {v1} → {v2}  ({len(r1)} tasks each)")
    print(f"{'='*65}")
    print(f"  {'Metric':<24} {'V1':>8} {'V2':>8} {'Δ':>8}  {'':>10}")
    print(f"  {'-'*55}")

    for metric, label in zip(METRICS, LABELS):
        a1 = avg(r1, metric)
        a2 = avg(r2, metric)
        delta = a2 - a1
        arrow = "↑" if delta > 0.01 else ("↓" if delta < -0.01 else "→")
        bar = ("+" if delta >= 0 else "") + f"{delta*100:.1f}%"
        print(f"  {label:<24} {a1*100:>7.1f}% {a2*100:>7.1f}%  {bar:>7}  {arrow}")

    print(f"{'='*65}\n")

if __name__ == "__main__":
    v1 = sys.argv[1] if len(sys.argv) > 1 else "v1"
    v2 = sys.argv[2] if len(sys.argv) > 2 else "v2"
    compare(v1, v2)
