import asyncio

from dispatcher import Dispatcher
from routing_table import RoutingTable
from transport import start_server


LOCAL_NODE_ID = (
    "0000000000000000000000000000000000000000000000000000000000000000"
)


routing_table = RoutingTable(
    local_node_id=LOCAL_NODE_ID
)

dispatcher = Dispatcher(
    routing_table=routing_table
)


asyncio.run(
    start_server(
        host="127.0.0.1",
        port=9000,
        dispatcher=dispatcher,
    )
)