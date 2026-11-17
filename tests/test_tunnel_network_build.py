import sys
from pathlib import Path

# Добавляем папку src в путь поиска модулей
sys.path.insert(
    0,
    str(Path(__file__).resolve().parent.parent / "src")
)

import asyncio
import pytest
from relay_profile import RelayProfile
from relay_selector import RelaySelector
from relay_server import RelayServer
from tunnel_builder import TunnelBuilder
from tunnel_pool import TunnelPool


@pytest.mark.asyncio
async def test_network_tunnel_build_3_hops():
    """
    Проверяет сетевое построение туннеля из 3 ретрансляторов
    через реальные TCP-сообщения TUNNEL_BUILD / TUNNEL_OK.
    """
    # 1. Запускаем 3 ретранслятора и узел назначения
    r1 = RelayServer("127.0.0.1", 0)
    r2 = RelayServer("127.0.0.1", 0)
    r3 = RelayServer("127.0.0.1", 0)
    dest = RelayServer("127.0.0.1", 0)

    s1 = await r1.start()
    s2 = await r2.start()
    s3 = await r3.start()
    sd = await dest.start()

    p1 = s1.sockets[0].getsockname()[1]
    p2 = s2.sockets[0].getsockname()[1]
    p3 = s3.sockets[0].getsockname()[1]
    pd = sd.sockets[0].getsockname()[1]

    node_addresses = {
        101: ("127.0.0.1", p1),
        102: ("127.0.0.1", p2),
        103: ("127.0.0.1", p3),
        999: ("127.0.0.1", pd),
    }

    try:
        # 2. Создаем селектор с 3 кандидатами
        profiles = [
            RelayProfile(node_id=101, ema_latency=0.1),
            RelayProfile(node_id=102, ema_latency=0.2),
            RelayProfile(node_id=103, ema_latency=0.3),
        ]
        selector = RelaySelector(profiles)
        pool = TunnelPool()
        builder = TunnelBuilder(selector=selector, pool=pool)

        # 3. Строим туннель по сети (Source=1 -> R1 -> R2 -> R3 -> Dest=999)
        tunnel = await builder.build_network_tunnel(
            source_node_id=1,
            destination_node_id=999,
            node_addresses=node_addresses,
            relay_count=3,
            strategy="random",
            timeout=3.0,
        )

        assert tunnel.is_active()
        assert tunnel.relay_count == 3
        assert pool.size == 1

        # 4. Проверяем, что каждый ретранслятор сохранил в памяти маршрут для tunnel_id
        tid = str(tunnel.tunnel_id)
        assert tid in r1.active_routes
        assert tid in r2.active_routes
        assert tid in r3.active_routes

    finally:
        await r1.stop()
        await r2.stop()
        await r3.stop()
        await dest.stop()