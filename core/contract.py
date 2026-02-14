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
        code = account.get("code")

        # Defensive copy of storage to prevent direct mutation
        storage = dict(account.get("storage", {}))

        if not code:
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
            # SECURITY WARNING:
            # This is a restricted but still educational sandbox.
            # Production systems should use WASM or a proper VM.
            exec(code, globals_for_exec, context)

            # Commit updated storage only after successful execution
            self.state.update_contract_storage(
                contract_address,
                context["storage"]
            )

            return True

        except Exception as e:
            print(f"Contract Execution Failed: {e}")
            return False
