import json
import logging
import asyncio
import struct
import uuid
from typing import Dict, Set, Optional, Callable, Any

logger = logging.getLogger(__name__)

# Message frame: 4-byte length prefix + JSON body
HEADER_SIZE = 4
MAX_MESSAGE_SIZE = 10 * 1024 * 1024  # 10MB limit


class Peer:
    """Represents a connected peer."""
    
    def __init__(self, node_id: str, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, address: str):
        self.node_id = node_id
        self.reader = reader
        self.writer = writer
        self.address = address
    
    async def send(self, message: dict):
        """Send a JSON message with length prefix."""
        try:
            data = json.dumps(message).encode('utf-8')
            header = struct.pack('>I', len(data))
            self.writer.write(header + data)
            await self.writer.drain()
        except Exception as e:
            logger.error("Failed to send to peer %s: %s", self.address, e)
            raise
    
    async def receive(self) -> Optional[dict]:
        """Receive a length-prefixed JSON message."""
        try:
            header = await self.reader.readexactly(HEADER_SIZE)
            length = struct.unpack('>I', header)[0]
            
            if length > MAX_MESSAGE_SIZE:
                logger.warning("Message too large from %s: %d bytes", self.address, length)
                return None
            
            data = await self.reader.readexactly(length)
            return json.loads(data.decode('utf-8'))
        except asyncio.IncompleteReadError:
            return None
        except Exception as e:
            logger.error("Failed to receive from peer %s: %s", self.address, e)
            return None
    
    def close(self):
        """Close the connection."""
        try:
            self.writer.close()
        except Exception:
            pass


