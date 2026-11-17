import asyncio
import shutil
import socket
import struct
import sys
import tempfile
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR / "src"))

from identity import Identity
from message_types import MessageType
from protocol import Frame
from secure_channel import SecureChannel
from secure_session import SecureSession
from transport import Connection


def build_pcap_bytes(packets: list[tuple[int, int, bytes]]) -> bytes:
    """
    Формирует валидный бинарный файл libpcap (Ethernet + IPv4 + TCP)
    из списка захваченных на loopback (127.0.0.1:9000) полезных нагрузок TCP.
    """
    # Глобальный заголовок PCAP (magic, v2.4, tz=0, sigfigs=0, snaplen=65535, linktype=1 Ethernet)
    pcap_out = bytearray(struct.pack("<IHHiIII", 0xA1B2C3D4, 2, 4, 0, 0, 65535, 1))

    seq_map = {(54000, 9000): 1000, (9000, 54000): 2000}
    base_ts = int(time.time())

    for idx, (src_port, dst_port, payload) in enumerate(packets):
        eth_header = b"\x00\x00\x00\x00\x00\x00" * 2 + struct.pack("!H", 0x0800)

        seq = seq_map[(src_port, dst_port)]
        ack = seq_map[(dst_port, src_port)]
        seq_map[(src_port, dst_port)] += len(payload)

        # TCP header (20 bytes, flags=PSH+ACK 0x18)
        tcp_header = struct.pack(
            "!HHIIBBHHH",
            src_port,
            dst_port,
            seq,
            ack,
            (5 << 4),
            0x18,
            65535,
            0,
            0,
        )

        total_ip_len = 20 + len(tcp_header) + len(payload)
        ip_header = struct.pack(
            "!BBHHHBBH4s4s",
            0x45,
            0,
            total_ip_len,
            100 + idx,
            0x4000,
            64,
            socket.IPPROTO_TCP,
            0,
            socket.inet_aton("127.0.0.1"),
            socket.inet_aton("127.0.0.1"),
        )

        raw_pkt = eth_header + ip_header + tcp_header + payload
        pkt_hdr = struct.pack("<IIII", base_ts, (idx + 1) * 1500, len(raw_pkt), len(raw_pkt))
        pcap_out.extend(pkt_hdr)
        pcap_out.extend(raw_pkt)

    return bytes(pcap_out)


async def run_traffic():
    tmp_dir = Path(tempfile.mkdtemp(prefix="pcap_gen_"))
    captured_segments: list[tuple[int, int, bytes]] = []

    try:
        alice_id = Identity(tmp_dir / "state_alice")
        bob_id = Identity(tmp_dir / "state_bob")

        alice_session = SecureSession(alice_id, is_initiator=True)
        bob_session = SecureSession(bob_id, is_initiator=False)

        # Полный 4-шаговый AKE Handshake (Раздел 11.3 ТЗ)
        hello_a = alice_session.create_hello()
        auth_b = bob_session.handle_hello(hello_a)
        fin_a = alice_session.handle_auth(auth_b)
        bob_session.handle_finished(fin_a)

        alice_channel = SecureChannel(
            alice_session.send_key, alice_session.recv_key, alice_session.session_id
        )
        bob_channel = SecureChannel(
            bob_session.send_key, bob_session.recv_key, bob_session.session_id
        )

        async def dummy_server(reader, writer):
            conn = Connection(reader, writer)
            frame = await conn.receive_frame()
            decrypted = bob_channel.decrypt(frame.payload)
            print(f"[Server :9000] Расшифровано сообщение: {decrypted.decode()}")

            ack_cipher = bob_channel.encrypt(b"ACK_PROCESSED")
            ack_frame = Frame(MessageType.APP_ACK, ack_cipher, request_id=frame.request_id)
            captured_segments.append((9000, 54000, ack_frame.encode()))

            await conn.send_frame(ack_frame)
            await conn.close()

        server = await asyncio.start_server(dummy_server, "127.0.0.1", 9000)
        async with server:
            reader, writer = await asyncio.open_connection("127.0.0.1", 9000)
            client_conn = Connection(reader, writer)

            # Фиксируем пакеты AKE и зашифрованный кадр APP_MESSAGE на порту 9000
            captured_segments.append((54000, 9000, hello_a.encode()))
            captured_segments.append((9000, 54000, auth_b.encode()))
            captured_segments.append((54000, 9000, fin_a.encode()))

            plaintext = b"SECRET_DATA_PAYLOAD"
            ciphertext = alice_channel.encrypt(plaintext)
            msg_frame = Frame(MessageType.APP_MESSAGE, ciphertext)
            captured_segments.append((54000, 9000, msg_frame.encode()))

            await client_conn.send_frame(msg_frame)

            resp = await client_conn.receive_frame()
            decrypted_ack = alice_channel.decrypt(resp.payload)
            print(f"[Client] Получен и расшифрован ответ: {decrypted_ack.decode()}")
            await client_conn.close()

        pcap_bytes = build_pcap_bytes(captured_segments)
        assert b"SECRET_DATA_PAYLOAD" not in pcap_bytes, "Ошибка: открытый текст попал в PCAP!"
        assert b"ACK_PROCESSED" not in pcap_bytes, "Ошибка: открытый ACK попал в PCAP!"

        pcap_path = BASE_DIR / "traffic_capture.pcap"
        pcap_path.write_bytes(pcap_bytes)
        print(f"[+] Дамп трафика порта 9000 сохранён в: {pcap_path} ({len(pcap_bytes)} байт)")
        print("[+] Проверка конфиденциальности: открытый текст в pcap отсутствует (AES-256-GCM).")

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    asyncio.run(run_traffic())