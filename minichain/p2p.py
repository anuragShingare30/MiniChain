"""
TCP-based P2P networking for Minichain.
Supports peer registration, chain sync, and tx/block broadcasting.
"""
import asyncio
import json
import logging
import threading
from typing import Callable, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


class P2PNetwork:
    """
    TCP-based peer-to-peer network for blockchain synchronization.
    
    Message types:
        - "register": Register a new peer
        - "tx": Broadcast transaction
        - "block": Broadcast new block
        - "request_chain": Request full chain from peer
        - "chain": Response with full chain data
    """

    def __init__(self, node, port: int = 8000):
        """
        Initialize P2P network.
        
        Args:
            node: The node instance (has chain, mempool, etc.)
            port: Port to listen on
        """
        self.node = node
        self.port = port
        self.peers: Set[tuple] = set()  # Set of (host, port) tuples
        self.server: Optional[asyncio.AbstractServer] = None
        self._running = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self.on_block_received = None  # Callback for block notifications
        self.on_tx_received = None  # Callback for tx notifications

    @property
    def peer_list(self) -> List[str]:
        """Get list of connected peers as strings."""
        return [f"{host}:{port}" for host, port in self.peers]

    def start_background(self):
        """Start the P2P server in a background thread."""
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_event_loop, daemon=True)
        self._thread.start()
        # Wait a bit for server to start
        import time
        time.sleep(0.1)

    def _run_event_loop(self):
        """Run the asyncio event loop in background thread."""
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._start_server())
        self._loop.run_forever()

    async def _start_server(self):
        """Internal: start the TCP server."""
        try:
            self.server = await asyncio.start_server(
                self._handle_connection,
                host='0.0.0.0',
                port=self.port
            )
            self._running = True
            logger.info(f"P2P server listening on port {self.port}")
            asyncio.create_task(self.server.serve_forever())
        except OSError as e:
            logger.error(f"Failed to start P2P server on port {self.port}: {e}")
            raise

    async def start(self):
        """Start the P2P server (async version)."""
        await self._start_server()

    def stop_background(self):
        """Stop the P2P server running in background thread."""
        self._running = False
        if self._loop and self._loop.is_running():
            # Schedule proper shutdown in the event loop
            async def _shutdown():
                if self.server:
                    self.server.close()
                    await self.server.wait_closed()
                # Cancel all pending tasks
                tasks = [t for t in asyncio.all_tasks(self._loop) 
                         if t is not asyncio.current_task()]
                for task in tasks:
                    task.cancel()
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)
            
            future = asyncio.run_coroutine_threadsafe(_shutdown(), self._loop)
            try:
                future.result(timeout=2.0)
            except Exception:
                pass
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread:
            self._thread.join(timeout=2.0)
        logger.info("P2P server stopped")

    async def stop(self):
        """Stop the P2P server."""
        self._running = False
        if self.server:
            self.server.close()
            await self.server.wait_closed()
            logger.info("P2P server stopped")

    def connect_to_peer_sync(self, host: str, port: int) -> bool:
        """Connect to peer synchronously (for use from main thread)."""
        if self._loop:
            future = asyncio.run_coroutine_threadsafe(
                self.connect_to_peer(host, port), self._loop
            )
            return future.result(timeout=10.0)
        return False

    async def connect_to_peer(self, host: str, port: int) -> bool:
        """
        Connect to a peer and register with them.
        
        Args:
            host: Peer hostname/IP
            port: Peer port
            
        Returns:
            True if connection successful
        """
        if (host, port) in self.peers:
            return True
            
        try:
            # Send registration message
            await self._send_message(host, port, {
                "type": "register",
                "data": {"port": self.port}
            })
            self.peers.add((host, port))
            logger.info(f"Connected to peer {host}:{port}")
            
            # Request their chain to sync
            await self.request_chain(host, port)
            return True
            
        except Exception as e:
            logger.warning(f"Failed to connect to {host}:{port}: {e}")
            return False

    async def request_chain(self, host: str, port: int):
        """Request full chain from a peer."""
        await self._send_message(host, port, {
            "type": "request_chain",
            "data": {"port": self.port}
        })

    def broadcast_transaction_sync(self, tx):
        """Broadcast transaction synchronously (for use from main thread)."""
        if self._loop:
            future = asyncio.run_coroutine_threadsafe(
                self.broadcast_transaction(tx), self._loop
            )
            try:
                future.result(timeout=5.0)
            except Exception as e:
                logger.warning(f"Broadcast tx failed: {e}")

    def broadcast_block_sync(self, block):
        """Broadcast block synchronously (for use from main thread)."""
        if self._loop:
            future = asyncio.run_coroutine_threadsafe(
                self.broadcast_block(block), self._loop
            )
            try:
                future.result(timeout=5.0)
            except Exception as e:
                logger.warning(f"Broadcast block failed: {e}")

    async def broadcast_transaction(self, tx):
        """Broadcast a transaction to all peers."""
        logger.info(f"Broadcasting tx from {tx.sender[:8]}...")
        await self._broadcast({
            "type": "tx",
            "data": tx.to_dict()
        })

    async def broadcast_block(self, block):
        """Broadcast a new block to all peers."""
        logger.info(f"Broadcasting block #{block.index}")
        await self._broadcast({
            "type": "block",
            "data": block.to_dict()
        })

    async def _broadcast(self, message: dict):
        """Broadcast a message to all connected peers."""
        tasks = []
        for host, port in list(self.peers):
            tasks.append(self._send_message(host, port, message))
        
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _send_message(self, host: str, port: int, message: dict):
        """Send a message to a specific peer."""
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port),
                timeout=5.0
            )
            
            data = json.dumps(message).encode() + b'\n'
            writer.write(data)
            await writer.drain()
            writer.close()
            await writer.wait_closed()
            
        except asyncio.TimeoutError:
            logger.warning(f"Timeout connecting to {host}:{port}")
            self.peers.discard((host, port))
        except ConnectionRefusedError:
            logger.warning(f"Connection refused by {host}:{port}")
            self.peers.discard((host, port))
        except Exception as e:
            logger.warning(f"Error sending to {host}:{port}: {e}")

    async def _handle_connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        """Handle incoming connection from a peer."""
        peer_addr = writer.get_extra_info('peername')
        
        try:
            data = await asyncio.wait_for(reader.readline(), timeout=30.0)
            if not data:
                return
                
            message = json.loads(data.decode().strip())
            await self._handle_message(message, peer_addr)
            
        except json.JSONDecodeError as e:
            logger.warning(f"Invalid JSON from {peer_addr}: {e}")
        except asyncio.TimeoutError:
            logger.warning(f"Timeout reading from {peer_addr}")
        except Exception as e:
            logger.warning(f"Error handling connection from {peer_addr}: {e}")
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    async def _handle_message(self, message: dict, peer_addr: tuple):
        """
        Process incoming P2P message.
        
        Args:
            message: Parsed JSON message with 'type' and 'data'
            peer_addr: Peer address tuple (host, port)
        """
        msg_type = message.get("type")
        msg_data = message.get("data", {})
        
        if msg_type == "register":
            # Register peer with their listening port
            peer_port = msg_data.get("port", peer_addr[1])
            self.peers.add((peer_addr[0], peer_port))
            logger.info(f"Registered peer: {peer_addr[0]}:{peer_port}")
            print(f"\n[P2P] Peer connected: {peer_addr[0]}:{peer_port}")
            
        elif msg_type == "tx":
            # Handle incoming transaction
            await self._handle_incoming_tx(msg_data)
            
        elif msg_type == "block":
            # Handle incoming block
            await self._handle_incoming_block(msg_data)
            
        elif msg_type == "request_chain":
            # Send our chain to the requesting peer
            peer_port = msg_data.get("port", peer_addr[1])
            await self._send_chain(peer_addr[0], peer_port)
            
        elif msg_type == "chain":
            # Handle incoming chain (for sync)
            await self._handle_incoming_chain(msg_data)
            
        else:
            logger.warning(f"Unknown message type: {msg_type}")

    async def _handle_incoming_tx(self, tx_data: dict):
        """Process incoming transaction from peer."""
        from minichain.transaction import Transaction
        
        try:
            tx = Transaction.from_dict(tx_data)
            if self.node.mempool.add_transaction(tx):
                logger.info(f"Added tx from peer: {tx.sender[:8]}...")
                print(f"\n[P2P] New transaction received!")
                print(f"      From: {tx.sender[:16]}...")
                print(f"      To: {tx.receiver[:16] if tx.receiver else 'CONTRACT'}...")
                print(f"      Amount: {tx.amount}")
                # Notify callback if set
                if self.on_tx_received:
                    self.on_tx_received(tx)
        except Exception as e:
            logger.warning(f"Invalid tx from peer: {e}")

    async def _handle_incoming_block(self, block_data: dict):
        """Process incoming block from peer."""
        from minichain.block import Block
        
        try:
            block = Block.from_dict(block_data)
            
            # Check if this extends our chain
            if block.index == self.node.chain.height:
                if self.node.chain.add_block(block):
                    logger.info(f"Added block #{block.index} from peer")
                    print(f"\n[P2P] New block #{block.index} received and added!")
                    print(f"      Hash: {block.hash[:32]}...")
                    print(f"      Transactions: {len(block.transactions)}")
                    # Notify callback if set
                    if self.on_block_received:
                        self.on_block_received(block)
                    # Remove mined transactions from mempool
                    for tx in block.transactions:
                        self.node.mempool.remove_transaction(tx)
            elif block.index > self.node.chain.height:
                # We're behind, request full chain
                logger.info(f"We're behind (have {self.node.chain.height - 1}, got #{block.index})")
                print(f"\n[P2P] Behind on blocks, syncing...")
                # Request chain from a peer
                for host, port in list(self.peers):
                    await self.request_chain(host, port)
                    break
                    
        except Exception as e:
            logger.warning(f"Invalid block from peer: {e}")

    async def _send_chain(self, host: str, port: int):
        """Send our full chain to a peer."""
        await self._send_message(host, port, {
            "type": "chain",
            "data": self.node.chain.to_dict()
        })

    async def _handle_incoming_chain(self, chain_data):
        """Process incoming chain from peer (for sync)."""
        try:
            # Handle both old format (list) and new format (dict with 'blocks' key)
            if isinstance(chain_data, list):
                incoming_blocks = chain_data
            elif isinstance(chain_data, dict):
                incoming_blocks = chain_data.get("blocks", [])
            else:
                logger.warning(f"Invalid chain data type: {type(chain_data)}")
                return
            
            # If incoming chain is longer and valid, replace ours
            if len(incoming_blocks) > self.node.chain.height:
                if self.node.chain.replace_chain(incoming_blocks):
                    logger.info(f"Synced chain: now at height {self.node.chain.height}")
                    print(f"\n[P2P] Chain synced! Now at height {self.node.chain.height}")
                else:
                    logger.warning("Rejected incoming chain (invalid)")
                    
        except Exception as e:
            logger.warning(f"Error processing incoming chain: {e}")
