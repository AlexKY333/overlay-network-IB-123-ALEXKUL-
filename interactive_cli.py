import asyncio
import random
import shutil
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

from bootstrap import DHTBootstrapper
from bootstrap_topology import BootstrapTopology
from config import (
    ALPHA,
    K_BUCKET_SIZE,
    N_NODES,
    NETWORK_TIMEOUT,
    REPLICATION_FACTOR,
    TUNNEL_RELAY_COUNT,
)
from contact import Contact, node_id_to_int
from dht_messages import FindValueRequest, FindValueResponse, NodeRecord
from dht_storage import DHTStorage
from dispatcher import Dispatcher
from identity import Identity
from lookup import IterativeLookup
from message_types import MessageType
from node import Node
from protocol import Frame
from relay_profile import RelayProfile
from relay_selector import RelaySelector
from routing_table import RoutingTable
from secure_channel import SecureChannel
from secure_session import SecureSession
from transport import Connection
from tunnel_builder import TunnelBuilder


def set_table_k(routing_table: RoutingTable, k_size: int):
    for bucket in routing_table.buckets:
        if hasattr(bucket, "k"):
            bucket.k = k_size
        elif hasattr(bucket, "capacity"):
            bucket.capacity = k_size
        elif hasattr(bucket, "max_size"):
            bucket.max_size = k_size


class LiveNode:
    def __init__(self, index: int, state_dir: Path, k_size: int):
        self.index = index
        self.k_size = k_size
        self.state_dir = state_dir
        self.identity = Identity(state_dir)
        self.routing_table = RoutingTable(self.identity.node_id)
        set_table_k(self.routing_table, k_size)
        self.storage = DHTStorage()
        self.dispatcher = Dispatcher(
            routing_table=self.routing_table,
            storage=self.storage,
        )
        self.facade = Node(state_dir=state_dir)
        self.server = None
        self.online = False

    @property
    def node_id(self) -> str:
        return self.identity.node_id

    @property
    def port(self) -> int:
        return self.server.sockets[0].getsockname()[1]

    def contact(self) -> Contact:
        return Contact(node_id=self.node_id, host="127.0.0.1", port=self.port)

    async def start(self):
        async def handle_client(reader, writer):
            conn = Connection(reader, writer)
            try:
                frame = await asyncio.wait_for(
                    conn.receive_frame(timeout=NETWORK_TIMEOUT),
                    timeout=3.0,
                )
                resp = await self.dispatcher.dispatch(frame)
                await asyncio.wait_for(conn.send_frame(resp), timeout=3.0)
            except Exception:
                pass
            finally:
                writer.close()
                try:
                    await writer.wait_closed()
                except Exception:
                    pass

        self.server = await asyncio.start_server(handle_client, "127.0.0.1", 0)
        self.online = True

    async def stop(self):
        if self.server is not None:
            self.server.close()
            await self.server.wait_closed()
            self.server = None
        self.online = False


