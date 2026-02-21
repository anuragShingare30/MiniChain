"""
main.py - CLI interface for MiniChain v0.
Simple command-line tool to run a blockchain node.
"""

import asyncio
import argparse
import os
from nacl.signing import SigningKey
from nacl.encoding import HexEncoder

from blockchain import Blockchain
from mempool import Mempool
from network import Network
from transaction import Transaction
from consensus import mine_block
from config import TREASURY_PRIVATE_KEY, TREASURY_ADDRESS


def get_wallet_file(port: int) -> str:
    """Get port-specific wallet filename."""
    return f"wallet_{port}.key"


def create_wallet(port: int) -> SigningKey:
    """Generate a new Ed25519 keypair and save to port-specific file."""
    wallet_file = get_wallet_file(port)
    
    if os.path.exists(wallet_file):
        # Load existing wallet
        with open(wallet_file, "rb") as f:
            return SigningKey(f.read())
    
    # Create new wallet
    key = SigningKey.generate()
    with open(wallet_file, "wb") as f:
        f.write(key.encode())
    
    address = key.verify_key.encode(encoder=HexEncoder).decode()
    print(f"✅ New wallet created for port {port}")
    print(f"📍 Your address: {address}")
    return key


def get_address(key: SigningKey) -> str:
    """Get address from signing key."""
    return key.verify_key.encode(encoder=HexEncoder).decode()


def print_banner(port: int, address: str, is_bootstrap: bool):
    """Print clean startup banner."""
    print()
    print("╔══════════════════════════════════════════════════════════════╗")
    print("║                    🔗 MINICHAIN v0                            ║")
    print("║               Educational Blockchain Node                    ║")
    print("╠══════════════════════════════════════════════════════════════╣")
    print(f"║  Port:    {port:<52}║")
    print(f"║  Address: {address[:20]}...{address[-8:]:<21}║")
    if is_bootstrap:
        print("║  Role:    Bootstrap Node (Treasury Access)                  ║")
    else:
        print("║  Role:    Peer Node                                         ║")
    print("╚══════════════════════════════════════════════════════════════╝")
    print()


def print_help():
    """Print organized help menu."""
    print()
    print("┌─────────────────── COMMANDS ───────────────────┐")
    print("│                                                │")
    print("│  💰 WALLET                                     │")
    print("│     balance (b)  - Show your balance           │")
    print("│     address (a)  - Show your wallet address    │")
    print("│                                                │")
    print("│  💸 TRANSACTIONS                               │")
    print("│     send <addr> <amt>  - Send coins            │")
    print("│     faucet <addr> <amt> - Treasury send        │")
    print("│     mempool (mp)  - View pending transactions  │")
    print("│                                                │")
    print("│  ⛏️  MINING                                     │")
    print("│     mine (m)     - Mine block (+50 reward)     │")
    print("│                                                │")
    print("│  🔍 INFO                                       │")
    print("│     chain (c)    - Show blockchain             │")
    print("│     peers (p)    - Show connected peers        │")
    print("│     treasury (t) - Show treasury balance       │")
    print("│                                                │")
    print("│  🚪 EXIT                                       │")
    print("│     quit (q)     - Exit node                   │")
    print("│                                                │")
    print("└────────────────────────────────────────────────┘")
    print()


