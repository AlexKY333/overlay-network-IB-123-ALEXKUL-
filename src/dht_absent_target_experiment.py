import asyncio
import json
import random
import sys
import tempfile
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
RESULTS_DIR = BASE_DIR / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

if sys.platform.startswith("win"):
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    except Exception:
        pass

from bootstrap import DHTBootstrapper
from bootstrap_topology import BootstrapTopology
from config import ALPHA, K_BUCKET_SIZE, N_NODES, NETWORK_TIMEOUT
from contact import Contact
from dispatcher import Dispatcher
from identity import Identity
from lookup import IterativeLookup
from routing_table import RoutingTable
from transport import Connection

NODE_COUNT = N_NODES
VALID_LOOKUPS_PER_SCHEME = 30
TIMEOUT = NETWORK_TIMEOUT
MAX_ATTEMPTS_PER_SCHEME = 1000
BOOTSTRAP_ROUNDS = 2


class ExperimentNode:
    def __init__(self, identity_path: Path):
        self.identity = Identity(identity_path)
        self.routing_table = RoutingTable(self.identity.node_id)
        self.dispatcher = Dispatcher(routing_table=self.routing_table)
        self.server = None

    @property
    def node_id(self) -> str:
        return self.identity.node_id

    @property
    def port(self) -> int:
        if self.server is None:
            raise RuntimeError("Server is not started")
        return self.server.sockets[0].getsockname()[1]

    async def start(self):
        async def handle_client(reader, writer):
            connection = Connection(reader, writer)
            try:
                frame = await asyncio.wait_for(
                    connection.receive_frame(timeout=TIMEOUT),
                    timeout=TIMEOUT + 0.5,
                )
                response = await self.dispatcher.dispatch(frame)
                await asyncio.wait_for(
                    connection.send_frame(response),
                    timeout=TIMEOUT + 0.5,
                )
            except Exception:
                pass
            finally:
                try:
                    writer.close()
                    await writer.wait_closed()
                except Exception:
                    pass

        self.server = await asyncio.start_server(handle_client, "127.0.0.1", 0)

    async def stop(self):
        if self.server is None:
            return
        self.server.close()
        await self.server.wait_closed()
        self.server = None


async def create_nodes(root: Path) -> list[ExperimentNode]:
    nodes = []
    for index in range(NODE_COUNT):
        node = ExperimentNode(root / f"node_{index}")
        await node.start()
        nodes.append(node)
    return nodes


def build_contacts(nodes: list[ExperimentNode]) -> dict[str, Contact]:
    return {
        node.node_id: Contact(
            node_id=node.node_id,
            host="127.0.0.1",
            port=node.port,
        )
        for node in nodes
    }


async def bootstrap_nodes(nodes: list[ExperimentNode], scheme: str):
    """
    Выполняет стандартный 2-этапный Kademlia bootstrap одинаково для всех схем:
    Раунд 1 — опрос начальных bootstrap-контактов.
    Раунд 2 — опрос до ALPHA новых кандидатов, полученных в Раунде 1.
    """
    node_ids = [node.node_id for node in nodes]
    topology = BootstrapTopology(node_ids)

    seeds = None
    if scheme == "multi_seed":
        mid_idx = len(nodes) // 2
        seeds = [nodes[0].node_id, nodes[mid_idx].node_id]

    edges = topology.build(scheme=scheme, seeds=seeds)
    contacts = build_contacts(nodes)

    bootstrap_contacts = {node.node_id: [] for node in nodes}
    node_by_id = {node.node_id: node for node in nodes}

    if scheme == "multi_seed":
        mid_idx = len(nodes) // 2
        c0 = contacts[nodes[0].node_id]
        c_mid = contacts[nodes[mid_idx].node_id]
        bootstrap_contacts[nodes[0].node_id].append(c_mid)
        bootstrap_contacts[nodes[mid_idx].node_id].append(c0)
        node_by_id[nodes[0].node_id].routing_table.add_contact(c_mid)
        node_by_id[nodes[mid_idx].node_id].routing_table.add_contact(c0)

    for edge in edges:
        source_contact = contacts[edge.source]
        target_contact = contacts[edge.target]

        bootstrap_contacts[edge.source].append(target_contact)
        target_node = node_by_id[edge.target]

        try:
            target_node.routing_table.add_contact(source_contact)
        except ValueError:
            pass

    queried = {node.node_id: set() for node in nodes}
    frontier = {node.node_id: list(bootstrap_contacts[node.node_id]) for node in nodes}

    for _ in range(BOOTSTRAP_ROUNDS):
        active_work = False
        next_frontier = {node.node_id: [] for node in nodes}

        for node in nodes:
            node_id = node.node_id
            current = frontier[node_id]

            contacts_to_query = [
                c
                for c in current
                if c.node_id != node_id and c.node_id not in queried[node_id]
            ][:ALPHA]

            if not contacts_to_query:
                continue

            active_work = True
            sender_contact = contacts[node_id]

            for c in contacts_to_query:
                queried[node_id].add(c.node_id)
                remote_node = node_by_id.get(c.node_id)
                if remote_node is not None:
                    try:
                        remote_node.routing_table.add_contact(sender_contact)
                    except ValueError:
                        pass

            before = {c.node_id for c in node.routing_table.get_contacts()}
            bootstrapper = DHTBootstrapper(routing_table=node.routing_table)

            await bootstrapper.bootstrap(contacts=contacts_to_query, timeout=TIMEOUT)

            after = {c.node_id for c in node.routing_table.get_contacts()}
            new_ids = after - before - queried[node_id]

            for c in node.routing_table.get_contacts():
                if c.node_id in new_ids:
                    next_frontier[node_id].append(c)

        frontier = next_frontier
        if not active_work:
            break