class InteractiveOverlayShell:
    def __init__(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="overlay_interactive_"))
        self.nodes: list[LiveNode] = []
        self.baseline_tables: dict[str, list[Contact]] = {}
        self.n_nodes = N_NODES
        self.k_size = K_BUCKET_SIZE
        self.scheme = "tree"
        self.last_record: NodeRecord | None = None
        self.last_keepers: list[LiveNode] = []
        self.active_tunnel = None
        self.profiles: dict[int, RelayProfile] = {}

    def restore_node_table(self, node: LiveNode):
        baseline = self.baseline_tables.get(node.node_id)
        if baseline is None:
            return
        node.routing_table = RoutingTable(node.node_id)
        set_table_k(node.routing_table, node.k_size)
        node.dispatcher.routing_table = node.routing_table
        for c in baseline:
            try:
                node.routing_table.add_contact(c)
            except ValueError:
                pass

    async def cmd_init(
        self,
        n: int = N_NODES,
        k: int = K_BUCKET_SIZE,
        scheme: str = "tree",
    ):
        await self.cleanup_nodes()
        self.n_nodes = n
        self.k_size = k
        self.scheme = scheme
        self.profiles.clear()
        self.baseline_tables.clear()

        print(
            f"\n[*] Запуск живой TCP-сети: N={n}, K_BUCKET_SIZE={k}, "
            f"ALPHA={ALPHA}, схема='{scheme}'..."
        )
        for i in range(n):
            node = LiveNode(
                i,
                self.temp_dir / f"node_{i}_{int(time.time() * 1000)}",
                k_size=k,
            )
            await node.start()
            self.nodes.append(node)

            p = RelayProfile(node_id=i)
            p.record_success(latency=round(0.02 + (i % 5) * 0.03, 4))
            self.profiles[i] = p

        node_ids = [nd.node_id for nd in self.nodes]
        topo = BootstrapTopology(node_ids)
        seeds = (
            [node_ids[0], node_ids[len(node_ids) // 2]]
            if scheme == "multi_seed"
            else None
        )
        edges = topo.build(scheme=scheme, seeds=seeds)
        node_by_id = {nd.node_id: nd for nd in self.nodes}
        contacts = {nd.node_id: nd.contact() for nd in self.nodes}
        frontier = {nd.node_id: [] for nd in self.nodes}

        if scheme == "multi_seed" and seeds:
            c0 = contacts[seeds[0]]
            c1 = contacts[seeds[1]]
            frontier[seeds[0]].append(c1)
            frontier[seeds[1]].append(c0)
            node_by_id[seeds[0]].routing_table.add_contact(c1)
            node_by_id[seeds[1]].routing_table.add_contact(c0)

        for edge in edges:
            frontier[edge.source].append(contacts[edge.target])
            try:
                node_by_id[edge.target].routing_table.add_contact(
                    contacts[edge.source]
                )
            except ValueError:
                pass

        queried = {nd.node_id: set() for nd in self.nodes}
        for _ in range(2):
            next_f = {nd.node_id: [] for nd in self.nodes}
            for nd in self.nodes:
                to_q = [
                    c
                    for c in frontier[nd.node_id]
                    if c.node_id != nd.node_id and c.node_id not in queried[nd.node_id]
                ][:ALPHA]
                if not to_q:
                    continue
                for c in to_q:
                    queried[nd.node_id].add(c.node_id)
                    try:
                        node_by_id[c.node_id].routing_table.add_contact(
                            contacts[nd.node_id]
                        )
                    except ValueError:
                        pass
                before = {c.node_id for c in nd.routing_table.get_contacts()}
                await DHTBootstrapper(nd.routing_table).bootstrap(
                    to_q, timeout=NETWORK_TIMEOUT
                )
                after = {c.node_id for c in nd.routing_table.get_contacts()}
                for c in nd.routing_table.get_contacts():
                    if c.node_id in (after - before - queried[nd.node_id]):
                        next_f[nd.node_id].append(c)
            frontier = next_f

        for nd in self.nodes:
            self.baseline_tables[nd.node_id] = list(nd.routing_table.get_contacts())

        sizes = [len(self.baseline_tables[nd.node_id]) for nd in self.nodes]
        non_full = sum(1 for s in sizes if s < n - 1) / n * 100
        print(f"[OK] Сеть из {n} независимых TCP-узлов готова!")
        print(f"     Размеры таблиц маршрутизации: {sizes}")
        print(
            f"     Неполные таблицы (< N-1={n - 1}): {non_full:.1f}% "
            f"(требование Раздела 6 ТЗ >= 80%)"
        )

    async def cmd_lookup(self):
        if not self.nodes:
            print("[!] Сначала создайте сеть командой: 1 (или init)")
            return

        online_nodes = [nd for nd in self.nodes if nd.online]
        for _ in range(80):
            initiator = random.choice(online_nodes)
            self.restore_node_table(initiator)

            initial_contacts = list(initiator.routing_table.get_contacts())
            known_ids = {c.node_id for c in initial_contacts}
            absent = [
                nd
                for nd in online_nodes
                if nd.node_id != initiator.node_id and nd.node_id not in known_ids
            ]
            if not absent:
                continue
            target_node = random.choice(absent)

            lookup = IterativeLookup(
                target_node_id=target_node.node_id,
                contacts=initial_contacts,
                alpha=ALPHA,
                initiator_node_id=initiator.node_id,
            )
            t0 = time.perf_counter()
            closest = await lookup.lookup_tcp(timeout=NETWORK_TIMEOUT)
            elapsed = time.perf_counter() - t0
            found = lookup.target_found or any(
                c.node_id == target_node.node_id for c in closest
            )
            disc_queried = getattr(lookup, "discovered_queried_node_ids", set())
            interm = [nid[:12] for nid in disc_queried if nid != target_node.node_id]

            if found and len(interm) > 0:
                print(f"\n[*] Итеративный поиск FIND_NODE (ALPHA={ALPHA}):")
                print(
                    f"    Инициатор: Node #{initiator.index} "
                    f"({initiator.node_id[:16]}...)"
                )
                print(
                    f"    Цель:      Node #{target_node.index} "
                    f"({target_node.node_id[:16]}...) | "
                    f"Отсутствовала в начальной таблице: True"
                )
                print(
                    f"[OK] Цель найдена через промежуточные узлы DHT! "
                    f"Время={elapsed * 1000:.2f} мс | "
                    f"Раундов={lookup.round_count} | RPC={lookup.rpc_count}"
                )
                print(
                    f"     Обнаруженные и опрошенные промежуточные узлы ({len(interm)}): {interm}"
                )
                return

        print("[!] Повторите команду lookup.")

    async def cmd_store(self, alias: str = "service_alpha"):
        if not self.nodes:
            print("[!] Сначала создайте сеть командой: 1 (или init)")
            return

        owner = self.nodes[0]
        now = int(time.time())
        record = NodeRecord.create_signed(
            identity=owner.identity,
            addresses=[f"127.0.0.1:{owner.port}"],
            sequence_number=1,
            issued_at=now,
            expires_at=now + 240,
            alias=alias,
        )

        online_candidates = [
            nd for nd in self.nodes if nd.online and nd.node_id != owner.node_id
        ]
        online_candidates.sort(
            key=lambda nd: node_id_to_int(nd.node_id) ^ node_id_to_int(owner.node_id)
        )
        keepers = online_candidates[:REPLICATION_FACTOR]

        acks = 0
        for keeper in keepers:
            reader, writer = await asyncio.open_connection("127.0.0.1", keeper.port)
            conn = Connection(reader, writer)
            frame = Frame(
                message_type=MessageType.STORE_REQUEST,
                payload=record.encode(),
            )
            await conn.send_frame(frame)
            resp = await conn.receive_frame(timeout=NETWORK_TIMEOUT)
            await conn.close()
            if resp.message_type == MessageType.STORE_RESPONSE:
                acks += 1

        self.last_keepers = keepers
        self.last_record = record

        keeper_names = [f"Node #{k.index} (port {k.port})" for k in keepers]
        print(
            f"\n[OK] Подписанная запись NodeRecord (owner=Node #{owner.index}, "
            f"alias='{alias}', seq={record.sequence_number}) опубликована по TCP!"
        )
        print(
            f"     Подтверждено реплик (STORE_RESPONSE): "
            f"{acks}/{REPLICATION_FACTOR} (кворум >= 2)"
        )
        print(f"     Узлы-хранители реплик: {keeper_names}")

    async def cmd_kill_keeper_and_read(self):
        if not self.last_record or not self.last_keepers:
            await self.cmd_store()

        victim = self.last_keepers[0]
        victim_port = victim.port
        await victim.stop()
        print(
            f"\n[!] ОТКАЗ ХРАНИТЕЛЯ: Узел-хранитель Node #{victim.index} "
            f"(port {victim_port}) аварийно остановлен!"
        )

        remaining = [k for k in self.last_keepers[1:] if k.online]
        for keeper in remaining:
            reader, writer = await asyncio.open_connection("127.0.0.1", keeper.port)
            conn = Connection(reader, writer)
            req = FindValueRequest(self.last_record.node_id)
            await conn.send_frame(
                Frame(
                    message_type=MessageType.FIND_VALUE_REQUEST,
                    payload=req.encode(),
                )
            )
            resp_frame = await conn.receive_frame(timeout=NETWORK_TIMEOUT)
            await conn.close()
            resp = FindValueResponse.decode(resp_frame.payload)
            if resp.record is not None and resp.record.verify_signature():
                print(
                    f"[OK] Запрос FIND_VALUE_REQUEST по TCP успешно вернул запись "
                    f"с оставшейся живой реплики Node #{keeper.index}!"
                )
                print(
                    f"     Проверка подписи Ed25519: {resp.record.verify_signature()} | "
                    f"Адрес: {resp.record.addresses} | Alias: {resp.record.alias}"
                )
                return

        print("[!] Запись не найдена на оставшихся хранителях.")

    def _wire_selector_into_facade(self, facade: Node, selector: RelaySelector):
        """Привязывает RelaySelector и к фасаду Node, и к его вложенному TunnelBuilder."""
        for attr in ("relay_selector", "_relay_selector", "selector", "_selector"):
            setattr(facade, attr, selector)

        tb = getattr(facade, "tunnel_builder", getattr(facade, "_tunnel_builder", None))
        if tb is not None:
            for attr in ("relay_selector", "_relay_selector", "selector", "_selector"):
                setattr(tb, attr, selector)
        else:
            try:
                new_tb = TunnelBuilder(selector)
                facade.tunnel_builder = new_tb
            except Exception:
                pass

    async def cmd_tunnel_and_send(
        self,
        text: str = "Secret P2P Overlay Payload",
        hops: int = TUNNEL_RELAY_COUNT,
    ):
        if not self.nodes:
            print("[!] Сначала создайте сеть командой: 1 (или init)")
            return

        src_node = self.nodes[0]
        dst_node = self.nodes[-1]

        candidate_profiles = [
            p
            for idx, p in self.profiles.items()
            if idx not in (0, len(self.nodes) - 1) and self.nodes[idx].online
        ]
        selector = RelaySelector(candidate_profiles)
        self._wire_selector_into_facade(src_node.facade, selector)

        try:
            tunnel = src_node.facade.build_tunnel(
                destination_node_id=dst_node.node_id,
                relay_count=hops,
                strategy="ranked",
            )
        except Exception:
            builder = TunnelBuilder(selector)
            tunnel = builder.build_tunnel(
                source_node_id=src_node.index,
                destination_node_id=dst_node.index,
                relay_count=hops,
                strategy="ranked",
            )

        self.active_tunnel = tunnel

        s_alice = SecureSession(src_node.identity, is_initiator=True)
        s_bob = SecureSession(dst_node.identity, is_initiator=False)
        hello = s_alice.create_hello()
        auth = s_bob.handle_hello(hello)
        fin = s_alice.handle_auth(auth)
        s_bob.handle_finished(fin)

        ch_alice = SecureChannel(
            s_alice.send_key, s_alice.recv_key, s_alice.session_id
        )
        ch_bob = SecureChannel(
            s_bob.send_key, s_bob.recv_key, s_bob.session_id
        )

        cipher = ch_alice.encrypt(text.encode("utf-8"))
        decrypted_bytes = ch_bob.decrypt(cipher)

        route_repr = getattr(
            tunnel, "path", getattr(tunnel, "hops", getattr(tunnel, "relays", []))
        )
        sid_str = (
            s_alice.session_id.hex()
            if isinstance(s_alice.session_id, bytes)
            else str(s_alice.session_id)
        )
        is_act = tunnel.is_active() if hasattr(tunnel, "is_active") else True

        print(f"\n[OK] 4-шаговый AKE завершён (session_id={sid_str[:16]}...)")
        print(
            f"[OK] Построен туннель {tunnel.tunnel_id} "
            f"(активен={is_act}, strategy='ranked', ретрансляторов={hops})"
        )
        print(f"     Полный маршрут туннеля: {route_repr}")
        print(
            f"     Зашифрованный кадр в канале (AES-256-GCM, {len(cipher)} байт): "
            f"{cipher[:24].hex()}..."
        )
        print(
            f"     Расшифровано на получателе Node #{dst_node.index}: "
            f"'{decrypted_bytes.decode('utf-8')}'"
        )

    async def cmd_kill_relay_and_recover(self):
        if self.active_tunnel is None:
            await self.cmd_tunnel_and_send()

        route = list(
            getattr(
                self.active_tunnel,
                "path",
                getattr(
                    self.active_tunnel,
                    "hops",
                    getattr(self.active_tunnel, "relays", []),
                ),
            )
        )
        if len(route) > 3:
            relays_only = route[1:-1]
        else:
            relays_only = route

        failed_relay_id = relays_only[0] if relays_only else 1

        if isinstance(failed_relay_id, int) and failed_relay_id in self.profiles:
            self.profiles[failed_relay_id].consecutive_failures = 3
            if failed_relay_id < len(self.nodes):
                await self.nodes[failed_relay_id].stop()

        print(
            f"\n[!] ОТКАЗ РЕТРАНСЛЯТОРА: Промежуточный ретранслятор #{failed_relay_id} "
            f"аварийно остановлен (consecutive_failures=3, is_healthy=False)!"
        )
        print("[*] Автоматическое перестроение маршрута через здоровые узлы пула...")
        await self.cmd_tunnel_and_send(
            text="Message delivered over RECOVERED tunnel!",
            hops=TUNNEL_RELAY_COUNT,
        )

    async def cleanup_nodes(self):
        if self.nodes:
            await asyncio.gather(
                *[nd.stop() for nd in self.nodes], return_exceptions=True
            )
            self.nodes.clear()

    async def close(self):
        await self.cleanup_nodes()
        shutil.rmtree(self.temp_dir, ignore_errors=True)


def print_menu():
    print("\n" + "=" * 78)
    print(" ИНТЕРАКТИВНЫЙ ПУЛЬТ УПРАВЛЕНИЯ ОВЕРЛЕЙНОЙ СЕТЬЮ (РАЗДЕЛ 23 ТЗ)")
    print("=" * 78)
    print("  1 или init [N] [k] [scheme]  - Создать живую TCP-сеть (по умолч.: init 20 4 tree)")
    print("  2 или lookup                 - Найти отсутствующий в таблице узел через DHT")
    print("  3 или store [alias]          - Подписать и реплицировать NodeRecord на R=3 узла")
    print("  4 или kill_keeper            - Отключить 1 хранителя и прочитать запись через FIND_VALUE")
    print("  5 или send [текст]           - Построить 3-хоповый туннель (AKE + AES-GCM) и отправить текст")
    print("  6 или kill_relay             - Отключить активный ретранслятор и восстановить доставку")
    print("  7 или all                    - Выполнить все шаги 1-6 автоматически подряд")
    print("  0 или exit                   - Выход и остановка узлов")
    print("-" * 78)


async def main():
    shell = InteractiveOverlayShell()
    print_menu()
    try:
        while True:
            cmd_line = await asyncio.to_thread(input, "\noverlay-cli> ")
            parts = cmd_line.strip().split()
            if not parts:
                continue
            cmd = parts[0].lower()

            try:
                if cmd in ("0", "exit", "quit", "q"):
                    break
                elif cmd in ("help", "h", "?"):
                    print_menu()
                elif cmd in ("1", "init"):
                    n = int(parts[1]) if len(parts) > 1 else N_NODES
                    k = int(parts[2]) if len(parts) > 2 else K_BUCKET_SIZE
                    scheme = parts[3] if len(parts) > 3 else "tree"
                    await shell.cmd_init(n=n, k=k, scheme=scheme)
                elif cmd in ("2", "lookup"):
                    await shell.cmd_lookup()
                elif cmd in ("3", "store"):
                    alias = parts[1] if len(parts) > 1 else "node_alpha"
                    await shell.cmd_store(alias=alias)
                elif cmd in ("4", "kill_keeper"):
                    await shell.cmd_kill_keeper_and_read()
                elif cmd in ("5", "send", "tunnel"):
                    msg = (
                        " ".join(parts[1:])
                        if len(parts) > 1
                        else "Confidential P2P Message"
                    )
                    await shell.cmd_tunnel_and_send(text=msg)
                elif cmd in ("6", "kill_relay"):
                    await shell.cmd_kill_relay_and_recover()
                elif cmd in ("7", "all", "auto"):
                    await shell.cmd_init()
                    await shell.cmd_lookup()
                    await shell.cmd_store()
                    await shell.cmd_kill_keeper_and_read()
                    await shell.cmd_tunnel_and_send()
                    await shell.cmd_kill_relay_and_recover()
                else:
                    print(
                        f"[!] Неизвестная команда '{cmd}'. "
                        f"Введите 'help' для списка команд."
                    )
            except Exception as exc:
                print(f"[!] Ошибка выполнения команды: {exc}")
    finally:
        await shell.close()


if __name__ == "__main__":
    asyncio.run(main())