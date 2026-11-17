import asyncio

from contact import Contact
from dht_messages import NodeRecord
from dht_messages import StoreRequest
from dht_messages import StoreResponse
from dht_storage import DHTStorage
from message_types import MessageType
from protocol import Frame
from routing_table import RoutingTable
from transport import Connection
from config import NETWORK_TIMEOUT, REPLICATION_FACTOR, REPLICATION_QUORUM


class DHTReplicator:
    def __init__(
        self,
        routing_table: RoutingTable,
        storage: DHTStorage,
        replication_factor: int = REPLICATION_FACTOR,
        quorum: int = REPLICATION_QUORUM,
    ):
        if replication_factor < 1:
            raise ValueError(
                "Replication factor must be >= 1"
            )

        if quorum < 1:
            raise ValueError(
                "Replication quorum must be >= 1"
            )

        if quorum > replication_factor:
            raise ValueError(
                "Quorum cannot exceed replication factor"
            )

        self.routing_table = routing_table
        self.storage = storage
        self.replication_factor = replication_factor
        self.quorum = quorum

    async def replicate(
            self,
            record: NodeRecord,
            timeout: float = NETWORK_TIMEOUT,
    ) -> int:
        """
        Stores a NodeRecord on up to R nodes.

        The local node always receives one copy first.

        The remaining copies are sent to the closest
        contacts through real TCP STORE requests.

        Returns the number of successful replicas.
        """

        # Проверяем запись локально.
        self.storage.store(record)

        successful_replicas = 1

        # Нам нужно ещё R - 1 удалённых копий.
        remote_count = self.replication_factor - 1

        if remote_count <= 0:
            if successful_replicas < self.quorum:
                raise RuntimeError(
                    "Replication quorum was not reached"
                )

            return successful_replicas

        contacts = (
            self.routing_table.find_closest_nodes(
                target_node_id=record.node_id,
                count=remote_count,
            )
        )

        # Отправляем STORE параллельно.
        tasks = [
            self._store_on_contact(
                contact=contact,
                record=record,
                timeout=timeout,
            )
            for contact in contacts
        ]

        if tasks:
            results = await asyncio.gather(
                *tasks,
                return_exceptions=True,
            )

            for result in results:
                if result is True:
                    successful_replicas += 1

        if successful_replicas < self.quorum:
            raise RuntimeError(
                "Replication quorum was not reached"
            )

        return successful_replicas

    async def _store_on_contact(
        self,
        contact: Contact,
        record: NodeRecord,
        timeout: float,
    ) -> bool:
        """
        Sends a real STORE request to one remote node.

        Returns True only when the remote node confirms
        successful storage.
        """

        writer = None

        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(
                    contact.host,
                    contact.port,
                ),
                timeout=timeout,
            )

            connection = Connection(
                reader,
                writer,
            )

            request = StoreRequest(
                record=record,
            )

            frame = Frame(
                message_type=MessageType.STORE_REQUEST,
                payload=request.encode(),
            )

            await connection.send_frame(frame)

            response_frame = await connection.receive_frame(
                timeout=timeout,
            )

            if (
                response_frame.message_type
                != MessageType.STORE_RESPONSE
            ):
                return False

            response = StoreResponse.decode(
                response_frame.payload
            )

            return response.success

        except (
            asyncio.TimeoutError,
            ConnectionError,
            OSError,
            ValueError,
        ):
            return False

        finally:
            if writer is not None:
                writer.close()

                try:
                    await writer.wait_closed()
                except Exception:
                    pass