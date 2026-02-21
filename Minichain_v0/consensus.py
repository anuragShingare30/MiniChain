"""
consensus.py - Proof-of-Work mining for MiniChain.
Finds a nonce that makes the block hash start with required zeros.
"""

import time
from typing import List
from block import Block
from transaction import Transaction, create_coinbase_tx
from config import DIFFICULTY, MINING_REWARD


def mine_block(prev_block: Block, transactions: List[Transaction], 
               miner_address: str, difficulty: int = DIFFICULTY) -> Block:
    """
    Mine a new block using Proof-of-Work.
    Includes coinbase transaction as mining reward.
    Increments nonce until hash has required leading zeros.
    """
    index = prev_block.index + 1
    prev_hash = prev_block.hash
    timestamp = time.time()
    nonce = 0
    
    # Add coinbase (mining reward) as first transaction
    coinbase = create_coinbase_tx(miner_address, MINING_REWARD, index)
    all_txs = [coinbase] + transactions
    
    print(f"⛏️  Mining block #{index} with {len(all_txs)} transactions (including coinbase)...")
    print(f"💰 Mining reward: {MINING_REWARD} coins")
    start = time.time()
    
    # Try nonces until we find valid hash
    while True:
        block = Block(index, prev_hash, all_txs, timestamp, nonce)
        
        if block.hash.startswith("0" * difficulty):
            elapsed = time.time() - start
            print(f"✅ Mined! Hash: {block.hash}")
            print(f"⏱️  Time: {elapsed:.2f}s, Nonce: {nonce}")
            return block
        
        nonce += 1
        
        # Progress indicator
        if nonce % 50000 == 0:
            print(f"   Trying nonce {nonce}...")
