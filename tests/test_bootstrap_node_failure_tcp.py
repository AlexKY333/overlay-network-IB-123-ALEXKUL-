import asyncio
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from bootstrap import DHTBootstrapper
from bootstrap_topology import BootstrapTopology
from config import ALPHA, K_BUCKET_SIZE, N_NODES, NETWORK_TIMEOUT, REPLICATION_FACTOR
from contact import Contact, node_id_to_int
from dht_messages import FindValueRequest, FindValueResponse, NodeRecord
from dht_storage import DHTStorage
from dispatcher import Dispatcher
from identity import Identity
from lookup import IterativeLookup
from message_types import MessageType
from protocol import Frame
from routing_table import RoutingTable
from transport import Connection


class SimpleTCPNode:
    def __init__(self, index: int, state_dir: Path, k_size: int = K_BUCKET_SIZE):
        self.index = index
        self.identity = Identity(state_dir)
        self.routing_table = RoutingTable(self.identity.node_id)
        for bucket in self.routing_table.buckets:
            if hasattr(bucket, "k"):
                bucket.k = k_size
            elif hasattr(bucket, "capacity"):
                bucket.capacity = k_size
            elif hasattr(bucket, "max_size"):
                bucket.max_size = k_size
        self.storage = DHTStorage()
        self.dispatcher = Dispatcher(
            routing_table=self.routing_table,
            storage=self.storage,
        )
        self.server = None
        self.port = 0

    @property
    def node_id(self) -> str:
        return self.identity.node_id

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
        self.port = self.server.sockets[0].getsockname()[1]

    async def stop(self):
        if self.server is not None:
            self.server.close()
            await self.server.wait_closed()
            self.server = None


