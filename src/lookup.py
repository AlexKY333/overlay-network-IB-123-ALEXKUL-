import asyncio
import time
from dataclasses import dataclass
from uuid import UUID, uuid4

from config import ALPHA, K_BUCKET_SIZE, NETWORK_TIMEOUT
from contact import Contact, xor_distance
from dht_messages import FindNodeRequest, FindNodeResponse
from message_types import MessageType
from protocol import Frame
from transport import Connection


@dataclass
class LookupCandidate:
    contact: Contact
    distance: int
    queried: bool = False
    responded: bool = False


class IterativeLookup:
    def __init__(
        self,
        target_node_id: str,
        contacts: list[Contact],
        alpha: int = ALPHA,
        initiator_node_id: str = "",
    ):
        if alpha <= 0:
            raise ValueError("Alpha must be greater than 0")

        self.lookup_id: UUID = uuid4()
        self.initiator_node_id: str = initiator_node_id
        self.target_node_id = target_node_id
        self.alpha = alpha

        self.target_found = False
        self.target_contact: Contact | None = None

        # --------------------------------------------------------
        # Метрики и журнал lookup (Раздел 10.2 ТЗ)
        # --------------------------------------------------------
        self.rpc_count = 0
        self.round_count = 0
        self.errors_count = 0
        self.duration_seconds: float = 0.0
        self.iterations_log: list[list[str]] = []

        self.queried_node_ids: set[str] = set()
        self.discovered_node_ids: set[str] = set()
        self.discovered_queried_node_ids: set[str] = set()

        self.candidates = [
            LookupCandidate(
                contact=contact,
                distance=xor_distance(
                    contact.node_id,
                    target_node_id,
                ),
            )
            for contact in contacts
            if contact.node_id != target_node_id
        ]

        self.candidates.sort(key=lambda candidate: candidate.distance)

    def next_batch(self) -> list[LookupCandidate]:
        """Возвращает до ALPHA ближайших ещё не опрошенных узлов."""
        batch = [
            candidate
            for candidate in self.candidates
            if not candidate.queried
        ]

        batch = batch[: self.alpha]

        if batch:
            round_ids = []
            for candidate in batch:
                candidate.queried = True
                self.queried_node_ids.add(candidate.contact.node_id)
                round_ids.append(candidate.contact.node_id)
            self.iterations_log.append(round_ids)

        return batch

    def add_contacts(self, contacts: list[Contact]):
        existing_ids = {
            candidate.contact.node_id for candidate in self.candidates
        }

        for contact in contacts:
            if contact.node_id == self.target_node_id:
                self.target_found = True
                self.target_contact = contact
                continue

            if contact.node_id in existing_ids:
                continue

            self.candidates.append(
                LookupCandidate(
                    contact=contact,
                    distance=xor_distance(
                        contact.node_id,
                        self.target_node_id,
                    ),
                )
            )

            existing_ids.add(contact.node_id)
            self.discovered_node_ids.add(contact.node_id)

        self.candidates.sort(key=lambda candidate: candidate.distance)

    def mark_responded(self, node_id: str):
        for candidate in self.candidates:
            if candidate.contact.node_id == node_id:
                candidate.responded = True
                return

    async def _query_contact(
        self,
        contact: Contact,
        timeout: float,
    ) -> list[Contact] | None:
        """Выполняет реальный TCP FIND_NODE. Возвращает None при тайм-ауте/ошибке."""
        writer = None

        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(
                    contact.host,
                    contact.port,
                ),
                timeout=timeout,
            )

            connection = Connection(reader, writer)
            request = FindNodeRequest(target_node_id=self.target_node_id)
            frame = Frame(
                message_type=MessageType.FIND_NODE_REQUEST,
                payload=request.encode(),
            )

            await connection.send_frame(frame)
            response_frame = await connection.receive_frame(timeout=timeout)

            if response_frame.message_type != MessageType.FIND_NODE_RESPONSE:
                self.errors_count += 1
                return None

            response = FindNodeResponse.decode(response_frame.payload)
            return response.contacts

        except (
            asyncio.TimeoutError,
            ConnectionError,
            OSError,
            ValueError,
            asyncio.IncompleteReadError,
        ):
            self.errors_count += 1
            return None

        finally:
            if writer is not None:
                writer.close()
                try:
                    await writer.wait_closed()
                except Exception:
                    pass

    async def lookup_tcp(
        self,
        timeout: float = NETWORK_TIMEOUT,
    ) -> list[Contact]:
        """Полный итеративный Kademlia-style lookup с журналированием (Раздел 10.2 ТЗ)."""
        t0 = time.perf_counter()

        try:
            while True:
                if self.target_found:
                    break

                batch = self.next_batch()
                if not batch:
                    break

                self.round_count += 1
                self.rpc_count += len(batch)

                results = await asyncio.gather(
                    *[
                        self._query_contact(
                            candidate.contact,
                            timeout,
                        )
                        for candidate in batch
                    ],
                    return_exceptions=True,
                )

                for candidate, result in zip(batch, results):
                    if isinstance(result, Exception) or result is None:
                        continue

                    self.mark_responded(candidate.contact.node_id)
                    self.add_contacts(result)

                    if self.target_found:
                        break

            self.discovered_queried_node_ids = (
                self.queried_node_ids & self.discovered_node_ids
            )

            return self.closest()

        finally:
            self.duration_seconds = time.perf_counter() - t0

    def closest(self, count: int = K_BUCKET_SIZE) -> list[Contact]:
        result = [
            candidate.contact for candidate in self.candidates[:count]
        ]

        if self.target_found and self.target_contact is not None:
            result.append(self.target_contact)

        return result[:count]

    def get_lookup_log(self) -> dict:
        """Возвращает полный журнал lookup по требованиям раздела 10.2 ТЗ."""
        return {
            "lookup_id": str(self.lookup_id),
            "initiator_node_id": self.initiator_node_id,
            "target_node_id": self.target_node_id,
            "iterations": self.iterations_log,
            "rpc_count": self.rpc_count,
            "round_count": self.round_count,
            "errors_and_timeouts": self.errors_count,
            "target_found": self.target_found,
            "duration_seconds": round(self.duration_seconds, 6),
        }