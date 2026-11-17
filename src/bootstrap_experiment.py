import asyncio
import random
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from bootstrap import DHTBootstrapper
from bootstrap_topology import BootstrapTopology
from config import ALPHA, N_NODES, NETWORK_TIMEOUT
from contact import Contact, node_id_to_int
from dht_messages import FindNodeRequest, FindNodeResponse
from dispatcher import Dispatcher
from identity import Identity
from lookup import IterativeLookup
from message_types import MessageType
from protocol import Frame
from routing_table import RoutingTable
from transport import Connection


@dataclass
class BootstrapNode:
    identity: Identity
    routing_table: RoutingTable
    dispatcher: Dispatcher
    server: asyncio.AbstractServer | None = None

    @property
    def node_id(self) -> str:
        return self.identity.node_id

    @property
    def port(self) -> int:
        if self.server is None:
            raise RuntimeError("Server is not started")
        return self.server.sockets[0].getsockname()[1]

    async def start(self) -> None:
        async def handle_client(reader, writer):
            connection = Connection(reader, writer)
            try:
                frame = await connection.receive_frame(timeout=NETWORK_TIMEOUT)
                response = await self.dispatcher.dispatch(frame)
                await connection.send_frame(response)
            finally:
                writer.close()
                try:
                    await writer.wait_closed()
                except Exception:
                    pass

        self.server = await asyncio.start_server(handle_client, "127.0.0.1", 0)

    async def stop(self) -> None:
        if self.server is None:
            return
        self.server.close()
        await self.server.wait_closed()
        self.server = None


async def create_node(identity_path: Path) -> BootstrapNode:
    identity = Identity(identity_path)
    routing_table = RoutingTable(identity.node_id)
    dispatcher = Dispatcher(routing_table=routing_table)
    node = BootstrapNode(
        identity=identity,
        routing_table=routing_table,
        dispatcher=dispatcher,
    )
    await node.start()
    return node


async def check_lookup(initiator: BootstrapNode, target_id: str) -> bool:
    """
    Чистая read-only проверка тестового оркестратора (Раздел 15.1 ТЗ).
    Не изменяет таблицы маршрутизации узлов.
    """
    init_contacts = list(initiator.routing_table.get_contacts())
    if not init_contacts:
        return False

    if any(c.node_id == target_id for c in init_contacts):
        return True

    lookup = IterativeLookup(
        target_node_id=target_id,
        contacts=init_contacts,
        alpha=ALPHA,
        initiator_node_id=initiator.node_id,
    )
    try:
        closest = await asyncio.wait_for(
            lookup.lookup_tcp(timeout=NETWORK_TIMEOUT), timeout=3.0
        )
        return lookup.target_found or any(c.node_id == target_id for c in closest)
    except Exception:
        return False


async def evaluate_orchestrator_lookups(
    nodes: list[BootstrapNode],
    probe_set: list[tuple[int, str]],
) -> float:
    if not probe_set:
        return 1.0

    tasks = [
        check_lookup(nodes[init_idx], target_id)
        for init_idx, target_id in probe_set
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    success_count = sum(1 for res in results if res is True)
    return success_count / len(probe_set)


async def refresh_bucket_target(
    node: BootstrapNode,
    contact: Contact,
    target_node_id: str,
    timeout: float,
) -> int:
    """
    Стандартный запрос Kademlia FIND_NODE для обновления конкретного диапазона k-bucket.
    Все контакты добавляются строго через штатный routing_table.add_contact() без вытеснения.
    """
    writer = None
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(contact.host, contact.port),
            timeout=timeout,
        )
        conn = Connection(reader, writer)
        req = FindNodeRequest(target_node_id=target_node_id)
        frame = Frame(
            message_type=MessageType.FIND_NODE_REQUEST,
            payload=req.encode(),
        )
        await conn.send_frame(frame)
        resp_frame = await conn.receive_frame(timeout=timeout)
        if resp_frame.message_type != MessageType.FIND_NODE_RESPONSE:
            return 0

        resp = FindNodeResponse.decode(resp_frame.payload)
        existing_ids = {c.node_id for c in node.routing_table.get_contacts()}
        added = 0
        for c in resp.contacts:
            if c.node_id == node.node_id or c.node_id in existing_ids:
                continue
            try:
                node.routing_table.add_contact(c)
                existing_ids.add(c.node_id)
                added += 1
            except ValueError:
                continue
        return added
    except Exception:
        return 0
    finally:
        if writer is not None:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass


def extract_non_empty_buckets(routing_table: RoutingTable) -> dict[str, list[str]]:
    """Возвращает содержимое непустых k-bucket (Раздел 10.1 ТЗ)."""
    distribution: dict[str, list[str]] = {}
    for idx, bucket in enumerate(routing_table.buckets):
        contacts = bucket.get_contacts()
        if contacts:
            distribution[f"bucket_{idx}"] = [c.node_id[:16] for c in contacts]
    return distribution


