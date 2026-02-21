"""
network.py - Simple P2P networking for MiniChain.
Uses basic TCP sockets for educational clarity.
For production, consider upgrading to libp2p.
"""

import asyncio
import json
from typing import Callable, Optional, List

from blockchain import Blockchain
from mempool import Mempool
from transaction import Transaction
from block import Block
from config import PROTOCOL_ID


class Network:
    """Simple TCP-based P2P network node for MiniChain."""
    
    def __init__(self, blockchain: Blockchain, mempool: Mempool):
        self.blockchain = blockchain
        self.mempool = mempool
        self.server = None
        self.peers: List[tuple] = []  # List of (host, port)
        self.port = None
        
        # Callbacks for new blocks/transactions
        self.on_block: Optional[Callable] = None
        self.on_transaction: Optional[Callable] = None
    
    async def start(self, port: int):
        """Start the P2P server."""
        self.port = port
        self.server = await asyncio.start_server(
            self._handle_connection,
            '0.0.0.0',
            port
        )
        print(f"🌐 Node started on port {port}")
        print(f"🔗 Address: localhost:{port}")
        
        # Start the server
        asyncio.create_task(self._run_server())
    
    async def _run_server(self):
        """Run the server in background."""
        async with self.server:
            await self.server.serve_forever()
    
    async def connect(self, host: str, port: int):
        """Connect to a peer."""
        try:
            if (host, port) not in self.peers:
                self.peers.append((host, port))
            print(f"✅ Added peer {host}:{port}")
            
            # Register ourselves with the peer so they add us back
            await self._send_to_peer(host, port, {
                "type": "register",
                "data": {"port": self.port}
            })
            
            # Request their chain
            await self._request_chain(host, port)
        except Exception as e:
            print(f"❌ Connection failed: {e}")
    
    async def _handle_connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        """Handle incoming connection."""
        try:
            # Get peer address
            peer_addr = writer.get_extra_info('peername')
            
            data = await reader.read(1048576)  # 1MB max
            if not data:
                return
            
            msg = json.loads(data.decode())
            response = await self._handle_message(msg, peer_addr)
            
            if response:
                writer.write(json.dumps(response).encode())
                await writer.drain()
                
        except Exception as e:
            print(f"⚠️  Connection error: {e}")
        finally:
            writer.close()
            await writer.wait_closed()
    
    async def _handle_message(self, msg: dict, peer_addr: tuple = None) -> Optional[dict]:
        """Handle incoming message and return response if needed."""
        msg_type = msg.get("type")
        
        if msg_type == "tx":
            await self._handle_tx(msg["data"])
            return None
        
        elif msg_type == "block":
            await self._handle_block(msg["data"])
            return None
        
        elif msg_type == "request_chain":
            return {"type": "chain", "data": self.blockchain.to_dict()}
        
        elif msg_type == "chain":
            await self._handle_chain(msg["data"])
            return None
        
        elif msg_type == "register":
            # Peer is telling us their listening port
            peer_port = msg["data"]["port"]
            peer_host = peer_addr[0] if peer_addr else "localhost"
            if (peer_host, peer_port) not in self.peers:
                self.peers.append((peer_host, peer_port))
                print(f"📥 Peer registered: {peer_host}:{peer_port}")
            return None
        
        return None
    
    async def _handle_tx(self, tx_data: dict):
        """Handle received transaction."""
        tx = Transaction.from_dict(tx_data)
        state = self.blockchain.get_state()
        
        if self.mempool.add(tx, state):
            print(f"📥 Received tx: {tx}")
            if self.on_transaction:
                self.on_transaction(tx)
    
    async def _handle_block(self, block_data: dict):
        """Handle received block."""
        block = Block.from_dict(block_data)
        
        if self.blockchain.add_block(block):
            print(f"📥 Added block #{block.index}")
            self.mempool.remove(block.transactions)
            if self.on_block:
                self.on_block(block)
    
    async def _handle_chain(self, chain_data: list):
        """Handle received chain (for sync)."""
        new_chain = [Block.from_dict(b) for b in chain_data]
        if self.blockchain.replace_chain(new_chain):
            self.mempool.clear()
    
    async def _send_to_peer(self, host: str, port: int, msg: dict) -> Optional[dict]:
        """Send message to a peer and optionally receive response."""
        try:
            reader, writer = await asyncio.open_connection(host, port)
            writer.write(json.dumps(msg).encode())
            await writer.drain()
            
            # Wait for response if expecting one
            if msg["type"] == "request_chain":
                data = await reader.read(1048576)
                writer.close()
                await writer.wait_closed()
                if data:
                    return json.loads(data.decode())
            else:
                writer.close()
                await writer.wait_closed()
            
            return None
        except Exception as e:
            print(f"⚠️  Failed to send to {host}:{port}: {e}")
            return None
    
    async def _request_chain(self, host: str, port: int):
        """Request full chain from a peer."""
        response = await self._send_to_peer(host, port, {"type": "request_chain"})
        if response and response.get("type") == "chain":
            await self._handle_chain(response["data"])
    
    async def broadcast_tx(self, tx: Transaction):
        """Broadcast transaction to all peers."""
        msg = {"type": "tx", "data": tx.to_dict()}
        for host, port in self.peers:
            await self._send_to_peer(host, port, msg)
    
    async def broadcast_block(self, block: Block):
        """Broadcast block to all peers."""
        msg = {"type": "block", "data": block.to_dict()}
        for host, port in self.peers:
            await self._send_to_peer(host, port, msg)
