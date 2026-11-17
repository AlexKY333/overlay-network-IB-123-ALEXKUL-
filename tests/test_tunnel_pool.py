import sys
from pathlib import Path

import pytest

sys.path.insert(
    0,
    str(
        Path(__file__).resolve().parent.parent / "src"
    )
)

from tunnel import Tunnel
from tunnel_pool import TunnelPool


def make_tunnel(source=1, destination=100):
    tunnel = Tunnel(
        source_node_id=source,
        destination_node_id=destination,
        relay_node_ids=[10, 20, 30],
    )

    tunnel.activate()

    return tunnel


def make_prepared_tunnel(source=1, destination=100):
    return Tunnel(
        source_node_id=source,
        destination_node_id=destination,
        relay_node_ids=[10, 20, 30],
    )


def test_add_tunnel():
    pool = TunnelPool()
    tunnel = make_tunnel()

    pool.add(tunnel)

    assert pool.size == 1
    assert pool.get(tunnel.tunnel_id) is tunnel


def test_duplicate_tunnel_rejected():
    pool = TunnelPool()
    tunnel = make_tunnel()

    pool.add(tunnel)

    with pytest.raises(ValueError):
        pool.add(tunnel)


def test_invalid_tunnel_rejected():
    pool = TunnelPool()

    with pytest.raises(TypeError):
        pool.add("not a tunnel")


def test_remove_tunnel():
    pool = TunnelPool()
    tunnel = make_tunnel()

    pool.add(tunnel)

    removed = pool.remove(tunnel.tunnel_id)

    assert removed is tunnel
    assert pool.size == 0


def test_remove_unknown_tunnel_rejected():
    pool = TunnelPool()

    with pytest.raises(KeyError):
        pool.remove("unknown")


def test_list_all():
    pool = TunnelPool()

    tunnel1 = make_tunnel(1, 100)
    tunnel2 = make_tunnel(2, 200)
    tunnel3 = make_tunnel(3, 300)

    pool.add(tunnel1)
    pool.add(tunnel2)
    pool.add(tunnel3)

    tunnels = pool.list_all()

    assert len(tunnels) == 3
    assert tunnel1 in tunnels
    assert tunnel2 in tunnels
    assert tunnel3 in tunnels


def test_three_tunnel_pool():
    pool = TunnelPool()

    tunnel1 = make_tunnel(1, 100)
    tunnel2 = make_tunnel(2, 200)
    tunnel3 = make_tunnel(3, 300)

    pool.add(tunnel1)
    pool.add(tunnel2)
    pool.add(tunnel3)

    assert pool.size == 3
    assert pool.active_count == 3
    assert pool.prepared_count == 0


def test_select_active_tunnel():
    pool = TunnelPool()

    tunnel1 = make_tunnel(1, 100)
    tunnel2 = make_tunnel(2, 200)

    pool.add(tunnel1)
    pool.add(tunnel2)

    selected = pool.select_tunnel()

    assert selected in [tunnel1, tunnel2]


def test_select_without_active_tunnels():
    pool = TunnelPool()

    tunnel = make_prepared_tunnel()

    pool.add(tunnel)

    assert pool.active_count == 0
    assert pool.prepared_count == 1

    with pytest.raises(RuntimeError):
        pool.select_tunnel()


def test_clear_pool():
    pool = TunnelPool()

    pool.add(make_tunnel(1, 100))
    pool.add(make_tunnel(2, 200))
    pool.add(make_tunnel(3, 300))

    assert pool.size == 3

    pool.clear()

    assert pool.size == 0
    assert pool.active_count == 0
    assert pool.prepared_count == 0

def test_closed_tunnel_is_excluded_from_selection():
    pool = TunnelPool()

    tunnel1 = make_tunnel(1, 100)
    tunnel2 = make_tunnel(2, 200)
    tunnel3 = make_tunnel(3, 300)

    pool.add(tunnel1)
    pool.add(tunnel2)
    pool.add(tunnel3)

    assert pool.active_count == 3

    # Первый туннель выходит из строя.
    tunnel1.close()

    assert pool.active_count == 2
    assert pool.prepared_count == 1

    # Закрытый туннель больше не должен выбираться.
    selected = pool.select_tunnel()

    assert selected in [tunnel2, tunnel3]
    assert selected is not tunnel1

def test_pool_has_no_active_tunnels_after_all_failures():
    pool = TunnelPool()

    tunnel1 = make_tunnel(1, 100)
    tunnel2 = make_tunnel(2, 200)
    tunnel3 = make_tunnel(3, 300)

    pool.add(tunnel1)
    pool.add(tunnel2)
    pool.add(tunnel3)

    tunnel1.close()
    tunnel2.close()
    tunnel3.close()

    assert pool.active_count == 0
    assert pool.prepared_count == 3

    with pytest.raises(RuntimeError):
        pool.select_tunnel()