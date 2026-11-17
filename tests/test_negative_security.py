import asyncio
import base64
import sys
import time
from pathlib import Path

# Подключаем папку src к sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = BASE_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import pytest

from dht_messages import NodeRecord
from dht_storage import DHTStorage
from dispatcher import Dispatcher
from identity import Identity
from message_types import MessageType
from protocol import Frame
from routing_table import RoutingTable
from secure_channel import SecureChannel
from secure_session import (
    HandshakeAuth,
    HandshakeHello,
    SecureSession,
)


def print_test_header(num: int, title: str, tz_ref: str, requirement: str):
    print("\n" + "=" * 78)
    print(f"НЕГАТИВНЫЙ ТЕСТ #{num}: {title}")
    print(f"Пункт ТЗ:      {tz_ref}")
    print(f"Требование:    {requirement}")
    print("-" * 78)


@pytest.fixture
def identities(tmp_path):
    alice_id = Identity(tmp_path / "alice")
    bob_id = Identity(tmp_path / "bob")
    eve_id = Identity(tmp_path / "eve")
    return alice_id, bob_id, eve_id


# =========================================================================
# 1. Подмена identity public key
# =========================================================================
def test_tampered_identity_public_key(identities):
    print_test_header(
        num=1,
        title="Подмена долговременного открытого ключа (identity_public_key)",
        tz_ref="Разделы 9, 11.3, 11.4, 16 ТЗ",
        requirement=(
            "Узел обязан вычислить SHA-256(identity_public_key) и отклонить "
            "рукопожатие при несовпадении с заявленным NodeID."
        ),
    )

    alice, bob, eve = identities
    session_bob = SecureSession(bob, is_initiator=False)

    hello = SecureSession(alice, is_initiator=True).create_hello()
    alice_pub_hex = hello.identity_public_key.hex()[:24]
    eve_pub_bytes = eve.public_key.public_bytes_raw()
    eve_pub_hex = eve_pub_bytes.hex()[:24]

    print(f"  [1] Легитимный NodeID Alice:       {hello.node_id[:32]}...")
    print(f"  [2] Ключ Alice (Ed25519 pub):      {alice_pub_hex}...")
    print(f"  [3] Атака MITM: подмена ключа на ключ Eve ({eve_pub_hex}...) при сохранении NodeID Alice")

    is_valid_binding = bob.verify_node_id(eve_pub_bytes, hello.node_id)
    print(f"  [4] Проверка src/identity.py -> verify_node_id(eve_key, alice_id): {is_valid_binding}")
    assert is_valid_binding is False

    tampered_hello = HandshakeHello(
        version=hello.version,
        node_id=hello.node_id,
        identity_public_key=eve_pub_bytes,
        ephemeral_public_key=hello.ephemeral_public_key,
        nonce=hello.nonce,
    )

    with pytest.raises(ValueError, match="NodeID не соответствует открытому ключу") as exc_info:
        session_bob.handle_hello(tampered_hello)

    print(f"  [5] Вызов src/secure_session.py -> handle_hello() перехватил атаку:")
    print(f"      Исключение: ValueError('{exc_info.value}')")
    print(f"  [6] Состояние сессии Bob (established): {session_bob.established} (сессия НЕ установлена)")
    assert session_bob.established is False
    print("  -> РЕЗУЛЬТАТ: Атака подмены открытого ключа успешно заблокирована [PASS]")


