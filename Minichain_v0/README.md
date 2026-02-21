# MiniChain v0 - Educational Blockchain

A minimal, educational blockchain implementation in Python

## Quick Start

```bash
cd Minichain_v0
pip install -r requirements.txt

# Using the launcher (recommended)
./minichain start 8000           # Bootstrap node
./minichain start 8001 8000      # Connect to port 8000
./minichain start 8002 8000      # Third node

# Or using Python directly
python3 main.py --port 8000
python3 main.py --port 8001 --connect localhost:8000
```

## Test Scenarios

### 1. Mining for rewards
```
mine                # Mine block (earns 50 coins)
balance             # Check balance
```

### 2. Distribute from treasury
```
treasury            # Check treasury balance
faucet <addr> 1000
mine               # Confirm transaction
```

### 3. Send coins
```
address                 # Show your address (copy recipient's)
send <addr> 100
mempool                # View mempool
mine                   # Confirm
```

## Commands

|---------|----------|-------------|
| `balance` | `b` | Show your balance |
| `address` | `a` | Show your wallet address |
| `send <addr> <amt>` | - | Send coins |
| `mine` | `m` | Mine block (+50 reward) |
| `faucet <addr> <amt>` | - | Treasury send |
| `treasury` | `t` | Show treasury balance |
| `chain` | `c` | Show blockchain |
| `peers` | `p` | Show connected peers |
| `mempool` | `mp` | Show pending transactions |
| `quit` | `q` | Exit |


## File and folder structure

| File | Lines | Description |
|------|-------|-------------|
| `config.py` | 19 | Configuration constants |
| `transaction.py` | 91 | Signed transactions (Ed25519) |
| `state.py` | 70 | Account balances and nonces |
| `block.py` | 80 | Block structure |
| `blockchain.py` | 133 | Chain validation and storage |
| `mempool.py` | 66 | Pending transaction pool |
| `consensus.py` | 40 | Proof-of-Work mining |
| `network.py` | 154 | P2P networking (TCP sockets) |
| `main.py` | 185 | CLI interface |
| `minichain` | - | Bash launcher script |


## What Users/Dev Learn

1. **Transactions** - Ed25519 digital signatures for authentication
2. **State** - Account-based ledger (balances + nonces)
3. **Blocks** - Linking transactions with hashes
4. **Consensus** - Proof-of-Work mining with rewards
5. **Networking** - P2P communication with TCP sockets


## Architecture

```
Transaction (signed) → Mempool → Block → Blockchain
                                   ↑
                           Consensus (PoW)
                                   ↓
                              Network → Peers
```


## Not Included (v0 Simplifications)

- ❌ Merkle trees (optimization)
- ❌ State snapshots (optimization)
- ❌ Persistence (in-memory only)
- ❌ GossipSub (using simpler streams)

## Progression Path

`v0` (currently we are here) → `v1` (optimizations) → `v2` (smart contracts)