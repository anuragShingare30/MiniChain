import time
import hashlib
import json
from typing import List, Optional
from minichain.transaction import Transaction, create_genesis_tx
from minichain.config import GENESIS_TIMESTAMP, TREASURY_ADDRESS, TREASURY_BALANCE


def _sha256(data: str) -> str:
    return hashlib.sha256(data.encode()).hexdigest()


def _calculate_merkle_root(transactions: List[Transaction]) -> Optional[str]:
    if not transactions:
        return None

    # Hash each transaction deterministically
    tx_hashes = [
        _sha256(json.dumps(tx.to_dict(), sort_keys=True))
        for tx in transactions
    ]

    # Build Merkle tree
    while len(tx_hashes) > 1:
        if len(tx_hashes) % 2 != 0:
            tx_hashes.append(tx_hashes[-1])  # duplicate last if odd

        new_level = []
        for i in range(0, len(tx_hashes), 2):
            combined = tx_hashes[i] + tx_hashes[i + 1]
            new_level.append(_sha256(combined))

        tx_hashes = new_level

    return tx_hashes[0]


class Block:
    def __init__(
        self,
        index: int,
        previous_hash: str,
        transactions: Optional[List[Transaction]] = None,
        timestamp: Optional[float] = None,
        difficulty: Optional[int] = None,
    ):
        self.index = index
        self.previous_hash = previous_hash
        self.transactions: List[Transaction] = transactions or []

        # Deterministic timestamp (ms)
        self.timestamp: int = (
            round(time.time() * 1000)
            if timestamp is None
            else int(timestamp)
        )

        self.difficulty: Optional[int] = difficulty
        self.nonce: int = 0
        self.hash: Optional[str] = None

        # NEW: compute merkle root once
        self.merkle_root: Optional[str] = _calculate_merkle_root(self.transactions)

    # -------------------------
    # HEADER (used for mining)
    # -------------------------
    def to_header_dict(self):
        return {
            "index": self.index,
            "previous_hash": self.previous_hash,
            "merkle_root": self.merkle_root,
            "timestamp": self.timestamp,
            "difficulty": self.difficulty,
            "nonce": self.nonce,
        }

    # -------------------------
    # BODY (transactions only)
    # -------------------------
    def to_body_dict(self):
        return {
            "transactions": [
                tx.to_dict() for tx in self.transactions
            ]
        }

    # -------------------------
    # FULL BLOCK
    # -------------------------
    def to_dict(self):
        return {
            **self.to_header_dict(),
            **self.to_body_dict(),
            "hash": self.hash,
        }

    # -------------------------
    # HASH CALCULATION
    # -------------------------
    def compute_hash(self) -> str:
        header_string = json.dumps(
            self.to_header_dict(),
            sort_keys=True
        )
        return _sha256(header_string)

    @staticmethod
    def from_dict(data: dict) -> "Block":
        """Create block from dictionary."""
        txs = [Transaction.from_dict(tx) for tx in data.get("transactions", [])]
        block = Block(
            index=data["index"],
            previous_hash=data["previous_hash"],
            transactions=txs,
            timestamp=data.get("timestamp"),
            difficulty=data.get("difficulty"),
        )
        block.nonce = data.get("nonce", 0)
        block.hash = data.get("hash")
        return block

    def __repr__(self):
        return f"Block(#{self.index}, txs={len(self.transactions)}, hash={self.hash[:8] if self.hash else 'None'})"


def create_genesis_block() -> "Block":
    """Create the genesis (first) block with treasury funds."""
    genesis_txs = [create_genesis_tx(TREASURY_ADDRESS, TREASURY_BALANCE)]

    block = Block(
        index=0,
        previous_hash="0" * 64,
        transactions=genesis_txs,
        timestamp=GENESIS_TIMESTAMP * 1000,  # Convert to ms
        difficulty=None,
    )
    block.nonce = 0
    block.hash = block.compute_hash()
    return block
