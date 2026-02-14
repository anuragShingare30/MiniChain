import time
from typing import List, Optional, Union
from core.transaction import Transaction  # Assuming Transaction is defined in core.transaction

class Block:
    def __init__(self, index: int, previous_hash: str, transactions: List[Transaction], timestamp: Optional[float] = None, difficulty: Optional[int] = None):
        self.index = index
        self.previous_hash = previous_hash
        self.transactions: List[Transaction] = transactions if transactions is not None else [] # Ensure transactions is a list
        # Use integer milliseconds for timestamp for determinism
        self.timestamp: int = round(time.time() * 1000) if timestamp is None else round(timestamp * 1000)
        # Ensure difficulty is an integer
        self.nonce: int = 0
        self.hash: Optional[str] = None
        self.difficulty: Optional[int] = difficulty

    def _base_dict(self):
        """Shared dictionary building logic."""
        return {
            "index": self.index,
            "previous_hash": self.previous_hash,
            "transactions": [tx.to_dict() for tx in (self.transactions or [])],
            "timestamp": self.timestamp,
            "difficulty": self.difficulty,
            "nonce": self.nonce
        }

    def to_dict(self):
        """Full block data for serialization/transport."""
        data = self._base_dict()
        data["hash"] = self.hash
        return data

    def to_header_dict(self):
        """Data used for mining (consensus)."""
        return self._base_dict()
