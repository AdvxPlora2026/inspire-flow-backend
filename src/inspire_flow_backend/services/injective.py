"""Injective chain access via the EVM JSON-RPC endpoints.

Network facts supplied by the Injective team:

- testnet: EVM chain id 1439, JSON-RPC https://k8s.testnet.json-rpc.injective.network/,
  native chain id ``injective-888``, faucet https://testnet.faucet.injective.network/
- mainnet: EVM chain id 1776, JSON-RPC https://sentry.evm-rpc.injective.network/,
  native chain id ``injective-1``

The EVM chain id used for signing is read live from the RPC endpoint, so the
preset value below is documentation only.

Only commercial execution facts (digests) are placed in transaction data.
Private keys are read from settings and never persisted or logged.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal, Protocol

from inspire_flow_backend.core.config import Settings

ChainConfirmation = Literal["broadcast", "confirmed", "failed"]

WEI_PER_INJ = 10**18


@dataclass(frozen=True)
class NetworkPreset:
    evm_chain_id: int
    native_chain_id: str
    rpc_url: str
    explorer_base_url: str


NETWORK_PRESETS: dict[str, NetworkPreset] = {
    "testnet": NetworkPreset(
        evm_chain_id=1439,
        native_chain_id="injective-888",
        rpc_url="https://k8s.testnet.json-rpc.injective.network/",
        explorer_base_url="https://testnet.blockscout.injective.network",
    ),
    "mainnet": NetworkPreset(
        evm_chain_id=1776,
        native_chain_id="injective-1",
        rpc_url="https://sentry.evm-rpc.injective.network/",
        explorer_base_url="https://blockscout.injective.network",
    ),
}


@dataclass(frozen=True)
class ChainBroadcast:
    network: str
    chain_id: str
    transaction_hash: str
    explorer_url: str
    nonce: int


class ChainBroadcastError(Exception):
    def __init__(self, reason: str, *, retryable: bool) -> None:
        super().__init__(reason)
        self.reason = reason
        self.retryable = retryable


class InjectiveProvider(Protocol):
    @property
    def network(self) -> str: ...

    @property
    def chain_id(self) -> str: ...

    def broadcast(self, memo: str) -> ChainBroadcast:
        """Broadcast a transaction carrying the memo and return chain facts."""
        ...

    def get_transaction_status(
        self, transaction_hash: str, *, nonce: int | None = None
    ) -> ChainConfirmation:
        """Query the network for the confirmation state of a transaction."""
        ...


class EvmJsonRpcInjectiveProvider:
    """Broadcasts self-transfers carrying commercial facts via Injective EVM."""

    def __init__(
        self,
        *,
        network: str,
        private_key: str,
        rpc_url: str | None = None,
        explorer_base_url: str | None = None,
        amount: str = "0.000000000000000001",
    ) -> None:
        preset = NETWORK_PRESETS[network]
        self._network = network
        self._preset = preset
        self._private_key = private_key
        self._rpc_url = rpc_url or preset.rpc_url
        self._explorer_base_url = (explorer_base_url or preset.explorer_base_url).rstrip("/")
        self._value_wei = int(Decimal(amount) * WEI_PER_INJ)

    @property
    def network(self) -> str:
        return self._network

    @property
    def chain_id(self) -> str:
        return self._preset.native_chain_id

    def broadcast(self, memo: str) -> ChainBroadcast:
        try:
            from eth_account import Account
            from web3 import Web3
        except ImportError as error:
            raise ChainBroadcastError(
                "Injective EVM dependencies are not installed (install the 'injective' group)",
                retryable=False,
            ) from error
        try:
            web3 = Web3(Web3.HTTPProvider(self._rpc_url, request_kwargs={"timeout": 30}))
            account = Account.from_key(self._private_key)
            nonce = web3.eth.get_transaction_count(account.address, "pending")
            transaction = {
                "from": account.address,
                "to": account.address,
                "value": self._value_wei,
                "nonce": nonce,
                "chainId": web3.eth.chain_id,
                "gasPrice": web3.eth.gas_price,
                "data": memo.encode("utf-8"),
            }
            transaction["gas"] = web3.eth.estimate_gas(transaction)
            signed = account.sign_transaction(transaction)
            raw_hash = web3.eth.send_raw_transaction(signed.raw_transaction)
        except ChainBroadcastError:
            raise
        except Exception as error:
            raise ChainBroadcastError(
                str(error) or type(error).__name__,
                retryable=True,
            ) from error
        transaction_hash = raw_hash.to_0x_hex()
        return ChainBroadcast(
            network=self._network,
            chain_id=self._preset.native_chain_id,
            transaction_hash=transaction_hash,
            explorer_url=f"{self._explorer_base_url}/tx/{transaction_hash}",
            nonce=nonce,
        )

    def get_transaction_status(
        self, transaction_hash: str, *, nonce: int | None = None
    ) -> ChainConfirmation:
        try:
            from eth_account import Account
            from web3 import Web3
            from web3.exceptions import TransactionNotFound
        except ImportError:
            return "broadcast"
        web3 = Web3(Web3.HTTPProvider(self._rpc_url, request_kwargs={"timeout": 30}))
        try:
            receipt = web3.eth.get_transaction_receipt(transaction_hash)
        except TransactionNotFound:
            receipt = None
        except Exception:  # noqa: BLE001 - network failures leave the tx pending
            return "broadcast"
        if receipt is not None:
            return "confirmed" if receipt.get("status") == 1 else "failed"
        # Some Injective EVM RPC endpoints do not index transactions by hash, so
        # the receipt is never returned even after inclusion. Fall back to nonce
        # progression: once the sender's mined nonce passes this transaction's
        # nonce, the transaction has been included in a block.
        if nonce is None:
            return "broadcast"
        try:
            account = Account.from_key(self._private_key)
            mined = web3.eth.get_transaction_count(account.address, "latest")
        except Exception:  # noqa: BLE001 - transient failures leave the tx pending
            return "broadcast"
        return "confirmed" if mined > nonce else "broadcast"


def create_injective_provider(settings: Settings) -> InjectiveProvider | None:
    if settings.injective_private_key is None:
        return None
    return EvmJsonRpcInjectiveProvider(
        network=settings.injective_network,
        private_key=settings.injective_private_key.get_secret_value(),
        rpc_url=settings.injective_rpc_url,
        explorer_base_url=settings.injective_explorer_base_url,
        amount=settings.injective_broadcast_amount,
    )
