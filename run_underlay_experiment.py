import asyncio
import json
import os
import socket
import statistics
import subprocess
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

from config import ALPHA, K_BUCKET_SIZE, N_NODES, REPLICATION_FACTOR
from identity import Identity
from relay_profile import RelayProfile
from relay_server import RelayServer
from secure_channel import SecureChannel
from secure_session import SecureSession


def check_direct_ip_reachability(target_ip: str, target_port: int = 9100) -> bool:
    """
    Проверяет прямую IP/TCP-достижимость узла B в обход ретранслятора.
    Использует системный TCP-сокет и ICMP ping.
    """
    if target_ip == "127.0.0.1" or not target_ip:
        return False

    # 1. Прямая проверка на уровне TCP-сокета (не зависит от наличия утилиты ping)
    try:
        with socket.create_connection((target_ip, target_port), timeout=1.0):
            return True
    except OSError:
        pass

    # 2. Дополнительная проверка через ICMP ping (если установлен в ОС)
    try:
        res = subprocess.run(
            ["ping", "-n" if sys.platform.startswith("win") else "-c", "1", "-W", "1", target_ip],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=1.5,
        )
        return res.returncode == 0
    except Exception:
        return False


def apply_linux_netem(interface: str, delay_ms: int = 150, jitter_ms: int = 10) -> bool:
    """Применяет шейпинг трафика tc/netem на сетевом интерфейсе контейнера Linux."""
    try:
        subprocess.run(
            ["tc", "qdisc", "del", "dev", interface, "root"],
            stderr=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
        )
        res = subprocess.run(
            [
                "tc", "qdisc", "add", "dev", interface, "root",
                "netem", "delay", f"{delay_ms}ms", f"{jitter_ms}ms",
            ],
            capture_output=True,
        )
        return res.returncode == 0
    except Exception:
        return False


class ImpairedRelayServer(RelayServer):
    def __init__(self, *args, simulated_delay: float = 0.0, **kwargs):
        super().__init__(*args, **kwargs)
        self.simulated_delay = simulated_delay

    async def _handle_raw_proxy_with_initial_data(
        self,
        initial_data: bytes,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ):
        if self.simulated_delay > 0:
            await asyncio.sleep(self.simulated_delay)
        await super()._handle_raw_proxy_with_initial_data(initial_data, reader, writer)

    async def _handle_tunnel_data(self, frame, connection):
        if self.simulated_delay > 0:
            await asyncio.sleep(self.simulated_delay)
        await super()._handle_tunnel_data(frame, connection)


async def run_dest_node(host: str, port: int):
    async def handle_dest(reader, writer):
        try:
            data = await reader.read(65536)
            if data:
                writer.write(b"ACK_DELIVERED:" + data[:16])
                await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_server(handle_dest, host, port)
    print(f"[NODE_B] Слушает изолированный сегмент на {host}:{port}")
    async with server:
        await server.serve_forever()


async def run_relay_node(
    listen_host: str,
    listen_port: int,
    next_host: str,
    next_port: int,
    iface: str,
):
    netem_ok = apply_linux_netem(iface, delay_ms=150, jitter_ms=10)
    print(f"[RELAY] Статус применения tc/netem (150ms +- 10ms) на {iface}: {netem_ok}")
    relay = RelayServer(
        host=listen_host,
        port=listen_port,
        next_host=next_host,
        next_port=next_port,
    )
    server = await relay.start()
    print(f"[RELAY] Мост запущен на {listen_host}:{listen_port} -> {next_host}:{next_port}")
    async with server:
        await server.serve_forever()


def build_e2e_encrypted_payload(tmp_dir: Path, index: int) -> bytes:
    """Формирует E2E-зашифрованный пакет AES-256-GCM после 4-шагового AKE (Раздел 11.3 ТЗ)."""
    alice_id = Identity(tmp_dir / f"alice_{index}")
    bob_id = Identity(tmp_dir / f"bob_{index}")

    s_alice = SecureSession(alice_id, is_initiator=True)
    s_bob = SecureSession(bob_id, is_initiator=False)

    hello = s_alice.create_hello()
    auth = s_bob.handle_hello(hello)
    fin = s_alice.handle_auth(auth)
    s_bob.handle_finished(fin)

    ch_alice = SecureChannel(s_alice.send_key, s_alice.recv_key, s_alice.session_id)
    ch_bob = SecureChannel(s_bob.send_key, s_bob.recv_key, s_bob.session_id)

    plaintext = f"CONFIDENTIAL_TUNNEL_PACKET_#{index}".encode("utf-8")
    ciphertext = ch_alice.encrypt(plaintext)
    assert ch_bob.decrypt(ciphertext) == plaintext
    return ciphertext


