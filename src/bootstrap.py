import asyncio

from contact import Contact
from dht_messages import FindNodeRequest
from dht_messages import FindNodeResponse
from message_types import MessageType
from protocol import Frame
from routing_table import RoutingTable
from transport import Connection
from config import NETWORK_TIMEOUT

class DHTBootstrapper:
    def __init__(
        self,
        routing_table: RoutingTable,
    ):
        self.routing_table = routing_table

    async def bootstrap(
        self,
        contacts: list[Contact],
        timeout: float = NETWORK_TIMEOUT,
    ) -> int:
        """
        Connects to bootstrap nodes and discovers
        additional contacts through FIND_NODE.

        Returns the number of newly discovered contacts.
        """

        if not contacts:
            return 0

        results = await asyncio.gather(
            *[
                self._bootstrap_contact(
                    contact=contact,
                    timeout=timeout,
                )
                for contact in contacts
            ],
            return_exceptions=True,
        )

        discovered = 0

        for result in results:
            if isinstance(result, int):
                discovered += result

        return discovered

    async def _bootstrap_contact(
        self,
        contact: Contact,
        timeout: float,
    ) -> int:
        """
        Performs one bootstrap exchange.

        Returns the number of newly discovered contacts.
        """

        if (
            contact.node_id
            == self.routing_table.local_node_id
        ):
            return 0

        try:
            self.routing_table.add_contact(
                contact
            )
        except ValueError:
            return 0

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

            request = FindNodeRequest(
                target_node_id=(
                    self.routing_table.local_node_id
                )
            )

            frame = Frame(
                message_type=(
                    MessageType.FIND_NODE_REQUEST
                ),
                payload=request.encode(),
            )

            await connection.send_frame(
                frame
            )

            response_frame = (
                await connection.receive_frame(
                    timeout=timeout,
                )
            )

            if (
                response_frame.message_type
                != MessageType.FIND_NODE_RESPONSE
            ):
                return 0

            response = FindNodeResponse.decode(
                response_frame.payload
            )

            discovered = 0

            for discovered_contact in response.contacts:
                if (
                    discovered_contact.node_id
                    == self.routing_table.local_node_id
                ):
                    continue

                existing_ids = {
                    existing.node_id
                    for existing
                    in self.routing_table.get_contacts()
                }

                if (
                    discovered_contact.node_id
                    in existing_ids
                ):
                    continue

                try:
                    self.routing_table.add_contact(
                        discovered_contact
                    )

                    discovered += 1

                except ValueError:
                    continue

            return discovered

        except (
            asyncio.TimeoutError,
            ConnectionError,
            OSError,
            ValueError,
        ):
            return 0

        finally:
            if writer is not None:
                writer.close()

                try:
                    await writer.wait_closed()
                except Exception:
                    pass