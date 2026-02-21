#!/usr/bin/env python3
"""
MiniChain CLI - Node-based blockchain interface with P2P networking.

Usage: 
    python3 cli.py --port 8000              # Start node on port 8000
    python3 cli.py --port 8001 --connect 8000   # Start and connect to peer
"""

import argparse
import json
import os
import sys
import logging
import time
from typing import Optional

from nacl.signing import SigningKey
from nacl.encoding import HexEncoder

from minichain import (
    Block,
    Blockchain,
    Transaction,
    Mempool,
    mine_block,
    calculate_hash,
)
from minichain.p2p import P2PNetwork
from minichain.config import TREASURY_ADDRESS, TREASURY_PRIVATE_KEY, DIFFICULTY

# Logging - quieter by default
logging.basicConfig(level=logging.WARNING, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

WALLET_DIR = "wallets"

# ANSI Colors
class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BOLD = '\033[1m'
    DIM = '\033[2m'
    RESET = '\033[0m'

def c(text, color):
    """Colorize text."""
    return f"{color}{text}{Colors.RESET}"


class Node:
    """Blockchain node with wallet, chain, mempool, and P2P."""
    
    def __init__(self, port: int):
        self.port = port
        self.blockchain = Blockchain()
        self.mempool = Mempool()
        self.p2p = P2PNetwork(self, port)
        
        # Load or create wallet for this port
        self.wallet_name = f"wallet_{port}"
        self.signing_key, self.address = self._load_or_create_wallet()
        
    def _load_or_create_wallet(self):
        """Load existing wallet or create new one for this port."""
        os.makedirs(WALLET_DIR, exist_ok=True)
        path = os.path.join(WALLET_DIR, f"{self.wallet_name}.key")
        
        if os.path.exists(path):
            with open(path) as f:
                sk = SigningKey(bytes.fromhex(f.read().strip()))
            logger.info(f"Loaded wallet from {path}")
        else:
            sk = SigningKey.generate()
            with open(path, "w") as f:
                f.write(sk.encode().hex())
            logger.info(f"Created new wallet: {path}")
            
        pk = sk.verify_key.encode(encoder=HexEncoder).decode()
        return sk, pk

    @property
    def chain(self):
        return self.blockchain


class MiniChainCLI:
    """Node-based CLI for MiniChain with P2P networking."""

    def __init__(self, port: int, connect_port: Optional[int] = None):
        self.node = Node(port)
        self.connect_port = connect_port
        self.nonce_map = {}

    # === NODE INFO ===

    def cmd_address(self, args):
        """address - Show node wallet address"""
        addr = self.node.address
        return (
            f"{c('Address:', Colors.CYAN)} {addr}\n"
            f"{c('Short:', Colors.DIM)}   {addr[:16]}...{addr[-8:]}"
        )

    def cmd_peers(self, args):
        """peers - Show connected peers"""
        peers = self.node.p2p.peer_list
        if not peers:
            return c("No connected peers", Colors.DIM)
        header = c(f"Connected Peers ({len(peers)}):", Colors.CYAN)
        peer_list = "\n".join(f"  • {p}" for p in peers)
        return f"{header}\n{peer_list}"

    def cmd_status(self, args):
        """status - Show node status overview"""
        bal = self.node.blockchain.state.get_balance(self.node.address)
        peers = len(self.node.p2p.peer_list)
        height = self.node.blockchain.height
        mempool = len(self.node.mempool._pending_txs)
        
        return (
            f"{c('═══ Node Status ═══', Colors.BOLD)}\n"
            f"  Port:     {c(self.node.port, Colors.CYAN)}\n"
            f"  Balance:  {c(f'{bal:,}', Colors.GREEN)} coins\n"
            f"  Peers:    {c(peers, Colors.YELLOW)}\n"
            f"  Height:   {c(height, Colors.BLUE)} blocks\n"
            f"  Mempool:  {c(mempool, Colors.DIM)} pending tx"
        )

    def cmd_treasury(self, args):
        """treasury - Show treasury info"""
        bal = self.node.blockchain.state.get_balance(TREASURY_ADDRESS)
        return (
            f"{c('═══ Treasury ═══', Colors.BOLD)}\n"
            f"  Address:  {TREASURY_ADDRESS[:24]}...\n"
            f"  Balance:  {c(f'{bal:,}', Colors.GREEN)} coins"
        )

    def cmd_faucet(self, args):
        """faucet [amount] - Request coins from treasury (default: 100)"""
        try:
            amt = int(args[0]) if args else 100
        except ValueError:
            return c("Amount must be a number", Colors.RED)
        
        if amt > 10000:
            return c("Maximum faucet amount is 10,000 coins", Colors.RED)
        
        # Check treasury balance
        treasury_bal = self.node.blockchain.state.get_balance(TREASURY_ADDRESS)
        if treasury_bal < amt:
            return c(f"Treasury has insufficient funds ({treasury_bal})", Colors.RED)
        
        # Create transaction from treasury to node wallet
        nonce = self.node.blockchain.state.get_nonce(TREASURY_ADDRESS)
        tx = Transaction(
            sender=TREASURY_ADDRESS,
            receiver=self.node.address,
            amount=amt,
            nonce=nonce
        )
        tx.sign_with_hex(TREASURY_PRIVATE_KEY)
        
        if self.node.mempool.add_transaction(tx):
            return (
                f"{c('✓', Colors.GREEN)} Faucet request: {c(f'{amt}', Colors.GREEN)} coins\n"
                f"  To: {self.node.address[:24]}...\n"
                f"  {c('→ Run', Colors.DIM)} {c('mine', Colors.YELLOW)} {c('to confirm', Colors.DIM)}"
            )
        return c("✗ Faucet request rejected", Colors.RED)

    # === BLOCKCHAIN ===

    def cmd_chain(self, args):
        """chain - Show blockchain info"""
        last = self.node.blockchain.last_block
        height = self.node.blockchain.height
        return (
            f"{c('═══ Blockchain ═══', Colors.BOLD)}\n"
            f"  Height:     {c(height, Colors.CYAN)} blocks\n"
            f"  Last Block: {c(f'#{last.index}', Colors.BLUE)}\n"
            f"  Last Hash:  {last.hash[:32]}...\n"
            f"  Difficulty: {c(DIFFICULTY, Colors.YELLOW)}"
        )

    def cmd_block(self, args):
        """block [n] - Show block details (default: latest)"""
        if args:
            try:
                idx = int(args[0])
            except ValueError:
                return c("Index must be a number", Colors.RED)
        else:
            idx = self.node.blockchain.last_block.index
            
        if idx < 0 or idx >= len(self.node.blockchain.chain):
            return c(f"Block {idx} not found", Colors.RED)
        
        b = self.node.blockchain.chain[idx]
        tx_count = len(b.transactions)
        
        lines = [
            f"{c(f'═══ Block #{b.index} ═══', Colors.BOLD)}",
            f"  Hash:       {b.hash[:32]}...",
            f"  Prev Hash:  {b.previous_hash[:32]}...",
            f"  Timestamp:  {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(b.timestamp/1000))}",
            f"  Nonce:      {b.nonce}",
            f"  Txs:        {c(tx_count, Colors.CYAN)}",
        ]
        
        if tx_count > 0:
            lines.append(f"\n  {c('Transactions:', Colors.DIM)}")
            for i, tx in enumerate(b.transactions[:5]):
                sender = tx.sender[:8] if tx.sender else "COINBASE"
                receiver = tx.receiver[:8] if tx.receiver else "CONTRACT"
                lines.append(f"    {i+1}. {sender}... → {receiver}... ({tx.amount})")
            if tx_count > 5:
                lines.append(f"    ... and {tx_count - 5} more")
        
        return "\n".join(lines)

    def cmd_mine(self, args):
        """mine - Mine pending transactions"""
        miner = self.node.address
        txs = self.node.mempool.get_transactions_for_block()

        print(c("Mining...", Colors.DIM), end=" ", flush=True)
        
        block = Block(
            index=self.node.blockchain.last_block.index + 1,
            previous_hash=self.node.blockchain.last_block.hash,
            transactions=txs,
            difficulty=DIFFICULTY,
        )

        try:
            start = time.time()
            mined = mine_block(block, difficulty=DIFFICULTY)
            elapsed = time.time() - start
            
            if self.node.blockchain.add_block(mined):
                self.node.blockchain.state.credit_mining_reward(miner)
                for tx in txs:
                    self._sync_nonce(tx.sender)
                
                # Broadcast to peers
                self.node.p2p.broadcast_block_sync(mined)
                
                new_bal = self.node.blockchain.state.get_balance(miner)
                
                return (
                    f"\r{c('✓ Block Mined!', Colors.GREEN)}                    \n"
                    f"  Block:    {c(f'#{mined.index}', Colors.CYAN)}\n"
                    f"  Hash:     {mined.hash[:24]}...\n"
                    f"  Txs:      {len(txs)} processed\n"
                    f"  Time:     {elapsed:.2f}s\n"
                    f"  Reward:   {c('+50', Colors.GREEN)} coins\n"
                    f"  Balance:  {c(f'{new_bal:,}', Colors.GREEN)} coins"
                )
            return c("\r✗ Block rejected", Colors.RED)
        except Exception as e:
            return c(f"\r✗ Mining failed: {e}", Colors.RED)

    # === TRANSACTIONS ===

    def cmd_send(self, args):
        """send <to> <amount> - Send coins"""
        if len(args) < 2:
            return f"Usage: {c('send <address> <amount>', Colors.YELLOW)}"

        to = args[0]
        try:
            amt = int(args[1])
        except ValueError:
            return c("Amount must be a number", Colors.RED)

        # Check balance
        bal = self.node.blockchain.state.get_balance(self.node.address)
        if bal < amt:
            return c(f"Insufficient balance ({bal} < {amt})", Colors.RED)

        sender = self.node.address
        nonce = self._get_nonce(sender)

        tx = Transaction(sender=sender, receiver=to, amount=amt, nonce=nonce)
        tx.sign(self.node.signing_key)

        if self.node.mempool.add_transaction(tx):
            # Broadcast to peers
            self.node.p2p.broadcast_transaction_sync(tx)
            
            return (
                f"{c('✓', Colors.GREEN)} Transaction submitted\n"
                f"  From:   {self.node.wallet_name}\n"
                f"  To:     {to[:24]}...\n"
                f"  Amount: {c(amt, Colors.YELLOW)} coins\n"
                f"  {c('→ Run', Colors.DIM)} {c('mine', Colors.YELLOW)} {c('to confirm', Colors.DIM)}"
            )
        return c("✗ Transaction rejected", Colors.RED)

    def cmd_deploy(self, args):
        """deploy - Deploy a smart contract"""
        print(f"{c('Enter contract code (empty line to finish):', Colors.CYAN)}")
        lines = []
        while True:
            try:
                line = input(c("  | ", Colors.DIM))
                if line == "":
                    break
                lines.append(line)
            except EOFError:
                break

        if not lines:
            return c("No code entered", Colors.RED)

        code = "\n".join(lines)
        sender = self.node.address
        nonce = self._get_nonce(sender)

        tx = Transaction(sender=sender, receiver=None, amount=0, nonce=nonce, data=code)
        tx.sign(self.node.signing_key)

        if self.node.mempool.add_transaction(tx):
            addr = self.node.blockchain.state.derive_contract_address(sender, nonce + 1)
            return (
                f"{c('✓', Colors.GREEN)} Contract deployment submitted\n"
                f"  Expected address: {addr[:32]}...\n"
                f"  {c('→ Run', Colors.DIM)} {c('mine', Colors.YELLOW)} {c('to deploy', Colors.DIM)}"
            )
        return c("✗ Deployment rejected", Colors.RED)

    def cmd_call(self, args):
        """call <contract> <data> - Call contract"""
        if len(args) < 2:
            return f"Usage: {c('call <contract> <data>', Colors.YELLOW)}"

        contract, data = args[0], " ".join(args[1:])
        sender = self.node.address
        nonce = self._get_nonce(sender)

        tx = Transaction(sender=sender, receiver=contract, amount=0, nonce=nonce, data=data)
        tx.sign(self.node.signing_key)

        if self.node.mempool.add_transaction(tx):
            return (
                f"{c('✓', Colors.GREEN)} Contract call submitted\n"
                f"  {c('→ Run', Colors.DIM)} {c('mine', Colors.YELLOW)} {c('to execute', Colors.DIM)}"
            )
        return c("✗ Call rejected", Colors.RED)

    # === ACCOUNT ===

    def cmd_balance(self, args):
        """balance [address] - Check balance"""
        if args:
            addr = args[0]
            label = addr[:16] + "..."
        else:
            addr = self.node.address
            label = self.node.wallet_name
            
        bal = self.node.blockchain.state.get_balance(addr)
        return f"{c(label, Colors.CYAN)}: {c(f'{bal:,}', Colors.GREEN)} coins"

    def cmd_account(self, args):
        """account [address] - Full account info"""
        if args:
            addr = args[0]
        else:
            addr = self.node.address

        acc = self.node.blockchain.state.get_account(addr)
        is_contract = acc["code"] is not None
        balance = acc["balance"]
        nonce = acc["nonce"]
        
        lines = [
            f"{c('═══ Account ═══', Colors.BOLD)}",
            f"  Address:  {addr[:32]}...",
            f"  Balance:  {c(f'{balance:,}', Colors.GREEN)} coins",
            f"  Nonce:    {nonce}",
            f"  Type:     {c('Contract', Colors.HEADER) if is_contract else 'Wallet'}",
        ]
        
        if is_contract and acc.get("storage"):
            lines.append(f"\n  {c('Storage:', Colors.DIM)}")
            for k, v in list(acc["storage"].items())[:3]:
                lines.append(f"    {k}: {v}")
        
        return "\n".join(lines)

    # === MEMPOOL ===

    def cmd_mempool(self, args):
        """mempool - Show pending transactions"""
        txs = self.node.mempool._pending_txs
        if not txs:
            return c("Mempool: empty", Colors.DIM)

        lines = [f"{c(f'═══ Mempool ({len(txs)} pending) ═══', Colors.BOLD)}"]
        for i, tx in enumerate(txs[:8]):
            sender = tx.sender[:8] if tx.sender else "COINBASE"
            to = tx.receiver[:8] + "..." if tx.receiver else "CONTRACT"
            lines.append(f"  {i+1}. {sender}... → {to} ({c(tx.amount, Colors.YELLOW)})")
        if len(txs) > 8:
            lines.append(c(f"  ... and {len(txs) - 8} more", Colors.DIM))
        return "\n".join(lines)

    # === DEMO & HELP ===

    def cmd_demo(self, args):
        """demo - Run a quick demo workflow"""
        steps = [
            ("Checking status...", "status", []),
            ("Requesting 500 coins from faucet...", "faucet", ["500"]),
            ("Mining block to confirm faucet...", "mine", []),
            ("Checking balance...", "balance", []),
            ("Viewing latest block...", "block", []),
        ]
        
        print(f"\n{c('═══ MiniChain Demo ═══', Colors.BOLD)}")
        print(c("Running through basic workflow...\n", Colors.DIM))
        
        for desc, cmd, cmd_args in steps:
            print(f"{c('→', Colors.CYAN)} {desc}")
            time.sleep(0.3)
            
            method = getattr(self, f"cmd_{cmd}")
            result = method(cmd_args)
            if result:
                # Indent the result
                for line in result.split('\n'):
                    print(f"  {line}")
            print()
            time.sleep(0.5)
        
        print(f"{c('Demo complete!', Colors.GREEN)} Your node is ready.")
        print(c("Try: send <address> <amount>, then mine", Colors.DIM))
        return None

    def cmd_quickstart(self, args):
        """quickstart - Show quick start guide"""
        return f"""
{c('═══ Quick Start Guide ═══', Colors.BOLD)}

{c('1. Get coins:', Colors.CYAN)}
   faucet 1000     {c('# Request 1000 coins from treasury', Colors.DIM)}
   mine            {c('# Mine to confirm the transaction', Colors.DIM)}

{c('2. Check your balance:', Colors.CYAN)}
   balance         {c('# Shows your current balance', Colors.DIM)}
   status          {c('# Full node status overview', Colors.DIM)}

{c('3. Send coins:', Colors.CYAN)}
   send <addr> 100 {c('# Send 100 coins to address', Colors.DIM)}
   mine            {c('# Mine to confirm', Colors.DIM)}

{c('4. Multi-node testing:', Colors.CYAN)}
   {c('Terminal 1:', Colors.DIM)} python3 cli.py --port 8000
   {c('Terminal 2:', Colors.DIM)} python3 cli.py --port 8001 --connect 8000

{c('5. Useful commands:', Colors.CYAN)}
   peers           {c('# List connected peers', Colors.DIM)}
   chain           {c('# Blockchain info', Colors.DIM)}
   block [n]       {c('# View block details', Colors.DIM)}
   mempool         {c('# Pending transactions', Colors.DIM)}
   demo            {c('# Run automated demo', Colors.DIM)}
"""

    # === HELPERS ===

    def _get_nonce(self, address):
        acc_nonce = self.node.blockchain.state.get_account(address).get("nonce", 0)
        local = self.nonce_map.get(address, acc_nonce)
        nonce = max(acc_nonce, local)
        self.nonce_map[address] = nonce + 1
        return nonce

    def _sync_nonce(self, address):
        self.nonce_map[address] = self.node.blockchain.state.get_account(address).get("nonce", 0)

    # === MAIN ===

    def run(self):
        """Run interactive CLI with P2P networking."""
        # Start P2P server in background thread
        try:
            self.node.p2p.start_background()
        except Exception as e:
            print(c(f"Failed to start P2P: {e}", Colors.RED))
            return
        
        # Connect to peer if specified
        if self.connect_port:
            print(c(f"Connecting to peer on port {self.connect_port}...", Colors.DIM))
            self.node.p2p.connect_to_peer_sync("127.0.0.1", self.connect_port)
        
        self._print_banner()

        cmds = {
            # Help & Demo
            "help": self.cmd_help,
            "?": self.cmd_help,
            "quickstart": self.cmd_quickstart,
            "demo": self.cmd_demo,
            
            # Exit
            "exit": self._exit,
            "quit": self._exit,
            "q": self._exit,
            
            # Node info
            "address": self.cmd_address,
            "addr": self.cmd_address,
            "peers": self.cmd_peers,
            "status": self.cmd_status,
            "treasury": self.cmd_treasury,
            "faucet": self.cmd_faucet,
            
            # Blockchain
            "chain": self.cmd_chain,
            "block": self.cmd_block,
            "mine": self.cmd_mine,
            
            # Transactions
            "send": self.cmd_send,
            "deploy": self.cmd_deploy,
            "call": self.cmd_call,
            
            # Account
            "balance": self.cmd_balance,
            "bal": self.cmd_balance,
            "account": self.cmd_account,
            "mempool": self.cmd_mempool,
            "pool": self.cmd_mempool,
        }

        while True:
            try:
                bal = self.node.blockchain.state.get_balance(self.node.address)
                prompt = f"{c(f'[:{self.node.port}]', Colors.CYAN)} {c(f'({bal})', Colors.GREEN)} › "
                line = input(prompt).strip()
                if not line:
                    continue

                parts = line.split()
                cmd, args = parts[0].lower(), parts[1:]

                if cmd in cmds:
                    result = cmds[cmd](args)
                    if result:
                        print(result)
                        print()
                else:
                    print(c(f"Unknown command: {cmd}", Colors.RED))
                    print(c("Type 'help' for available commands.\n", Colors.DIM))

            except KeyboardInterrupt:
                print(c("\n(Use 'exit' or 'q' to quit)", Colors.DIM))
            except EOFError:
                break
            except Exception as e:
                print(c(f"Error: {e}", Colors.RED))
                print()
        
        self._cleanup()

    def _exit(self, args):
        print(c("\nShutting down...", Colors.DIM))
        self._cleanup()
        sys.exit(0)

    def _cleanup(self):
        self.node.p2p.stop_background()

    def _print_banner(self):
        bal = self.node.blockchain.state.get_balance(self.node.address)
        treasury = self.node.blockchain.state.get_balance(TREASURY_ADDRESS)
        peers = len(self.node.p2p.peer_list)
        
        print(f"""
{c('╔════════════════════════════════════════════════════════╗', Colors.CYAN)}
{c('║', Colors.CYAN)}  {c('⛓️  MiniChain Node', Colors.BOLD)}                                   {c('║', Colors.CYAN)}
{c('║', Colors.CYAN)}  {c('Educational Blockchain Implementation', Colors.DIM)}                {c('║', Colors.CYAN)}
{c('╚════════════════════════════════════════════════════════╝', Colors.CYAN)}

  {c('Port:', Colors.DIM)}     {c(self.node.port, Colors.CYAN)}
  {c('Wallet:', Colors.DIM)}   {self.node.wallet_name}
  {c('Address:', Colors.DIM)}  {self.node.address[:32]}...
  {c('Balance:', Colors.DIM)}  {c(f'{bal:,}', Colors.GREEN)} coins
  {c('Peers:', Colors.DIM)}    {c(peers, Colors.YELLOW)}
  {c('Treasury:', Colors.DIM)} {c(f'{treasury:,}', Colors.DIM)} coins available

  Type {c('help', Colors.YELLOW)} for commands or {c('quickstart', Colors.YELLOW)} for a guide.
  Type {c('demo', Colors.YELLOW)} to run an automated demo.
""")

    def cmd_help(self, args):
        """Show help"""
        return f"""
{c('═══════════════════════════════════════════════════════════', Colors.BOLD)}
{c('                    MINICHAIN COMMANDS', Colors.BOLD)}
{c('═══════════════════════════════════════════════════════════', Colors.BOLD)}

{c('GETTING STARTED', Colors.CYAN)}
  {c('help, ?', Colors.YELLOW)}          Show this help
  {c('quickstart', Colors.YELLOW)}       Show quick start guide
  {c('demo', Colors.YELLOW)}             Run automated demo
  {c('status', Colors.YELLOW)}           Node status overview

{c('WALLET & FUNDS', Colors.CYAN)}
  {c('address, addr', Colors.YELLOW)}    Show wallet address
  {c('balance, bal', Colors.YELLOW)}     Check balance [address]
  {c('account', Colors.YELLOW)}          Account details [address]
  {c('faucet', Colors.YELLOW)}           Get coins from treasury [amount]

{c('BLOCKCHAIN', Colors.CYAN)}
  {c('chain', Colors.YELLOW)}            Blockchain info
  {c('block', Colors.YELLOW)}            View block details [index]
  {c('mine', Colors.YELLOW)}             Mine pending transactions

{c('TRANSACTIONS', Colors.CYAN)}
  {c('send', Colors.YELLOW)}             Send coins <address> <amount>
  {c('mempool, pool', Colors.YELLOW)}    View pending transactions

{c('SMART CONTRACTS', Colors.CYAN)}
  {c('deploy', Colors.YELLOW)}           Deploy a contract
  {c('call', Colors.YELLOW)}             Call contract <address> <data>

{c('NETWORK', Colors.CYAN)}
  {c('peers', Colors.YELLOW)}            List connected peers
  {c('treasury', Colors.YELLOW)}         Treasury info

{c('EXIT', Colors.CYAN)}
  {c('exit, quit, q', Colors.YELLOW)}    Quit the CLI

{c('═══════════════════════════════════════════════════════════', Colors.DIM)}
"""


def main():
    parser = argparse.ArgumentParser(description="MiniChain Node CLI")
    parser.add_argument("--port", "-p", type=int, default=8000,
                        help="Port to listen on (default: 8000)")
    parser.add_argument("--connect", "-c", type=int, default=None,
                        help="Port of peer to connect to")
    args = parser.parse_args()
    
    cli = MiniChainCLI(port=args.port, connect_port=args.connect)
    cli.run()


if __name__ == "__main__":
    main()