async def test_dht_works_after_bootstrap_node_shutdown():
    """
    Критерий невырожденности DHT (Раздел 6 ТЗ):
    После отключения корневого bootstrap-узла ранее присоединившиеся узлы
    продолжают успешно выполнять FIND_NODE (для отсутствующей цели через
    промежуточные узлы) и STORE/FIND_VALUE по сети TCP.
    """
    tmp_dir = Path(tempfile.mkdtemp(prefix="test_bootstrap_shutdown_"))
    nodes: list[SimpleTCPNode] = []

    try:
        n_nodes = N_NODES
        for i in range(n_nodes):
            node = SimpleTCPNode(i, tmp_dir / f"node_{i}", k_size=K_BUCKET_SIZE)
            await node.start()
            nodes.append(node)

        node_ids = [nd.node_id for nd in nodes]
        node_by_id = {nd.node_id: nd for nd in nodes}
        contacts = {nd.node_id: nd.contact() for nd in nodes}

        # Строим дерево bootstrap с корневым сидом Node #0 (как в interactive_cli / bootstrap_experiment)
        edges = BootstrapTopology(node_ids).build(scheme="tree")
        frontier = {nd.node_id: [] for nd in nodes}
        for edge in edges:
            frontier[edge.source].append(contacts[edge.target])
            try:
                node_by_id[edge.target].routing_table.add_contact(contacts[edge.source])
            except ValueError:
                pass

        queried = {nd.node_id: set() for nd in nodes}
        for _ in range(2):
            next_f = {nd.node_id: [] for nd in nodes}
            for nd in nodes:
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
                        node_by_id[c.node_id].routing_table.add_contact(contacts[nd.node_id])
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

        seed = nodes[0]
        peers = nodes[1:]

        # Проверяем невырожденность таблиц (< N - 1 у не менее 80% узлов)
        non_full_count = sum(
            1 for nd in peers if len(nd.routing_table.get_contacts()) < n_nodes - 1
        )
        assert non_full_count / len(peers) >= 0.8

        # === ШАГ 1: АВАРИЙНО ОТКЛЮЧАЕМ КОРНЕВОЙ BOOTSTRAP-УЗЕЛ (Node #0) ===
        seed_port = seed.port
        await seed.stop()

        seed_unreachable = False
        try:
            _, w = await asyncio.wait_for(
                asyncio.open_connection("127.0.0.1", seed_port),
                timeout=0.35,
            )
            w.close()
            await w.wait_closed()
        except (OSError, asyncio.TimeoutError, TimeoutError):
            seed_unreachable = True
        assert seed_unreachable, "Bootstrap-узел должен быть полностью остановлен!"

        # === ШАГ 2: FIND_NODE ДЛЯ ОТСУТСТВУЮЩЕЙ ЦЕЛИ ПОСЛЕ СМЕРТИ SEED ===
        find_node_passed = False
        for initiator in peers:
            known_ids = {c.node_id for c in initiator.routing_table.get_contacts()}
            absent_targets = [
                nd
                for nd in peers
                if nd.node_id != initiator.node_id and nd.node_id not in known_ids
            ]
            for target in absent_targets:
                lookup = IterativeLookup(
                    target_node_id=target.node_id,
                    contacts=initiator.routing_table.get_contacts(),
                    alpha=ALPHA,
                    initiator_node_id=initiator.node_id,
                )
                await lookup.lookup_tcp(timeout=0.35)
                if lookup.target_found and lookup.target_contact is not None:
                    find_node_passed = True
                    print(
                        f"\n[OK] FIND_NODE после отключения bootstrap-узла Node #0: "
                        f"Node #{initiator.index} нашёл отсутствующего Node #{target.index} "
                        f"(раундов={lookup.round_count}, RPC={lookup.rpc_count})"
                    )
                    break
            if find_node_passed:
                break

        assert find_node_passed, "FIND_NODE не сработал после отключения bootstrap-узла!"

        # === ШАГ 3: STORE И FIND_VALUE ПОСЛЕ СМЕРТИ SEED ===
        owner = peers[0]
        reader_node = peers[-1]
        now = int(time.time())
        record = NodeRecord.create_signed(
            identity=owner.identity,
            addresses=[f"127.0.0.1:{owner.port}"],
            sequence_number=1,
            issued_at=now,
            expires_at=now + 240,
            alias="post_seed_service",
        )

        # Соседний ключ (XOR 1) обеспечивает полную сходимость IterativeLookup
        # к ближайшим живым хранителям без досрочной остановки на самом owner
        convergence_key = f"{node_id_to_int(owner.node_id) ^ 1:064x}"

        store_lookup = IterativeLookup(
            target_node_id=convergence_key,
            contacts=owner.routing_table.get_contacts(),
            alpha=ALPHA,
            initiator_node_id=owner.node_id,
        )
        await store_lookup.lookup_tcp(timeout=0.35)

        live_store_candidates = [
            c.contact
            for c in store_lookup.candidates
            if c.responded and c.contact.node_id not in (seed.node_id, owner.node_id)
        ]
        live_store_candidates.sort(
            key=lambda c: node_id_to_int(c.node_id) ^ node_id_to_int(owner.node_id)
        )
        keepers = live_store_candidates[:REPLICATION_FACTOR]
        assert len(keepers) >= 2, "Недостаточно живых хранителей для кворума!"

        acks = 0
        for keeper in keepers:
            try:
                r, w = await asyncio.wait_for(
                    asyncio.open_connection(keeper.host, keeper.port),
                    timeout=0.5,
                )
                conn = Connection(r, w)
                await conn.send_frame(
                    Frame(message_type=MessageType.STORE_REQUEST, payload=record.encode())
                )
                resp = await conn.receive_frame(timeout=0.5)
                await conn.close()
                if resp.message_type == MessageType.STORE_RESPONSE:
                    acks += 1
            except (OSError, asyncio.TimeoutError, TimeoutError):
                continue

        assert acks >= 2, f"Кворум STORE не достигнут: {acks}/{len(keepers)}"

        # Другой узел ищет ближайших живых хранителей через DHT (при выключенном seed)
        # и читает запись запросом FIND_VALUE_REQUEST
        read_lookup = IterativeLookup(
            target_node_id=convergence_key,
            contacts=reader_node.routing_table.get_contacts(),
            alpha=ALPHA,
            initiator_node_id=reader_node.node_id,
        )
        await read_lookup.lookup_tcp(timeout=0.35)

        live_read_candidates = [
            c.contact
            for c in read_lookup.candidates
            if c.responded and c.contact.node_id != seed.node_id
        ]
        live_read_candidates.sort(
            key=lambda c: node_id_to_int(c.node_id) ^ node_id_to_int(owner.node_id)
        )

        found_record = None
        for cand in live_read_candidates[: REPLICATION_FACTOR + 2]:
            try:
                r, w = await asyncio.wait_for(
                    asyncio.open_connection(cand.host, cand.port),
                    timeout=0.5,
                )
                conn = Connection(r, w)
                req = FindValueRequest(owner.node_id)
                await conn.send_frame(
                    Frame(
                        message_type=MessageType.FIND_VALUE_REQUEST,
                        payload=req.encode(),
                    )
                )
                resp_frame = await conn.receive_frame(timeout=0.5)
                await conn.close()
                resp = FindValueResponse.decode(resp_frame.payload)
                if resp.record is not None:
                    found_record = resp.record
                    break
            except (OSError, asyncio.TimeoutError, TimeoutError):
                continue

        assert found_record is not None, "FIND_VALUE не нашёл запись после отключения seed!"
        assert found_record.verify_signature() is True
        assert found_record.node_id == owner.node_id
        assert found_record.alias == "post_seed_service"
        print(
            f"[OK] FIND_VALUE после отключения bootstrap-узла Node #0: "
            f"запись alias='{found_record.alias}' прочитана и верифицирована по Ed25519 "
            f"(кворум STORE={acks}/{len(keepers)})"
        )

    finally:
        await asyncio.gather(*[nd.stop() for nd in nodes], return_exceptions=True)
        shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    asyncio.run(test_dht_works_after_bootstrap_node_shutdown())