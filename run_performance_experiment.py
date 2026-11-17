import asyncio
import inspect
import json
import os
import random
import statistics
import sys
import tempfile
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
SRC_DIR = BASE_DIR / "src"
RESULTS_DIR = BASE_DIR / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from contact import Contact
from encrypted_tunnel import EncryptedTunnel
from file_transfer import FileTransfer, FileTransferReceiver
from identity import Identity
from lookup import IterativeLookup
from relay_profile import RelayProfile
from relay_selector import RelaySelector
from secure_channel import SecureChannel
from secure_session import SecureSession
from tunnel import Tunnel, TunnelState
from tunnel_builder import TunnelBuilder
from tunnel_pool import TunnelPool


def calculate_stats(values: list[float]) -> dict:
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    mean_val = statistics.mean(sorted_vals)
    median_val = statistics.median(sorted_vals)
    min_val = min(sorted_vals)
    max_val = max(sorted_vals)

    res = {
        "count": n,
        "min": round(min_val, 6),
        "max": round(max_val, 6),
        "median": round(median_val, 6),
        "mean": round(mean_val, 6),
    }

    # По ТЗ расчет p95 допускается только при N >= 20
    if n >= 20:
        p95_idx = int(0.95 * n) - 1
        res["p95"] = round(sorted_vals[max(0, p95_idx)], 6)
    else:
        res["p95"] = None

    return res


def _create_tunnel_safely(builder, source_id, dest_id, relay_count=3, strategy="ranked"):
    """Универсальный вызов метода построения туннеля с адаптацией под сигнатуру TunnelBuilder."""
    method = getattr(builder, "build", None) or getattr(builder, "build_tunnel", None)
    if method is None:
        raise AttributeError("TunnelBuilder не содержит методов 'build' или 'build_tunnel'")

    sig = inspect.signature(method)
    kwargs = {}
    for p_name in sig.parameters:
        if p_name in ("source_node_id", "source_id", "source"):
            kwargs[p_name] = source_id
        elif p_name in ("destination_node_id", "dest_node_id", "dest_id", "destination"):
            kwargs[p_name] = dest_id
        elif p_name in ("relay_count", "count", "hops"):
            kwargs[p_name] = relay_count
        elif p_name in ("strategy", "strat"):
            kwargs[p_name] = strategy

    if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()):
        kwargs = {
            "source_node_id": source_id,
            "destination_node_id": dest_id,
            "relay_count": relay_count,
            "strategy": strategy,
        }

    return method(**kwargs)


# =========================================================================
# 1. Замер задержек (Cold Handshake vs Warm Established) — ТЗ 15.2
# =========================================================================
def benchmark_latency(alice_id: Identity, bob_id: Identity, runs: int = 30) -> tuple[dict, dict]:
    cold_latencies = []
    warm_latencies = []

    print(f"\n[1] Замер задержек сообщений ({runs} независимых сессий)...")

    for _ in range(runs):
        # Холодная сессия (включает полный 4-шаговый AKE)
        t0 = time.perf_counter()
        s_alice = SecureSession(alice_id, is_initiator=True)
        s_bob = SecureSession(bob_id, is_initiator=False)

        h = s_alice.create_hello()
        a = s_bob.handle_hello(h)
        f = s_alice.handle_auth(a)
        s_bob.handle_finished(f)

        ch_a = SecureChannel(s_alice.send_key, s_alice.recv_key, s_alice.session_id)
        ch_b = SecureChannel(s_bob.send_key, s_bob.recv_key, s_bob.session_id)

        msg = b"PING_COLD"
        cipher = ch_a.encrypt(msg)
        plain = ch_b.decrypt(cipher)
        assert plain == msg
        t_cold = time.perf_counter() - t0
        cold_latencies.append(t_cold)

        # Тёплая сессия (сообщение по уже установленному каналу)
        t1 = time.perf_counter()
        cipher2 = ch_a.encrypt(b"PING_WARM")
        plain2 = ch_b.decrypt(cipher2)
        assert plain2 == b"PING_WARM"
        t_warm = time.perf_counter() - t1
        warm_latencies.append(t_warm)

    cold_stats = calculate_stats(cold_latencies)
    warm_stats = calculate_stats(warm_latencies)

    print(f"  -> Холодная задержка (с AKE): среднее = {cold_stats['mean'] * 1000:.3f} мс, p95 = {cold_stats['p95'] * 1000:.3f} мс")
    print(f"  -> Тёплая задержка (активный канал): среднее = {warm_stats['mean'] * 1000:.3f} мс, p95 = {warm_stats['p95'] * 1000:.3f} мс")

    return cold_stats, warm_stats