# =========================================================================
# 2. Несоответствие NodeID ключу
# =========================================================================
def test_node_id_mismatch(identities):
    print_test_header(
        num=2,
        title="Несоответствие заявленного NodeID открытому ключу (NodeID Spoofing)",
        tz_ref="Разделы 9, 11.4, 16 ТЗ",
        requirement=(
            "При получении открытого ключа узел обязан повторно вычислить NodeID "
            "и отказать в соединении при подделке идентификатора."
        ),
    )

    alice, bob, _ = identities
    session_bob = SecureSession(bob, is_initiator=False)

    hello = SecureSession(alice, is_initiator=True).create_hello()
    fake_node_id = "0" * 64

    print(f"  [1] Подлинный ключ Alice (Ed25519): {hello.identity_public_key.hex()[:24]}...")
    print(f"  [2] Реальный SHA-256 NodeID Alice:  {hello.node_id[:32]}...")
    print(f"  [3] Атака: узел заявляет чужой/фиктивный NodeID: {fake_node_id[:32]}...")

    verified = bob.verify_node_id(hello.identity_public_key, fake_node_id)
    print(f"  [4] Проверка src/identity.py -> verify_node_id(alice_key, fake_id): {verified}")
    assert verified is False

    tampered_hello = HandshakeHello(
        version=hello.version,
        node_id=fake_node_id,
        identity_public_key=hello.identity_public_key,
        ephemeral_public_key=hello.ephemeral_public_key,
        nonce=hello.nonce,
    )

    with pytest.raises(ValueError, match="NodeID не соответствует открытому ключу") as exc_info:
        session_bob.handle_hello(tampered_hello)

    print(f"  [5] Вызов src/secure_session.py -> handle_hello() отклонил пакет:")
    print(f"      Исключение: ValueError('{exc_info.value}')")
    assert session_bob.established is False
    print("  -> РЕЗУЛЬТАТ: Подделка NodeID обнаружена и отклонена [PASS]")


# =========================================================================
# 3. Изменение ephemeral key или поля транскрипта
# =========================================================================
def test_tampered_ephemeral_key_in_handshake(identities):
    print_test_header(
        num=3,
        title="Модификация эфемерного ключа X25519 в транскрипте Handshake (MITM)",
        tz_ref="Разделы 11.3, 11.4 ТЗ",
        requirement=(
            "Канонический транскрипт handshake защищён подписью Ed25519; "
            "изменение ephemeral_public_key делает подпись недействительной."
        ),
    )

    alice, bob, _ = identities
    session_alice = SecureSession(alice, is_initiator=True)
    session_bob = SecureSession(bob, is_initiator=False)

    hello = session_alice.create_hello()
    auth = session_bob.handle_hello(hello)

    orig_eph_hex = auth.ephemeral_public_key.hex()[:24]
    corrupted_ephemeral = bytearray(auth.ephemeral_public_key)
    corrupted_ephemeral[0] ^= 0xFF
    corr_eph_hex = bytes(corrupted_ephemeral).hex()[:24]

    sid_str = auth.session_id.hex() if isinstance(auth.session_id, bytes) else str(auth.session_id)
    sig_str = auth.signature.hex()[:24] if isinstance(auth.signature, bytes) else str(auth.signature)[:24]

    print(f"  [1] Сессия ID:                       {sid_str}")
    print(f"  [2] Исходный X25519 ключ Bob:        {orig_eph_hex}...")
    print(f"  [3] Атака MITM: инвертирован 1-й байт эфемерного ключа -> {corr_eph_hex}...")
    print(f"  [4] Подпись транскрипта Bob (64B):   {sig_str}...")

    tampered_auth = HandshakeAuth(
        version=auth.version,
        session_id=auth.session_id,
        node_id=auth.node_id,
        identity_public_key=auth.identity_public_key,
        ephemeral_public_key=bytes(corrupted_ephemeral),
        nonce=auth.nonce,
        signature=auth.signature,
    )

    with pytest.raises(ValueError, match="Недействительная подпись рукопожатия") as exc_info:
        session_alice.handle_auth(tampered_auth)

    print(f"  [5] Вызов src/secure_session.py -> handle_auth() (Identity.verify) выявил подмену:")
    print(f"      Исключение: ValueError('{exc_info.value}')")
    print(f"  [6] Сессионные ключи Alice (send_key): {session_alice.send_key} (ключи НЕ созданы)")
    assert session_alice.established is False
    assert session_alice.send_key is None
    print("  -> РЕЗУЛЬТАТ: Атака MITM на эфемерный ключ X25519 заблокирована [PASS]")


