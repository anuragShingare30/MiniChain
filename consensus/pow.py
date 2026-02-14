import json
import time
from nacl.hash import sha256
from nacl.encoding import HexEncoder


class MiningExceededError(Exception):
    """Raised when max_nonce, timeout, or cancellation is exceeded during mining."""


def calculate_hash(block_dict):
    """Calculates SHA256 hash of a block header."""
    block_string = json.dumps(block_dict, sort_keys=True).encode("utf-8")
    return sha256(block_string, encoder=HexEncoder).decode("utf-8")


def mine_block(
    block,
    difficulty=4,
    max_nonce=10_000_000,
    timeout_seconds=None,
    logger=None,
    progress_callback=None
):
    """Mines a block using Proof-of-Work without mutating input block until success."""

    target = "0" * difficulty
    local_nonce = 0
    start_time = time.time()

    if logger:
        logger.info(
            "Mining block %s (Difficulty: %s)",
            block.index,
            difficulty,
        )

    while True:

        # Enforce max_nonce limit before hashing
        if local_nonce >= max_nonce:
            if logger:
                logger.warning("Max nonce exceeded during mining.")
            raise MiningExceededError("Mining failed: max_nonce exceeded")

        # Enforce timeout if specified
        if timeout_seconds is not None and (time.time() - start_time) > timeout_seconds:
            if logger:
                logger.warning("Mining timeout exceeded.")
            raise MiningExceededError("Mining failed: timeout exceeded")

        # Temporarily set nonce for hashing only
        block.nonce = local_nonce
        block_hash = calculate_hash(block.to_header_dict())

        # Allow cancellation via progress callback (pass nonce explicitly)
        if progress_callback:
            should_continue = progress_callback(local_nonce, block_hash)
            if should_continue is False:
                if logger:
                    logger.info("Mining cancelled via progress_callback.")
                raise MiningExceededError("Mining cancelled")

        # Check difficulty target
        if block_hash.startswith(target):
            block.nonce = local_nonce
            block.hash = block_hash
            if logger:
                logger.info("Success! Hash: %s", block_hash)
            return block

        # Increment nonce after attempt
        local_nonce += 1
