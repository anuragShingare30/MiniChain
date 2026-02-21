"""
blockchain.py - Chain management for MiniChain.
Stores blocks, validates new blocks, and handles longest-chain rule.
"""

from typing import List
from block import Block, create_genesis_block
from state import State, apply_tx
from config import DIFFICULTY


class Blockchain:
    """The blockchain: a list of validated blocks."""
    
    def __init__(self):
        genesis = create_genesis_block()
        self.chain: List[Block] = [genesis]
        self.difficulty = DIFFICULTY
    
    @property
    def latest_block(self) -> Block:
        """Get the most recent block."""
        return self.chain[-1]
    
    @property
    def height(self) -> int:
        """Get chain length."""
        return len(self.chain)
    
    def get_state(self) -> State:
        """Recompute current state by replaying all transactions from genesis."""
        state = State()
        for block in self.chain:
            for tx in block.transactions:
                state = apply_tx(state, tx)
        return state
    
    def validate_block(self, block: Block, prev_block: Block) -> bool:
        """Check if a block is valid (structure, PoW, transactions)."""
        # Check index is sequential
        if block.index != prev_block.index + 1:
            print(f"Invalid index: expected {prev_block.index + 1}, got {block.index}")
            return False
        
        # Check previous hash links correctly
        if block.prev_hash != prev_block.hash:
            print("Invalid previous hash")
            return False
        
        # Check hash is correct
        if block.hash != block.compute_hash():
            print("Invalid hash")
            return False
        
        # Check proof-of-work
        if not block.hash.startswith("0" * self.difficulty):
            print("Hash does not meet difficulty")
            return False
        
        return True
    
    def validate_block_transactions(self, block: Block, state: State) -> bool:
        """Validate all transactions in block against given state."""
        try:
            for tx in block.transactions:
                state = apply_tx(state, tx)
            return True
        except ValueError as e:
            print(f"Transaction validation failed: {e}")
            return False
    
    def add_block(self, block: Block) -> bool:
        """Add a new block to the chain if valid."""
        # Validate block structure and PoW
        if not self.validate_block(block, self.latest_block):
            return False
        
        # Validate transactions against current state
        current_state = self.get_state()
        if not self.validate_block_transactions(block, current_state):
            return False
        
        self.chain.append(block)
        return True
    
    def is_valid_chain(self, chain: List[Block]) -> bool:
        """Validate an entire chain from genesis."""
        if not chain:
            return False
        
        # Check genesis block matches expected
        expected_genesis = create_genesis_block()
        if chain[0].hash != expected_genesis.hash:
            return False
        
        # Validate each block
        state = State()
        for i, block in enumerate(chain):
            # Apply transactions
            try:
                for tx in block.transactions:
                    state = apply_tx(state, tx)
            except ValueError:
                return False
            
            # Validate structure (skip genesis)
            if i > 0 and not self.validate_block(block, chain[i - 1]):
                return False
        
        return True
    
    def replace_chain(self, new_chain: List[Block]) -> bool:
        """Replace chain if new one is longer and valid (longest-chain rule)."""
        if len(new_chain) <= len(self.chain):
            print("New chain is not longer")
            return False
        
        if not self.is_valid_chain(new_chain):
            print("New chain is invalid")
            return False
        
        self.chain = new_chain
        print(f"Chain replaced with {len(new_chain)} blocks")
        return True
    
    def to_dict(self) -> List[dict]:
        """Serialize chain for network transmission."""
        return [block.to_dict() for block in self.chain]
    
    @staticmethod
    def from_dict(data: List[dict]) -> List[Block]:
        """Deserialize chain from network."""
        return [Block.from_dict(b) for b in data]
