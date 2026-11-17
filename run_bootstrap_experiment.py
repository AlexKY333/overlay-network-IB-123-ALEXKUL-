import asyncio
import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
SRC_DIR = BASE_DIR / "src"
RESULTS_DIR = BASE_DIR / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(SRC_DIR))

from config import CONFIG, N_NODES
from bootstrap_experiment import run_bootstrap_experiment

NODE_COUNT = N_NODES
TRIALS = 5


def calculate_summary(results):
    schemes = ["star", "ring", "tree", "multi_seed"]
    summaries = []

    for scheme in schemes:
        scheme_results = [r for r in results if r["scheme"] == scheme]
        times = [r["convergence_time"] for r in scheme_results]
        rpc = [r["total_rpc"] for r in scheme_results]
        contacts = [r["average_contacts"] for r in scheme_results]
        non_full = [r["non_full_fraction"] for r in scheme_results]
        non_empty_b = [r.get("avg_non_empty_buckets", 0.0) for r in scheme_results]
        successful = sum(1 for r in scheme_results if r["converged"])

        summaries.append(
            {
                "scheme": scheme,
                "trials": len(scheme_results),
                "average_convergence_time": sum(times) / len(times),
                "min_convergence_time": min(times),
                "max_convergence_time": max(times),
                "average_rpc": sum(rpc) / len(rpc),
                "min_rpc": min(rpc),
                "max_rpc": max(rpc),
                "average_contacts": sum(contacts) / len(contacts),
                "average_non_full_fraction": sum(non_full) / len(non_full),
                "average_non_empty_buckets": sum(non_empty_b) / len(non_empty_b),
                "sample_k_bucket_occupancy": scheme_results[-1].get(
                    "sample_node_bucket_contents", {}
                ),
                "successful_convergence_runs": successful,
                "convergence_success_rate": successful / len(scheme_results),
            }
        )
    return summaries


def print_summary(summaries):
    print("\n" + "=" * 80)
    print("CONTROLLED BOOTSTRAP EXPERIMENT SUMMARY")
    print("=" * 80)

    for summary in summaries:
        print(f"\n--- {summary['scheme'].upper()} ---")
        print(f"Trials: {summary['trials']}")
        print(f"Average convergence time: {summary['average_convergence_time']:.4f} s")
        print(f"Min convergence time: {summary['min_convergence_time']:.4f} s")
        print(f"Max convergence time: {summary['max_convergence_time']:.4f} s")
        print(f"Average RPC: {summary['average_rpc']:.2f}")
        print(f"RPC range: {summary['min_rpc']} - {summary['max_rpc']}")
        print(f"Average contacts: {summary['average_contacts']:.3f}")
        print(f"Average non-empty k-buckets: {summary['average_non_empty_buckets']:.2f}")
        print(f"Average non-full fraction: {summary['average_non_full_fraction']:.3f}")
        print(f"Successful convergence: {summary['successful_convergence_runs']}/{summary['trials']}")
        print(f"Convergence success rate: {summary['convergence_success_rate']:.1%}")


async def main():
    print("=== CONTROLLED BOOTSTRAP EXPERIMENT ===")
    print(f"Nodes: {NODE_COUNT}")
    print(f"Trials: {TRIALS}")

    results = await run_bootstrap_experiment(node_count=NODE_COUNT, trials=TRIALS)
    summaries = calculate_summary(results)
    print_summary(summaries)

    output = {
        "configuration": {
            "node_count": NODE_COUNT,
            "k_bucket_size": CONFIG.get("K_BUCKET_SIZE", 4),
            "alpha": CONFIG.get("ALPHA", 3),
            "trials": TRIALS,
            "schemes": ["star", "ring", "tree", "multi_seed"],
            "controlled_node_ids": True,
        },
        "raw_results": results,
        "summary": summaries,
    }

    output_path = RESULTS_DIR / "bootstrap_experiment_results.json"
    with output_path.open("w", encoding="utf-8") as file:
        json.dump(output, file, indent=4, ensure_ascii=False)

    print(f"\nResults saved to {output_path}")


if __name__ == "__main__":
    asyncio.run(main())