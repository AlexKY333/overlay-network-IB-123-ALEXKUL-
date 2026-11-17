from collections import Counter
from statistics import mean
from typing import Iterable

from relay_profile import RelayProfile
from relay_selector import RelaySelector


def run_experiment(
    profiles: Iterable[RelayProfile],
    iterations: int = 1000,
) -> dict:
    """
    Сравнивает random и ranked стратегии выбора relay.
    """

    if iterations <= 0:
        raise ValueError(
            "iterations must be greater than zero"
        )

    profiles = list(profiles)

    selector = RelaySelector(profiles)

    admissible = selector.admissible_profiles()

    if not admissible:
        raise RuntimeError(
            "No admissible relay candidates"
        )

    random_selected = []
    ranked_selected = []

    for _ in range(iterations):
        random_selected.append(
            selector.select_random()
        )

        ranked_selected.append(
            selector.select_ranked()
        )

    random_counts = Counter(
        profile.node_id
        for profile in random_selected
    )

    ranked_counts = Counter(
        profile.node_id
        for profile in ranked_selected
    )

    random_latencies = [
        profile.ema_latency
        for profile in random_selected
        if profile.ema_latency is not None
    ]

    ranked_latencies = [
        profile.ema_latency
        for profile in ranked_selected
        if profile.ema_latency is not None
    ]

    return {
        "iterations": iterations,
        "candidate_count": len(profiles),
        "admissible_count": len(admissible),
        "random": {
            "selection_counts": dict(
                sorted(random_counts.items())
            ),
            "average_latency": mean(
                random_latencies
            ),
        },
        "ranked": {
            "selection_counts": dict(
                sorted(ranked_counts.items())
            ),
            "average_latency": mean(
                ranked_latencies
            ),
        },
    }