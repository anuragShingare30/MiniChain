#!/usr/bin/env python3
"""
MiniChain Node CLI

Simple command-line interface for running a MiniChain testnet node.

Usage:
    # Start first node (no peers)
    python cli.py --port 9000

    # Start second node, connect to first
    python cli.py --port 9001 --peers 127.0.0.1:9000

    # Enable mining
    python cli.py --port 9000 --mine

    # With custom miner address
    python cli.py --port 9000 --mine --miner <address>
"""

import argparse
import asyncio
import logging
import signal
import sys

from minichain import Blockchain, Block, Mempool, P2PNetwork, Transaction, mine_block
from minichain.pow import calculate_hash

logger = logging.getLogger(__name__)


class Node:
    """MiniChain testnet node."""

    def __init__(self, port: int, peers: list = None, mining: bool = False, miner_address: str = None):
        self.port = port
        self.initial_peers = peers or []
        self.mining = mining
        self.miner_address = miner_address or "0" * 40  # Burn address if not set

        self.chain = Blockchain()
        self.mempool = Mempool()
        self.network = P2PNetwork()
        self.network.configure(port=port)

        self._running = False
        self._sync_complete = False
        self._chain_received_event = asyncio.Event()

    async def start(self):
        """Start the node."""
        self._running = True

        # Register message handler
        self.network.register_handler(self._handle_message)

        # Start network
        await self.network.start()
        logger.info("Node ID: %s", self.network.node_id)

        # Connect to initial peers
        for peer_addr in self.initial_peers:
            await self.network.connect_to_peer(peer_addr)

        # Request chain sync from peers
        await self._sync_chain()

        # Start main loop
        await self._run()

    async def stop(self):
        """Stop the node gracefully."""
        logger.info("Stopping node...")
        self._running = False
        await self.network.stop()
        logger.info("Node stopped")

    async def _sync_chain(self):
        """Sync chain from connected peers."""
        if not self.network.peers:
            logger.info("No peers connected, starting with genesis chain")
            self._sync_complete = True
            return

        logger.info("Requesting chain from %d peer(s)...", len(self.network.peers))

        for peer in list(self.network.peers.values()):
            await self.network.request_chain(peer)

        # Wait for chain response with timeout
        try:
            await asyncio.wait_for(self._chain_received_event.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            logger.warning("Chain sync timeout - no response from peers")
        
        self._sync_complete = True
        logger.info("Chain sync complete. Height: %d", len(self.chain.chain))

    async def _handle_message(self, message: dict, sender):
        """Handle incoming P2P messages."""
        msg_type = message.get("type")
        msg_data = message.get("data", {})

        try:
            if msg_type == "tx":
                await self._handle_tx(msg_data, sender)

            elif msg_type == "block":
                await self._handle_block(msg_data, sender)

            elif msg_type == "get_chain":
                await self._handle_get_chain(sender)

            elif msg_type == "chain":
                await self._handle_chain(msg_data)

        except Exception:
            logger.exception("Error handling message: %s", message)

    async def _handle_tx(self, tx_data: dict, sender):
        """Handle incoming transaction."""
        try:
            tx = Transaction(**tx_data)
            if self.mempool.add_transaction(tx):
                logger.info("Added tx to mempool from %s...", tx.sender[:8])
                # Relay to other peers (exclude sender)
                sender_id = sender.node_id if sender else None
                await self.network.broadcast({"type": "tx", "data": tx_data}, exclude_peer=sender_id)
        except Exception as e:
            logger.warning("Invalid transaction: %s", e)

    async def _handle_block(self, block_data: dict, sender):
        """Handle incoming block."""
        try:
            transactions = [Transaction(**tx) for tx in block_data.get("transactions", [])]

            block = Block(
                index=block_data.get("index"),
                previous_hash=block_data.get("previous_hash"),
                transactions=transactions,
                timestamp=block_data.get("timestamp"),
                difficulty=block_data.get("difficulty")
            )
            block.nonce = block_data.get("nonce", 0)
            block.hash = block_data.get("hash")

            if self.chain.add_block(block):
                logger.info("Added block #%d to chain", block.index)
                # Relay to other peers
                sender_id = sender.node_id if sender else None
                await self.network.broadcast({"type": "block", "data": block_data}, exclude_peer=sender_id)
            else:
                logger.warning("Rejected block #%d", block.index)

        except Exception as e:
            logger.warning("Invalid block: %s", e)

    async def _handle_get_chain(self, sender):
        """Handle chain request - send our chain to requester."""
        if sender is None:
            return

        chain_data = self.chain.to_dict_list()
        await self.network.send_chain(sender, chain_data)
        logger.info("Sent chain (%d blocks) to peer %s", len(chain_data), sender.node_id)

    async def _handle_chain(self, chain_data: list):
        """Handle received chain - validate and potentially replace ours."""
        if not chain_data:
            return

        logger.info("Received chain with %d blocks", len(chain_data))

        # Only replace if longer or equal (let replace_chain validate)
        if len(chain_data) < len(self.chain.chain):
            logger.info("Received chain shorter than ours, ignoring")
            self._chain_received_event.set()
            return

        # Validate and replace
        if self.chain.replace_chain(chain_data):
            logger.info("Replaced chain with received chain (new height: %d)", len(self.chain.chain))
        else:
            logger.warning("Received chain validation failed")
        
        # Signal that we received a chain response
        self._chain_received_event.set()

    async def _run(self):
        """Main node loop."""
        logger.info("Node running. Type 'help' for commands.")
        logger.info("Connected to %d peer(s)", self.network.get_peer_count())

        mine_interval = 10  # seconds between mining attempts
        last_mine_time = 0
        
        # Start input reader task
        input_task = asyncio.create_task(self._read_input())

        while self._running:
            try:
                # Check for user input
                if input_task.done():
                    try:
                        cmd = input_task.result()
                        if cmd is not None:
                            result = self._handle_command(cmd)
                            if result == False:
                                break
                            elif result == "sync":
                                self._chain_received_event.clear()
                                await self._sync_chain()
                            elif isinstance(result, tuple) and result[0] == "connect":
                                success = await self.network.connect_to_peer(result[1])
                                if success:
                                    print(f"Connected to {result[1]}")
                                else:
                                    print(f"Failed to connect to {result[1]}")
                    except Exception:
                        pass
                    # Start new input reader
                    input_task = asyncio.create_task(self._read_input())
                
                # Mining loop
                if self.mining and self._sync_complete:
                    import time
                    now = time.time()
                    if now - last_mine_time >= mine_interval:
                        await self._try_mine_block()
                        last_mine_time = now

                # Keep event loop responsive
                await asyncio.sleep(0.1)

            except asyncio.CancelledError:
                break
        
        # Cancel input task on exit
        if not input_task.done():
            input_task.cancel()

    async def _read_input(self):
        """Read a line from stdin asynchronously."""
        loop = asyncio.get_event_loop()
        try:
            return await loop.run_in_executor(None, sys.stdin.readline)
        except Exception:
            return None

    async def _try_mine_block(self):
        """Attempt to mine a new block."""
        pending_txs = self.mempool.get_transactions_for_block()

        # Create coinbase transaction for mining reward
        coinbase_tx = Transaction(
            sender="0" * 40,  # Coinbase has no sender
            receiver=self.miner_address,
            amount=50,  # Mining reward
            nonce=0,
            data=None,
            signature=None,  # Coinbase doesn't need a signature
            timestamp=None  # Will be set to current time
        )

        # Insert coinbase transaction at the beginning
        all_txs = [coinbase_tx] + pending_txs

        block = Block(
            index=self.chain.last_block.index + 1,
            previous_hash=self.chain.last_block.hash,
            transactions=all_txs,
        )

        try:
            # Mine with low difficulty for testnet
            mined_block = mine_block(block, difficulty=4, timeout_seconds=5)

            if self.chain.add_block(mined_block):
                logger.info("Mined block #%d! Hash: %s...", mined_block.index, mined_block.hash[:16])

                # Broadcast to peers
                await self.network.broadcast_block(mined_block)

        except Exception as e:
            # Mining timeout or other error - return transactions to mempool
            for tx in pending_txs:
                self.mempool.add_transaction(tx)

    def _print_help(self):
        """Print available commands."""
        print("""
Available commands:
  status             - Show node status
  peers              - List connected peers
  chain              - Show chain status
  balance <addr>     - Show balance of an address
  mempool            - Show pending transactions
  block <index>      - Show block details
  connect <ip:port>  - Connect to a new peer
  mine               - Toggle mining on/off
  sync               - Request chain sync from peers
  help               - Show this help
  exit / quit        - Stop the node
""")

    def _handle_command(self, cmd: str):
        """Handle interactive command."""
        parts = cmd.strip().split()
        if not parts:
            return True  # Continue running
        
        command = parts[0].lower()
        args = parts[1:]
        
        if command in ("exit", "quit"):
            return False  # Stop running
        
        elif command == "help":
            self._print_help()
        
        elif command == "status":
            print(f"Node ID: {self.network.node_id}")
            print(f"Port: {self.port}")
            print(f"Peers: {self.network.get_peer_count()}")
            print(f"Chain height: {len(self.chain.chain)}")
            print(f"Mempool: {self.mempool.size()} txns")
            print(f"Mining: {'ON' if self.mining else 'OFF'}")
            print(f"Synced: {'Yes' if self._sync_complete else 'No'}")
        
        elif command == "peers":
            peers = self.network.get_peer_ids()
            if peers:
                print(f"Connected peers ({len(peers)}):")
                for pid in peers:
                    peer = self.network.peers.get(pid)
                    addr = peer.address if peer else "unknown"
                    print(f"  {pid} @ {addr}")
            else:
                print("No peers connected")
        
        elif command == "chain":
            height = len(self.chain.chain)
            last = self.chain.last_block
            print(f"Chain height: {height}")
            print(f"Last block: #{last.index}")
            print(f"  Hash: {last.hash[:32]}...")
            print(f"  Txns: {len(last.transactions)}")
            print(f"Mining: {'ON' if self.mining else 'OFF'}")
            print(f"Synced: {'Yes' if self._sync_complete else 'No'}")
        
        elif command == "balance":
            if not args:
                print("Usage: balance <address>")
            else:
                addr = args[0]
                account = self.chain.state.get_account(addr)
                print(f"Address: {addr[:16]}...")
                print(f"  Balance: {account['balance']}")
                print(f"  Nonce: {account['nonce']}")
        
        elif command == "mempool":
            pending = self.mempool.get_pending_transactions()
            if pending:
                print(f"Pending transactions ({len(pending)}):")
                for tx in pending[:10]:  # Show first 10
                    print(f"  {tx.sender[:8]}... -> {tx.receiver[:8] if tx.receiver else 'deploy'}... : {tx.amount}")
                if len(pending) > 10:
                    print(f"  ... and {len(pending) - 10} more")
            else:
                print("Mempool is empty")
        
        elif command == "block":
            if not args:
                print("Usage: block <index>")
            else:
                try:
                    idx = int(args[0])
                    if 0 <= idx < len(self.chain.chain):
                        block = self.chain.chain[idx]
                        print(f"Block #{block.index}")
                        print(f"  Hash: {block.hash}")
                        print(f"  Prev: {block.previous_hash[:32]}...")
                        print(f"  Time: {block.timestamp}")
                        print(f"  Txns: {len(block.transactions)}")
                        print(f"  Difficulty: {block.difficulty}")
                        print(f"  Nonce: {block.nonce}")
                    else:
                        print(f"Block {idx} not found (height: {len(self.chain.chain)})")
                except ValueError:
                    print("Invalid block index")
        
        elif command == "mine":
            self.mining = not self.mining
            print(f"Mining: {'ON' if self.mining else 'OFF'}")
        
        elif command == "connect":
            if not args:
                print("Usage: connect <ip:port>")
            else:
                addr = args[0]
                print(f"Connecting to {addr}...")
                return ("connect", addr)
        
        elif command == "sync":
            print("Requesting chain sync...")
            # Will be handled in async context
            return "sync"
        
        else:
            print(f"Unknown command: {command}. Type 'help' for commands.")
        
        return True  # Continue running


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="MiniChain Testnet Node",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python cli.py --port 9000                          # Start first node
  python cli.py --port 9001 --peers 127.0.0.1:9000   # Connect to peer
  python cli.py --port 9000 --mine                   # Enable mining
        """
    )

    parser.add_argument(
        "--port", "-p",
        type=int,
        default=9000,
        help="Port to listen on (default: 9000)"
    )

    parser.add_argument(
        "--peers",
        type=str,
        default="",
        help="Comma-separated list of peer addresses (e.g., 192.168.1.10:9000,192.168.1.20:9001)"
    )

    parser.add_argument(
        "--mine",
        action="store_true",
        help="Enable mining"
    )

    parser.add_argument(
        "--miner",
        type=str,
        default=None,
        help="Miner wallet address for rewards"
    )

    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging"
    )

    return parser.parse_args()


# Module-level variable to store shutdown task
shutdown_task = None

async def run_node(args):
    """Run the node with given arguments."""
    global shutdown_task
    
    # Parse peers
    peers = []
    if args.peers:
        peers = [p.strip() for p in args.peers.split(",") if p.strip()]

    # Create and start node
    node = Node(
        port=args.port,
        peers=peers,
        mining=args.mine,
        miner_address=args.miner
    )

    # Handle shutdown signals
    loop = asyncio.get_event_loop()

    def shutdown_handler():
        global shutdown_task
        logger.info("Shutdown signal received")
        shutdown_task = asyncio.create_task(node.stop())

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, shutdown_handler)
        except NotImplementedError:
            # Windows doesn't support add_signal_handler
            pass

    try:
        await node.start()
    except KeyboardInterrupt:
        pass
    finally:
        # If shutdown was already initiated by signal handler, wait for it
        if shutdown_task is not None:
            try:
                await asyncio.wait_for(shutdown_task, timeout=5.0)
            except asyncio.TimeoutError:
                logger.warning("Shutdown task timed out")
        else:
            await node.stop()


def main():
    """Main entry point."""
    args = parse_args()

    # Setup logging
    level = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S"
    )

    print(f"""
╔══════════════════════════════════════════════╗
║          MiniChain Testnet Node              ║
╚══════════════════════════════════════════════╝
  Port: {args.port}
  Mining: {'Enabled' if args.mine else 'Disabled'}
  Peers: {args.peers if args.peers else 'None'}

  Type 'help' for available commands.
""")

    asyncio.run(run_node(args))


if __name__ == "__main__":
    main()
