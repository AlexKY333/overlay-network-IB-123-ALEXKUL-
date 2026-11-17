from dataclasses import dataclass

from relay_server import RelayServer
from tunnel import Tunnel


@dataclass
class TunnelRecoveryManager:
    """
    Управляет восстановлением маршрута туннеля.

    Основной маршрут:
        R1 -> R2 -> R3

    Резервный маршрут:
        R1 -> R4 -> R3

    При отказе следующего relay первый relay
    переключается на резервный маршрут.
    """

    tunnel: Tunnel
    entry_relay: RelayServer

    backup_host: str
    backup_port: int

    recovered: bool = False

    def __post_init__(self):
        if not self.tunnel.is_active():
            raise ValueError(
                "Tunnel must be active"
            )

        if self.entry_relay is None:
            raise ValueError(
                "entry_relay is required"
            )

    @property
    def is_recovered(self) -> bool:
        return self.recovered

    def recover(self) -> None:
        """
        Переключает entry relay
        на резервный следующий hop.
        """

        self.entry_relay.next_host = (
            self.backup_host
        )

        self.entry_relay.next_port = (
            self.backup_port
        )

        self.recovered = True

    def reset(self) -> None:
        """
        Сбрасывает состояние восстановления.
        """

        self.recovered = False

    async def send_with_recovery(
        self,
        send_function,
        host,
        port,
        encrypted_data,
    ):
        """
        Отправляет данные.

        Если основной маршрут недоступен,
        автоматически переключается на резервный
        и повторяет отправку.

        send_function должна иметь сигнатуру:

            await send_function(
                host,
                port,
                encrypted_data,
            )
        """

        try:
            return await send_function(
                host,
                port,
                encrypted_data,
            )

        except Exception:
            self.recover()

            return await send_function(
                host,
                port,
                encrypted_data,
            )