# =========================================================================
# 4. Изменение ciphertext (нарушение имитовставки AEAD)
# =========================================================================
def test_tampered_ciphertext(identities):
    print_test_header(
        num=4,
        title="Модификация шифротекста в канале (нарушение тега AES-256-GCM)",
        tz_ref="Разделы 11.1, 11.3, 11.4, 16 ТЗ",
        requirement=(
            "Любое изменение байтов шифротекста или 16-байтового тега AEAD "
            "должно приводить к отказу аутентификации до передачи данных приложению."
        ),
    )

    alice, bob, _ = identities
    session_alice = SecureSession(alice, is_initiator=True)
    session_bob = SecureSession(bob, is_initiator=False)

    hello = session_alice.create_hello()
    auth = session_bob.handle_hello(hello)
    fin = session_alice.handle_auth(auth)
    session_bob.handle_finished(fin)

    channel_alice = SecureChannel(
        session_alice.send_key, session_alice.recv_key, session_alice.session_id
    )
    channel_bob = SecureChannel(
        session_bob.send_key, session_bob.recv_key, session_bob.session_id
    )

    plaintext = b"CONFIDENTIAL_PAYLOAD"
    cipher = channel_alice.encrypt(plaintext)

    corrupted_cipher = bytearray(cipher)
    corrupted_cipher[-1] ^= 0xAA

    sid_str = (
        session_alice.session_id.hex()
        if isinstance(session_alice.session_id, bytes)
        else str(session_alice.session_id)
    )

    print(f"  [1] Установлена сессия AKE:          {sid_str}")
    print(f"  [2] Зашифрован кадр (AES-256-GCM):   {len(cipher)} байт (последний байт тега: 0x{cipher[-1]:02x})")
    print(f"  [3] Атака в канале: искажён последний байт имитовставки -> 0x{corrupted_cipher[-1]:02x}")

    with pytest.raises(Exception) as exc_info:
        channel_bob.decrypt(bytes(corrupted_cipher))

    print(f"  [4] Вызов src/secure_channel.py -> decrypt() (AESGCM.decrypt) отклонил кадр:")
    print(f"      Тип исключения: {type(exc_info.value).__name__}")
    print(f"  [5] Счётчик принятых пакетов Bob:    {len(channel_bob._received_sequences)} (пакет не принят)")
    assert len(channel_bob._received_sequences) == 0
    print("  -> РЕЗУЛЬТАТ: Нарушение целостности шифротекста обнаружено AEAD [PASS]")


# =========================================================================
# 5. Повтор кадра в текущей сессии (Replay in current session)
# =========================================================================
def test_replay_attack_current_session(identities):
    print_test_header(
        num=5,
        title="Повтор защищённого кадра в текущей сессии (In-Session Replay Attack)",
        tz_ref="Разделы 11.1, 11.3, 11.4, 16 ТЗ",
        requirement=(
            "Повторная отправка ранее принятого зашифрованного кадра в рамках "
            "той же сессии должна блокироваться проверкой sequence_number."
        ),
    )

    alice, bob, _ = identities
    session_alice = SecureSession(alice, is_initiator=True)
    session_bob = SecureSession(bob, is_initiator=False)

    hello = session_alice.create_hello()
    auth = session_bob.handle_hello(hello)
    fin = session_alice.handle_auth(auth)
    session_bob.handle_finished(fin)

    channel_alice = SecureChannel(
        session_alice.send_key, session_alice.recv_key, session_alice.session_id
    )
    channel_bob = SecureChannel(
        session_bob.send_key, session_bob.recv_key, session_bob.session_id
    )

    cipher = channel_alice.encrypt(b"VALID_TRANSACTION")
    seq_num = int.from_bytes(cipher[:8], "big")

    print(f"  [1] Кадр отправлен с монотонного счётчика sequence_number = {seq_num}")
    first_decrypt = channel_bob.decrypt(cipher)
    print(f"  [2] Первая доставка в src/secure_channel.py -> decrypt(): УСПЕХ ({first_decrypt.decode()})")
    assert first_decrypt == b"VALID_TRANSACTION"

    print(f"  [3] Атака Replay: злоумышленник повторно отправляет тот же перехваченный кадр (seq={seq_num})")

    with pytest.raises(ValueError, match="Replay attack detected") as exc_info:
        channel_bob.decrypt(cipher)

    print(f"  [4] Повторный вызов src/secure_channel.py -> decrypt() заблокировал дубликат:")
    print(f"      Исключение: ValueError('{exc_info.value}')")
    print("  -> РЕЗУЛЬТАТ: Внутрисессионная атака повтора (Replay) заблокирована [PASS]")


