from dataclasses import dataclass
from time import monotonic
from typing import Optional, Union
from config import DEGRADATION_CONSECUTIVE_FAILURES

NodeIdType = Union[str, int]


@dataclass
class RelayProfile:
    """
    Профиль relay-кандидата (Разделы 12, 15 ТЗ).

    Хранит статистику работы ретранслятора, вычисляет экспоненциальное скользящее
    среднее (EMA) успешности и задержки, а также отслеживает последовательные отказы
    для ранжирования маршрутов.
    """

    node_id: NodeIdType
    subnet: Optional[str] = None

    success_count: int = 0
    failure_count: int = 0

    ema_success: float = 1.0
    ema_latency: Optional[float] = None

    last_observation: Optional[float] = None
    consecutive_failures: int = 0

    ema_alpha: float = 0.2

    def __post_init__(self) -> None:
        if not 0.0 < self.ema_alpha <= 1.0:
            raise ValueError("ema_alpha must be in range (0, 1]")

    @property
    def total_observations(self) -> int:
        """Общее количество наблюдений."""
        return self.success_count + self.failure_count

    @property
    def success_rate(self) -> float:
        """Фактическая доля успешных операций."""
        total = self.total_observations
        if total == 0:
            return 0.0
        return self.success_count / total

    def record_success(
        self,
        latency: float,
        observed_at: Optional[float] = None,
    ) -> None:
        """
        Записывает успешное использование relay.
        latency — задержка операции в секундах.
        """
        if latency < 0:
            raise ValueError("latency cannot be negative")

        self.success_count += 1
        self.consecutive_failures = 0

        if observed_at is None:
            observed_at = monotonic()

        self.last_observation = observed_at

        # EMA успешности (успешное наблюдение = 1.0)
        self.ema_success = (
            self.ema_alpha * 1.0
            + (1.0 - self.ema_alpha) * self.ema_success
        )

        # EMA задержки
        if self.ema_latency is None:
            self.ema_latency = latency
        else:
            self.ema_latency = (
                self.ema_alpha * latency
                + (1.0 - self.ema_alpha) * self.ema_latency
            )

    def record_failure(
        self,
        observed_at: Optional[float] = None,
    ) -> None:
        """Записывает неудачное использование relay."""
        self.failure_count += 1
        self.consecutive_failures += 1

        if observed_at is None:
            observed_at = monotonic()

        self.last_observation = observed_at

        # Неудачное наблюдение = 0.0
        self.ema_success = (
            self.ema_alpha * 0.0
            + (1.0 - self.ema_alpha) * self.ema_success
        )

    def reset_failures(self) -> None:
        """Сбрасывает счётчик последовательных отказов."""
        self.consecutive_failures = 0

    def is_healthy(
        self,
        max_consecutive_failures: int = DEGRADATION_CONSECUTIVE_FAILURES,
    ) -> bool:
        """
        Определяет, считается ли relay пригодным по количеству отказов подряд.
        """
        if max_consecutive_failures < 0:
            raise ValueError("max_consecutive_failures cannot be negative")

        return self.consecutive_failures < max_consecutive_failures