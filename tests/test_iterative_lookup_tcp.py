from pathlib import Path
import sys
import asyncio

sys.path.insert(
    0,
    str(Path(__file__).resolve().parent.parent / "src")
)

from contact import Contact, xor_distance
from dht_messages import FindNodeRequest, FindNodeResponse
from lookup import IterativeLookup


def make_node_id(value: int) -> str:
    return f"{value:064x}"


async def start_node_server(
    routing_table,
    host,
    port
):
    from dispatcher import Dispatcher

    dispatcher = Dispatcher(routing_table)

    server = await asyncio.start_server(
        lambda reader, writer: handle_client(
            reader,
            writer,
            dispatcher
        ),
        host,
        port
    )

    return server


async def start_node(
    node_id,
    contacts
):
    from routing_table import RoutingTable

    routing_table = RoutingTable(node_id)

    for contact in contacts:
        routing_table.add_contact(contact)

    server = await start_node_server(
        routing_table,
        "127.0.0.1",
        0
    )

    port = server.sockets[0].getsockname()[1]

    return server, port


async def handle_client(
    reader,
    writer,
    dispatcher
):
    from transport import Connection

    connection = Connection(
        reader,
        writer
    )

    try:
        while True:
            frame = await connection.receive_frame(
                timeout=5.0
            )

            response = await dispatcher.dispatch(
                frame
            )

            await connection.send_frame(
                response
            )

    except (
        asyncio.IncompleteReadError,
        asyncio.TimeoutError,
        ConnectionError
    ):
        pass

    finally:
        await connection.close()


async def find_node(
    contact,
    target_node_id
):
    from transport import Connection
    from protocol import Frame
    from message_types import MessageType

    reader, writer = await asyncio.open_connection(
        contact.host,
        contact.port
    )

    connection = Connection(
        reader,
        writer
    )

    request = FindNodeRequest(
        target_node_id=target_node_id
    )

    frame = Frame(
        message_type=MessageType.FIND_NODE_REQUEST,
        payload=request.encode()
    )

    try:
        await connection.send_frame(
            frame
        )

        response_frame = await connection.receive_frame(
            timeout=2.0
        )

        assert (
            response_frame.message_type
            == MessageType.FIND_NODE_RESPONSE
        )

        response = FindNodeResponse.decode(
            response_frame.payload
        )

        return response.contacts

    finally:
        await connection.close()


async def test_iterative_find_node_over_tcp():
    print("\n" + "=" * 70)
    print("DEMO: ITERATIVE LOOKUP OVER TCP (WEEKS 3-4 MILESTONE)")
    print("=" * 70)

    # ============================================================
    # Целевой узел
    # ============================================================
    target_node_id = make_node_id(50)
    print(f"  [*] Target NodeID to find:  ...{target_node_id[-8:]} (int: 50)")

    # ============================================================
    # Node C (знает о Target)
    # ============================================================
    node_c_id = make_node_id(4)
    node_c_contacts = [
        Contact(
            node_id=target_node_id,
            host="127.0.0.1",
            port=0,
        ),
    ]

    server_c, port_c = await start_node(
        node_c_id,
        node_c_contacts,
    )
    print(f"  [+] Node C started on port {port_c} (knows Target)")

    # ============================================================
    # Node B (знает о Node C)
    # ============================================================
    node_b_id = make_node_id(2)
    node_b_contacts = [
        Contact(
            node_id=node_c_id,
            host="127.0.0.1",
            port=port_c,
        ),
    ]

    server_b, port_b = await start_node(
        node_b_id,
        node_b_contacts,
    )
    print(f"  [+] Node B started on port {port_b} (knows Node C)")

    # ============================================================
    # Node A (знает ТОЛЬКО Node B)
    # ============================================================
    node_a_id = make_node_id(1)
    initial_contacts = [
        Contact(
            node_id=node_b_id,
            host="127.0.0.1",
            port=port_b,
        ),
    ]
    print(f"  [+] Initiator Node A started (knows ONLY Node B)")
    print(f"      Initial knowledge: Target is ABSENT from Node A's table.")

    try:
        lookup = IterativeLookup(
            target_node_id=target_node_id,
            contacts=initial_contacts,
            alpha=3,
        )

        # ========================================================
        # Первый раунд: Node A -> Node B
        # ========================================================
        print("\n  --- ROUND 1: Querying immediate neighbors ---")
        batch = lookup.next_batch()
        assert len(batch) == 1

        for candidate in batch:
            print(f"  -> Sending FIND_NODE to Node B (...{candidate.contact.node_id[-8:]}) on port {candidate.contact.port}")
            contacts = await find_node(
                candidate.contact,
                target_node_id,
            )
            lookup.mark_responded(candidate.contact.node_id)
            lookup.add_contacts(contacts)

            print(f"  <- Node B replied with {len(contacts)} contact(s):")
            for c in contacts:
                print(f"     * Discovered: ...{c.node_id[-8:]} on port {c.port}")

        assert any(
            candidate.contact.node_id == node_c_id
            for candidate in lookup.candidates
        )
        print("  [+] Candidate queue updated: Node C discovered!")

        # ========================================================
        # Второй раунд: Node A -> Node C
        # ========================================================
        print("\n  --- ROUND 2: Querying intermediate Node C ---")
        batch = lookup.next_batch()
        assert len(batch) == 1

        for candidate in batch:
            print(f"  -> Sending FIND_NODE to Node C (...{candidate.contact.node_id[-8:]}) on port {candidate.contact.port}")
            contacts = await find_node(
                candidate.contact,
                target_node_id,
            )
            lookup.mark_responded(candidate.contact.node_id)
            lookup.add_contacts(contacts)

            print(f"  <- Node C replied with {len(contacts)} contact(s):")
            for c in contacts:
                print(f"     * Discovered: ...{c.node_id[-8:]}")

        # ========================================================
        # Проверяем итоговый результат
        # ========================================================
        assert lookup.target_found is True
        assert lookup.target_contact is not None
        assert lookup.target_contact.node_id == target_node_id

        result = lookup.closest()
        assert any(
            contact.node_id == target_node_id
            for contact in result
        )

        print("\n" + "-" * 70)
        print(f"  [SUCCESS] Target found in 2 rounds via intermediate hops!")
        print(f"  Hops chain:     Node A -> Node B (port {port_b}) -> Node C (port {port_c}) -> Target")
        print(f"  Target NodeID:  ...{lookup.target_contact.node_id[-8:]}")
        print(f"  Target Found:   {lookup.target_found}")
        print("  -> Weeks 3-4 Milestone criterion: PASS")
        print("-" * 70)

    finally:
        server_b.close()
        server_c.close()
        await server_b.wait_closed()
        await server_c.wait_closed()


if __name__ == "__main__":
    asyncio.run(test_iterative_find_node_over_tcp())