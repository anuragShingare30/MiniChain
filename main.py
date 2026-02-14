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
    """Generate a new keypair."""
    sk = SigningKey.generate()
    pk = sk.verify_key.encode(encoder=HexEncoder).decode()
    return sk, pk


async def node_loop():
    logger.info("Starting MiniChain Node with Smart Contracts")

    state = State()
    chain = Blockchain()
    mempool = Mempool()

    pending_nonce_map = {}

    def sync_nonce(address):
        account = state.get_account(address)
        if account:
            pending_nonce_map[address] = account["nonce"]
        else:
            pending_nonce_map.pop(address, None)

    def get_next_nonce(address):
        account_nonce = state.get_account(address)["nonce"]
        local_nonce = pending_nonce_map.get(address, account_nonce)
        next_nonce = max(account_nonce, local_nonce)
        pending_nonce_map[address] = next_nonce
        return next_nonce

    def increment_nonce(address):
        pending_nonce_map[address] = pending_nonce_map.get(
            address, state.get_account(address)["nonce"]
        ) + 1

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

    logger.info("[2] Transaction: Alice sends 10 coins to Bob")

    nonce = get_next_nonce(alice_pk)

    tx_payment = Transaction(
        sender=alice_pk,
        receiver=bob_pk,
        amount=10,
        nonce=nonce,
    )
    tx_payment.sign(alice_sk)
    increment_nonce(alice_pk)

    if mempool.add_transaction(tx_payment):
        await network.broadcast_transaction(tx_payment)
    else:
        logger.warning("Transaction rejected by mempool: %s", getattr(tx_payment, "hash", None))
        sync_nonce(alice_pk)

    logger.info("[3] Smart Contract: Alice deploys a 'Storage' contract")

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
    increment_nonce(alice_pk)

    if mempool.add_transaction(tx_deploy):
        await network.broadcast_transaction(tx_deploy)
    else:
        logger.warning("Contract deploy rejected: %s", getattr(tx_deploy, "hash", None))
        sync_nonce(alice_pk)

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

        for tx in mined_block_1.transactions:
            result = state.apply_transaction(tx)

            if isinstance(result, str):
                contract_address = result
                logger.info("New Contract Deployed at: %s...", contract_address[:10])
                sync_nonce(tx.sender)

            elif result is False or result is None:
                logger.error(
                    "Transaction failed in block %s: %s",
                    mined_block_1.index,
                    getattr(tx, "hash", None),
                )
                sync_nonce(tx.sender)

            else:
                sync_nonce(tx.sender)
    else:
        logger.error("Block 1 rejected by chain")

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
    increment_nonce(bob_pk)

    if mempool.add_transaction(tx_call):
        await network.broadcast_transaction(tx_call)
    else:
        logger.warning("Contract call rejected: %s", getattr(tx_call, "hash", None))
        sync_nonce(bob_pk)

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

        for tx in mined_block_2.transactions:
            result = state.apply_transaction(tx)

            if result is False or result is None:
                logger.error(
                    "Transaction failed in block %s: %s",
                    mined_block_2.index,
                    getattr(tx, "hash", None),
                )
                sync_nonce(tx.sender)
            else:
                sync_nonce(tx.sender)
    else:
        logger.error("Block 2 rejected by chain")

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
