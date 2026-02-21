"""
transaction.py - Signed transactions for MiniChain.
Uses Ed25519 signatures via PyNaCl for authentication.
"""

import json
import hashlib
from nacl.signing import SigningKey, VerifyKey
from nacl.encoding import HexEncoder


class Transaction:
    """A signed transfer of value from sender to receiver"""
    
    def __init__(self, sender: str, receiver: str, amount: int, nonce: int, signature: str = None):
        self.sender = sender      # Public key (hex) of sender
        self.receiver = receiver  # Public key (hex) of receiver
        self.amount = amount      # Amount to transfer
        self.nonce = nonce        # Sender's transaction count (replay protection)
        self.signature = signature  # Ed25519 signature (hex)
    
    def to_bytes(self) -> bytes:
        """Serialize transaction for signing (deterministic JSON)."""
        data = {
            "sender": self.sender,
            "receiver": self.receiver,
            "amount": self.amount,
            "nonce": self.nonce
        }
        return json.dumps(data, sort_keys=True).encode()
    
    def hash(self) -> str:
        """Get unique hash of this transaction."""
        return hashlib.sha256(self.to_bytes()).hexdigest()
    
    def sign(self, private_key_hex: str):
        """Sign transaction with sender's private key."""
        signing_key = SigningKey(private_key_hex.encode(), encoder=HexEncoder)
        signed = signing_key.sign(self.to_bytes())
        self.signature = signed.signature.hex()
    
    def verify(self) -> bool:
        """Verify signature is valid. Genesis transactions (sender=0x00...) are always valid."""
        # Genesis transactions need no signature
        if self.sender == "0" * 64:
            return True
        
        if not self.signature:
            return False
        
        try:
            verify_key = VerifyKey(self.sender.encode(), encoder=HexEncoder)
            verify_key.verify(self.to_bytes(), bytes.fromhex(self.signature))
            return True
        except Exception:
            return False
    
    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "sender": self.sender,
            "receiver": self.receiver,
            "amount": self.amount,
            "nonce": self.nonce,
            "signature": self.signature
        }
    
    @staticmethod
    def from_dict(data: dict) -> "Transaction":
        """Create transaction from dictionary."""
        return Transaction(
            sender=data["sender"],
            receiver=data["receiver"],
            amount=data["amount"],
            nonce=data["nonce"],
            signature=data.get("signature")
        )
    
    def __repr__(self):
        return f"Tx({self.sender[:8]}→{self.receiver[:8]}, {self.amount})"


def create_genesis_tx(receiver: str, amount: int) -> Transaction:
    """Create a genesis transaction (no signature needed)."""
    return Transaction(
        sender="0" * 64,  # System address
        receiver=receiver,
        amount=amount,
        nonce=0,
        signature=None
    )


def create_coinbase_tx(miner_address: str, reward: int, block_index: int) -> Transaction:
    """Create a coinbase (mining reward) transaction."""
    return Transaction(
        sender="0" * 64,  # System address (coins created from nothing)
        receiver=miner_address,
        amount=reward,
        nonce=block_index,  # Use block index as nonce to ensure uniqueness
        signature=None
    )
