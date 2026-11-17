import asyncio
from dataclasses import dataclass
from uuid import UUID
from config import MAX_FRAME_PAYLOAD, NETWORK_TIMEOUT
from message_types import MessageType
from protocol import Frame, PROTOCOL_VERSION, HEADER_SIZE
from relay import Relay
from transport import Connection
from tunnel import Tunnel
from tunnel_messages import (
    TunnelBuildRequest,
    TunnelBuildResponse,
    TunnelDataPayload,
)


@dataclass
class RelayRoute:
    next_host: str
    next_port: int


class RelayServer:
    """
    TCP Relay с прозрачной поддержкой:
    1. Сетевого хэндшейка TUNNEL_BUILD / TUNNEL_OK / TUNNEL_FAIL.
    2. Маршрутизации пакетов TUNNEL_DATA по tunnel_id.
    3. Полной обратной совместимости с raw TCP-прокси тестами (с сохранением буфера).
    """

    def __init__(
            self,
            host: str,
            port: int,
            next_host: str | None = None,
            next_port: int | None = None,
            tunnel: Tunnel | None = None,
            relay_node_id: int | None = None,
            node_addresses: dict[int, tuple[str, int]] | None = None,
    ):
        self.host = host
        self.port = port
        self.next_host = next_host
        self.next_port = next_port
        self.tunnel = tunnel
        self.relay_node_id = relay_node_id
        self.node_addresses = node_addresses

        self.server: asyncio.AbstractServer | None = None
        self.forwarded_messages: int = 0
        self.active_routes: dict[str, RelayRoute] = {}

    @classmethod
    def from_tunnel(
            cls,
            host: str,
            port: int,
            tunnel: Tunnel,
            relay_node_id: int,
            node_addresses: dict[int, tuple[str, int]],
    ):
        if relay_node_id not in tunnel.relay_node_ids:
            raise ValueError("Relay node is not part of the tunnel")

        relay_position = tunnel.relay_node_ids.index(relay_node_id)
        relay = Relay(
            node_id=relay_node_id,
            tunnel=tunnel,
            position=relay_position,
        )

        next_hop = relay.next_hop
        if next_hop not in node_addresses:
            raise ValueError(f"No address for next hop {next_hop}")

        next_host, next_port = node_addresses[next_hop]

        instance = cls(
            host=host,
            port=port,
            next_host=next_host,
            next_port=next_port,
            tunnel=tunnel,
            relay_node_id=relay_node_id,
            node_addresses=node_addresses,
        )
        instance.active_routes[str(tunnel.tunnel_id)] = RelayRoute(
            next_host=next_host, next_port=next_port
        )
        return instance

    def register_tunnel_route(self, tunnel_id: str, next_host: str, next_port: int):
        self.active_routes[str(tunnel_id)] = RelayRoute(
            next_host=next_host, next_port=next_port
        )

    def _resolve_next_hop(self, tunnel_id: str | None = None) -> tuple[str, int]:
        if tunnel_id and str(tunnel_id) in self.active_routes:
            route = self.active_routes[str(tunnel_id)]
            return route.next_host, route.next_port

        if self.tunnel is not None:
            if self.relay_node_id is None or self.node_addresses is None:
                raise RuntimeError("Invalid tunnel configuration")
            relay_position = self.tunnel.relay_node_ids.index(self.relay_node_id)
            relay = Relay(
                node_id=self.relay_node_id,
                tunnel=self.tunnel,
                position=relay_position,
            )
            next_hop = relay.next_hop
            return self.node_addresses[next_hop]

        if self.next_host is not None and self.next_port is not None:
            return self.next_host, self.next_port

        raise RuntimeError("Next hop is not configured")

    async def start(self):
        self.server = await asyncio.start_server(
            self._handle_client,
            self.host,
            self.port,
        )
        return self.server

    async def stop(self):
        if self.server is not None:
            self.server.close()
            await self.server.wait_closed()
            self.server = None

    async def _handle_client(
            self,
            reader: asyncio.StreamReader,
            writer: asyncio.StreamWriter,
    ):
        try:
            # Читаем первую порцию данных, которая пришла в сокет
            initial_data = await reader.read(MAX_FRAME_PAYLOAD)
            if not initial_data:
                writer.close()
                await writer.wait_closed()
                return

            # Проверяем: это валидный Frame протокола (TUNNEL_BUILD / TUNNEL_DATA)?
            is_protocol_frame = False
            frame = None

            if len(initial_data) >= HEADER_SIZE:
                # Первый байт заголовка — это версия протокола (1)
                # Второй байт — message_type
                version = initial_data[0]
                msg_type = initial_data[1]

                if version == PROTOCOL_VERSION and msg_type in (
                        MessageType.TUNNEL_BUILD,
                        MessageType.TUNNEL_DATA,
                        MessageType.TUNNEL_CLOSE,
                ):
                    try:
                        frame = Frame.decode(initial_data)
                        is_protocol_frame = True
                    except Exception:
                        is_protocol_frame = False

            if is_protocol_frame and frame is not None:
                # Режим структурированного протокола Frame
                connection = Connection(reader, writer)
                try:
                    if frame.message_type == MessageType.TUNNEL_BUILD:
                        resp = await self._handle_tunnel_build(frame)
                        await connection.send_frame(resp)
                    elif frame.message_type == MessageType.TUNNEL_DATA:
                        await self._handle_tunnel_data(frame, connection)
                    elif frame.message_type == MessageType.TUNNEL_CLOSE:
                        tunnel_id = frame.payload.decode("utf-8")
                        self.active_routes.pop(str(tunnel_id), None)
                        ack = Frame(
                            message_type=MessageType.TUNNEL_ACK,
                            payload=b"CLOSED",
                            request_id=frame.request_id,
                        )
                        await connection.send_frame(ack)
                finally:
                    await connection.close()
            else:
                # Режим Transparent TCP Proxy для прямых шифрованных тестов
                # ВАЖНО: передаем initial_data целиком, без потери первых 24 байт!
                await self._handle_raw_proxy_with_initial_data(
                    initial_data, reader, writer
                )

        except Exception:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    async def _handle_tunnel_build(self, frame: Frame) -> Frame:
        try:
            req = TunnelBuildRequest.decode(frame.payload)
            self.register_tunnel_route(
                req.tunnel_id, req.next_host, req.next_port
            )

            if req.remaining_hops:
                next_hop_info = req.remaining_hops[0]
                next_remaining = req.remaining_hops[1:]

                next_req = TunnelBuildRequest(
                    tunnel_id=req.tunnel_id,
                    next_host=next_hop_info["host"],
                    next_port=next_hop_info["port"],
                    remaining_hops=next_remaining,
                )

                next_reader, next_writer = await asyncio.open_connection(
                    req.next_host, req.next_port
                )
                next_conn = Connection(next_reader, next_writer)

                try:
                    fwd_frame = Frame(
                        message_type=MessageType.TUNNEL_BUILD,
                        payload=next_req.encode(),
                        request_id=frame.request_id,
                    )
                    await next_conn.send_frame(fwd_frame)
                    resp_frame = await next_conn.receive_frame(timeout=NETWORK_TIMEOUT)

                    if resp_frame.message_type != MessageType.TUNNEL_OK:
                        return Frame(
                            message_type=MessageType.TUNNEL_FAIL,
                            payload=resp_frame.payload,
                            request_id=frame.request_id,
                        )
                finally:
                    await next_conn.close()

            resp = TunnelBuildResponse(tunnel_id=req.tunnel_id, success=True)
            return Frame(
                message_type=MessageType.TUNNEL_OK,
                payload=resp.encode(),
                request_id=frame.request_id,
            )

        except Exception as err:
            resp = TunnelBuildResponse(
                tunnel_id="", success=False, error=str(err)
            )
            return Frame(
                message_type=MessageType.TUNNEL_FAIL,
                payload=resp.encode(),
                request_id=frame.request_id,
            )

    async def _handle_tunnel_data(self, frame: Frame, connection: Connection):
        self.forwarded_messages += 1
        payload_obj = TunnelDataPayload.decode(frame.payload)
        next_host, next_port = self._resolve_next_hop(payload_obj.tunnel_id)

        next_reader, next_writer = await asyncio.open_connection(
            next_host, next_port
        )
        next_conn = Connection(next_reader, next_writer)
        try:
            await next_conn.send_frame(frame)
            response = await next_conn.receive_frame(timeout=NETWORK_TIMEOUT)
            await connection.send_frame(response)
        finally:
            await next_conn.close()

    async def _handle_raw_proxy_with_initial_data(
            self,
            initial_data: bytes,
            reader: asyncio.StreamReader,
            writer: asyncio.StreamWriter,
    ):
        """
        Пересылает начальную порцию данных (initial_data) и далее проксирует трафик.
        Первые 24 байта НЕ теряются!
        """
        next_writer: asyncio.StreamWriter | None = None
        try:
            self.forwarded_messages += 1
            next_host, next_port = self._resolve_next_hop()

            next_reader, next_writer = await asyncio.open_connection(
                next_host, next_port
            )

            # Отправляем полные данные (включая первые байты)
            next_writer.write(initial_data)
            await next_writer.drain()

            # Читаем ответ от следующего узла
            response = await next_reader.read(1024 * 1024)
            if response:
                writer.write(response)
                await writer.drain()
        finally:
            if next_writer is not None:
                next_writer.close()
                try:
                    await next_writer.wait_closed()
                except Exception:
                    pass
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass