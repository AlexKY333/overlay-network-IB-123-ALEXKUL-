from random import choice
from typing import Iterable

from relay_profile import RelayProfile
from config import DEGRADATION_CONSECUTIVE_FAILURES

class RelaySelector:
    """
    Выбор relay-кандидата.

    Поддерживает две стратегии:
    - random — случайный выбор;
    - ranked — выбор по профилю relay.

    Ranked-стратегия учитывает:
    - EMA успешности;
    - EMA задержки;
    - количество последовательных отказов.
    """

    def __init__(
        self,
        profiles: Iterable[RelayProfile] = (),
        max_consecutive_failures: int = DEGRADATION_CONSECUTIVE_FAILURES,
    ):
        if max_consecutive_failures < 0:
            raise ValueError(
                "max_consecutive_failures cannot be negative"
            )

        self.max_consecutive_failures = (
            max_consecutive_failures
        )

        self._profiles: dict[int, RelayProfile] = {}

        for profile in profiles:
            self.add_profile(profile)

    def add_profile(
        self,
        profile: RelayProfile,
    ) -> None:
        """
        Добавляет профиль relay.
        """

        if not isinstance(profile, RelayProfile):
            raise TypeError(
                "profile must be an instance of RelayProfile"
            )

        if profile.node_id in self._profiles:
            raise ValueError(
                f"Profile for node {profile.node_id} "
                "already exists"
            )

        self._profiles[profile.node_id] = profile

    def get_profile(
        self,
        node_id: int,
    ) -> RelayProfile:
        """
        Возвращает профиль relay по NodeID.
        """

        try:
            return self._profiles[node_id]
        except KeyError:
            raise KeyError(
                f"Profile for node {node_id} not found"
            )

    def list_profiles(self) -> list[RelayProfile]:
        """
        Возвращает все профили.
        """

        return list(self._profiles.values())

    def admissible_profiles(self) -> list[RelayProfile]:
        """
        Возвращает relay, пригодные для выбора.
        """

        return [
            profile
            for profile in self._profiles.values()
            if profile.is_healthy(
                self.max_consecutive_failures
            )
        ]

    def select_random(self) -> RelayProfile:
        """
        Случайный выбор среди пригодных relay.
        """

        candidates = self.admissible_profiles()

        if not candidates:
            raise RuntimeError(
                "No admissible relay candidates available"
            )

        return choice(candidates)

    @staticmethod
    def _score(
        profile: RelayProfile,
    ) -> float:
        """
        Рассчитывает рейтинг relay.

        Чем выше результат, тем лучше кандидат.

        EMA успешности повышает рейтинг.
        Низкая EMA задержки повышает рейтинг.
        Последовательные отказы уменьшают рейтинг.
        """

        success_score = profile.ema_success

        if profile.ema_latency is None:
            latency_score = 1.0
        else:
            latency_score = 1.0 / (
                1.0 + profile.ema_latency
            )

        failure_penalty = (
            1.0 / (1.0 + profile.consecutive_failures)
        )

        return (
            success_score
            * latency_score
            * failure_penalty
        )

    def select_ranked(self) -> RelayProfile:
        """
        Выбирает лучший relay по рейтингу.
        """

        candidates = self.admissible_profiles()

        if not candidates:
            raise RuntimeError(
                "No admissible relay candidates available"
            )

        return max(
            candidates,
            key=self._score,
        )