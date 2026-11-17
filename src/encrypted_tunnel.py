from uuid import uuid4
from tunnel import Tunnel
from secure_session import SecureSession
from secure_channel import SecureChannel
from application_message import ApplicationMessage


class EncryptedTunnel:
    """
    Защищённый логический туннель со сквозным (E2E) шифрованием.
    При закрытии уничтожает сессионные ключи в SecureChannel и SecureSession.
    """

    def __init__(
        self,
        tunnel: Tunnel,
        session: SecureSession,
    ):
        self.tunnel = tunnel
        self.session = session

        if not getattr(session, "established", False):
            raise ValueError("Secure session is not established")

        send_key = getattr(session, "send_key", None) or getattr(session, "session_key", None)
        recv_key = getattr(session, "recv_key", None) or getattr(session, "session_key", None)
        session_id = getattr(session, "session_id", None) or uuid4()

        if send_key is None or recv_key is None:
            raise ValueError("Secure session keys are unavailable")

        self.channel = SecureChannel(
            send_key=send_key,
            recv_key=recv_key,
            session_id=session_id,
        )

    @property
    def tunnel_id(self):
        return self.tunnel.tunnel_id

    @property
    def path(self):
        return self.tunnel.path

    @property
    def is_active(self) -> bool:
        return self.tunnel.is_active() and not self.channel.is_closed

    def close(self) -> None:
        """Закрывает туннель и уничтожает сессионные ключи (Раздел 11.3 ТЗ)."""
        self.tunnel.close()
        self.channel.close()
        if hasattr(self.session, "close"):
            self.session.close()

    def encrypt(self, plaintext: bytes) -> bytes:
        if not self.tunnel.is_active():
            raise RuntimeError("Cannot encrypt through inactive tunnel")
        return self.channel.encrypt(plaintext)

    def decrypt(self, encrypted: bytes) -> bytes:
        if not self.tunnel.is_active():
            raise RuntimeError("Cannot decrypt through inactive tunnel")
        return self.channel.decrypt(encrypted)

    def encrypt_message(self, message: str) -> bytes:
        return self.encrypt(message.encode("utf-8"))

    def decrypt_message(self, encrypted: bytes) -> str:
        return self.decrypt(encrypted).decode("utf-8")

    def encrypt_application_message(self, message: ApplicationMessage) -> bytes:
        return self.encrypt(message.encode())

    def decrypt_application_message(self, encrypted: bytes) -> ApplicationMessage:
        plaintext = self.decrypt(encrypted)
        return ApplicationMessage.decode(plaintext)

    def create_text_message(self, text: str) -> bytes:
        message = ApplicationMessage(
            message_type="TEXT",
            payload=text.encode("utf-8"),
        )
        return self.encrypt_application_message(message)

    def decrypt_text_message(self, encrypted: bytes) -> ApplicationMessage:
        message = self.decrypt_application_message(encrypted)
        if message.message_type != "TEXT":
            raise ValueError("Expected TEXT application message")
        return message