async def run_scheme(
    scheme: str,
    node_count: int,
    seeds: list[int] | None = None,
    max_rounds: int = 100,
    identity_paths: list[Path] | None = None,
    probe_set: list[tuple[int, str]] | None = None,
) -> dict:
    own_temp_directory = identity_paths is None
    temp_directory = None

    if own_temp_directory:
        temp_directory = tempfile.TemporaryDirectory()
        root = Path(temp_directory.name)
        identity_paths = [root / f"node_{index}" for index in range(node_count)]
    else:
        identity_paths = list(identity_paths)
        if len(identity_paths) != node_count:
            raise ValueError("identity_paths count must match node_count")

    nodes: list[BootstrapNode] = []

    try:
        for identity_path in identity_paths:
            node = await create_node(identity_path)
            nodes.append(node)

        node_ids = [node.node_id for node in nodes]
        topology = BootstrapTopology(node_ids)

        topology_seeds = None
        if seeds is not None:
            topology_seeds = [nodes[index].node_id for index in seeds]

        edges = topology.build(scheme=scheme, seeds=topology_seeds)

        contacts = {
            node.node_id: Contact(
                node_id=node.node_id,
                host="127.0.0.1",
                port=node.port,
            )
            for node in nodes
        }

        bootstrap_contacts: dict[str, list[Contact]] = {
            node.node_id: [] for node in nodes
        }
        node_by_id = {node.node_id: node for node in nodes}

        # В схеме multi_seed точки входа (сиды) изначально знают друг друга
        if scheme == "multi_seed" and topology_seeds and len(topology_seeds) >= 2:
            s0_id = topology_seeds[0]
            s1_id = topology_seeds[1]
            c0 = contacts[s0_id]
            c1 = contacts[s1_id]
            bootstrap_contacts[s0_id].append(c1)
            bootstrap_contacts[s1_id].append(c0)
            try:
                node_by_id[s0_id].routing_table.add_contact(c1)
                node_by_id[s1_id].routing_table.add_contact(c0)
            except ValueError:
                pass

        for edge in edges:
            source_contact = contacts[edge.source]
            target_contact = contacts[edge.target]

            bootstrap_contacts[edge.source].append(target_contact)
            target_node = node_by_id[edge.target]
            source_node = node_by_id[edge.source]

            try:
                target_node.routing_table.add_contact(source_contact)
            except ValueError:
                pass
            try:
                source_node.routing_table.add_contact(target_contact)
            except ValueError:
                pass

        queried: dict[str, set[str]] = {node.node_id: set() for node in nodes}
        frontier: dict[str, list[Contact]] = {
            node.node_id: list(bootstrap_contacts[node.node_id])
            for node in nodes
        }

        if probe_set is None:
            probe_set = []
            for i, node in enumerate(nodes):
                other_ids = [n.node_id for n in nodes if n.node_id != node.node_id]
                if other_ids:
                    probe_set.append((i, random.choice(other_ids)))

        total_discovered = 0
        total_rpc = 0
        rounds = 0

        prev_total_contacts = None
        consecutive_stable_rounds = 0
        operational_converged = False
        last_success_rate = 0.0
        last_contacts_delta = 1.0

        start_time = time.perf_counter()

        while rounds < max_rounds:
            rounds += 1
            round_discovered = 0
            round_rpc = 0
            active_work = False

            next_frontier: dict[str, list[Contact]] = {
                node.node_id: [] for node in nodes
            }

            # 1. Штатный опрос новых контактов из frontier (FIND_NODE(self))
            for node in nodes:
                node_id = node.node_id
                current_frontier = frontier[node_id]
                if not current_frontier:
                    continue

                contacts_to_query = [
                    c
                    for c in current_frontier
                    if c.node_id != node_id and c.node_id not in queried[node_id]
                ]

                if not contacts_to_query:
                    continue

                active_work = True
                sender_contact = contacts[node_id]

                for contact in contacts_to_query:
                    queried[node_id].add(contact.node_id)
                    remote_node = node_by_id.get(contact.node_id)
                    if remote_node is not None:
                        try:
                            remote_node.routing_table.add_contact(sender_contact)
                        except ValueError:
                            pass

                round_rpc += len(contacts_to_query)

                before_ids = {c.node_id for c in node.routing_table.get_contacts()}
                bootstrapper = DHTBootstrapper(routing_table=node.routing_table)

                discovered = await bootstrapper.bootstrap(
                    contacts=contacts_to_query,
                    timeout=NETWORK_TIMEOUT,
                )
                round_discovered += discovered

                after_contacts = node.routing_table.get_contacts()
                after_ids = {c.node_id for c in after_contacts}
                new_ids = after_ids - before_ids - queried[node_id]

                for contact in after_contacts:
                    if contact.node_id in new_ids:
                        next_frontier[node_id].append(contact)

            # 2. Канонический Kademlia bucket refresh:
            # каждый узел обновляет один из своих старших бакетов (252..255),
            # запрашивая цель на расстоянии 2^b_idx от своего NodeID (Раздел 10.1 ТЗ)
            bucket_idx = 255 - ((rounds - 1) % 4)
            for node in nodes:
                known_peers = node.routing_table.get_contacts()
                if not known_peers:
                    continue
                peer = known_peers[(rounds - 1) % len(known_peers)]
                target_int = node_id_to_int(node.node_id) ^ (1 << bucket_idx)
                target_hex = f"{target_int:064x}"

                before_ids = {c.node_id for c in node.routing_table.get_contacts()}
                added = await refresh_bucket_target(
                    node=node,
                    contact=peer,
                    target_node_id=target_hex,
                    timeout=NETWORK_TIMEOUT,
                )
                round_rpc += 1
                round_discovered += added

                remote_node = node_by_id.get(peer.node_id)
                if remote_node is not None:
                    try:
                        remote_node.routing_table.add_contact(contacts[node.node_id])
                    except ValueError:
                        pass

                if added > 0:
                    active_work = True
                    for c in node.routing_table.get_contacts():
                        if c.node_id not in before_ids and c.node_id not in queried[node.node_id]:
                            next_frontier[node.node_id].append(c)

            total_rpc += round_rpc
            total_discovered += round_discovered
            frontier = next_frontier

            # 3. Контроль операционной сходимости тестовым оркестратором (Раздел 15.1 ТЗ)
            current_total_contacts = sum(
                len(n.routing_table.get_contacts()) for n in nodes
            )
            if prev_total_contacts is not None and prev_total_contacts > 0:
                contacts_delta = (
                    abs(current_total_contacts - prev_total_contacts)
                    / prev_total_contacts
                )
            else:
                contacts_delta = 1.0

            prev_total_contacts = current_total_contacts
            last_contacts_delta = contacts_delta

            success_rate = await evaluate_orchestrator_lookups(nodes, probe_set)
            last_success_rate = success_rate

            if success_rate >= 0.95 and contacts_delta <= 0.10:
                consecutive_stable_rounds += 1
            else:
                consecutive_stable_rounds = 0

            if consecutive_stable_rounds >= 2:
                operational_converged = True
                break

            if not active_work and rounds >= 6 and consecutive_stable_rounds == 0:
                break

        convergence_time = time.perf_counter() - start_time

        contact_counts = [len(node.routing_table.get_contacts()) for node in nodes]
        min_contacts = min(contact_counts)
        max_contacts = max(contact_counts)
        average_contacts = sum(contact_counts) / len(contact_counts)
        non_full_nodes = sum(1 for count in contact_counts if count < node_count - 1)
        non_full_fraction = non_full_nodes / node_count

        non_empty_bucket_counts = [
            sum(1 for b in node.routing_table.buckets if len(b) > 0)
            for node in nodes
        ]
        sample_buckets = extract_non_empty_buckets(nodes[-1].routing_table)

        return {
            "scheme": scheme,
            "node_count": node_count,
            "node_ids": [node.node_id for node in nodes],
            "rounds": rounds,
            "total_discovered": total_discovered,
            "total_rpc": total_rpc,
            "convergence_time": convergence_time,
            "average_contacts": average_contacts,
            "min_contacts": min_contacts,
            "max_contacts": max_contacts,
            "non_full_nodes": non_full_nodes,
            "non_full_fraction": non_full_fraction,
            "avg_non_empty_buckets": sum(non_empty_bucket_counts)
            / len(non_empty_bucket_counts),
            "sample_node_bucket_contents": sample_buckets,
            "converged": operational_converged,
            "operational_converged": operational_converged,
            "final_lookup_success_rate": round(last_success_rate, 4),
            "final_contacts_delta": round(last_contacts_delta, 4),
        }

    finally:
        await asyncio.gather(*[node.stop() for node in nodes], return_exceptions=True)
        if temp_directory is not None:
            temp_directory.cleanup()