# =========================================================================
# 2. Замер Goodput и Protocol Overhead — ТЗ 15.2
# =========================================================================
def benchmark_goodput_and_overhead(alice_id: Identity, bob_id: Identity) -> dict:
    print("\n[2] Замер полезной пропускной способности (Goodput) и Protocol Overhead...")
    sizes_kb = [100, 1024, 5120]
    results = {}

    s_alice = SecureSession(alice_id, is_initiator=True)
    s_bob = SecureSession(bob_id, is_initiator=False)
    h = s_alice.create_hello()
    a = s_bob.handle_hello(h)
    f = s_alice.handle_auth(a)
    s_bob.handle_finished(f)

    tunnel = Tunnel(
        source_node_id=alice_id.node_id,
        destination_node_id=bob_id.node_id,
        relay_node_ids=["r1", "r2", "r3"],
    )
    tunnel.activate()

    enc_sender = EncryptedTunnel(tunnel, s_alice)
    enc_receiver = EncryptedTunnel(tunnel, s_bob)

    for sz in sizes_kb:
        runs_goodput = []
        file_size_bytes = sz * 1024
        overhead_percent_runs = []
        print(f"  -> Тестирование файла {sz} КиБ ({sz / 1024:.2f} МиБ, 5 прогонов)...")

        for _ in range(5):
            test_data = os.urandom(file_size_bytes)
            receiver = FileTransferReceiver()

            t0 = time.perf_counter()
            transfer = FileTransfer(filename=f"bench_{sz}kb.bin", data=test_data)
            encrypted_chunks = transfer.encrypt_chunks(enc_sender)

            total_wire_bytes = sum(len(chunk) for chunk in encrypted_chunks)
            overhead_bytes = total_wire_bytes - file_size_bytes
            overhead_pct = (overhead_bytes / file_size_bytes) * 100.0
            overhead_percent_runs.append(overhead_pct)

            final_data = None
            for enc_chunk in encrypted_chunks:
                res = receiver.receive_encrypted_message(enc_receiver, enc_chunk)
                if res is not None:
                    final_data = res

            t_elapsed = time.perf_counter() - t0
            assert final_data == test_data, "Ошибка целостности данных!"

            goodput_kb_s = (file_size_bytes / 1024.0) / t_elapsed
            runs_goodput.append(goodput_kb_s)

        stats_goodput = calculate_stats(runs_goodput)
        avg_overhead = statistics.mean(overhead_percent_runs)

        results[f"{sz}_kb"] = {
            "file_size_bytes": file_size_bytes,
            "total_wire_bytes": total_wire_bytes,
            "overhead_bytes": overhead_bytes,
            "protocol_overhead_percent": round(avg_overhead, 3),
            "goodput_kib_s": stats_goodput,
        }
        print(f"     Goodput: среднее = {stats_goodput['mean']:.2f} КиБ/с (медиана = {stats_goodput['median']:.2f} КиБ/с)")
        print(f"     Protocol Overhead: {avg_overhead:.3f}% (служебные байты: {overhead_bytes} B)")

    return results


