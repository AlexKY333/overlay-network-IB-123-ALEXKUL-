from tunnel import Tunnel


class TunnelPool:
    """
    Пул активных и подготовленных туннелей.

    Используется для Advanced-уровня:
    один узел может одновременно иметь
    несколько независимых туннелей.
    """

    def __init__(self):
        self._tunnels: dict[str, Tunnel] = {}

    def add(self, tunnel: Tunnel) -> None:
        """
        Добавляет туннель в пул.
        """

        if not isinstance(tunnel, Tunnel):
            raise TypeError(
                "tunnel must be an instance of Tunnel"
            )

        tunnel_id = str(tunnel.tunnel_id)

        if tunnel_id in self._tunnels:
            raise ValueError(
                f"Tunnel {tunnel_id} already exists"
            )

        self._tunnels[tunnel_id] = tunnel

    def remove(self, tunnel_id: str) -> Tunnel:
        """
        Удаляет туннель из пула и возвращает его.
        """

        try:
            return self._tunnels.pop(str(tunnel_id))
        except KeyError:
            raise KeyError(
                f"Tunnel {tunnel_id} not found"
            )

    def get(self, tunnel_id: str) -> Tunnel:
        """
        Возвращает туннель по ID.
        """

        try:
            return self._tunnels[str(tunnel_id)]
        except KeyError:
            raise KeyError(
                f"Tunnel {tunnel_id} not found"
            )

    @property
    def size(self) -> int:
        """
        Общее количество туннелей.
        """

        return len(self._tunnels)

    @property
    def active_count(self) -> int:
        """
        Количество активных туннелей.
        """

        return sum(
            tunnel.is_active()
            for tunnel in self._tunnels.values()
        )

    @property
    def prepared_count(self) -> int:
        """
        Количество неактивных, но подготовленных туннелей.

        Подготовленным считается туннель, который существует
        в пуле, но пока не находится в ACTIVE-состоянии.
        """

        return self.size - self.active_count

    def list_all(self) -> list[Tunnel]:
        """
        Возвращает все туннели.
        """

        return list(self._tunnels.values())

    def list_active(self) -> list[Tunnel]:
        """
        Возвращает только активные туннели.
        """

        return [
            tunnel
            for tunnel in self._tunnels.values()
            if tunnel.is_active()
        ]

    def list_prepared(self) -> list[Tunnel]:
        """
        Возвращает подготовленные, но неактивные туннели.
        """

        return [
            tunnel
            for tunnel in self._tunnels.values()
            if not tunnel.is_active()
        ]

    def select_tunnel(self) -> Tunnel:
        """
        Выбирает первый доступный активный туннель.

        Закрытые туннели автоматически исключаются из выбора.
        """

        active = self.list_active()

        if not active:
            raise RuntimeError(
                "No active tunnels available"
            )

        return active[0]
    def clear(self) -> None:
        """
        Очищает пул.
        """

        self._tunnels.clear()