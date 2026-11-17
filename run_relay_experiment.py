import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
SRC_DIR = BASE_DIR / "src"
RESULTS_DIR = BASE_DIR / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(SRC_DIR))

from relay_experiment import run_experiment
from relay_profile import RelayProfile


def make_profile(
    node_id: int,
    success: int,
    latency: float,
    consecutive_failures: int = 0,
) -> RelayProfile:
    profile = RelayProfile(node_id=node_id)
    for _ in range(success):
        profile.record_success(latency=latency)
    profile.consecutive_failures = consecutive_failures
    return profile


profiles = [
    make_profile(node_id=1, success=9, latency=0.80),
    make_profile(node_id=2, success=8, latency=0.40),
    make_profile(node_id=3, success=10, latency=0.10),
    make_profile(node_id=4, success=6, latency=0.25),
    make_profile(node_id=5, success=7, latency=0.60, consecutive_failures=2),
]

result = run_experiment(profiles, iterations=1000)

print("\n=== RELAY SELECTION EXPERIMENT ===")
print(f"Iterations: {result['iterations']}")
print(f"Candidates: {result['candidate_count']}")
print(f"Admissible: {result['admissible_count']}")

print("\n--- RANDOM ---")
print("Selection counts:", result["random"]["selection_counts"])
print("Average latency:", result["random"]["average_latency"])

print("\n--- RANKED ---")
print("Selection counts:", result["ranked"]["selection_counts"])
print("Average latency:", result["ranked"]["average_latency"])

output_path = RESULTS_DIR / "relay_experiment_results.json"
with open(output_path, "w", encoding="utf-8") as file:
    json.dump(result, file, indent=4, ensure_ascii=False)

print(f"\nResults saved to {output_path}")