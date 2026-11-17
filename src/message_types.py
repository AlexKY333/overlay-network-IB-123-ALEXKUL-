from enum import IntEnum


class MessageType(IntEnum):
    PING = 1
    PONG = 2

    FIND_NODE_REQUEST = 3
    FIND_NODE_RESPONSE = 4

    STORE_REQUEST = 5
    STORE_RESPONSE = 6

    FIND_VALUE_REQUEST = 7
    FIND_VALUE_RESPONSE = 8

    TUNNEL_BUILD = 9
    TUNNEL_OK = 10
    TUNNEL_FAIL = 11

    TUNNEL_DATA = 12
    TUNNEL_ACK = 13
    TUNNEL_CLOSE = 14

    APP_MESSAGE = 15
    APP_ACK = 16

    ERROR = 17