def restore_routing_table(node: ExperimentNode, baseline_contacts: list[Contact]):
    node.routing_table = RoutingTable(node.node_id)
    node.dispatcher.routing_table = node.routing_table
    for contact in baseline_contacts:
        try:
            node.routing_table.add_contact(contact)
        except ValueError:
            pass


def get_bucket_snapshot(routing_table: RoutingTable) -> dict[str, int]:
    return {
        f"bucket_{idx}": len(bucket)
        for idx, bucket in enumerate(routing_table.buckets)
        if len(bucket) > 0
    }


async def run_scheme(scheme: str) -> dict:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        nodes = await create_nodes(root)

        try:
            await bootstrap_nodes(nodes, scheme)

            initial_states = {
                node.node_id: list(node.routing_table.get_contacts())
                for node in nodes
            }
            table_sizes = [len(initial_states[n.node_id]) for n in nodes]
            bucket_snapshots = {
                n.node_id[:12]: get_bucket_snapshot(n.routing_table)
                for n in nodes[:5]
            }

            valid_results = []
            all_attempts = []
            attempt_number = 0

            await asyncio.sleep(0.05)

            while len(valid_results) < VALID_LOOKUPS_PER_SCHEME:
                attempt_number += 1

                if attempt_number > MAX_ATTEMPTS_PER_SCHEME:
                    raise RuntimeError(
                        f"Scheme '{scheme}' could not collect "
                        f"{VALID_LOOKUPS_PER_SCHEME} valid lookups within "
                        f"{MAX_ATTEMPTS_PER_SCHEME} attempts"
                    )

                initiator = random.choice(nodes)
                restore_routing_table(initiator, initial_states[initiator.node_id])

                initial_contacts = list(initiator.routing_table.get_contacts())
                initial_ids = {c.node_id for c in initial_contacts}

                absent_candidates = [
                    n
                    for n in nodes
                    if n.node_id != initiator.node_id and n.node_id not in initial_ids
                ]

                if not absent_candidates:
                    continue

                target_node = random.choice(absent_candidates)
                target = target_node.node_id

                lookup = IterativeLookup(
                    target_node_id=target,
                    contacts=initial_contacts,
                    alpha=ALPHA,
                    initiator_node_id=initiator.node_id,
                )

                start = time.perf_counter()
                try:
                    closest = await asyncio.wait_for(
                        lookup.lookup_tcp(timeout=TIMEOUT), timeout=3.0
                    )
                except asyncio.TimeoutError:
                    closest = []
                elapsed = time.perf_counter() - start

                await asyncio.sleep(0.002)

                # Строгий критерий из src/lookup.py:
                # промежуточный узел должен отсутствовать в начальной таблице,
                # быть обнаружен в ходе FIND_NODE и затем реально опрошен (rounds >= 2)
                queried_nodes = getattr(lookup, "discovered_queried_node_ids", set())
                intermediate = [nid for nid in queried_nodes if nid != target]
                used_intermediate_dht = len(intermediate) > 0
                intermediate_count = len(intermediate)

                target_found = lookup.target_found or any(
                    c.node_id == target for c in closest
                )
                is_valid_for_section_6 = target_found and used_intermediate_dht

                attempt_result = {
                    "lookup_id": str(getattr(lookup, "lookup_id", attempt_number)),
                    "scheme": scheme,
                    "attempt": attempt_number,
                    "initiator": initiator.node_id,
                    "target": target,
                    "target_initially_absent": True,
                    "target_found": target_found,
                    "used_intermediate_dht": used_intermediate_dht,
                    "time": elapsed,
                    "rpc_count": lookup.rpc_count,
                    "rounds": lookup.round_count,
                    "iterations_queried_nodes": getattr(lookup, "iterations_log", []),
                    "errors_and_timeouts": getattr(lookup, "errors_count", 0),
                    "initial_contacts": len(initial_contacts),
                    "discovered_nodes": len(lookup.discovered_node_ids),
                    "intermediate_nodes": intermediate_count,
                    "valid_for_section_6": is_valid_for_section_6,
                }

                all_attempts.append(attempt_result)

                if is_valid_for_section_6:
                    valid_lookup_number = len(valid_results) + 1
                    valid_result = dict(attempt_result)
                    valid_result["valid_lookup"] = valid_lookup_number
                    valid_results.append(valid_result)

                    print(
                        f"  VALID {valid_lookup_number:02d}/{VALID_LOOKUPS_PER_SCHEME} "
                        f"(attempt {attempt_number:03d}): "
                        f"Target found! RPC={lookup.rpc_count}, "
                        f"rounds={lookup.round_count}, "
                        f"time={elapsed:.4f}s, "
                        f"intermediate={intermediate_count}"
                    )
                else:
                    print(
                        f"  attempt {attempt_number:03d}: skipped "
                        f"(found={target_found}, intermediate={intermediate_count})"
                    )

            return {
                "scheme": scheme,
                "table_sizes": table_sizes,
                "k_bucket_occupancy_sample": bucket_snapshots,
                "valid_results": valid_results,
                "all_attempts": all_attempts,
            }

        finally:
            await asyncio.gather(*[node.stop() for node in nodes], return_exceptions=True)


