import json
import time
import hashlib
from nacl.signing import SigningKey, VerifyKey
from nacl.encoding import HexEncoder
from nacl.exceptions import BadSignatureError, CryptoError

# Coinbase sender address (for genesis and mining rewards)
COINBASE_SENDER = "0" * 64


class Transaction:
    def __init__(self, sender, receiver, amount, nonce, data=None, signature=None, timestamp=None):
        self.sender = sender        # Public key (Hex str)
        self.receiver = receiver    # Public key (Hex str) or None for Deploy
        self.amount = amount
        self.nonce = nonce
        self.data = data            # Preserve None (do NOT normalize to "")
        self.timestamp = round(timestamp * 1000) if timestamp is not None else round(time.time() * 1000) # Integer milliseconds for determinism
        self.signature = signature  # Hex str

    def to_dict(self):
        return {
            "sender": self.sender,
            "receiver": self.receiver,
            "amount": self.amount,
            "nonce": self.nonce,
            "data": self.data,
            "timestamp": self.timestamp,
            "signature": self.signature,
        }

    @staticmethod
    def from_dict(data: dict) -> "Transaction":
        """Create transaction from dictionary."""
        return Transaction(
            sender=data["sender"],
            receiver=data["receiver"],
            amount=data["amount"],
            nonce=data["nonce"],
            data=data.get("data"),
            signature=data.get("signature"),
            timestamp=data.get("timestamp") / 1000 if data.get("timestamp") else None,
        )

    def hash(self) -> str:
        """Get unique hash of this transaction."""
        return hashlib.sha256(self.hash_payload).hexdigest()

    @property
    def hash_payload(self):
        """Returns the bytes to be signed."""
        payload = {
            "sender": self.sender,
            "receiver": self.receiver,
            "amount": self.amount,
            "nonce": self.nonce,
            "data": self.data,
            "timestamp": self.timestamp, # Already integer milliseconds
        }
        return json.dumps(payload, sort_keys=True).encode("utf-8")

    def sign(self, signing_key: SigningKey):
        # Validate that the signing key matches the sender
        if signing_key.verify_key.encode(encoder=HexEncoder).decode() != self.sender:
            raise ValueError("Signing key does not match sender")
        signed = signing_key.sign(self.hash_payload)
        self.signature = signed.signature.hex()

    def sign_with_hex(self, private_key_hex: str):
        """Sign transaction with hex-encoded private key."""
        signing_key = SigningKey(private_key_hex.encode(), encoder=HexEncoder)
        signed = signing_key.sign(self.hash_payload)
        self.signature = signed.signature.hex()

    def is_coinbase(self) -> bool:
        """Check if this is a coinbase (genesis/reward) transaction."""
        return self.sender == COINBASE_SENDER

    def verify(self):
        # Coinbase transactions (genesis, mining rewards) need no signature
        if self.is_coinbase():
            return True

        if not self.signature:
            return False

        try:
            verify_key = VerifyKey(self.sender, encoder=HexEncoder)
            verify_key.verify(self.hash_payload, bytes.fromhex(self.signature))
            return True

        except (BadSignatureError, CryptoError, ValueError, TypeError):
            # Covers:
            # - Invalid signature
            # - Malformed public key hex
            # - Invalid hex in signature
            return False

    def __repr__(self):
        return f"Tx({self.sender[:8]}→{(self.receiver or 'CONTRACT')[:8]}, {self.amount})"


from minichain.config import GENESIS_TIMESTAMP


def create_genesis_tx(receiver: str, amount: int) -> Transaction:
    """Create a genesis transaction (no signature needed)."""
    return Transaction(
        sender=COINBASE_SENDER,
        receiver=receiver,
        amount=amount,
        nonce=0,
        signature=None,
        timestamp=GENESIS_TIMESTAMP,  # Deterministic timestamp
    )


def create_coinbase_tx(miner_address: str, reward: int, block_index: int) -> Transaction:
    """Create a coinbase (mining reward) transaction."""
    return Transaction(
        sender=COINBASE_SENDER,
        receiver=miner_address,
        amount=reward,
        nonce=block_index,  # Use block index as nonce to ensure uniqueness
        signature=None,
    )