class P2PNetwork:
    """
    Real TCP-based P2P networking for MiniChain.
    
    Features:
    - TCP server listening on a port
    - Connect to known peers by IP:port
    - Length-prefixed JSON message framing
    - Explicit node ID
    - Message deduplication (broadcast guard)
    """

    def __init__(self, handler_callback: Optional[Callable] = None):
        self.node_id: str = str(uuid.uuid4())[:8]  # Short unique ID
        self.host: str = "0.0.0.0"
        self.port: int = 9000
        
        self._handler_callback: Optional[Callable] = None
        if handler_callback is not None:
            self.register_handler(handler_callback)
        
        self.peers: Dict[str, Peer] = {}  # node_id -> Peer
        self.seen_messages: Set[str] = set()  # For broadcast deduplication
        self._server: Optional[asyncio.Server] = None
        self._running: bool = False
        self._tasks: list = []

    def register_handler(self, handler_callback: Callable):
        """Register callback for incoming messages."""
        if not callable(handler_callback):
            raise ValueError("handler_callback must be callable")
        self._handler_callback = handler_callback

    def configure(self, host: str = "0.0.0.0", port: int = 9000):
        """Configure network settings before starting."""
        self.host = host
        self.port = port

    async def start(self):
        """Start the TCP server."""
        self._running = True
        self._server = await asyncio.start_server(
            self._handle_incoming_connection,
            self.host,
            self.port
        )
        logger.info("Node %s listening on %s:%d", self.node_id, self.host, self.port)

    async def stop(self):
        """Clean shutdown of network."""
        logger.info("Node %s shutting down...", self.node_id)
        self._running = False
        
        # Close all peer connections
        for peer in list(self.peers.values()):
            peer.close()
        self.peers.clear()
        
        # Cancel background tasks
        for task in self._tasks:
            task.cancel()
        self._tasks.clear()
        
        # Close server
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        
        logger.info("Node %s shutdown complete", self.node_id)

    async def connect_to_peer(self, address: str) -> bool:
        """
        Connect to a peer by address (ip:port).
        Returns True if connection successful.
        """
        try:
            host, port_str = address.split(':')
            port = int(port_str)
            
            logger.info("Node %s connecting to %s...", self.node_id, address)
            reader, writer = await asyncio.open_connection(host, port)
            
            # Send HELLO
            hello_msg = {
                "type": "hello",
                "data": {
                    "node_id": self.node_id,
                    "port": self.port
                }
            }
            data = json.dumps(hello_msg).encode('utf-8')
            header = struct.pack('>I', len(data))
            writer.write(header + data)
            await writer.drain()
            
            # Wait for HELLO response
            resp_header = await asyncio.wait_for(reader.readexactly(HEADER_SIZE), timeout=5.0)
            length = struct.unpack('>I', resp_header)[0]
            resp_data = await asyncio.wait_for(reader.readexactly(length), timeout=5.0)
            response = json.loads(resp_data.decode('utf-8'))
            
            if response.get("type") != "hello":
                logger.warning("Invalid response from %s", address)
                writer.close()
                return False
            
            peer_node_id = response["data"]["node_id"]
            
            # Check for self-connection
            if peer_node_id == self.node_id:
                logger.warning("Detected self-connection, closing")
                writer.close()
                return False
            
            # Check for duplicate connection
            if peer_node_id in self.peers:
                logger.info("Already connected to %s", peer_node_id)
                writer.close()
                return True
            
            peer = Peer(peer_node_id, reader, writer, address)
            self.peers[peer_node_id] = peer
            
            # Start listening for messages from this peer
            task = asyncio.create_task(self._listen_to_peer(peer))
            self._tasks.append(task)
            
            logger.info("Node %s connected to peer %s at %s", self.node_id, peer_node_id, address)
            return True
            
        except Exception as e:
            logger.error("Failed to connect to %s: %s", address, e)
            return False

    async def _handle_incoming_connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        """Handle a new incoming connection."""
        address = writer.get_extra_info('peername')
        address_str = f"{address[0]}:{address[1]}" if address else "unknown"
        
        try:
            # Wait for HELLO
            header = await asyncio.wait_for(reader.readexactly(HEADER_SIZE), timeout=10.0)
            length = struct.unpack('>I', header)[0]
            data = await asyncio.wait_for(reader.readexactly(length), timeout=10.0)
            message = json.loads(data.decode('utf-8'))
            
            if message.get("type") != "hello":
                logger.warning("Expected HELLO from %s, got %s", address_str, message.get("type"))
                writer.close()
                return
            
            peer_node_id = message["data"]["node_id"]
            
            # Check for self-connection
            if peer_node_id == self.node_id:
                logger.warning("Detected self-connection from %s, closing", address_str)
                writer.close()
                return
            
            # Check for duplicate
            if peer_node_id in self.peers:
                logger.info("Duplicate connection from %s, closing new one", peer_node_id)
                writer.close()
                return
            
            # Send HELLO response
            hello_resp = {
                "type": "hello",
                "data": {
                    "node_id": self.node_id,
                    "port": self.port
                }
            }
            resp_data = json.dumps(hello_resp).encode('utf-8')
            resp_header = struct.pack('>I', len(resp_data))
            writer.write(resp_header + resp_data)
            await writer.drain()
            
            peer = Peer(peer_node_id, reader, writer, address_str)
            self.peers[peer_node_id] = peer
            
            logger.info("Node %s accepted connection from peer %s", self.node_id, peer_node_id)
            
            # Listen for messages
            await self._listen_to_peer(peer)
            
        except asyncio.TimeoutError:
            logger.warning("Timeout waiting for HELLO from %s", address_str)
            writer.close()
        except Exception as e:
            logger.error("Error handling connection from %s: %s", address_str, e)
            writer.close()

    async def _listen_to_peer(self, peer: Peer):
        """Listen for messages from a peer."""
        while self._running:
            message = await peer.receive()
            if message is None:
                break
            
            await self._process_message(message, peer)
        
        # Peer disconnected
        if peer.node_id in self.peers:
            del self.peers[peer.node_id]
        peer.close()
        logger.info("Peer %s disconnected", peer.node_id)

    async def _process_message(self, message: dict, sender: Peer):
        """Process an incoming message."""
        msg_type = message.get("type")
        msg_data = message.get("data", {})
        
        # Generate message ID for deduplication
        msg_id = self._get_message_id(message)
        
        # Broadcast guard: skip if already seen
        if msg_id and msg_id in self.seen_messages:
            return
        
        if msg_id:
            self.seen_messages.add(msg_id)
            # Limit seen set size
            if len(self.seen_messages) > 10000:
                self.seen_messages = set(list(self.seen_messages)[-5000:])
        
        # Handle internal message types
        if msg_type == "get_chain":
            # Respond with chain (handled by callback)
            pass
        
        # Forward to registered handler
        if self._handler_callback:
            try:
                # Pass sender info for response handling
                await self._handler_callback(message, sender)
            except Exception:
                logger.exception("Error in message handler for: %s", message)

    def _get_message_id(self, message: dict) -> Optional[str]:
        """Get unique ID for message deduplication."""
        msg_type = message.get("type")
        msg_data = message.get("data", {})
        
        if msg_type == "tx":
            # Use transaction hash
            return msg_data.get("signature") or json.dumps(msg_data, sort_keys=True)
        elif msg_type == "block":
            # Use block hash
            return msg_data.get("hash")
        
        return None

    async def broadcast(self, message: dict, exclude_peer: Optional[str] = None):
        """
        Broadcast a message to all connected peers.
        exclude_peer: node_id to exclude (typically the sender)
        """
        msg_id = self._get_message_id(message)
        if msg_id:
            self.seen_messages.add(msg_id)
        
        for node_id, peer in list(self.peers.items()):
            if node_id == exclude_peer:
                continue
            try:
                await peer.send(message)
            except Exception as e:
                logger.error("Failed to broadcast to %s: %s", node_id, e)

    async def broadcast_transaction(self, tx):
        """Broadcast a transaction to all peers."""
        logger.info("Node %s broadcasting tx from %s...", self.node_id, tx.sender[:8])
        message = {"type": "tx", "data": tx.to_dict()}
        await self.broadcast(message)

    async def broadcast_block(self, block):
        """Broadcast a block to all peers."""
        logger.info("Node %s broadcasting block #%d", self.node_id, block.index)
        message = {"type": "block", "data": block.to_dict()}
        await self.broadcast(message)

    async def request_chain(self, peer: Peer) -> Optional[list]:
        """Request the full chain from a peer."""
        try:
            await peer.send({"type": "get_chain", "data": {}})
            # Response will be handled by the message callback
            return None
        except Exception as e:
            logger.error("Failed to request chain from %s: %s", peer.node_id, e)
            return None

    async def send_chain(self, peer: Peer, chain_data: list):
        """Send the full chain to a peer."""
        try:
            await peer.send({"type": "chain", "data": chain_data})
        except Exception as e:
            logger.error("Failed to send chain to %s: %s", peer.node_id, e)

    def get_peer_count(self) -> int:
        """Return number of connected peers."""
        return len(self.peers)

    def get_peer_ids(self) -> list:
        """Return list of connected peer node_ids."""
        return list(self.peers.keys())


# Legacy compatibility - handle_message interface for tests
async def _legacy_handle_message(self, msg):
    """Legacy callback interface for backward compatibility."""
    if not hasattr(msg, "data"):
        raise TypeError("Incoming message missing 'data' attribute")
    
    if not isinstance(msg.data, (bytes, bytearray)):
        raise TypeError("msg.data must be bytes")
    
    data = json.loads(msg.data.decode('utf-8'))
    
    if self._handler_callback:
        await self._handler_callback(data, None)

