import asyncio

from contact import Contact
from dht_messages import FindNodeRequest
from dht_messages import FindNodeResponse
from message_types import MessageType
from protocol import Frame
from routing_table import RoutingTable
from transport import Connection
from config import NETWORK_TIMEOUT, REFRESH_INTERVAL

class DHTRefreshService:
    def __init__(
        self,
        routing_table: RoutingTable,
        interval: float = REFRESH_INTERVAL,
    ):
        if interval <= 0:
            raise ValueError(
                "Refresh interval must be greater than 0"
            )

        self.routing_table = routing_table
        self.interval = interval

        self._task: asyncio.Task | None = None
        self._running = False

    @property
    def running(self) -> bool:
        return self._running

    async def refresh_once(
        self,
        timeout: float = NETWORK_TIMEOUT,
    ) -> int:
        """
        Performs one routing-table refresh cycle.

        Each non-empty bucket is refreshed by querying
        one contact from that bucket.

        Returns the number of newly discovered contacts.
        """

        discovered = 0

        for index in range(
            len(self.routing_table.buckets)
        ):
            bucket = (
                self.routing_table.get_bucket(index)
            )

            contacts = bucket.get_contacts()

            if not contacts:
                continue

            contact = contacts[0]

            discovered += await self._query_contact(
                contact=contact,
                timeout=timeout,
            )

        return discovered

    async def _query_contact(
        self,
        contact: Contact,
        timeout: float,
    ) -> int:
        """
        Sends FIND_NODE to one existing contact.
        """

        if (
            contact.node_id
            == self.routing_table.local_node_id
        ):
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

            await connection.send_frame(frame)

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

            existing_ids = {
                existing.node_id
                for existing
                in self.routing_table.get_contacts()
            }

            for discovered_contact in response.contacts:
                if (
                    discovered_contact.node_id
                    == self.routing_table.local_node_id
                ):
                    continue

                if (
                    discovered_contact.node_id
                    in existing_ids
                ):
                    continue

                try:
                    self.routing_table.add_contact(
                        discovered_contact
                    )

                    existing_ids.add(
                        discovered_contact.node_id
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

    async def _run(self):
        self._running = True

        try:
            while True:
                await self.refresh_once()

                await asyncio.sleep(
                    self.interval
                )

        except asyncio.CancelledError:
            raise

        finally:
            self._running = False

    def start(self) -> None:
        """
        Starts background routing-table refresh.
        """

        if self._task is not None:
            if not self._task.done():
                return

        self._task = asyncio.create_task(
            self._run()
        )

    async def stop(self) -> None:
        """
        Stops background routing-table refresh.
        """

        if self._task is None:
            return

        if self._task.done():
            self._task = None
            self._running = False
            return

        self._task.cancel()

        try:
            await self._task
        except asyncio.CancelledError:
            pass

        self._task = None
        self._running = False