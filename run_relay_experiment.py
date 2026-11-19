import json
import random
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
SRC_DIR = BASE_DIR / "src"
RESULTS_DIR = BASE_DIR / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from relay_experiment import run_experiment
from relay_profile import RelayProfile

SEED = 42
ITERATIONS = 1000


def get_code_version() -> str:
    try:
        res = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=BASE_DIR,
            capture_output=True,
            text=True,
            timeout=2,
        )
        if res.returncode == 0 and res.stdout.strip():
            return res.stdout.strip()
    except Exception:
        pass
    return "unknown"


def load_config_metadata() -> dict:
    config_path = BASE_DIR / "config.json"
    if config_path.exists():
        try:
            return json.loads(config_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def make_profile(
    node_id: int,
    success: int,
    latency: float,
    subnet: str,
    consecutive_failures: int = 0,
) -> RelayProfile:
    profile = RelayProfile(node_id=node_id, subnet=subnet)
    for _ in range(success):
        profile.record_success(latency=latency)
    profile.consecutive_failures = consecutive_failures
    return profile


def compute_latency_stats(
    selection_counts: dict,
    latency_by_node: dict[int, float],
) -> dict:
    samples = []
    for node_id, count in selection_counts.items():
        lat = latency_by_node[int(node_id)]
        samples.extend([lat] * int(count))

    if not samples:
        return {
            "observations": 0,
            "min": None,
            "median": None,
            "average": None,
            "p95": None,
            "max": None,
        }

    samples.sort()
    n = len(samples)
    p95 = samples[int(0.95 * (n - 1))] if n >= 20 else None

    return {
        "observations": n,
        "min": round(samples[0], 4),
        "median": round(statistics.median(samples), 4),
        "average": round(statistics.mean(samples), 4),
        "p95": round(p95, 4) if p95 is not None else None,
        "max": round(samples[-1], 4),
    }


def serialize_profile(profile: RelayProfile) -> dict:
    return {
        "node_id": profile.node_id,
        "subnet": getattr(profile, "subnet", None),
        "success_count": getattr(profile, "success_count", None),
        "failure_count": getattr(profile, "failure_count", None),
        "ema_success": round(profile.ema_success, 4),
        "ema_latency": round(profile.ema_latency, 4),
        "last_seen": getattr(profile, "last_seen", None),
        "consecutive_failures": profile.consecutive_failures,
        "is_healthy": profile.is_healthy(),
    }


def main():
    started_at_utc = datetime.now(timezone.utc).isoformat()
    t_start = time.perf_counter()

    random.seed(SEED)

    profiles = [
        make_profile(node_id=1, success=9, latency=0.80, subnet="10.0.1.0/24"),
        make_profile(node_id=2, success=8, latency=0.40, subnet="10.0.2.0/24"),
        make_profile(node_id=3, success=10, latency=0.10, subnet="10.0.3.0/24"),
        make_profile(node_id=4, success=6, latency=0.25, subnet="10.0.4.0/24"),
        make_profile(
            node_id=5,
            success=7,
            latency=0.60,
            subnet="10.0.5.0/24",
            consecutive_failures=2,
        ),
    ]

    result = run_experiment(profiles, iterations=ITERATIONS)
    elapsed_s = round(time.perf_counter() - t_start, 4)

    latency_by_node = {p.node_id: p.ema_latency for p in profiles}
    random_stats = compute_latency_stats(result["random"]["selection_counts"], latency_by_node)
    ranked_stats = compute_latency_stats(result["ranked"]["selection_counts"], latency_by_node)

    result["random"]["latency_stats"] = random_stats
    result["ranked"]["latency_stats"] = ranked_stats

    cfg = load_config_metadata()
    result["metadata"] = {
        "scenario": "relay_selection_strategy_comparison",
        "code_version": get_code_version(),
        "seed": SEED,
        "started_at_utc": started_at_utc,
        "time_base": "time.perf_counter",
        "elapsed_s": elapsed_s,
        "N": cfg.get("N_NODES", 20),
        "k": cfg.get("K_BUCKET_SIZE", 4),
        "ALPHA": cfg.get("ALPHA", 3),
        "R": cfg.get("REPLICATION_FACTOR", 3),
        "timeouts": {
            "network_timeout_s": cfg.get("NETWORK_TIMEOUT", 5.0),
        },
        "bootstrap_graph": "not_applicable (isolated relay selector benchmark)",
        "netem": "none",
        "config": cfg,
    }
    result["profiles"] = [serialize_profile(p) for p in profiles]

    print("\n=== RELAY SELECTION EXPERIMENT ===")
    print(f"Seed:       {SEED} | Code version: {result['metadata']['code_version']}")
    print(f"Iterations: {result['iterations']}")
    print(f"Candidates: {result['candidate_count']} | Admissible: {result['admissible_count']}")

    print("\n--- RANDOM ---")
    print("Selection counts:", result["random"]["selection_counts"])
    print("Average latency: ", round(result["random"]["average_latency"], 4))
    print("Latency stats:   ", random_stats)

    print("\n--- RANKED ---")
    print("Selection counts:", result["ranked"]["selection_counts"])
    print("Average latency: ", round(result["ranked"]["average_latency"], 4))
    print("Latency stats:   ", ranked_stats)

    output_path = RESULTS_DIR / "relay_experiment_results.json"
    with open(output_path, "w", encoding="utf-8") as file:
        json.dump(result, file, indent=4, ensure_ascii=False)

    print(f"\nResults saved to {output_path}")


if __name__ == "__main__":
    main()