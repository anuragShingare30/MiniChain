from nacl.hash import sha256
from nacl.encoding import HexEncoder
from minichain.contract import ContractMachine
from minichain.transaction import COINBASE_SENDER
import copy
import logging

logger = logging.getLogger(__name__)


class State:
    def __init__(self):
        # { address: {'balance': int, 'nonce': int, 'code': str|None, 'storage': dict} }
        self.accounts = {}
        self.contract_machine = ContractMachine(self)

    DEFAULT_MINING_REWARD = 50

    # =========================================================================
    # BASIC ACCOUNT METHODS (compatible with Minichain_v0)
    # =========================================================================

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
            self.accounts[address] = {
                "balance": balance,
                "nonce": 0,
                "code": None,
                "storage": {}
            }

    def get_account(self, address):
        if address not in self.accounts:
            self.accounts[address] = {
                'balance': 0,
                'nonce': 0,
                'code': None,
                'storage': {}
            }
        return self.accounts[address]

    # =========================================================================
    # TRANSACTION APPLICATION
    # =========================================================================

    def apply_tx(self, tx) -> "State":
        """
        Apply transaction to state (compatible with Minichain_v0).
        Returns self for chaining. Raises ValueError if transaction is invalid.
        """
        # Coinbase transaction: just create/credit receiver account
        if tx.sender == COINBASE_SENDER:
            self.create_account(tx.receiver, 0)
            self.accounts[tx.receiver]["balance"] += tx.amount
            return self

        # Validate signature
        if not tx.verify():
            raise ValueError("Invalid signature")

        # Validate sender exists
        if not self.exists(tx.sender):
            raise ValueError(f"Sender {tx.sender[:8]} does not exist")

        # Validate nonce (prevents replay attacks)
        expected_nonce = self.get_nonce(tx.sender)
        if tx.nonce != expected_nonce:
            raise ValueError(f"Bad nonce: expected {expected_nonce}, got {tx.nonce}")

        # Validate balance
        if self.get_balance(tx.sender) < tx.amount:
            raise ValueError("Insufficient balance")

        # Apply changes
        self.accounts[tx.sender]["balance"] -= tx.amount
        self.accounts[tx.sender]["nonce"] += 1

        # Handle contract deployment (receiver is None)
        if tx.receiver is None or tx.receiver == "":
            if tx.data:
                contract_address = self.derive_contract_address(tx.sender, tx.nonce)
                self.create_contract(contract_address, tx.data, initial_balance=tx.amount)
            return self

        # Create receiver if needed
        if not self.exists(tx.receiver):
            self.create_account(tx.receiver)

        # Handle contract call
        if tx.data and self.accounts.get(tx.receiver, {}).get("code"):
            self.accounts[tx.receiver]["balance"] += tx.amount
            success = self.contract_machine.execute(
                contract_address=tx.receiver,
                sender_address=tx.sender,
                payload=tx.data,
                amount=tx.amount
            )
            if not success:
                # Rollback
                self.accounts[tx.receiver]["balance"] -= tx.amount
                self.accounts[tx.sender]["balance"] += tx.amount
                self.accounts[tx.sender]["nonce"] -= 1
                raise ValueError("Contract execution failed")
            return self

        # Regular transfer
        self.accounts[tx.receiver]["balance"] += tx.amount
        return self

    def verify_transaction_logic(self, tx):
        if not tx.verify():
            logger.error(f"Error: Invalid signature for tx from {tx.sender[:8]}...")
            return False

        sender_acc = self.get_account(tx.sender)

        if sender_acc['balance'] < tx.amount:
            logger.error(f"Error: Insufficient balance for {tx.sender[:8]}...")
            return False

        if sender_acc['nonce'] != tx.nonce:
            logger.error(f"Error: Invalid nonce. Expected {sender_acc['nonce']}, got {tx.nonce}")
            return False

        return True

    def copy(self):
        """
        Return an independent copy of state for transactional validation.
        """
        new_state = copy.deepcopy(self)
        new_state.contract_machine = ContractMachine(new_state) # Reinitialize contract_machine
        return new_state

    def validate_and_apply(self, tx):
        """
        Validate and apply a transaction.
        Returns the same success/failure shape as apply_transaction().
        NOTE: Delegates to apply_transaction. Callers should use this for
        semantic validation entry points.
        """
        # Semantic validation: amount must be an integer and non-negative
        if not isinstance(tx.amount, int) or tx.amount < 0:
            return False
        # Further checks can be added here
        return self.apply_transaction(tx)

    def apply_transaction(self, tx):
        """
        Applies transaction and mutates state.
        Returns:
            - Contract address (str) if deployment
            - True if successful execution
            - False if failed
        """
        if not self.verify_transaction_logic(tx):
            return False

        sender = self.accounts[tx.sender]

        # Deduct funds and increment nonce
        sender['balance'] -= tx.amount
        sender['nonce'] += 1

        # LOGIC BRANCH 1: Contract Deployment
        if tx.receiver is None or tx.receiver == "":
            contract_address = self.derive_contract_address(tx.sender, tx.nonce)

            # Prevent redeploy collision
            existing = self.accounts.get(contract_address)
            if existing and existing.get("code"):
                # Restore sender state on failure
                sender['balance'] += tx.amount
                sender['nonce'] -= 1
                return False

            return self.create_contract(contract_address, tx.data, initial_balance=tx.amount)

        # LOGIC BRANCH 2: Contract Call
        # If data is provided (non-empty), treat as contract call
        if tx.data:
            receiver = self.accounts.get(tx.receiver)

            # Fail if contract does not exist or has no code
            if not receiver or not receiver.get("code"):
                # Rollback sender balance and nonce on failure
                sender['balance'] += tx.amount # Refund amount
                sender['nonce'] -= 1
                return False

            # Credit contract balance
            receiver['balance'] += tx.amount

            success = self.contract_machine.execute(
                contract_address=tx.receiver, # Pass receiver as contract_address
                sender_address=tx.sender,
                payload=tx.data,
                amount=tx.amount
            )

            if not success:
                # Rollback transfer and nonce if execution fails
                receiver['balance'] -= tx.amount
                sender['balance'] += tx.amount # Refund amount
                sender['nonce'] -= 1
                return False

            return True

        # LOGIC BRANCH 3: Regular Transfer
        receiver = self.get_account(tx.receiver)
        receiver['balance'] += tx.amount
        return True

    def derive_contract_address(self, sender, nonce):
        raw = f"{sender}:{nonce}".encode()
        return sha256(raw, encoder=HexEncoder).decode()[:40]

    def create_contract(self, contract_address, code, initial_balance=0):
        self.accounts[contract_address] = {
            'balance': initial_balance,
            'nonce': 0,
            'code': code,
            'storage': {}
        }
        return contract_address

    def update_contract_storage(self, address, new_storage):
        if address in self.accounts:
            self.accounts[address]['storage'] = new_storage
        else:
            raise KeyError(f"Contract address not found: {address}")

    def update_contract_storage_partial(self, address, updates):
        if address not in self.accounts:
            raise KeyError(f"Contract address not found: {address}")
        if isinstance(updates, dict):
            self.accounts[address]['storage'].update(updates)
        else:
            raise ValueError("Updates must be a dictionary")

    def credit_mining_reward(self, miner_address, reward=None):
        reward = reward if reward is not None else self.DEFAULT_MINING_REWARD
        account = self.get_account(miner_address)
        account['balance'] += reward
