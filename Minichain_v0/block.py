"""
block.py - Block structure for MiniChain.
A block contains transactions and links to the previous block via hash.
"""

import json
import hashlib
import time
from typing import List
from transaction import Transaction, create_genesis_tx
from config import GENESIS_TIMESTAMP, TREASURY_ADDRESS, TREASURY_BALANCE


class Block:
    """A block in the blockchain containing transactions."""
    
    def __init__(self, index: int, prev_hash: str, transactions: List[Transaction],
                 timestamp: float = None, nonce: int = 0):
        self.index = index
        self.prev_hash = prev_hash
        self.transactions = transactions
        self.timestamp = timestamp or time.time()
        self.nonce = nonce
        self.hash = self.compute_hash()
    
    def compute_hash(self) -> str:
        """Compute SHA-256 hash of block header."""
        header = {
            "index": self.index,
            "prev_hash": self.prev_hash,
            "tx_hashes": [tx.hash() for tx in self.transactions],
            "timestamp": self.timestamp,
            "nonce": self.nonce
        }
        header_bytes = json.dumps(header, sort_keys=True).encode()
        return hashlib.sha256(header_bytes).hexdigest()
    
    def to_dict(self) -> dict:
        """Convert block to dictionary for serialization."""
        return {
            "index": self.index,
            "prev_hash": self.prev_hash,
            "transactions": [tx.to_dict() for tx in self.transactions],
            "timestamp": self.timestamp,
            "nonce": self.nonce,
            "hash": self.hash
        }
    
    @staticmethod
    def from_dict(data: dict) -> "Block":
        """Create block from dictionary."""
        txs = [Transaction.from_dict(tx) for tx in data["transactions"]]
        block = Block(
            index=data["index"],
            prev_hash=data["prev_hash"],
            transactions=txs,
            timestamp=data["timestamp"],
            nonce=data["nonce"]
        )
        return block
    
    def __repr__(self):
        return f"Block(#{self.index}, txs={len(self.transactions)}, hash={self.hash[:8]})"


def create_genesis_block() -> Block:
    """Create the genesis (first) block with treasury funds."""
    # Genesis funds go to the fixed treasury address
    genesis_txs = [create_genesis_tx(TREASURY_ADDRESS, TREASURY_BALANCE)]
    
    return Block(
        index=0,
        prev_hash="0" * 64,
        transactions=genesis_txs,
        timestamp=GENESIS_TIMESTAMP,
        nonce=0
    )
