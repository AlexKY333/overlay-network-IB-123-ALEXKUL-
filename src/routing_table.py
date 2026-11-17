import asyncio
from datetime import datetime, timezone

from contact import Contact
from contact import node_id_to_int
from kbucket import KBucket
from protocol import Frame
from message_types import MessageType
from transport import Connection
from sybil_guard import SybilEclipseGuard
from config import K_BUCKET_SIZE, NETWORK_TIMEOUT, NODE_ID_BITS



class RoutingTable:
    def __init__(
        self,
        local_node_id: str,
        sybil_guard: SybilEclipseGuard | None = None,
    ):
        self.local_node_id = local_node_id

        self.sybil_guard = sybil_guard

        self.buckets = [
            KBucket(K_BUCKET_SIZE)
            for _ in range(NODE_ID_BITS)
        ]

    def _bucket_index(
        self,
        node_id: str,
    ) -> int:

        local_id = node_id_to_int(
            self.local_node_id
        )

        remote_id = node_id_to_int(
            node_id
        )

        distance = local_id ^ remote_id

        if distance == 0:
            raise ValueError(
                "Cannot add local node to routing table"
            )

        index = distance.bit_length() - 1

        return index

    def _check_contact_allowed(
        self,
        contact: Contact,
    ) -> None:

        if self.sybil_guard is None:
            return

        allowed, reason = (
            self.sybil_guard.check_contact(
                contact,
                self.get_contacts(),
            )
        )

        if not allowed:
            raise ValueError(
                f"Contact rejected by Sybil/Eclipse guard: "
                f"{reason}"
            )

    def add_contact(
        self,
        contact: Contact,
    ):

        if contact.node_id == self.local_node_id:
            raise ValueError(
                "Cannot add local node to routing table"
            )

        self._check_contact_allowed(
            contact
        )

        index = self._bucket_index(
            contact.node_id
        )

        self.buckets[index].add(
            contact
        )

    async def add_contact_with_ping(
            self,
            contact: Contact,
            timeout: float = NETWORK_TIMEOUT,
    ):
        """
        Добавляет контакт с проверкой старейшего
        контакта через настоящий PING по TCP.

        Если bucket заполнен:

        - PING старого контакта;
        - если отвечает PONG -> оставляем старого;
        - если не отвечает -> удаляем старого;
        - затем добавляем нового.

        Sybil/Eclipse guard проверяется до изменения
        routing table.
        """

        if contact.node_id == self.local_node_id:
            raise ValueError(
                "Cannot add local node to routing table"
            )

        self._check_contact_allowed(
            contact
        )

        index = self._bucket_index(
            contact.node_id
        )

        bucket = self.buckets[index]

        old_contact = bucket.add(
            contact
        )

        if old_contact is None:
            return None

        alive = await self._ping_contact(
            old_contact,
            timeout=timeout,
        )

        if alive:

            old_contact.last_seen = (
                datetime.now(timezone.utc)
            )

            bucket.add(
                old_contact
            )

            return old_contact

        bucket.remove(
            old_contact.node_id
        )

        bucket.add(
            contact
        )

        return None

    async def _ping_contact(
        self,
        contact: Contact,
        timeout: float,
    ) -> bool:
        """
        Отправляет настоящий PING по TCP
        и проверяет получение PONG.
        """

        try:

            reader, writer = (
                await asyncio.wait_for(
                    asyncio.open_connection(
                        contact.host,
                        contact.port,
                    ),
                    timeout=timeout,
                )
            )

            connection = Connection(
                reader,
                writer,
            )

            ping = Frame(
                message_type=MessageType.PING,
                payload=b"routing-table-ping",
            )

            await connection.send_frame(
                ping
            )

            response = (
                await connection.receive_frame(
                    timeout=timeout,
                )
            )

            await connection.close()

            return (
                response.message_type
                == MessageType.PONG
                and response.request_id
                == ping.request_id
            )

        except (
            asyncio.TimeoutError,
            ConnectionError,
            OSError,
        ):
            return False

    def remove_contact(
        self,
        node_id: str,
    ):

        index = self._bucket_index(
            node_id
        )

        self.buckets[index].remove(
            node_id
        )

    def get_bucket(
        self,
        index: int,
    ) -> KBucket:

        return self.buckets[index]

    def get_contacts(
        self,
    ) -> list[Contact]:

        contacts = []

        for bucket in self.buckets:
            contacts.extend(
                bucket.get_contacts()
            )

        return contacts

    def find_closest_nodes(
        self,
        target_node_id: str,
        count: int = K_BUCKET_SIZE,
    ) -> list[Contact]:

        contacts = self.get_contacts()

        contacts.sort(
            key=lambda contact: (
                node_id_to_int(
                    contact.node_id
                )
                ^ node_id_to_int(
                    target_node_id
                )
            )
        )

        return contacts[:count]