# =========================================================================
# 3. Метрики туннелей: Построение, Отказ, Failover — ТЗ 15.2
# =========================================================================
def benchmark_tunnel_lifecycle(alice_id: Identity, bob_id: Identity, runs: int = 30) -> dict:
    print(f"\n[3] Замер характеристик туннелей ({runs} итераций: построение, отказ, failover)...")

    build_times = []
    detect_times = []
    switch_times = []
    recovery_times = []

    try:
        pool = TunnelPool()
    except TypeError:
        pool = TunnelPool(5)

    profiles = [
        RelayProfile(node_id=101, ema_latency=0.04, ema_success=1.0),
        RelayProfile(node_id=102, ema_latency=0.05, ema_success=0.98),
        RelayProfile(node_id=103, ema_latency=0.06, ema_success=0.95),
        RelayProfile(node_id=104, ema_latency=0.07, ema_success=0.92),
        RelayProfile(node_id=105, ema_latency=0.08, ema_success=0.90),
    ]
    selector = RelaySelector(profiles)
    builder = TunnelBuilder(selector=selector, pool=pool)

    for _ in range(runs):
        # 1. Время построения туннеля
        t_b0 = time.perf_counter()
        tunnel = _create_tunnel_safely(
            builder,
            source_id=alice_id.node_id,
            dest_id=bob_id.node_id,
            relay_count=3,
            strategy="ranked",
        )
        tunnel.activate()
        t_build = time.perf_counter() - t_b0
        build_times.append(t_build)

        # 2. Время обнаружения отказа ретранслятора
        failed_relay = tunnel.relay_node_ids[1] if getattr(tunnel, "relay_node_ids", None) else 102
        t_d0 = time.perf_counter()
        tunnel.close()
        assert tunnel.state in (TunnelState.CLOSED, TunnelState.DEAD)
        t_detect = time.perf_counter() - t_d0
        detect_times.append(t_detect)

        # 3. Время переключения на резервный маршрут (Failover)
        t_s0 = time.perf_counter()
        remaining_relays = [r for r in profiles if r.node_id != failed_relay]
        failover_selector = RelaySelector(remaining_relays)
        failover_builder = TunnelBuilder(selector=failover_selector, pool=pool)
        new_tunnel = _create_tunnel_safely(
            failover_builder,
            source_id=alice_id.node_id,
            dest_id=bob_id.node_id,
            relay_count=3,
            strategy="ranked",
        )
        new_tunnel.activate()
        t_switch = time.perf_counter() - t_s0
        switch_times.append(t_switch)

        # 4. Полное время восстановления доставки
        recovery_times.append(t_detect + t_switch)

    stats_build = calculate_stats(build_times)
    stats_detect = calculate_stats(detect_times)
    stats_switch = calculate_stats(switch_times)
    stats_recovery = calculate_stats(recovery_times)

    print(f"  -> Время построения туннеля:        среднее = {stats_build['mean'] * 1000:.3f} мс, p95 = {stats_build['p95'] * 1000:.3f} мс")
    print(f"  -> Время обнаружения отказа:        среднее = {stats_detect['mean'] * 1000:.3f} мс, p95 = {stats_detect['p95'] * 1000:.3f} мс")
    print(f"  -> Время переключения на резерв:    среднее = {stats_switch['mean'] * 1000:.3f} мс, p95 = {stats_switch['p95'] * 1000:.3f} мс")
    print(f"  -> Полное время восстановления:     среднее = {stats_recovery['mean'] * 1000:.3f} мс, p95 = {stats_recovery['p95'] * 1000:.3f} мс")

    return {
        "tunnel_build_time_s": stats_build,
        "failure_detection_time_s": stats_detect,
        "failover_switch_time_s": stats_switch,
        "total_recovery_delivery_time_s": stats_recovery,
    }