async def run_bootstrap_experiment(
    node_count: int = N_NODES,
    trials: int = 10,
) -> list[dict]:
    results = []
    mid_seed = max(1, node_count // 2)
    schemes = [
        ("star", None),
        ("ring", None),
        ("tree", None),
        ("multi_seed", [0, mid_seed]),
    ]

    for trial in range(1, trials + 1):
        print(f"\n========== TRIAL {trial}/{trials} ==========")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            identity_paths = [root / f"node_{index}" for index in range(node_count)]
            identities = [Identity(path) for path in identity_paths]
            node_ids = [identity.node_id for identity in identities]

            probe_set = []
            for i, nid in enumerate(node_ids):
                other_ids = [o for o in node_ids if o != nid]
                if other_ids:
                    probe_set.append((i, random.choice(other_ids)))

            for scheme, seeds in schemes:
                print(f"\n--- {scheme.upper()} ---")
                result = await run_scheme(
                    scheme=scheme,
                    node_count=node_count,
                    seeds=seeds,
                    identity_paths=identity_paths,
                    probe_set=probe_set,
                )
                result["trial"] = trial
                results.append(result)

                print(f"Time: {result['convergence_time']:.4f}s")
                print(f"RPC: {result['total_rpc']}")
                print(f"Average contacts: {result['average_contacts']:.3f}")
                print(f"Non-full fraction: {result['non_full_fraction']:.3f}")
                print(
                    f"Operational Converged: {result['operational_converged']} "
                    f"(Lookup: {result['final_lookup_success_rate']*100:.1f}%, "
                    f"Delta: {result['final_contacts_delta']*100:.1f}%)"
                )

    return results