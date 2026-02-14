import asyncio
import logging
from nacl.signing import SigningKey
from nacl.encoding import HexEncoder

from core import Transaction, Blockchain, Block, State
from node import Mempool
from network import P2PNetwork
from consensus import mine_block


logger = logging.getLogger(__name__)


def create_wallet():
    sk = SigningKey.generate()
    pk = sk.verify_key.encode(encoder=HexEncoder).decode()
    return sk, pk


async def node_loop():
    logger.info("Starting MiniChain Node with Smart Contracts")

    state = State()
    chain = Blockchain()
    mempool = Mempool()

    pending_nonce_map = {}

    # Simplified: state.get_account always returns dict
    def sync_nonce(address):
        account = state.get_account(address)
        pending_nonce_map[address] = account["nonce"]

    def get_next_nonce(address):
        account_nonce = state.get_account(address)["nonce"]
        local_nonce = pending_nonce_map.get(address, account_nonce)
        next_nonce = max(account_nonce, local_nonce)
        pending_nonce_map[address] = next_nonce
        return next_nonce

    async def handle_network_data(data):
        logger.info("Received network data: %s", data)

    network = P2PNetwork(handle_network_data)
    await network.start()

    alice_sk, alice_pk = create_wallet()
    bob_sk, bob_pk = create_wallet()

    logger.info("Alice Address: %s...", alice_pk[:10])
    logger.info("Bob Address: %s...", bob_pk[:10])

    logger.info("[1] Genesis: Crediting Alice with 100 coins")
    state.credit_mining_reward(alice_pk, reward=100)
    sync_nonce(alice_pk)

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

    pending_txs = mempool.get_transactions_for_block()

    block_1 = Block(
        index=chain.last_block.index + 1,
        previous_hash=chain.last_block.hash,
        transactions=pending_txs,
    )

    mined_block_1 = mine_block(block_1)
    contract_address = None

    if chain.add_block(mined_block_1):
        logger.info("Block #%s added", mined_block_1.index)

        # Credit miner reward
        miner_address = getattr(mined_block_1, "miner", alice_pk)
        state.credit_mining_reward(miner_address)

        for tx in mined_block_1.transactions:
            result = state.apply_transaction(tx)

            if isinstance(result, str):
                contract_address = result
                logger.info("New Contract Deployed at: %s...", contract_address[:10])
                sync_nonce(tx.sender)

            elif result is False or result is None:
                logger.error(
                    "Transaction failed in block %s",
                    mined_block_1.index,
                )
                sync_nonce(tx.sender)

            else:
                sync_nonce(tx.sender)
    else:
        logger.error("Block 1 rejected by chain")

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

    pending_txs_2 = mempool.get_transactions_for_block()

    block_2 = Block(
        index=chain.last_block.index + 1,
        previous_hash=chain.last_block.hash,
        transactions=pending_txs_2,
    )

    mined_block_2 = mine_block(block_2)

    if chain.add_block(mined_block_2):
        logger.info("Block #%s added", mined_block_2.index)

        miner_address = getattr(mined_block_2, "miner", alice_pk)
        state.credit_mining_reward(miner_address)

        for tx in mined_block_2.transactions:
            result = state.apply_transaction(tx)

            if result is False or result is None:
                logger.error(
                    "Transaction failed in block %s",
                    mined_block_2.index,
                )
                sync_nonce(tx.sender)
            else:
                sync_nonce(tx.sender)
    else:
        logger.error("Block 2 rejected by chain")

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
