"""
mempool.py - Transaction pool for MiniChain.
Holds pending transactions before they are mined into a block.
"""

from typing import List, Set
from transaction import Transaction
from state import State
from config import MAX_TXS_PER_BLOCK


class Mempool:
    """Pool of pending transactions waiting to be mined."""
    
    def __init__(self):
        self.transactions: List[Transaction] = []
        self._seen_hashes: Set[str] = set()  # Prevent duplicates
    
    def add(self, tx: Transaction, state: State) -> bool:
        """Add transaction to mempool if valid. Returns True if added."""
        tx_hash = tx.hash()
        
        # Reject duplicates
        if tx_hash in self._seen_hashes:
            return False
        
        # Validate signature
        if not tx.verify():
            return False
        
        # Validate against current state (skip genesis txs)
        if tx.sender != "0" * 64:
            # Check sender exists
            if not state.exists(tx.sender):
                return False
            
            # Check nonce
            if tx.nonce != state.get_nonce(tx.sender):
                return False
            
            # Check balance
            if state.get_balance(tx.sender) < tx.amount:
                return False
        
        # Add to pool
        self.transactions.append(tx)
        self._seen_hashes.add(tx_hash)
        return True
    
    def get_pending(self, max_count: int = MAX_TXS_PER_BLOCK) -> List[Transaction]:
        """Get pending transactions for mining (FIFO order)."""
        return self.transactions[:max_count]
    
    def remove(self, txs: List[Transaction]):
        """Remove transactions (after they are mined)."""
        hashes_to_remove = {tx.hash() for tx in txs}
        self.transactions = [tx for tx in self.transactions if tx.hash() not in hashes_to_remove]
        self._seen_hashes -= hashes_to_remove
    
    def clear(self):
        """Clear all pending transactions."""
        self.transactions.clear()
        self._seen_hashes.clear()
    
    def __len__(self):
        return len(self.transactions)