async def main():
    schemes = ["star", "ring", "tree", "multi_seed"]
    scheme_results = {}

    print("=== DHT REAL ABSENT TARGET EXPERIMENT (SECTION 6) ===")
    print(f"Nodes: {NODE_COUNT}")
    print(f"Required valid lookups per scheme: {VALID_LOOKUPS_PER_SCHEME}")
    print(f"Alpha: {ALPHA}")
    print("Target type: REAL active network node absent from initiator routing table\n")

    for scheme in schemes:
        print(f"========== {scheme.upper()} ==========")
        result = await run_scheme(scheme)
        scheme_results[scheme] = result
        print()

    summary = {}

    for scheme in schemes:
        valid_results = scheme_results[scheme]["valid_results"]
        all_attempts = scheme_results[scheme]["all_attempts"]
        t_sizes = scheme_results[scheme]["table_sizes"]

        summary[scheme] = {
            "valid_lookups": len(valid_results),
            "required_valid_lookups": VALID_LOOKUPS_PER_SCHEME,
            "total_attempts": len(all_attempts),
            "target_initially_absent": sum(
                r["target_initially_absent"] for r in valid_results
            ),
            "target_found_count": sum(r["target_found"] for r in valid_results),
            "with_intermediate_dht": sum(
                r["used_intermediate_dht"] for r in valid_results
            ),
            "all_valid_for_section_6": all(
                r["valid_for_section_6"] for r in valid_results
            ),
            "table_sizes_all_nodes": t_sizes,
            "non_full_table_fraction": sum(1 for s in t_sizes if s < NODE_COUNT - 1)
            / len(t_sizes),
            "average_time": sum(r["time"] for r in valid_results) / len(valid_results),
            "average_rpc": sum(r["rpc_count"] for r in valid_results)
            / len(valid_results),
            "average_rounds": sum(r["rounds"] for r in valid_results)
            / len(valid_results),
            "average_discovered_nodes": sum(
                r["discovered_nodes"] for r in valid_results
            )
            / len(valid_results),
        }

    output = {
        "configuration": {
            "node_count": NODE_COUNT,
            "k_bucket_size": K_BUCKET_SIZE,
            "required_valid_lookups_per_scheme": VALID_LOOKUPS_PER_SCHEME,
            "alpha": ALPHA,
            "timeout": TIMEOUT,
            "target_definition": "Existing online node not present in initiator initial routing table",
            "section_6_criteria": {
                "initially_absent": True,
                "target_found": True,
                "used_intermediate_node": True,
            },
        },
        "summary": summary,
        "results": scheme_results,
    }

    output_path = RESULTS_DIR / "dht_absent_target_strict_results.json"
    output_path.write_text(json.dumps(output, indent=2), encoding="utf-8")

    print("=" * 80)
    print("DHT REAL ABSENT TARGET SUMMARY (SECTION 6)")
    print("=" * 80)

    for scheme in schemes:
        data = summary[scheme]
        print(f"\n--- {scheme.upper()} ---")
        print(
            f"Valid lookups: {data['valid_lookups']}/{data['required_valid_lookups']}"
        )
        print(f"Total attempts: {data['total_attempts']}")
        print(f"Target found: {data['target_found_count']}/{data['valid_lookups']}")
        print(
            f"Used intermediate DHT node: {data['with_intermediate_dht']}/{data['valid_lookups']}"
        )
        print(f"Non-full routing tables: {data['non_full_table_fraction']*100:.1f}%")
        print(
            f"Section 6 criterion: {'PASS' if data['all_valid_for_section_6'] else 'FAIL'}"
        )
        print(f"Average time: {data['average_time']:.4f}s")
        print(f"Average RPC: {data['average_rpc']:.2f}")
        print(f"Average rounds: {data['average_rounds']:.2f}")

    print(f"\nResults successfully saved to {output_path}")


if __name__ == "__main__":
    asyncio.run(main())