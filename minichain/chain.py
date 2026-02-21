from minichain.block import Block, create_genesis_block
from minichain.state import State
from minichain.pow import calculate_hash
from minichain.config import DIFFICULTY
from typing import List
import logging
import threading

logger = logging.getLogger(__name__)


class Blockchain:
    """
    Manages the blockchain, validates blocks, and commits state transitions.
    """

    def __init__(self):
        self.chain: List[Block] = []
        self.difficulty = DIFFICULTY
        self._lock = threading.RLock()
        self._create_genesis_block()

    def _create_genesis_block(self):
        """
        Creates the genesis block with treasury funds.
        """
        genesis_block = create_genesis_block()
        self.chain.append(genesis_block)

    @property
    def last_block(self) -> Block:
        """Returns the most recent block in the chain."""
        with self._lock:
            return self.chain[-1]

    @property
    def latest_block(self) -> Block:
        """Alias for last_block."""
        return self.last_block

    @property
    def height(self) -> int:
        """Get chain length."""
        return len(self.chain)

    def get_state(self) -> State:
        """Recompute current state by replaying all transactions from genesis."""
        state = State()
        for block in self.chain:
            for tx in block.transactions:
                state.apply_tx(tx)
        return state

    @property
    def state(self) -> State:
        """Get current state (computed from chain)."""
        return self.get_state()

    def add_block(self, block: Block) -> bool:
        """
        Validates and adds a block to the chain if all transactions succeed.
        """
        with self._lock:
            # Check previous hash linkage
            if block.previous_hash != self.last_block.hash:
                logger.warning(f"Block {block.index} rejected: Invalid previous hash (expected {self.last_block.hash[:16]}..., got {block.previous_hash[:16]}...)")
                return False

            # Check index linkage
            if block.index != self.last_block.index + 1:
                logger.warning("Block %s rejected: Invalid index", block.index)
                return False

            # Verify block hash
            if block.hash != calculate_hash(block.to_header_dict()):
                logger.warning("Block %s rejected: Invalid hash", block.index)
                return False

            # Check proof-of-work (skip for genesis)
            if block.index > 0 and not block.hash.startswith("0" * self.difficulty):
                logger.warning("Block %s rejected: Hash does not meet difficulty", block.index)
                return False

            # Validate transactions
            current_state = self.get_state()
            for tx in block.transactions:
                try:
                    current_state.apply_tx(tx)
                except ValueError as e:
                    logger.warning("Block %s rejected: Transaction failed - %s", block.index, e)
                    return False

            self.chain.append(block)
            return True

    def to_dict(self) -> dict:
        """Serialize chain for network transmission."""
        return {"blocks": [block.to_dict() for block in self.chain]}

    def replace_chain(self, new_chain_data: list) -> bool:
        """Replace chain if new one is longer and valid (longest-chain rule).
        
        Args:
            new_chain_data: List of block dicts from network
        """
        with self._lock:
            if len(new_chain_data) <= len(self.chain):
                logger.info("New chain is not longer")
                return False

            # Convert dicts to Block objects
            new_chain = []
            for block_data in new_chain_data:
                try:
                    new_chain.append(Block.from_dict(block_data))
                except Exception as e:
                    logger.warning(f"Failed to deserialize block: {e}")
                    return False

            # Validate the new chain
            if not self._is_valid_chain(new_chain):
                logger.warning("New chain is invalid")
                return False

            self.chain = new_chain
            logger.info("Chain replaced with %d blocks", len(new_chain))
            return True

    def _is_valid_chain(self, chain: List[Block]) -> bool:
        """Validate an entire chain from genesis."""
        if not chain:
            return False

        # Check genesis block matches expected
        expected_genesis = create_genesis_block()
        if chain[0].hash != expected_genesis.hash:
            logger.warning(f"Genesis mismatch: expected {expected_genesis.hash[:16]}..., got {chain[0].hash[:16]}...")
            return False

        # Validate each block
        state = State()
        for i, block in enumerate(chain):
            # Apply transactions
            for tx in block.transactions:
                try:
                    state.apply_tx(tx)
                except ValueError:
                    return False

            # Validate structure (skip genesis)
            if i > 0:
                prev = chain[i - 1]
                if block.previous_hash != prev.hash:
                    return False
                if block.index != prev.index + 1:
                    return False
                if not block.hash.startswith("0" * self.difficulty):
                    return False

        return True