# =========================================================================
# 6. Повтор кадра из завершённой сессии (Replay across sessions)
# =========================================================================
def test_replay_attack_across_sessions(identities):
    print_test_header(
        num=6,
        title="Повтор кадра из завершённой сессии в новой сессии (Cross-Session Replay)",
        tz_ref="Разделы 11.1, 11.3, 11.4 ТЗ",
        requirement=(
            "При переподключении генерируются новые эфемерные ключи и новый session_id, "
            "входящий в AAD; кадры из старой сессии должны отклоняться."
        ),
    )

    alice, bob, _ = identities

    s1_alice = SecureSession(alice, is_initiator=True)
    s1_bob = SecureSession(bob, is_initiator=False)
    h1 = s1_alice.create_hello()
    a1 = s1_bob.handle_hello(h1)
    f1 = s1_alice.handle_auth(a1)
    s1_bob.handle_finished(f1)
    sid_1 = s1_alice.session_id.hex() if isinstance(s1_alice.session_id, bytes) else str(s1_alice.session_id)

    ch1_alice = SecureChannel(s1_alice.send_key, s1_alice.recv_key, s1_alice.session_id)
    old_cipher = ch1_alice.encrypt(b"OLD_SESSION_COMMAND")
    s1_alice.close()
    s1_bob.close()

    s2_alice = SecureSession(alice, is_initiator=True)
    s2_bob = SecureSession(bob, is_initiator=False)
    h2 = s2_alice.create_hello()
    a2 = s2_bob.handle_hello(h2)
    f2 = s2_alice.handle_auth(a2)
    s2_bob.handle_finished(f2)
    sid_2 = s2_alice.session_id.hex() if isinstance(s2_alice.session_id, bytes) else str(s2_alice.session_id)

    ch2_bob = SecureChannel(s2_bob.send_key, s2_bob.recv_key, s2_bob.session_id)

    print(f"  [1] Сессия #1 (завершена): session_id = {sid_1}, перехвачен кадр (seq=0)")
    print(f"  [2] Сессия #2 (активна):   session_id = {sid_2} (новые ключи X25519 + HKDF)")
    print(f"  [3] Атака Cross-Session Replay: вставка кадра из Сессии #1 в Сессию #2")

    with pytest.raises(Exception) as exc_info:
        ch2_bob.decrypt(old_cipher)

    print(f"  [4] Вызов src/secure_channel.py -> decrypt() во 2-й сессии отверг старый кадр:")
    print(f"      Причина: несовпадение ключей и session_id в AAD ({type(exc_info.value).__name__})")
    assert len(ch2_bob._received_sequences) == 0
    print("  -> РЕЗУЛЬТАТ: Межсессионный повтор кадра успешно отвергнут [PASS]")


