from .block import Block
from .transaction import Transaction
from .state import State
from .pow import calculate_hash
import logging
import threading

logger = logging.getLogger(__name__)


class Blockchain:
    """
    Manages the blockchain, validates blocks, and commits state transitions.
    """

    # Expected genesis hash (all zeros)
    GENESIS_HASH = "0" * 64

    def __init__(self):
        self.chain = []
        self.state = State()
        self._lock = threading.RLock()
        self._create_genesis_block()

    def _create_genesis_block(self):
        """
        Creates the genesis block with a fixed hash.
        """
        genesis_block = Block(
            index=0,
            previous_hash="0",
            transactions=[]
        )
        genesis_block.hash = self.GENESIS_HASH
        self.chain.append(genesis_block)

    @property
    def last_block(self):
        """
        Returns the most recent block in the chain.
        """
        with self._lock:  # Acquire lock for thread-safe access
            return self.chain[-1]

    @property
    def height(self):
        """Returns the current chain height (number of blocks)."""
        with self._lock:
            return len(self.chain)

    def add_block(self, block):
        """
        Validates and adds a block to the chain if all transactions succeed.
        Uses a copied State to ensure atomic validation.
        """

        with self._lock:
            # Check previous hash linkage
            if block.previous_hash != self.last_block.hash:
                logger.warning("Block %s rejected: Invalid previous hash %s != %s", block.index, block.previous_hash, self.last_block.hash)
                return False

            # Check index linkage
            if block.index != self.last_block.index + 1:
                logger.warning("Block %s rejected: Invalid index %s != %s", block.index, block.index, self.last_block.index + 1)
                return False

            # Verify block hash
            computed_hash = calculate_hash(block.to_header_dict())
            if block.hash != computed_hash:
                logger.warning("Block %s rejected: Invalid hash %s", block.index, block.hash)
                return False

            # Verify proof-of-work meets difficulty target
            difficulty = block.difficulty or 0
            if difficulty > 0:
                required_prefix = "0" * difficulty
                if not computed_hash.startswith(required_prefix):
                    logger.warning("Block %s rejected: Hash does not meet difficulty %d", block.index, difficulty)
                    return False

            # Validate transactions on a temporary state copy
            temp_state = self.state.copy()

            for tx in block.transactions:
                result = temp_state.validate_and_apply(tx)

                # Reject block if any transaction fails
                if not result:
                    logger.warning("Block %s rejected: Transaction failed validation", block.index)
                    return False

            # All transactions valid → commit state and append block
            self.state = temp_state
            self.chain.append(block)
            return True

    def validate_chain(self, chain_data: list) -> bool:
        """
        Validate a chain received from a peer.
        
        Checks:
        1. Genesis block matches our expected genesis
        2. Each block's hash is valid
        3. Each block's previous_hash links correctly
        4. All transactions in each block are valid
        
        Args:
            chain_data: List of block dictionaries
            
        Returns:
            True if chain is valid, False otherwise
        """
        if not chain_data:
            return False

        # Validate genesis block
        genesis = chain_data[0]
        if genesis.get("hash") != self.GENESIS_HASH:
            logger.warning("Chain validation failed: Invalid genesis hash")
            return False

        if genesis.get("index") != 0:
            logger.warning("Chain validation failed: Genesis index not 0")
            return False

        # Validate each subsequent block
        temp_state = State()  # Fresh state for validation
        
        for i in range(1, len(chain_data)):
            block_data = chain_data[i]
            prev_block = chain_data[i - 1]

            # Check index linkage
            if block_data.get("index") != prev_block.get("index") + 1:
                logger.warning("Chain validation failed: Invalid index at block %d", i)
                return False

            # Check previous hash linkage
            if block_data.get("previous_hash") != prev_block.get("hash"):
                logger.warning("Chain validation failed: Invalid previous_hash at block %d", i)
                return False

            # Reconstruct block and verify hash
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
                
                # Verify hash matches
                computed_hash = calculate_hash(block.to_header_dict())
                if block_data.get("hash") != computed_hash:
                    logger.warning("Chain validation failed: Invalid hash at block %d", i)
                    return False

                # Verify proof-of-work meets difficulty target
                difficulty = block_data.get("difficulty", 0) or 0
                if difficulty > 0:
                    required_prefix = "0" * difficulty
                    if not computed_hash.startswith(required_prefix):
                        logger.warning("Chain validation failed: Hash does not meet difficulty %d at block %d", difficulty, i)
                        return False

                # Validate and apply transactions
                for tx in transactions:
                    if not temp_state.validate_and_apply(tx):
                        logger.warning("Chain validation failed: Invalid tx in block %d", i)
                        return False

            except Exception as e:
                logger.warning("Chain validation failed at block %d: %s", i, e)
                return False

        return True

    def replace_chain(self, chain_data: list) -> bool:
        """
        Replace the current chain with a longer valid chain.
        
        Uses "longest valid chain wins" rule.
        
        Args:
            chain_data: List of block dictionaries from peer
            
        Returns:
            True if chain was replaced, False otherwise
        """
        with self._lock:
            # Only replace if longer (or equal during initial sync)
            if len(chain_data) < len(self.chain):
                logger.info("Received chain shorter than ours (%d < %d)", 
                           len(chain_data), len(self.chain))
                return False
            
            # If equal length, only replace if it validates (essentially a no-op for same chain)
            if len(chain_data) == len(self.chain):
                # Validate but don't bother replacing if identical
                if self.validate_chain(chain_data):
                    logger.debug("Received chain same length as ours and valid")
                    return True  # Consider it a successful sync
                return False

            # Validate the received chain
            if not self.validate_chain(chain_data):
                logger.warning("Received chain failed validation")
                return False

            # Build new chain and state locally for atomic replacement
            logger.info("Replacing chain: %d -> %d blocks", len(self.chain), len(chain_data))
            
            new_chain = []
            new_state = State()
            
            # Add genesis
            genesis_block = Block(
                index=0,
                previous_hash="0",
                transactions=[]
            )
            genesis_block.hash = self.GENESIS_HASH
            new_chain.append(genesis_block)

            # Add each subsequent block
            for i in range(1, len(chain_data)):
                block_data = chain_data[i]
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

                # Apply transactions to new state
                for tx in transactions:
                    if not new_state.validate_and_apply(tx):
                        logger.warning("Chain rebuild failed: Invalid tx in block %d", i)
                        return False

                new_chain.append(block)

            # Atomically assign new chain and state
            self.chain = new_chain
            self.state = new_state

            logger.info("Chain replaced successfully. New height: %d", len(self.chain))
            return True

    def to_dict_list(self) -> list:
        """Export chain as list of block dictionaries."""
        with self._lock:
            return [block.to_dict() for block in self.chain]
