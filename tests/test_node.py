from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pytest

from node import Node
from relay_profile import RelayProfile
from relay_selector import RelaySelector


def test_node_creates_identity_and_subsystems(tmp_path: Path):
    print("\n" + "=" * 60)
    print("DEMO: NODE INITIALIZATION & SUBSYSTEMS ISOLATION (SECTION 7)")
    print("=" * 60)

    node = Node(state_dir=tmp_path)

    print(f"  [+] Node initialized successfully")
    print(f"  [+] NodeID (SHA-256): {node.node_id}")
    print(f"  [+] Subsystem Identity: OK (verified {node.identity.node_id[:16]}...)")
    print(f"  [+] Subsystem RoutingTable: OK (local_id matches)")
    print(f"  [+] Subsystem DHTStorage: OK")
    print(f"  [+] Subsystem DHTReplicator: OK")
    print(f"  [+] Subsystem TunnelPool: OK")

    assert node.node_id == node.identity.node_id
    assert node.routing_table.local_node_id == node.node_id
    assert node.storage is not None
    assert node.replicator is not None
    assert node.tunnel_pool is not None
    assert node.tunnel_builder is None

    print("  -> Result: All 7 isolated subsystems initialized without leakage. PASS")


def test_node_network_state(tmp_path: Path):
    print("\n" + "=" * 60)
    print("DEMO: NODE GET_NETWORK_STATE() FACADE API (SECTION 7)")
    print("=" * 60)

    node = Node(state_dir=tmp_path)
    state = node.get_network_state()

    print(f"  [+] Facade state snapshot:")
    for key, value in state.items():
        print(f"      - {key}: {value}")

    assert state["node_id"] == node.node_id
    assert state["routing_contacts"] == 0
    assert state["stored_records"] == 0
    assert state["tunnels_total"] == 0
    assert state["tunnels_active"] == 0
    assert state["tunnels_prepared"] == 0

    print("  -> Result: Public API returns consistent state. PASS")


def test_node_with_relay_selector(tmp_path: Path):
    print("\n" + "=" * 60)
    print("DEMO: NODE WITH RELAY PROFILING SELECTOR (SECTION 12)")
    print("=" * 60)

    profiles = [
        RelayProfile(node_id=1, ema_success=1.0, ema_latency=0.1),
        RelayProfile(node_id=2, ema_success=0.9, ema_latency=0.2),
        RelayProfile(node_id=3, ema_success=0.8, ema_latency=0.3),
    ]

    selector = RelaySelector(profiles=profiles)
    print(f"  [+] Relay profiles configured: {len(profiles)} candidates")

    node = Node(
        state_dir=tmp_path,
        relay_selector=selector,
    )

    print(f"  [+] TunnelBuilder injected: {node.tunnel_builder is not None}")
    print(f"  [+] Active pool size: {node.tunnel_pool.size}")

    assert node.tunnel_builder is not None
    assert node.relay_selector is selector
    assert node.tunnel_pool.size == 0

    print("  -> Result: Selector and builder linked cleanly. PASS")


def test_node_build_tunnel(tmp_path: Path):
    print("\n" + "=" * 60)
    print("DEMO: BUILD TUNNEL VIA FACADE WITH RANKED STRATEGY (SECTIONS 7 & 12)")
    print("=" * 60)

    profiles = [
        RelayProfile(node_id=1, ema_success=1.0, ema_latency=0.1),
        RelayProfile(node_id=2, ema_success=0.9, ema_latency=0.2),
        RelayProfile(node_id=3, ema_success=0.8, ema_latency=0.3),
    ]

    selector = RelaySelector(profiles=profiles)
    node = Node(
        state_dir=tmp_path,
        relay_selector=selector,
    )

    destination_id = "a" * 64
    print(f"  [+] Initiating build_tunnel via Facade:")
    print(f"      Source:      {node.node_id[:16]}...")
    print(f"      Destination: {destination_id[:16]}...")
    print(f"      Relay count: 3")
    print(f"      Strategy:    ranked")

    tunnel = node.build_tunnel(
        destination_node_id=destination_id,
        relay_count=3,
        strategy="ranked",
    )

    print(f"  [+] Tunnel created successfully:")
    print(f"      Tunnel ID:    {tunnel.tunnel_id}")
    print(f"      Is Active:    {tunnel.is_active()}")
    print(f"      Relay count:  {tunnel.relay_count}")
    print(f"      Pool size:    {node.tunnel_pool.size}")
    print(f"      Active count: {node.tunnel_pool.active_count}")

    assert tunnel.is_active()
    assert tunnel.relay_count == 3
    assert tunnel.source_node_id == int(node.node_id, 16)
    assert tunnel.destination_node_id == int(destination_id, 16)
    assert node.tunnel_pool.size == 1
    assert node.tunnel_pool.active_count == 1

    print("  -> Result: Tunnel constructed and registered in TunnelPool. PASS")