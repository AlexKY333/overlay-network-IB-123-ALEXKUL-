import asyncio
from pathlib import Path
from typing import Union

from application_message import ApplicationMessage
from contact import Contact
from dht_messages import FindValueRequest, FindValueResponse, NodeRecord
from dht_storage import DHTStorage
from encrypted_tunnel import EncryptedTunnel
from file_transfer import FileChunk, FileTransfer, FileTransferReceiver
from identity import Identity
from lookup import IterativeLookup
from message_types import MessageType
from protocol import Frame
from relay_selector import RelaySelector
from replication import DHTReplicator
from routing_table import RoutingTable
from transport import Connection
from tunnel_builder import TunnelBuilder
from tunnel_pool import TunnelPool
from config import NETWORK_TIMEOUT, TUNNEL_RELAY_COUNT


class Node:
    """
    Единый фасад узла оверлейной сети (Разделы 7, 10, 12, 13 ТЗ).

    Фасад объединяет подсистемы:
    - Identity (Ed25519, NodeID = SHA256(pk))
    - RoutingTable (k-bucket, XOR-метрика, Sybil-guard)
    - DHTStorage & DHTReplicator (R=3, sequence rollback guard)
    - IterativeLookup (ALPHA=3)
    - TunnelBuilder & TunnelPool (E2E-сессии, ретрансляция)
    - FileTransfer & FileTransferReceiver (чанкование, E2E-шифрование, SHA-256)
    """

    def __init__(
        self,
        state_dir: str | Path,
        relay_selector: RelaySelector | None = None,
    ):
        self.identity = Identity(state_dir=state_dir)
        self.node_id = self.identity.node_id

        self.routing_table = RoutingTable(local_node_id=self.node_id)
        self.storage = DHTStorage()

        self.replicator = DHTReplicator(
            routing_table=self.routing_table,
            storage=self.storage,
        )

        self.tunnel_pool = TunnelPool()
        self.relay_selector = relay_selector

        if relay_selector is not None:
            self.tunnel_builder = TunnelBuilder(
                selector=relay_selector,
                pool=self.tunnel_pool,
            )
        else:
            self.tunnel_builder = None

        # Изолированный каталог загрузок для файлового сервиса (Раздел 13.2 ТЗ)
        self.downloads_dir = self.identity.state_dir / "downloads"
        self.downloads_dir.mkdir(parents=True, exist_ok=True)
        self.file_receiver = FileTransferReceiver()

    # =========================================================================
    # DHT И МАРШРУТИЗАЦИЯ
    # =========================================================================

    async def join(
        self,
        bootstrap_contacts: list[Contact],
        timeout: float = NETWORK_TIMEOUT,
    ) -> int:
        """
        Подключает узел к сети через bootstrap-контакты с валидацией через TCP PING.
        """
        added = 0
        for contact in bootstrap_contacts:
            try:
                await self.routing_table.add_contact_with_ping(
                    contact,
                    timeout=timeout,
                )
                added += 1
            except Exception:
                continue
        return added

    async def lookup_node(
        self,
        target_node_id: str,
        timeout: float = NETWORK_TIMEOUT,
    ) -> list[Contact]:
        """
        Выполняет итеративный поиск узла (Kademlia lookup, ALPHA=3).
        """
        contacts = self.routing_table.get_contacts()
        lookup = IterativeLookup(
            target_node_id=target_node_id,
            contacts=contacts,
        )
        return await lookup.lookup_tcp(timeout=timeout)

    async def put_record(
        self,
        record: NodeRecord,
        timeout: float = NETWORK_TIMEOUT,
    ) -> int:
        """
        Публикует и реплицирует NodeRecord на R=3 ближайших узлах сети.
        """
        return await self.replicator.replicate(
            record=record,
            timeout=timeout,
        )

    async def _query_value_contact(
        self,
        contact: Contact,
        target_id: str,
        timeout: float,
    ) -> NodeRecord | None:
        """Отправляет сетевой запрос FIND_VALUE одному контакту по TCP."""
        writer = None
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(contact.host, contact.port),
                timeout=timeout,
            )
            conn = Connection(reader, writer)
            req = FindValueRequest(node_id=target_id)
            frame = Frame(
                message_type=MessageType.FIND_VALUE_REQUEST,
                payload=req.encode(),
            )
            await conn.send_frame(frame)
            resp_frame = await conn.receive_frame(timeout=timeout)

            if resp_frame.message_type == MessageType.FIND_VALUE_RESPONSE:
                resp = FindValueResponse.decode(resp_frame.payload)
                if resp.record is not None and resp.record.verify_signature():
                    return resp.record
            return None
        except Exception:
            return None
        finally:
            if writer is not None:
                writer.close()
                try:
                    await writer.wait_closed()
                except Exception:
                    pass

    async def get_record(
        self,
        node_id: str,
        timeout: float = NETWORK_TIMEOUT,
    ) -> NodeRecord | None:
        """
        Извлекает запись NodeRecord.
        Сначала проверяется локальное хранилище, при отсутствии выполняется
        сетевой опрос ближайших узлов через TCP FIND_VALUE.
        """
        local_rec = self.storage.get(node_id)
        if local_rec is not None:
            return local_rec

        # Сетевой поиск среди известных и ближайших узлов
        candidates = self.routing_table.find_closest_nodes(node_id)
        for contact in candidates:
            rec = await self._query_value_contact(contact, node_id, timeout)
            if rec is not None:
                try:
                    self.storage.store(rec)
                except Exception:
                    pass
                return rec

        # Если ближайшие узлы не вернули значение, запускаем итеративный поиск узлов
        discovered_nodes = await self.lookup_node(node_id, timeout=timeout)
        for contact in discovered_nodes:
            rec = await self._query_value_contact(contact, node_id, timeout)
            if rec is not None:
                try:
                    self.storage.store(rec)
                except Exception:
                    pass
                return rec

        return None

    async def resolve_alias(
        self,
        alias: str,
        timeout: float = NETWORK_TIMEOUT,
    ) -> NodeRecord | None:
        """
        Разрешает псевдоним (alias) в подписанную NodeRecord (Раздел 10.3 ТЗ).
        Ключ поиска: SHA-256("alias:" || normalize(alias)).
        """
        norm_alias = NodeRecord.normalize_alias(alias)
        for rec in self.storage.records.values():
            if rec.alias and NodeRecord.normalize_alias(rec.alias) == norm_alias:
                return rec

        alias_key = NodeRecord.alias_key(alias)
        return await self.get_record(alias_key, timeout=timeout)

    # =========================================================================
    # ТУННЕЛИ И ПРИКЛАДНЫЕ СЕРВИСЫ
    # =========================================================================

    def build_tunnel(
            self,
            destination_node_id: Union[str, int],
            relay_count: int = TUNNEL_RELAY_COUNT,
            strategy: str = "ranked",
    ):
        """
        Строит логический туннель через TunnelBuilder.
        Автоматически приводит 64-значные hex NodeID к int для совместимости с тестами фасада.
        """
        if self.tunnel_builder is None:
            raise RuntimeError("RelaySelector is required to build tunnels")

        # Приведение hex-строки к int для согласованности с проверками фасада
        if isinstance(self.node_id, str) and len(self.node_id) == 64:
            source_id = int(self.node_id, 16)
        else:
            source_id = self.node_id

        if isinstance(destination_node_id, str) and len(destination_node_id) == 64:
            dest_id = int(destination_node_id, 16)
        else:
            dest_id = destination_node_id

        return self.tunnel_builder.build(
            source_node_id=source_id,
            destination_node_id=dest_id,
            relay_count=relay_count,
            strategy=strategy,
        )

    def close_tunnel(self, tunnel_id: str) -> None:
        """Закрывает туннель и переводит его в состояние DEAD (Раздел 7 ТЗ)."""
        tunnel = self.tunnel_pool.get(str(tunnel_id))
        tunnel.close()

    def send_via_tunnel(
        self,
        encrypted_tunnel: EncryptedTunnel,
        message: Union[ApplicationMessage, str],
    ) -> bytes:
        """
        Шифрует текстовое прикладное сообщение через EncryptedTunnel.
        """
        if not isinstance(encrypted_tunnel, EncryptedTunnel):
            raise TypeError("encrypted_tunnel must be an EncryptedTunnel")

        if isinstance(message, str):
            app_msg = ApplicationMessage(
                message_type="TEXT",
                payload=message.encode("utf-8"),
            )
        elif isinstance(message, ApplicationMessage):
            app_msg = message
        else:
            raise TypeError("message must be str or ApplicationMessage")

        return encrypted_tunnel.encrypt_application_message(app_msg)

    def send_file_via_tunnel(
        self,
        encrypted_tunnel: EncryptedTunnel,
        file_path: Union[str, Path],
    ) -> list[bytes]:
        """
        Читает локальный файл, делит на чанки (по умолчанию 32 КиБ)
        и шифрует каждый чанк через EncryptedTunnel (Раздел 13.2 ТЗ).
        """
        path = Path(file_path)
        if not path.is_file():
            raise FileNotFoundError(f"Файл {path} не найден")

        file_bytes = path.read_bytes()
        # Имя файла очищается от относительных путей для безопасной передачи
        safe_filename = path.name

        transfer = FileTransfer(
            filename=safe_filename,
            data=file_bytes,
        )
        return transfer.encrypt_chunks(encrypted_tunnel)

    def process_incoming_file_chunk(
        self,
        encrypted_tunnel: EncryptedTunnel,
        encrypted_chunk_data: bytes,
    ) -> Path | None:
        """
        Принимает зашифрованный чанк, расшифровывает его РОВНО ОДИН РАЗ
        (во избежание срабатывания replay guard) и передает в сборщик.
        При завершении сборки сохраняет файл в папку downloads.
        """
        msg = encrypted_tunnel.decrypt_application_message(encrypted_chunk_data)
        chunk = FileChunk.from_application_message(msg)
        decrypted_data = self.file_receiver.receive_chunk(chunk)

        if decrypted_data is not None:
            # Файл собран целиком, сохраняем с защитой от path traversal
            safe_name = Path(chunk.filename).name
            dest_path = self.downloads_dir / safe_name
            dest_path.write_bytes(decrypted_data)
            return dest_path

        return None

    def get_network_state(self) -> dict:
        """Возвращает машинно-читаемое состояние узла для экспериментов и телеметрии."""
        return {
            "node_id": self.node_id,
            "routing_contacts": len(self.routing_table.get_contacts()),
            "stored_records": len(self.storage),
            "tunnels_total": self.tunnel_pool.size,
            "tunnels_active": self.tunnel_pool.active_count,
            "tunnels_prepared": self.tunnel_pool.prepared_count,
        }