"""
config.py - MiniChain configuration constants.
Simple settings for the blockchain.
"""

# Proof-of-Work difficulty (number of leading zeros required)
DIFFICULTY = 4

# Genesis block timestamp (fixed for reproducibility)
GENESIS_TIMESTAMP = 1704067200.0

# Initial treasury balance (distributed via faucet to nodes)
TREASURY_BALANCE = 10000000

# Mining reward per block
MINING_REWARD = 50

# Maximum transactions per block
MAX_TXS_PER_BLOCK = 100

# Network protocol ID
PROTOCOL_ID = "/minichain/1.0.0"

# Special addresses
COINBASE_SENDER = "0" * 64  # Mining rewards come from "nowhere"

# Pre-generated treasury keypair (Ed25519, hex-encoded)
# This is a FIXED keypair for educational/testing purposes
# In production, this would be securely managed
TREASURY_PRIVATE_KEY = "b705c5f56f218a2003f940f3d7d825ee7369c504ba3ad5fda8a2303f4b3c5e26"
TREASURY_ADDRESS = "6b97d4ed320c6a8d1400dc034e183fd4678c4aa3f6301edf92e1cb4bd6337f44"