async def run_node(args):
    """Run the blockchain node."""
    # Create/load port-specific wallet
    wallet = create_wallet(args.port)
    address = get_address(wallet)
    
    # Initialize blockchain (all nodes share same genesis with treasury)
    blockchain = Blockchain()
    mempool = Mempool()
    network = Network(blockchain, mempool)
    
    # Start network
    await network.start(args.port)
    
    is_bootstrap = not args.connect
    
    # Connect to bootstrap peer if provided (format: host:port)
    if args.connect:
        try:
            host, port = args.connect.rsplit(":", 1)
            await network.connect(host, int(port))
        except ValueError:
            print("❌ Invalid peer format. Use host:port, e.g., localhost:8001")
    
    # Print clean startup banner
    print_banner(args.port, address, is_bootstrap)
    
    # Show help on startup
    print("Type 'help' or 'h' for commands\n")
    
    while True:
        try:
            cmd = await asyncio.get_event_loop().run_in_executor(None, input, "minichain> ")
            cmd = cmd.strip().lower()
            
            if cmd == "quit" or cmd == "q":
                print("👋 Goodbye!")
                break
            
            elif cmd == "balance" or cmd == "b":
                state = blockchain.get_state()
                bal = state.get_balance(address)
                nonce = state.get_nonce(address)
                print(f"💰 Balance: {bal}")
                print(f"🔢 Nonce: {nonce}")
            
            elif cmd.startswith("send "):
                parts = cmd.split()
                if len(parts) != 3:
                    print("Usage: send <address> <amount>")
                    continue
                
                receiver = parts[1]
                amount = int(parts[2])
                state = blockchain.get_state()
                
                tx = Transaction(address, receiver, amount, state.get_nonce(address))
                tx.sign(wallet.encode(encoder=HexEncoder).decode())
                
                if mempool.add(tx, state):
                    print(f"✅ Transaction added to mempool")
                    await network.broadcast_tx(tx)
                    print(f"📡 Broadcasted to peers")
                else:
                    print("❌ Transaction rejected (check balance/nonce)")
            
            elif cmd == "mine" or cmd == "m":
                pending = mempool.get_pending()
                # Can mine even with no pending transactions (just for reward)
                
                block = mine_block(blockchain.latest_block, pending, address)
                
                if blockchain.add_block(block):
                    mempool.remove(pending)
                    await network.broadcast_block(block)
                    print(f"📡 Block broadcasted")
            
            elif cmd.startswith("faucet "):
                # Treasury sends coins to an address (only works on bootstrap node)
                parts = cmd.split()
                if len(parts) != 3:
                    print("Usage: faucet <address> <amount>")
                    continue
                
                receiver = parts[1]
                amount = int(parts[2])
                state = blockchain.get_state()
                
                # Create transaction from treasury
                treasury_key = SigningKey(TREASURY_PRIVATE_KEY.encode(), encoder=HexEncoder)
                treasury_nonce = state.get_nonce(TREASURY_ADDRESS)
                
                tx = Transaction(TREASURY_ADDRESS, receiver, amount, treasury_nonce)
                tx.sign(TREASURY_PRIVATE_KEY)
                
                if mempool.add(tx, state):
                    print(f"✅ Faucet transaction added to mempool")
                    print(f"   {amount} coins → {receiver[:16]}...")
                    await network.broadcast_tx(tx)
                    print(f"📡 Broadcasted. Mine a block to confirm!")
                else:
                    print("❌ Faucet failed (check treasury balance)")
            
            elif cmd == "chain" or cmd == "c":
                print(f"\n⛓️  Blockchain ({blockchain.height} blocks)")
                print("-" * 40)
                for block in blockchain.chain:
                    print(f"Block #{block.index}")
                    print(f"  Hash:     {block.hash[:16]}...")
                    print(f"  PrevHash: {block.prev_hash[:16]}...")
                    print(f"  Txs:      {len(block.transactions)}")
                    print()
            
            elif cmd == "peers" or cmd == "p":
                if not network.peers:
                    print("No connected peers")
                else:
                    for host, port in network.peers:
                        print(f"👤 {host}:{port}")
            
            elif cmd == "mempool" or cmd == "mp":
                print(f"📋 Mempool: {len(mempool)} pending transactions")
                for tx in mempool.transactions:
                    print(f"  {tx}")
            
            elif cmd == "address" or cmd == "addr" or cmd == "a":
                print(f"📍 Your address: {address}")
            
            elif cmd == "treasury" or cmd == "t":
                state = blockchain.get_state()
                bal = state.get_balance(TREASURY_ADDRESS)
                print(f"🏦 Treasury address: {TREASURY_ADDRESS}")
                print(f"💰 Treasury balance: {bal}")
            
            elif cmd == "help" or cmd == "h":
                print_help()
            
            elif cmd:
                print("Unknown command. Type 'help' for commands.")
                
        except KeyboardInterrupt:
            print("\n👋 Goodbye!")
            break
        except EOFError:
            break
        except Exception as e:
            print(f"Error: {e}")


def main():
    parser = argparse.ArgumentParser(description="MiniChain v0 - Educational Blockchain")
    parser.add_argument("--port", type=int, default=8000, help="P2P port (default: 8000)")
    parser.add_argument("--connect", type=str, help="Bootstrap peer address to connect")
    
    args = parser.parse_args()
    asyncio.run(run_node(args))


if __name__ == "__main__":
    main()