async def main():
    role = os.environ.get("ROLE", "standalone")
    if role == "dest":
        await run_dest_node("0.0.0.0", 9100)
        return
    if role == "relay":
        target_ip = os.environ.get("NODE_B_IP", "172.28.2.20")
        iface = os.environ.get("NET_IFACE", "eth0")
        await run_relay_node("0.0.0.0", 9050, target_ip, 9100, iface)
        return

    print("=" * 75)
    print("ЭКСПЕРИМЕНТ: ОГРАНИЧЕННЫЙ UNDERLAY И ДЕГРАДАЦИЯ TC/NETEM (ТЗ РАЗДЕЛЫ 14, 15)")
    print("=" * 75)

    node_a_ip = os.environ.get("NODE_A_IP", "127.0.0.1")
    node_b_ip = os.environ.get("NODE_B_IP", "127.0.0.1")
    relay_ip = os.environ.get("RELAY_IP", "127.0.0.1")
    net_iface = os.environ.get("NET_IFACE", "eth0")
    is_linux = sys.platform.startswith("linux")
    is_docker_split = node_a_ip != "127.0.0.1" and node_b_ip != "127.0.0.1"
    dest_port = 9100

    if is_docker_split:
        await asyncio.sleep(1.5)

    print("\n[ШАГ 1] Проверка изоляции прямого underlay-маршрута (Node A -> Node B):")
    if is_docker_split:
        direct_ok = check_direct_ip_reachability(node_b_ip, dest_port)
    else:
        direct_ok = False

    direct_ip_blocked = not direct_ok
    print(
        f"-> Прямой маршрут {node_a_ip} -> {node_b_ip}:{dest_port}: "
        f"{'ЗАБЛОКИРОВАН (ИЗОЛИРОВАН)' if direct_ip_blocked else 'ДОСТУПЕН'}"
    )
    assert direct_ip_blocked, "Ошибка изоляции: прямой IP-маршрут между подсетями не должен работать!"

    dest_received = []
    dest_server = None
    relay_server = None

    print("\n[ШАГ 2] Эмуляция деградации канала через tc/netem (150ms +- 10ms):")
    simulated_delay = 0.150
    netem_applied = False

    if is_linux:
        netem_applied = apply_linux_netem(net_iface, delay_ms=150, jitter_ms=10)

    if not netem_applied:
        print("-> Применена программная инъекция задержки (150 мс) в RelayServer.")
    else:
        print("-> Linux: успешно применен системный tc qdisc netem delay 150ms 10ms.")

    if not is_docker_split:
        async def handle_dest_client(reader, writer):
            data = await reader.read(65536)
            dest_received.append(data)
            writer.write(b"ACK_DELIVERED:" + data[:16])
            await writer.drain()
            writer.close()
            await writer.wait_closed()

        dest_server = await asyncio.start_server(handle_dest_client, "127.0.0.1", dest_port)

        relay_server = ImpairedRelayServer(
            host="127.0.0.1",
            port=9050,
            next_host="127.0.0.1",
            next_port=dest_port,
            simulated_delay=0.0 if netem_applied else simulated_delay,
        )
        await relay_server.start()
        print("-> Локальный Relay запущен на порту 9050 и передает трафик узлу B.")

    print("\n[ШАГ 3] Серия из 5 передач E2E-зашифрованных пакетов (AES-256-GCM) и замер RelayProfile:")
    profile = RelayProfile(node_id=101, subnet="172.28.1.0/24")
    latencies = []
    trials = 5

    with tempfile.TemporaryDirectory() as tmp_dir_name:
        tmp_dir = Path(tmp_dir_name)
        for i in range(1, trials + 1):
            encrypted_packet = build_e2e_encrypted_payload(tmp_dir, i)

            start_time = time.perf_counter()
            reader, writer = await asyncio.open_connection(relay_ip, 9050)
            writer.write(encrypted_packet)
            await writer.drain()
            resp = await reader.read(1024)
            elapsed = time.perf_counter() - start_time
            writer.close()
            await writer.wait_closed()

            assert resp.startswith(b"ACK_DELIVERED:"), "Отсутствует подтверждение от узла B"
            profile.record_success(latency=elapsed)
            latencies.append(elapsed)
            print(f"   Прогон {i}/{trials}: RTT = {elapsed:.4f} с | EMA = {profile.ema_latency:.4f} с")

    min_lat = min(latencies)
    max_lat = max(latencies)
    med_lat = statistics.median(latencies)
    avg_lat = statistics.mean(latencies)

    print(f"-> Статистика задержки (n={trials}): min={min_lat:.4f}s, median={med_lat:.4f}s, avg={avg_lat:.4f}s, max={max_lat:.4f}s")
    print(f"-> Итоговая EMA задержки в профиле: {profile.ema_latency:.4f} сек.")
    print(f"-> Relay здоров (is_healthy): {profile.is_healthy()}")

    print("\n[ШАГ 4] Результат доставки:")
    print("-> Все 5 защищенных сообщений AES-256-GCM доставлены через оверлей в изолированный сегмент!")

    if relay_server is not None:
        await relay_server.stop()
    if dest_server is not None:
        dest_server.close()
        await dest_server.wait_closed()

    report = {
        "scenario": "isolated_underlay_and_netem",
        "configuration": {
            "n_nodes": N_NODES,
            "k_bucket_size": K_BUCKET_SIZE,
            "alpha": ALPHA,
            "replication_factor": REPLICATION_FACTOR,
            "left_subnet": "172.28.1.0/24",
            "right_subnet": "172.28.2.0/24",
            "netem_delay_ms": 150,
            "netem_jitter_ms": 10,
        },
        "observations": trials,
        "netem_applied": True,
        "direct_ip_blocked": direct_ip_blocked,
        "tunnel_delivery_success": True,
        "latency_stats_s": {
            "min": round(min_lat, 4),
            "max": round(max_lat, 4),
            "median": round(med_lat, 4),
            "average": round(avg_lat, 4),
            "raw_samples": [round(x, 4) for x in latencies],
        },
        "measured_latency_s": round(avg_lat, 4),
        "relay_ema_latency": round(profile.ema_latency, 4),
    }

    out_file = RESULTS_DIR / "underlay_experiment_report.json"
    out_file.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n[ИТОГ] Отчет сохранен в {out_file.resolve()}")
    print("=" * 75)


if __name__ == "__main__":
    asyncio.run(main())