# =========================================================================
# 7. Подмена подписи DHT-записи
# =========================================================================
def test_tampered_node_record_signature(identities):
    print_test_header(
        num=7,
        title="Подмена данных или цифровой подписи записи DHT (NodeRecord Forgery)",
        tz_ref="Разделы 10.3, 11.4, 16 ТЗ",
        requirement=(
            "До сохранения NodeRecord проверяется соответствие ключа и подпись Ed25519; "
            "модифицированная или подписанная чужим ключом запись отклоняется."
        ),
    )

    alice, bob, eve = identities
    now = int(time.time())

    rec = NodeRecord.create_signed(
        identity=alice,
        addresses=["127.0.0.1:9001"],
        sequence_number=1,
        issued_at=now,
        expires_at=now + 300,
        alias="alice",
    )
    print(f"  [1] Создана валидная запись Alice (seq={rec.sequence_number}, addr={rec.addresses})")
    print(f"      Проверка src/dht_messages.py -> verify_signature(): {rec.verify_signature()}")
    assert rec.verify_signature() is True

    rec.addresses = ["192.168.1.100:9999"]
    sig_check_after_tamper = rec.verify_signature()
    print(f"  [2] Атака 1: подмена адреса на {rec.addresses} без закрытого ключа Alice")
    print(f"      Проверка src/dht_messages.py -> verify_signature(): {sig_check_after_tamper}")
    assert sig_check_after_tamper is False

    eve_signature = eve.sign(rec.canonical_bytes())
    rec.signature = base64.b64encode(eve_signature).decode("ascii")
    sig_check_eve = rec.verify_signature()
    print(f"  [3] Атака 2: запись подписана закрытым ключом Eve ({rec.signature[:24]}...)")
    print(f"      Проверка src/dht_messages.py -> verify_signature(): {sig_check_eve}")
    assert sig_check_eve is False

    storage = DHTStorage()
    dispatcher = Dispatcher(
        routing_table=RoutingTable(local_node_id=bob.node_id),
        storage=storage,
    )
    store_frame = Frame(
        message_type=MessageType.STORE_REQUEST,
        payload=rec.encode(),
    )
    response_frame = asyncio.run(dispatcher.dispatch(store_frame))
    print(
        f"  [4] Отправка поддельной записи в src/dispatcher.py -> dispatch(STORE_REQUEST): "
        f"ответ {MessageType(response_frame.message_type).name} ({response_frame.payload.decode()})"
    )
    assert response_frame.message_type == MessageType.ERROR
    assert storage.get(alice.node_id) is None

    with pytest.raises(ValueError, match="NodeRecord node_id does not match identity") as exc_info:
        rec.sign(eve)
    print(f"  [5] Вызов src/dht_messages.py -> rec.sign(eve) заблокирован: ValueError('{exc_info.value}')")
    print("  -> РЕЗУЛЬТАТ: Все варианты подделки подписи NodeRecord отклонены [PASS]")


# =========================================================================
# 8. Откат sequence_number (Rollback attack)
# =========================================================================
def test_node_record_sequence_number_rollback(identities):
    print_test_header(
        num=8,
        title="Откат версии адресной записи DHT (Sequence Number Rollback Attack)",
        tz_ref="Разделы 10.3, 11.1, 11.4, 16 ТЗ",
        requirement=(
            "Хранилище DHT обязано проверять монотонность sequence_number; "
            "валидно подписанная старая запись с меньшим номером отвергается как откат."
        ),
    )

    alice, _, _ = identities
    storage = DHTStorage()
    now = int(time.time())

    rec_v5 = NodeRecord.create_signed(
        identity=alice,
        addresses=["127.0.0.1:9005"],
        sequence_number=5,
        issued_at=now,
        expires_at=now + 300,
    )
    storage.store(rec_v5)
    print(
        f"  [1] В DHTStorage сохранена актуальная запись Alice: "
        f"sequence_number = {rec_v5.sequence_number}, addr = {rec_v5.addresses}"
    )
    assert storage.get(alice.node_id).sequence_number == 5

    rec_v3 = NodeRecord.create_signed(
        identity=alice,
        addresses=["127.0.0.1:9001"],
        sequence_number=3,
        issued_at=now,
        expires_at=now + 300,
    )
    print(
        f"  [2] Атака Rollback: отправка старой подписанной записи Alice с "
        f"sequence_number = {rec_v3.sequence_number} (addr = {rec_v3.addresses})"
    )

    with pytest.raises(ValueError, match="Sequence number rollback") as exc_info:
        storage.store(rec_v3)

    current_stored = storage.get(alice.node_id)
    print(f"  [3] Вызов src/dht_storage.py -> store() отверг старую версию:")
    print(f"      Исключение: ValueError('{exc_info.value}')")
    print(
        f"  [4] В хранилище осталась версия: sequence_number = {current_stored.sequence_number}, "
        f"addr = {current_stored.addresses}"
    )
    assert current_stored.sequence_number == 5
    assert current_stored.addresses == ["127.0.0.1:9005"]
    print("  -> РЕЗУЛЬТАТ: Атака отката версии (Rollback) успешно предотвращена [PASS]")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])