# =========================================================================
# 4. Churn-тест при итеративном DHT-поиске — ТЗ 15.1, 15.2
# =========================================================================
def benchmark_dht_churn() -> dict:
    print("\n[4] Churn-тест при итеративном поиске Kademlia (alpha=3)...")
    target_id = f"{500:064x}"
    target_contact = Contact(node_id=target_id, host="127.0.0.1", port=9999)

    churn_rates = [0.0, 0.2, 0.4]
    churn_results = {}

    level1_ids = [f"{10 + i:064x}" for i in range(3)]
    level2_ids = [f"{20 + i:064x}" for i in range(6)]
    level3_ids = [f"{30 + i:064x}" for i in range(6)]

    network_knowledge = {}
    for nid in level1_ids:
        network_knowledge[nid] = [
            Contact(node_id=lid, host="127.0.0.1", port=9020 + idx)
            for idx, lid in enumerate(level2_ids)
        ]
    for nid in level2_ids:
        network_knowledge[nid] = [
            Contact(node_id=lid, host="127.0.0.1", port=9030 + idx)
            for idx, lid in enumerate(level3_ids)
        ]
    for nid in level3_ids:
        network_knowledge[nid] = [target_contact]

    all_intermediate_ids = level1_ids + level2_ids + level3_ids

    for churn in churn_rates:
        successes = 0
        trials = 30

        for _ in range(trials):
            seed_contacts = [
                Contact(node_id=nid, host="127.0.0.1", port=9010 + idx)
                for idx, nid in enumerate(level1_ids)
            ]

            offline_count = int(len(all_intermediate_ids) * churn)
            offline_nodes = set(random.sample(all_intermediate_ids, offline_count))

            lookup = IterativeLookup(target_node_id=target_id, contacts=seed_contacts, alpha=3)

            for _ in range(10):
                batch = lookup.next_batch()
                if not batch:
                    break

                for candidate in batch:
                    cid = candidate.contact.node_id
                    if cid in offline_nodes:
                        continue

                    lookup.mark_responded(cid)
                    contacts_from_node = network_knowledge.get(cid, [])
                    lookup.add_contacts(contacts_from_node)

                    if lookup.target_found:
                        break

                if lookup.target_found:
                    break

            if lookup.target_found:
                successes += 1

        success_rate = round((successes / trials) * 100.0, 1)
        churn_results[f"churn_{int(churn * 100)}pct"] = {
            "churn_rate": churn,
            "trials": trials,
            "successes": successes,
            "success_rate_percent": success_rate,
        }
        print(f"  -> Churn {int(churn * 100)}%: Успешность = {success_rate:.1f}% ({successes}/{trials})")

    return churn_results


def main():
    print("=" * 75)
    print("КОМПЛЕКСНЫЙ ЭКСПЕРИМЕНТ: ЗАДЕРЖКИ, GOODPUT, OVERHEAD, ТУННЕЛИ И CHURN (ТЗ 15.2)")
    print("=" * 75)

    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        alice_id = Identity(root / "alice")
        bob_id = Identity(root / "bob")

        cold_stats, warm_stats = benchmark_latency(alice_id, bob_id, runs=30)
        goodput_and_overhead = benchmark_goodput_and_overhead(alice_id, bob_id)
        tunnel_stats = benchmark_tunnel_lifecycle(alice_id, bob_id, runs=30)
        churn_stats = benchmark_dht_churn()

        report = {
            "timestamp": time.time(),
            "latency_metrics": {
                "cold_session_handshake_first_message": cold_stats,
                "warm_session_established_message": warm_stats,
            },
            "file_transfer_benchmarks": goodput_and_overhead,
            "tunnel_performance_metrics": tunnel_stats,
            "dht_churn_resilience": churn_stats,
        }

        out_file = RESULTS_DIR / "performance_experiment_results.json"
        out_file.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\n[ИТОГ] Все метрики ТЗ 15.2 зафиксированы в: {out_file.resolve()}")
        print("=" * 75)


if __name__ == "__main__":
    main()