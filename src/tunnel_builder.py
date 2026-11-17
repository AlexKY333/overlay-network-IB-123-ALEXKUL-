from relay_selector import RelaySelector
from tunnel import Tunnel
from tunnel_pool import TunnelPool
import asyncio
from config import NETWORK_TIMEOUT, TUNNEL_RELAY_COUNT


class TunnelBuilder:
    """
    Построение туннеля через выбранные relay.

    Relay выбираются с помощью RelaySelector.
    """

    def __init__(
        self,
        selector: RelaySelector,
        pool: TunnelPool | None = None,
    ):
        if not isinstance(selector, RelaySelector):
            raise TypeError(
                "selector must be an instance of RelaySelector"
            )

        if pool is not None and not isinstance(pool, TunnelPool):
            raise TypeError(
                "pool must be an instance of TunnelPool"
            )

        self.selector = selector
        self.pool = pool

    def build(
        self,
        source_node_id: int,
        destination_node_id: int,
        relay_count: int = TUNNEL_RELAY_COUNT,
        strategy: str = "ranked",
    ) -> Tunnel:
        """
        Создаёт и активирует туннель.

        strategy:
        - ranked — выбираются лучшие relay;
        - random — случайный выбор.

        Для Advanced-уровня по умолчанию используется
        минимум 3 relay.
        """

        if relay_count < 1:
            raise ValueError(
                "relay_count must be at least 1"
            )

        if source_node_id == destination_node_id:
            raise ValueError(
                "source and destination must be different"
            )

        if strategy not in {"ranked", "random"}:
            raise ValueError(
                "strategy must be 'ranked' or 'random'"
            )

        candidates = (
            self.selector.admissible_profiles()
        )

        if len(candidates) < relay_count:
            raise RuntimeError(
                "Not enough admissible relay candidates"
            )

        tunnel = Tunnel(
            source_node_id=source_node_id,
            destination_node_id=destination_node_id,
        )

        selected_ids: set[int] = set()

        for _ in range(relay_count):
            remaining = [
                profile
                for profile in candidates
                if profile.node_id not in selected_ids
            ]

            if strategy == "ranked":
                profile = max(
                    remaining,
                    key=self.selector._score,
                )
            else:
                # Используем временный selector только
                # для выбора из оставшихся кандидатов.
                profile = RelaySelector(
                    remaining,
                    max_consecutive_failures=(
                        self.selector.max_consecutive_failures
                    ),
                ).select_random()

            selected_ids.add(profile.node_id)

            tunnel.add_relay(
                profile.node_id
            )

        tunnel.activate()

        if self.pool is not None:
            self.pool.add(tunnel)

        return tunnel

    async def build_network_tunnel(
            self,
            source_node_id: int,
            destination_node_id: int,
            node_addresses: dict[int, tuple[str, int]],
            relay_count: int = TUNNEL_RELAY_COUNT,
            strategy: str = "ranked",
            timeout: float = NETWORK_TIMEOUT,
    ) -> Tunnel:
        """
        Строит туннель и отправляет сетевой запрос TUNNEL_BUILD
        по всей цепочке ретрансляторов.
        """
        from message_types import MessageType
        from protocol import Frame
        from transport import Connection
        from tunnel_messages import TunnelBuildRequest, TunnelBuildResponse

        # Сначала строим логическую цепочку
        tunnel = self.build(
            source_node_id=source_node_id,
            destination_node_id=destination_node_id,
            relay_count=relay_count,
            strategy=strategy,
        )

        # Подготавливаем адреса хопов
        # path: [source, R1, R2, R3, destination]
        hops = []
        for rid in tunnel.relay_node_ids:
            host, port = node_addresses[rid]
            hops.append({"node_id": str(rid), "host": host, "port": port})

        # Добавляем конечный узел назначения
        dest_host, dest_port = node_addresses[destination_node_id]
        hops.append(
            {"node_id": str(destination_node_id), "host": dest_host, "port": dest_port}
        )

        first_relay_id = tunnel.relay_node_ids[0]
        first_relay_host, first_relay_port = node_addresses[first_relay_id]

        # Для R1 следующим будет R2
        second_hop = hops[1]
        remaining = hops[2:]

        request_payload = TunnelBuildRequest(
            tunnel_id=str(tunnel.tunnel_id),
            next_host=second_hop["host"],
            next_port=second_hop["port"],
            remaining_hops=remaining,
        )

        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(first_relay_host, first_relay_port),
            timeout=timeout,
        )
        conn = Connection(reader, writer)

        try:
            frame = Frame(
                message_type=MessageType.TUNNEL_BUILD,
                payload=request_payload.encode(),
            )
            await conn.send_frame(frame)
            resp_frame = await conn.receive_frame(timeout=timeout)

            if resp_frame.message_type != MessageType.TUNNEL_OK:
                tunnel.close()
                raise RuntimeError(
                    f"Failed to build tunnel: {resp_frame.payload.decode('utf-8', errors='ignore')}"
                )

            resp = TunnelBuildResponse.decode(resp_frame.payload)
            if not resp.success:
                tunnel.close()
                raise RuntimeError(f"Tunnel build rejected: {resp.error}")

            return tunnel

        finally:
            await conn.close()