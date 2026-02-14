import json
import logging

logger = logging.getLogger(__name__)


class P2PNetwork:
    """
    A minimal abstraction for Peer-to-Peer networking.

    Expected incoming message interface for handle_message():
        msg must have attribute:
            - data: bytes (JSON-encoded payload)

    JSON structure:
        {
            "type": "tx" | "block",
            "data": {...}
        }
    """

    def __init__(self, handler_callback):
        self.peers = []
        self.handler_callback = handler_callback
        self.pubsub = None  # Will be set in real implementation

    async def start(self):
        logger.info("Network: Listening on /ip4/0.0.0.0/tcp/0")
        # In real libp2p, we would await host.start() here

    async def broadcast_transaction(self, tx):
        msg = json.dumps({"type": "tx", "data": tx.to_dict()})
        logger.info("Network: Broadcasting Tx from %s...", tx.sender[:5])

        if self.pubsub:
            await self.pubsub.publish("minichain-global", msg.encode())
        else:
            logger.debug("Network: pubsub not initialized (mock mode)")

    async def broadcast_block(self, block):
        msg = json.dumps({"type": "block", "data": block.to_dict()})
        logger.info("Network: Broadcasting Block #%d", block.index)

        if self.pubsub:
            await self.pubsub.publish("minichain-global", msg.encode())
        else:
            logger.debug("Network: pubsub not initialized (mock mode)")

    async def handle_message(self, msg):
        """
        Callback when a p2p message is received.
        """

        try:
            if not hasattr(msg, "data"):
                raise TypeError("Incoming message missing 'data' attribute")

            if not isinstance(msg.data, (bytes, bytearray)):
                raise TypeError("msg.data must be bytes")

            decoded = msg.data.decode()
            data = json.loads(decoded)

            if not isinstance(data, dict) or "type" not in data or "data" not in data:
                raise ValueError("Invalid message format")

        except (TypeError, ValueError, json.JSONDecodeError) as e:
            logger.warning("Network Error: %s", e)
            return

        await self.handler_callback(data)
