from core.block import Block
from core.state import State


class Blockchain:
    """
    Manages the blockchain, validates blocks, and commits state transitions.
    """

    def __init__(self):
        self.chain = []
        self.state = State()
        self._create_genesis_block()

    def _create_genesis_block(self):
        """
        Creates the genesis block with a fixed hash.
        """
        genesis_block = Block(
            index=0,
            previous_hash="0",
            transactions=[]
        )
        genesis_block.hash = "0" * 64
        self.chain.append(genesis_block)

    @property
    def last_block(self):
        """
        Returns the most recent block in the chain.
        """
        return self.chain[-1]

    def add_block(self, block):
        """
        Validates and adds a block to the chain if all transactions succeed.
        Uses a copied State to ensure atomic validation.
        """

        # Check previous hash linkage
        if block.previous_hash != self.last_block.hash:
            return False

        # Validate transactions on a temporary state copy
        temp_state = self.state.copy()

        for tx in block.transactions:
            result = temp_state.validate_and_apply(tx)

            # Reject block if any transaction fails
            if result is False or result is None:
                return False

        # All transactions valid → commit state and append block
        self.state = temp_state
        self.chain.append(block)
        return True
