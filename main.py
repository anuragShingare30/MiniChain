import asyncio
import logging
import re
from nacl.signing import SigningKey
from nacl.encoding import HexEncoder

from core import Transaction, Blockchain, Block, State
from node import Mempool
from network import P2PNetwork
from consensus import mine_block


logger = logging.getLogger(__name__)

BURN_ADDRESS = "0" * 40

def create_wallet():
    sk = SigningKey.generate()
    pk = sk.verify_key.encode(encoder=HexEncoder).decode()
    return sk, pk


def mine_and_process_block(chain, mempool, state, pending_nonce_map):
    """Helper to mine a block and apply transactions."""
    pending_txs = mempool.get_transactions_for_block()

    block = Block(
        index=chain.last_block.index + 1,
        previous_hash=chain.last_block.hash,
        transactions=pending_txs,
    )

    mined_block = mine_block(block)
    contract_address = None

    if chain.add_block(mined_block):
        logger.info("Block #%s added", mined_block.index)

        # Credit miner reward
        miner_attr = getattr(mined_block, "miner", None)
        if isinstance(miner_attr, str) and re.match(r'^[0-9a-fA-F]{40}$', miner_attr):
            miner_address = miner_attr
        else:
            logger.warning("Block has no miner or invalid address. Crediting burn address.")
            miner_address = BURN_ADDRESS

        state.credit_mining_reward(miner_address)

        for tx in mined_block.transactions:
            result = state.apply_transaction(tx)

            # Check for valid contract address (40 hex chars)
            if isinstance(result, str) and re.match(r'^[0-9a-fA-F]{40}$', result):
                contract_address = result
                logger.info("New Contract Deployed at: %s", contract_address)
                sync_nonce(state, pending_nonce_map, tx.sender)
            elif result is True:
                sync_nonce(state, pending_nonce_map, tx.sender)
            elif result is False or result is None:
                logger.error("Transaction failed in block %s", mined_block.index)
                sync_nonce(state, pending_nonce_map, tx.sender)

        return mined_block, contract_address
    else:
        logger.error("Block rejected by chain")
        return None, None

def sync_nonce(state, pending_nonce_map, address):
    account = state.get_account(address)
    if account and "nonce" in account:
        pending_nonce_map[address] = account["nonce"]
    else:
        pending_nonce_map[address] = 0

async def node_loop():
    logger.info("Starting MiniChain Node with Smart Contracts")

    state = State()
    chain = Blockchain()
    mempool = Mempool()

    pending_nonce_map = {}

    def get_next_nonce(address):
        account_nonce = state.get_account(address)["nonce"]
        local_nonce = pending_nonce_map.get(address, account_nonce)
        next_nonce = max(account_nonce, local_nonce)
        return next_nonce

    async def handle_network_data(data):
        logger.info("Received network data: %s", data)

    network = P2PNetwork(handle_network_data)
    
    try:
        await _run_node(network, state, chain, mempool, pending_nonce_map, get_next_nonce)
    finally:
        await network.stop()

async def _run_node(network, state, chain, mempool, pending_nonce_map, get_next_nonce):
    await network.start()

    alice_sk, alice_pk = create_wallet()
    bob_sk, bob_pk = create_wallet()

    logger.info("Alice Address: %s...", alice_pk[:10])
    logger.info("Bob Address: %s...", bob_pk[:10])

    logger.info("[1] Genesis: Crediting Alice with 100 coins")
    state.credit_mining_reward(alice_pk, reward=100)
    sync_nonce(state, pending_nonce_map, alice_pk)

    # -------------------------------
    # Alice Payment
    # -------------------------------

    logger.info("[2] Transaction: Alice sends 10 coins to Bob")

    nonce = get_next_nonce(alice_pk)

    tx_payment = Transaction(
        sender=alice_pk,
        receiver=bob_pk,
        amount=10,
        nonce=nonce,
    )
    tx_payment.sign(alice_sk)

    if mempool.add_transaction(tx_payment):
        pending_nonce_map[alice_pk] = nonce + 1
        await network.broadcast_transaction(tx_payment)
    else:
        logger.warning("Transaction rejected by mempool")

    # -------------------------------
    # Contract Deployment (UNSAFE)
    # -------------------------------

    logger.info("[3] Smart Contract: Alice deploys a 'Storage' contract")

    # WARNING:
    # This contract uses raw Python executed via exec inside ContractMachine.
    # This is UNSAFE and should NEVER be used in production.
    # TODO: Replace ContractMachine exec-based runtime with:
    # - RestrictedPython
    # - WASM-based VM
    # - Custom DSL interpreter
    contract_code = """
# Storage Contract (UNSAFE EXAMPLE)
if msg['data']:
    storage['value'] = msg['data']
"""

    nonce = get_next_nonce(alice_pk)

    tx_deploy = Transaction(
        sender=alice_pk,
        receiver=None,
        amount=0,
        nonce=nonce,
        data=contract_code,
    )
    tx_deploy.sign(alice_sk)

    if mempool.add_transaction(tx_deploy):
        pending_nonce_map[alice_pk] = nonce + 1
        await network.broadcast_transaction(tx_deploy)
    else:
        logger.warning("Contract deploy rejected")

    # -------------------------------
    # Mine Block 1
    # -------------------------------

    logger.info("[4] Consensus: Mining Block 1")

    _, contract_address = mine_and_process_block(chain, mempool, state, pending_nonce_map)

    # -------------------------------
    # Bob Interaction
    # -------------------------------

    logger.info("[5] Interaction: Bob sends data to Contract")

    if contract_address is None:
        logger.error("Contract not deployed. Skipping interaction.")
        return

    nonce = get_next_nonce(bob_pk)

    tx_call = Transaction(
        sender=bob_pk,
        receiver=contract_address,
        amount=0,
        nonce=nonce,
        data="Hello Blockchain",
    )
    tx_call.sign(bob_sk)

    if mempool.add_transaction(tx_call):
        pending_nonce_map[bob_pk] = nonce + 1
        await network.broadcast_transaction(tx_call)
    else:
        logger.warning("Contract call rejected")

    # -------------------------------
    # Mine Block 2
    # -------------------------------

    logger.info("[6] Consensus: Mining Block 2")

    mine_and_process_block(chain, mempool, state, pending_nonce_map)

    # -------------------------------
    # Final State
    # -------------------------------

    logger.info("[7] Final State Check")
    logger.info("Alice Balance: %s", state.get_account(alice_pk)["balance"])
    logger.info("Bob Balance: %s", state.get_account(bob_pk)["balance"])

    if contract_address:
        contract_acc = state.get_account(contract_address)
        logger.info("Contract Storage: %s", contract_acc["storage"])
    else:
        logger.info("No contract deployed.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(node_loop())
