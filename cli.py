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

        # Wait a bit for responses
        await asyncio.sleep(2)
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

        chain_data = [block.to_dict() for block in self.chain.chain]
        await self.network.send_chain(sender, chain_data)
        logger.info("Sent chain (%d blocks) to peer %s", len(chain_data), sender.node_id)

    async def _handle_chain(self, chain_data: list):
        """Handle received chain - validate and potentially replace ours."""
        if not chain_data:
            return

        logger.info("Received chain with %d blocks", len(chain_data))

        # Only replace if longer
        if len(chain_data) <= len(self.chain.chain):
            logger.info("Received chain not longer than ours, ignoring")
            return

        # Validate and replace
        if self.chain.replace_chain(chain_data):
            logger.info("Replaced chain with received chain (new height: %d)", len(self.chain.chain))
        else:
            logger.warning("Received chain validation failed")

    async def _run(self):
        """Main node loop."""
        logger.info("Node running. Press Ctrl+C to stop.")
        logger.info("Connected to %d peer(s)", self.network.get_peer_count())

        mine_interval = 10  # seconds between mining attempts
        last_mine_time = 0

        while self._running:
            try:
                # Mining loop
                if self.mining and self._sync_complete:
                    import time
                    now = time.time()
                    if now - last_mine_time >= mine_interval:
                        await self._try_mine_block()
                        last_mine_time = now

                # Keep event loop responsive
                await asyncio.sleep(1)

            except asyncio.CancelledError:
                break

    async def _try_mine_block(self):
        """Attempt to mine a new block."""
        pending_txs = self.mempool.get_transactions_for_block()

        block = Block(
            index=self.chain.last_block.index + 1,
            previous_hash=self.chain.last_block.hash,
            transactions=pending_txs,
        )

        try:
            # Mine with low difficulty for testnet
            mined_block = mine_block(block, difficulty=4, timeout_seconds=5)

            if self.chain.add_block(mined_block):
                logger.info("Mined block #%d! Hash: %s...", mined_block.index, mined_block.hash[:16])

                # Credit mining reward
                self.chain.state.credit_mining_reward(self.miner_address)

                # Broadcast to peers
                await self.network.broadcast_block(mined_block)

        except Exception as e:
            # Mining timeout or other error - this is normal
            pass


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


async def run_node(args):
    """Run the node with given arguments."""
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
        logger.info("Shutdown signal received")
        asyncio.create_task(node.stop())

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
""")

    asyncio.run(run_node(args))


if __name__ == "__main__":
    main()
