"""
state.py - Account state management for MiniChain.
Tracks balances and nonces for all accounts.
"""

from transaction import Transaction


class State:
    """The current state of all accounts (balances and nonces)."""
    
    def __init__(self):
        self.accounts = {}  # {address: {"balance": int, "nonce": int}}
    
    def get_balance(self, address: str) -> int:
        """Get account balance (0 if account doesn't exist)."""
        return self.accounts.get(address, {"balance": 0})["balance"]
    
    def get_nonce(self, address: str) -> int:
        """Get account nonce (0 if account doesn't exist)."""
        return self.accounts.get(address, {"nonce": 0})["nonce"]
    
    def exists(self, address: str) -> bool:
        """Check if account exists."""
        return address in self.accounts
    
    def create_account(self, address: str, balance: int = 0):
        """Create new account with given balance."""
        if address not in self.accounts:
            self.accounts[address] = {"balance": balance, "nonce": 0}


def apply_tx(state: State, tx: Transaction) -> State:
    """
    Apply transaction to state and return new state.
    Raises ValueError if transaction is invalid.
    This is the core state transition function of the blockchain.
    """
    # Genesis transaction: just create receiver account
    if tx.sender == "0" * 64:
        state.create_account(tx.receiver, tx.amount)
        return state
    
    # Validate sender exists
    if not state.exists(tx.sender):
        raise ValueError(f"Sender {tx.sender[:8]} does not exist")
    
    # Validate signature
    if not tx.verify():
        raise ValueError("Invalid signature")
    
    # Validate nonce (prevents replay attacks)
    expected_nonce = state.get_nonce(tx.sender)
    if tx.nonce != expected_nonce:
        raise ValueError(f"Bad nonce: expected {expected_nonce}, got {tx.nonce}")
    
    # Validate balance
    if state.get_balance(tx.sender) < tx.amount:
        raise ValueError(f"Insufficient balance")
    
    # Apply changes
    state.accounts[tx.sender]["balance"] -= tx.amount
    state.accounts[tx.sender]["nonce"] += 1
    
    # Create receiver if needed
    if not state.exists(tx.receiver):
        state.create_account(tx.receiver)
    state.accounts[tx.receiver]["balance"] += tx.amount
    
    return state
