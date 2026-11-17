import asyncio
import hashlib
import sys
import tempfile
import time
from pathlib import Path

# Подключение каталога src к путям импорта
BASE_DIR = Path(__file__).resolve().parent
SRC_DIR = BASE_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from dht_messages import NodeRecord
from encrypted_tunnel import EncryptedTunnel
from node import Node
from relay_profile import RelayProfile
from relay_selector import RelaySelector
from secure_session import SecureSession
from tunnel_builder import TunnelBuilder


async def main():
    print("=" * 75)
    print("  ДЕМОНСТРАЦИЯ ПОЛЬЗОВАТЕЛЬСКИХ СЦЕНАРИЕВ ОВЕРЛЕЙНОЙ СЕТИ (USERGUIDE)")
    print("=" * 75)

    with tempfile.TemporaryDirectory() as tmp_dir:
        root_path = Path(tmp_dir)

        # ---------------------------------------------------------------------
        # СЦЕНАРИЙ 1: Инициализация узлов Алисы и Боба
        # ---------------------------------------------------------------------
        print("\n[СЦЕНАРИЙ 1] Инициализация узлов и криптографической идентичности...")
        alice = Node(state_dir=root_path / "alice_node")
        bob = Node(state_dir=root_path / "bob_node")

        print(f"  [+] Узел Alice: NodeID = {alice.node_id[:16]}... (SHA-256)")
        print(f"  [+] Узел Bob:   NodeID = {bob.node_id[:16]}... (SHA-256)")
        print("  -> Подсистемы инициализированы (RoutingTable, Storage, TunnelPool).")

        # ---------------------------------------------------------------------
        # СЦЕНАРИЙ 2: Публикация в DHT, цифровые подписи и псевдонимы (Aliases)
        # ---------------------------------------------------------------------
        print("\n[СЦЕНАРИЙ 2] Публикация подписанной записи и резолвинг псевдонима...")
        now = int(time.time())

        # Боб публикует свою запись с псевдонимом "bob_server"
        bob_record = NodeRecord.create_signed(
            identity=bob.identity,
            addresses=["127.0.0.1:9050"],
            sequence_number=1,
            issued_at=now,
            expires_at=now + 300,
            alias="bob_server",
        )
        bob.storage.store(bob_record)
        # Алиса сохраняет запись в локальном кэше/DHT
        alice.storage.store(bob_record)

        print(f"  [+] Запись Боба подписана Ed25519: signature valid = {bob_record.verify_signature()}")
        print(f"  [+] Запись содержит псевдоним: '{bob_record.alias}'")

        # Алиса разрешает псевдоним "bob_server"
        resolved = await alice.resolve_alias("bob_server")
        assert resolved is not None
        assert resolved.node_id == bob.node_id
        print(f"  [+] Алиса разрешила псевдоним 'bob_server' -> NodeID: {resolved.node_id[:16]}...")

        # ---------------------------------------------------------------------
        # СЦЕНАРИЙ 3: Профилирование ретрансляторов и построение туннеля
        # ---------------------------------------------------------------------
        print("\n[СЦЕНАРИЙ 3] Построение туннеля через 3 ретранслятора (Ranked Strategy)...")
        profiles = [
            RelayProfile(node_id=101, ema_latency=0.040, ema_success=1.0),
            RelayProfile(node_id=102, ema_latency=0.065, ema_success=0.98),
            RelayProfile(node_id=103, ema_latency=0.080, ema_success=0.95),
            RelayProfile(node_id=104, ema_latency=0.250, ema_success=0.50),  # Худший узел
        ]
        alice.relay_selector = RelaySelector(profiles)
        alice.tunnel_builder = TunnelBuilder(
            selector=alice.relay_selector,
            pool=alice.tunnel_pool,
        )

        tunnel = alice.build_tunnel(
            destination_node_id=bob.node_id,
            relay_count=3,
            strategy="ranked",
        )

        print(f"  [+] Туннель сформирован. ID: {tunnel.tunnel_id}")
        print(f"  [+] Статус туннеля: {tunnel.state.value} (is_active={tunnel.is_active()})")
        print(f"  [+] Выбранный маршрут: Alice -> {tunnel.relay_node_ids} -> Bob")
        print("  -> Худший узел 104 отсеян алгоритмом селекции.")

        # Установка E2E защищённой сессии между Алисой и Бобом
        session_alice = SecureSession(alice.identity, is_initiator=True)
        session_bob = SecureSession(bob.identity, is_initiator=False)

        hello = session_alice.create_hello()
        auth = session_bob.handle_hello(hello)
        finished = session_alice.handle_auth(auth)
        session_bob.handle_finished(finished)

        enc_tunnel_alice = EncryptedTunnel(tunnel, session_alice)
        enc_tunnel_bob = EncryptedTunnel(tunnel, session_bob)
        print("  [+] Рукопожатие 4-step AKE завершено (X25519 + Ed25519 transcript signature).")

        # Отправка текстового сообщения
        secret_msg = "Привет, Боб! Это конфиденциальное сообщение."
        encrypted_bytes = alice.send_via_tunnel(enc_tunnel_alice, secret_msg)
        decrypted_msg = enc_tunnel_bob.decrypt_text_message(encrypted_bytes).payload.decode("utf-8")

        print(f"  [+] Текст зашифрован (длина шифротекста: {len(encrypted_bytes)} байт)")
        print(f"  [+] Боб успешно расшифровал сообщение: '{decrypted_msg}'")

        # ---------------------------------------------------------------------
        # СЦЕНАРИЙ 4: Передача файла через туннель с проверкой целостности
        # ---------------------------------------------------------------------
        print("\n[СЦЕНАРИЙ 4] Сквозная передача файла через туннель (нарезка на чанки)...")
        send_file = root_path / "coursework_report.bin"
        file_content = b"CRITICAL OVERLAY DATA CONTENT\n" * 2000  # ~60 КБ
        send_file.write_bytes(file_content)
        original_hash = hashlib.sha256(file_content).hexdigest()

        print(f"  [+] Исходный файл: {send_file.name} ({len(file_content)} байт)")
        print(f"  [+] SHA-256 хэш:   {original_hash}")

        # Алиса шифрует файл и нарезает на блоки
        encrypted_chunks = alice.send_file_via_tunnel(enc_tunnel_alice, send_file)
        print(f"  [+] Файл разбит на {len(encrypted_chunks)} зашифрованных чанков")

        # Боб принимает блоки
        saved_file_path = None
        for chunk in encrypted_chunks:
            res = bob.process_incoming_file_chunk(enc_tunnel_bob, chunk)
            if res is not None:
                saved_file_path = res

        assert saved_file_path is not None
        received_data = saved_file_path.read_bytes()
        received_hash = hashlib.sha256(received_data).hexdigest()

        print(f"  [+] Файл собран Бобом и сохранён в: {saved_file_path.name}")
        print(f"  [+] Принятый SHA-256: {received_hash}")
        assert received_hash == original_hash
        print("  -> Проверка целостности пройдена: 100% совпадение данных.")

        # ---------------------------------------------------------------------
        # СЦЕНАРИЙ 5: Снятие телеметрии узла
        # ---------------------------------------------------------------------
        print("\n[СЦЕНАРИЙ 5] Снятие телеметрии и проверка состояния узла...")
        state_alice = alice.get_network_state()
        print("  [+] Метрики узла Алисы:")
        for k, v in state_alice.items():
            print(f"      * {k}: {v}")

    print("\n" + "=" * 75)
    print("  ВСЕ ПОЛЬЗОВАТЕЛЬСКИЕ СЦЕНАРИИ УСПЕШНО ПРОЙДЕНЫ (100% OK)")
    print("=" * 75)


if __name__ == "__main__":
    asyncio.run(main())