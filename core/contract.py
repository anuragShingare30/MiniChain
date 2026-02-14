import logging
import multiprocessing
import ast
import sys

logger = logging.getLogger(__name__)

def _safe_exec_worker(code, globals_dict, context_dict, result_queue):
    """
    Worker function to execute contract code in a separate process.
    """
    try:
        # Attempt to set resource limits (Unix only)
        try:
            import resource
            # Limit CPU time (seconds) and memory (bytes) - example values
            resource.setrlimit(resource.RLIMIT_CPU, (1, 1))
            # resource.setrlimit(resource.RLIMIT_AS, (100 * 1024 * 1024, 100 * 1024 * 1024))
        except ImportError as e:
            logger.error(f"Resource limits not enforced: {e}")
            raise RuntimeError(f"Resource limits not enforced: {e}")

        exec(code, globals_dict, context_dict)
        # Return the updated storage
        result_queue.put({"status": "success", "storage": context_dict.get("storage")})
    except Exception as e:
        result_queue.put({"status": "error", "error": str(e)})

class ContractMachine:
    """
    A minimal execution environment for Python-based smart contracts.
    WARNING: Still not production-safe. For educational use only.
    """

    def __init__(self, state):
        self.state = state

    def execute(self, contract_address, sender_address, payload, amount):
        """
        Executes the contract code associated with the contract_address.
        """

        account = self.state.get_account(contract_address)
        if not account:
            return False

        code = account.get("code")

        # Defensive copy of storage to prevent direct mutation
        storage = dict(account.get("storage", {}))

        if not code:
            return False

        # AST Validation to prevent introspection
        if not self._validate_code_ast(code):
            return False

        # Restricted builtins (explicit allowlist)
        safe_builtins = {
            "True": True,
            "False": False,
            "None": None,
            "range": range,
            "len": len,
            "min": min,
            "max": max,
            "abs": abs,
        }

        globals_for_exec = {
            "__builtins__": safe_builtins
        }

        # Execution context (locals)
        context = {
            "storage": storage,
            "msg": {
                "sender": sender_address,
                "value": amount,
                "data": payload,
            },
            "print": print,  # Explicitly allowed for debugging
        }

        try:
            # Execute in a subprocess with timeout
            queue = multiprocessing.Queue()
            p = multiprocessing.Process(
                target=_safe_exec_worker,
                args=(code, globals_for_exec, context, queue)
            )
            p.start()
            p.join(timeout=2)  # 2 second timeout

            if p.is_alive():
                p.kill()
                logger.error("Contract execution timed out")
                return False

            if queue.empty():
                logger.error("Contract execution crashed without result")
                return False

            result = queue.get()
            if result["status"] != "success":
                logger.error(f"Contract Execution Failed: {result.get('error')}")
                return False

            # Commit updated storage only after successful execution
            self.state.update_contract_storage(
                contract_address,
                result["storage"]
            )

            return True

        except Exception as e:
            logger.error("Contract Execution Failed", exc_info=True)
            return False

    def _validate_code_ast(self, code):
        """Reject code that uses double underscores or introspection."""
        try:
            tree = ast.parse(code)
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute) and node.attr.startswith("__"):
                    logger.warning("Rejected contract code with double-underscore attribute access.")
                    return False
                if isinstance(node, ast.Name) and node.id.startswith("__"):
                    logger.warning("Rejected contract code with double-underscore name.")
                    return False
            return True
        except SyntaxError:
            return False
