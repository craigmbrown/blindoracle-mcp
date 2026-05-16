#!/usr/bin/env python3
"""
Chainlink CRE (Chainlink Runtime Environment) Smart Contract Integration
@requirement: REQ-CRE-001 - On-chain AI payment escrow
@requirement: REQ-CRE-002 - x402 Payment Standard support
@requirement: REQ-CRE-003 - CRE workflow execution for AI agents
@requirement: REQ-MCP-003 - All exceptions print full details
@requirement: REQ-MCP-004 - Success responses logged before return
"""

import os
import json
import asyncio
import hashlib
import traceback
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from pathlib import Path
from enum import Enum
from web3 import Web3
from eth_account import Account
from eth_account.messages import encode_defunct

# Chainlink network configurations
CHAINLINK_NETWORKS = {
    "ethereum_mainnet": {
        "rpc_url": os.getenv("ETH_RPC_URL", "https://eth.llamarpc.com"),
        "chain_id": 1,
        "ccip_router": "0x80226fc0Ee2b096224EeAc085Bb9a8cba1146f7D",
        "price_feed_registry": "0x47Fb2585D2C56Fe188D0E6ec628a38b74fCeeeDf",
        "link_token": "0x514910771AF9Ca656af840dff83E8264EcF986CA",
    },
    "arbitrum_mainnet": {
        "rpc_url": os.getenv("ARBITRUM_RPC_URL", "https://arb1.arbitrum.io/rpc"),
        "chain_id": 42161,
        "ccip_router": "0x141fa059441E0ca23ce184B6A78bafD2A517DdE8",
        "price_feed_registry": "0x47Fb2585D2C56Fe188D0E6ec628a38b74fCeeeDf",
        "link_token": "0xf97f4df75117a78c1A5a0DBb814Af92458539FB4",
    },
    "base_mainnet": {
        "rpc_url": os.getenv("BASE_RPC_URL", "https://mainnet.base.org"),
        "chain_id": 8453,
        "ccip_router": "0x881e3A65B4d4a04dD529061dd0071cf975F58bCD",
        "price_feed_registry": None,  # Use direct feeds
        "link_token": "0x88Fb150BDc53A65fe94Dea0c9BA0a6dAf8C6e196",
    },
}


class EscrowState(Enum):
    """State machine for payment escrow"""

    CREATED = "created"
    FUNDED = "funded"
    TASK_STARTED = "task_started"
    TASK_COMPLETED = "task_completed"
    VERIFICATION_PENDING = "verification_pending"
    RELEASED = "released"
    DISPUTED = "disputed"
    REFUNDED = "refunded"


@dataclass
class AIPaymentEscrow:
    """On-chain payment escrow for AI agent tasks"""

    escrow_id: str
    task_id: str
    ai_agent_address: str
    client_address: str
    amount_wei: int
    token_address: str  # ETH = 0x0
    state: EscrowState = EscrowState.CREATED
    created_at: datetime = field(default_factory=datetime.now)
    funded_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    verification_hash: Optional[str] = None

    def to_dict(self) -> Dict:
        return {
            "escrow_id": self.escrow_id,
            "task_id": self.task_id,
            "ai_agent_address": self.ai_agent_address,
            "client_address": self.client_address,
            "amount_wei": self.amount_wei,
            "amount_eth": self.amount_wei / 1e18,
            "token_address": self.token_address,
            "state": self.state.value,
            "created_at": self.created_at.isoformat(),
            "funded_at": self.funded_at.isoformat() if self.funded_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "verification_hash": self.verification_hash,
        }


@dataclass
class x402PaymentRequest:
    """x402 Payment Standard - HTTP payment protocol for AI APIs"""

    request_id: str
    endpoint: str
    method: str = "POST"
    payment_type: str = "chainlink"  # chainlink, lightning, ecash
    price_wei: int = 0
    price_usd: float = 0.0
    expires_at: datetime = field(default_factory=lambda: datetime.now() + timedelta(hours=1))
    payment_address: Optional[str] = None
    invoice: Optional[str] = None  # For Lightning payments
    signed_receipt: Optional[str] = None

    def to_header(self) -> Dict[str, str]:
        """Generate x402 HTTP headers"""
        return {
            "X-Payment-Required": "402",
            "X-Payment-Request-Id": self.request_id,
            "X-Payment-Type": self.payment_type,
            "X-Payment-Price-Wei": str(self.price_wei),
            "X-Payment-Price-USD": f"{self.price_usd:.6f}",
            "X-Payment-Address": self.payment_address or "",
            "X-Payment-Expires": self.expires_at.isoformat(),
            "X-Payment-Invoice": self.invoice or "",
        }


@dataclass
class CREWorkflowTrigger:
    """CRE Workflow trigger configuration"""

    trigger_type: str  # EVM_LOG, CRON, WEBHOOK
    contract_address: Optional[str] = None
    event_signature: Optional[str] = None
    cron_schedule: Optional[str] = None
    webhook_url: Optional[str] = None
    conditions: Dict = field(default_factory=dict)


class CRESmartContractManager:
    """
    Chainlink CRE Smart Contract Integration Manager
    Handles on-chain AI monetization, payment escrow, and CRE workflows

    @requirement: REQ-CRE-001 - Payment escrow [@core/cre_smart_contracts.py:150-350]
    @requirement: REQ-CRE-002 - x402 standard [@core/cre_smart_contracts.py:350-500]
    @requirement: REQ-CRE-003 - CRE workflows [@core/cre_smart_contracts.py:500-700]
    """

    # AI Payment Escrow ABI (simplified for demonstration)
    ESCROW_ABI = [
        {
            "inputs": [
                {"name": "taskId", "type": "bytes32"},
                {"name": "aiAgent", "type": "address"},
                {"name": "deadline", "type": "uint256"},
            ],
            "name": "createEscrow",
            "outputs": [{"name": "escrowId", "type": "bytes32"}],
            "stateMutability": "payable",
            "type": "function",
        },
        {
            "inputs": [
                {"name": "escrowId", "type": "bytes32"},
                {"name": "verificationHash", "type": "bytes32"},
            ],
            "name": "completeTask",
            "outputs": [],
            "stateMutability": "nonpayable",
            "type": "function",
        },
        {
            "inputs": [{"name": "escrowId", "type": "bytes32"}],
            "name": "releasePayment",
            "outputs": [],
            "stateMutability": "nonpayable",
            "type": "function",
        },
        {
            "inputs": [{"name": "escrowId", "type": "bytes32"}],
            "name": "getEscrow",
            "outputs": [
                {"name": "client", "type": "address"},
                {"name": "aiAgent", "type": "address"},
                {"name": "amount", "type": "uint256"},
                {"name": "state", "type": "uint8"},
                {"name": "deadline", "type": "uint256"},
            ],
            "stateMutability": "view",
            "type": "function",
        },
        {
            "anonymous": False,
            "inputs": [
                {"indexed": True, "name": "escrowId", "type": "bytes32"},
                {"indexed": True, "name": "taskId", "type": "bytes32"},
                {"indexed": False, "name": "amount", "type": "uint256"},
            ],
            "name": "EscrowCreated",
            "type": "event",
        },
        {
            "anonymous": False,
            "inputs": [
                {"indexed": True, "name": "escrowId", "type": "bytes32"},
                {"indexed": False, "name": "verificationHash", "type": "bytes32"},
            ],
            "name": "TaskCompleted",
            "type": "event",
        },
        {
            "anonymous": False,
            "inputs": [
                {"indexed": True, "name": "escrowId", "type": "bytes32"},
                {"indexed": True, "name": "recipient", "type": "address"},
                {"indexed": False, "name": "amount", "type": "uint256"},
            ],
            "name": "PaymentReleased",
            "type": "event",
        },
    ]

    # Contract addresses (to be deployed)
    ESCROW_CONTRACTS = {
        "ethereum_mainnet": os.getenv("CRE_ESCROW_ETH", None),
        "arbitrum_mainnet": os.getenv("CRE_ESCROW_ARB", None),
        "base_mainnet": os.getenv("CRE_ESCROW_BASE", None),
    }

    def __init__(self, network: str = "ethereum_mainnet"):
        """Initialize CRE Smart Contract Manager"""
        self.network = network
        self.network_config = CHAINLINK_NETWORKS.get(
            network, CHAINLINK_NETWORKS["ethereum_mainnet"]
        )

        # Initialize Web3
        self.w3 = Web3(Web3.HTTPProvider(self.network_config["rpc_url"]))

        # Load wallet
        self.private_key = os.getenv("ETH_PRIVATE_KEY")
        if self.private_key:
            self.account = Account.from_key(self.private_key)
            self.address = self.account.address
        else:
            self.account = None
            self.address = os.getenv(
                "ETH_WALLET_ADDRESS", "0x5A559751c81a1bacFa009C3e4ff0bf9697d2Bf0E"
            )

        # Contract instances
        self.escrow_contract = None
        escrow_addr = self.ESCROW_CONTRACTS.get(network)
        if escrow_addr and self.w3.is_address(escrow_addr):
            self.escrow_contract = self.w3.eth.contract(
                address=Web3.to_checksum_address(escrow_addr), abi=self.ESCROW_ABI
            )

        # Active escrows tracking
        self.active_escrows: Dict[str, AIPaymentEscrow] = {}

        # x402 payment requests
        self.payment_requests: Dict[str, x402PaymentRequest] = {}

        # CRE workflow definitions
        self.workflows: Dict[str, Dict] = {}

        # Storage
        self.state_dir = Path("/home/craigmbrown/Project/logs/cre_state")
        self.state_dir.mkdir(parents=True, exist_ok=True)

        self._load_state()

        print(f"CRE Smart Contract Manager initialized")
        print(f"   Network: {network} (Chain ID: {self.network_config['chain_id']})")
        print(f"   Wallet: {self.address}")
        print(f"   Escrow Contract: {escrow_addr or 'NOT DEPLOYED'}")

    # ==================== PAYMENT ESCROW ====================

    async def create_escrow(
        self, task_id: str, ai_agent_address: str, amount_eth: float, deadline_hours: int = 24
    ) -> AIPaymentEscrow:
        """
        Create on-chain payment escrow for AI task
        @requirement: REQ-CRE-001 - Payment escrow creation
        """
        try:
            # Generate escrow ID
            escrow_id = hashlib.sha256(
                f"{task_id}:{ai_agent_address}:{datetime.now().isoformat()}".encode()
            ).hexdigest()[:16]

            amount_wei = self.w3.to_wei(amount_eth, "ether")

            # Create escrow object
            escrow = AIPaymentEscrow(
                escrow_id=escrow_id,
                task_id=task_id,
                ai_agent_address=ai_agent_address,
                client_address=self.address,
                amount_wei=amount_wei,
                token_address="0x0000000000000000000000000000000000000000",  # ETH
            )

            # If contract is deployed, create on-chain
            if self.escrow_contract and self.account:
                print(f"Creating on-chain escrow for task {task_id}")

                task_id_bytes = Web3.keccak(text=task_id)
                deadline = int((datetime.now() + timedelta(hours=deadline_hours)).timestamp())

                # Build transaction
                tx = self.escrow_contract.functions.createEscrow(
                    task_id_bytes, Web3.to_checksum_address(ai_agent_address), deadline
                ).build_transaction(
                    {
                        "from": self.address,
                        "value": amount_wei,
                        "gas": 300000,
                        "gasPrice": self.w3.eth.gas_price,
                        "nonce": self.w3.eth.get_transaction_count(self.address),
                        "chainId": self.network_config["chain_id"],
                    }
                )

                # Sign and send
                signed_tx = self.account.sign_transaction(tx)
                tx_hash = self.w3.eth.send_raw_transaction(signed_tx.rawTransaction)

                # Wait for receipt
                receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

                if receipt["status"] == 1:
                    escrow.state = EscrowState.FUNDED
                    escrow.funded_at = datetime.now()
                    print(f"   Escrow created on-chain: {tx_hash.hex()}")
                else:
                    raise Exception(f"Transaction failed: {tx_hash.hex()}")
            else:
                # Simulated mode (contract not deployed)
                print(f"[SIMULATED] Creating escrow for task {task_id}")
                escrow.state = EscrowState.FUNDED
                escrow.funded_at = datetime.now()

            # Track escrow
            self.active_escrows[escrow_id] = escrow
            self._save_state()

            # REQ-MCP-004: Log success
            print(
                f"Escrow {escrow_id} created: {amount_eth} ETH for agent {ai_agent_address[:10]}..."
            )
            return escrow

        except Exception as e:
            # REQ-MCP-003: Print full exception details
            print(f"Escrow creation failed: {str(e)}")
            print(f"   Exception type: {type(e).__name__}")
            print(f"   Full traceback: {traceback.format_exc()}")
            raise

    async def complete_task(
        self, escrow_id: str, output_data: Dict, verification_signature: Optional[str] = None
    ) -> bool:
        """
        Mark task as completed and submit verification
        @requirement: REQ-CRE-001 - Task completion verification
        """
        try:
            escrow = self.active_escrows.get(escrow_id)
            if not escrow:
                raise ValueError(f"Escrow {escrow_id} not found")

            if escrow.state != EscrowState.FUNDED and escrow.state != EscrowState.TASK_STARTED:
                raise ValueError(f"Invalid escrow state: {escrow.state.value}")

            # Generate verification hash from output
            verification_hash = hashlib.sha256(
                json.dumps(output_data, sort_keys=True).encode()
            ).hexdigest()

            # If contract deployed, submit on-chain
            if self.escrow_contract and self.account:
                print(f"Submitting task completion on-chain for escrow {escrow_id}")

                escrow_id_bytes = bytes.fromhex(escrow_id.ljust(64, "0"))
                verification_bytes = bytes.fromhex(verification_hash)

                tx = self.escrow_contract.functions.completeTask(
                    escrow_id_bytes, verification_bytes
                ).build_transaction(
                    {
                        "from": self.address,
                        "gas": 200000,
                        "gasPrice": self.w3.eth.gas_price,
                        "nonce": self.w3.eth.get_transaction_count(self.address),
                        "chainId": self.network_config["chain_id"],
                    }
                )

                signed_tx = self.account.sign_transaction(tx)
                tx_hash = self.w3.eth.send_raw_transaction(signed_tx.rawTransaction)
                receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

                if receipt["status"] != 1:
                    raise Exception(f"Transaction failed: {tx_hash.hex()}")

                print(f"   Task completion submitted: {tx_hash.hex()}")
            else:
                print(f"[SIMULATED] Task completion for escrow {escrow_id}")

            # Update escrow state
            escrow.state = EscrowState.TASK_COMPLETED
            escrow.completed_at = datetime.now()
            escrow.verification_hash = verification_hash

            self._save_state()

            print(f"Task completed for escrow {escrow_id}")
            return True

        except Exception as e:
            print(f"Task completion failed: {str(e)}")
            print(f"   Full traceback: {traceback.format_exc()}")
            raise

    async def release_payment(self, escrow_id: str) -> Tuple[bool, Optional[str]]:
        """
        Release payment to AI agent after verification
        @requirement: REQ-CRE-001 - Payment release
        """
        try:
            escrow = self.active_escrows.get(escrow_id)
            if not escrow:
                raise ValueError(f"Escrow {escrow_id} not found")

            if escrow.state != EscrowState.TASK_COMPLETED:
                raise ValueError(f"Task not completed: {escrow.state.value}")

            tx_hash = None

            if self.escrow_contract and self.account:
                print(f"Releasing payment on-chain for escrow {escrow_id}")

                escrow_id_bytes = bytes.fromhex(escrow_id.ljust(64, "0"))

                tx = self.escrow_contract.functions.releasePayment(
                    escrow_id_bytes
                ).build_transaction(
                    {
                        "from": self.address,
                        "gas": 100000,
                        "gasPrice": self.w3.eth.gas_price,
                        "nonce": self.w3.eth.get_transaction_count(self.address),
                        "chainId": self.network_config["chain_id"],
                    }
                )

                signed_tx = self.account.sign_transaction(tx)
                tx_hash = self.w3.eth.send_raw_transaction(signed_tx.rawTransaction)
                receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

                if receipt["status"] != 1:
                    raise Exception(f"Transaction failed: {tx_hash.hex()}")

                tx_hash = tx_hash.hex()
                print(f"   Payment released: {tx_hash}")
            else:
                print(f"[SIMULATED] Payment released for escrow {escrow_id}")

            # Update escrow state
            escrow.state = EscrowState.RELEASED
            self._save_state()

            print(
                f"Payment of {escrow.amount_wei / 1e18:.6f} ETH released to {escrow.ai_agent_address}"
            )
            return True, tx_hash

        except Exception as e:
            print(f"Payment release failed: {str(e)}")
            print(f"   Full traceback: {traceback.format_exc()}")
            raise

    # ==================== x402 PAYMENT STANDARD ====================

    def create_payment_request(
        self,
        endpoint: str,
        price_usd: float,
        payment_type: str = "chainlink",
        expires_hours: float = 1.0,
    ) -> x402PaymentRequest:
        """
        Create x402 payment request for AI API endpoint
        @requirement: REQ-CRE-002 - x402 Payment Standard
        """
        try:
            request_id = hashlib.sha256(
                f"{endpoint}:{datetime.now().isoformat()}".encode()
            ).hexdigest()[:16]

            # Convert USD to Wei using Chainlink Price Feed
            eth_price_usd = self._get_eth_price()
            price_eth = price_usd / eth_price_usd if eth_price_usd > 0 else 0
            price_wei = int(price_eth * 1e18)

            request = x402PaymentRequest(
                request_id=request_id,
                endpoint=endpoint,
                payment_type=payment_type,
                price_wei=price_wei,
                price_usd=price_usd,
                expires_at=datetime.now() + timedelta(hours=expires_hours),
                payment_address=self.address,
            )

            self.payment_requests[request_id] = request

            print(f"x402 payment request created: {request_id}")
            print(f"   Endpoint: {endpoint}")
            print(f"   Price: ${price_usd:.4f} ({price_wei} wei)")

            return request

        except Exception as e:
            print(f"x402 request creation failed: {str(e)}")
            raise

    async def verify_x402_payment(
        self, request_id: str, tx_hash: str
    ) -> Tuple[bool, Optional[str]]:
        """
        Verify x402 payment was made
        @requirement: REQ-CRE-002 - Payment verification
        """
        try:
            request = self.payment_requests.get(request_id)
            if not request:
                return False, "Payment request not found"

            if datetime.now() > request.expires_at:
                return False, "Payment request expired"

            # Verify transaction on-chain
            try:
                tx = self.w3.eth.get_transaction(tx_hash)
                receipt = self.w3.eth.get_transaction_receipt(tx_hash)

                if receipt["status"] != 1:
                    return False, "Transaction failed"

                if tx["to"].lower() != request.payment_address.lower():
                    return False, "Payment sent to wrong address"

                if tx["value"] < request.price_wei:
                    return False, f"Insufficient payment: {tx['value']} < {request.price_wei}"

            except Exception as e:
                return False, f"Transaction verification failed: {str(e)}"

            # Generate signed receipt
            receipt_data = {
                "request_id": request_id,
                "tx_hash": tx_hash,
                "amount_paid": tx["value"],
                "timestamp": datetime.now().isoformat(),
            }

            if self.account:
                message = encode_defunct(text=json.dumps(receipt_data, sort_keys=True))
                signed = self.account.sign_message(message)
                request.signed_receipt = signed.signature.hex()

            print(f"x402 payment verified: {request_id}")
            return True, request.signed_receipt

        except Exception as e:
            print(f"x402 verification failed: {str(e)}")
            return False, str(e)

    def _get_eth_price(self) -> float:
        """Get ETH/USD price from Chainlink Price Feed"""
        try:
            # Chainlink ETH/USD Price Feed on mainnet
            PRICE_FEED_ABI = [
                {
                    "inputs": [],
                    "name": "latestRoundData",
                    "outputs": [
                        {"name": "roundId", "type": "uint80"},
                        {"name": "answer", "type": "int256"},
                        {"name": "startedAt", "type": "uint256"},
                        {"name": "updatedAt", "type": "uint256"},
                        {"name": "answeredInRound", "type": "uint80"},
                    ],
                    "stateMutability": "view",
                    "type": "function",
                }
            ]

            # ETH/USD mainnet feed
            feed_address = "0x5f4eC3Df9cbd43714FE2740f5E3616155c5b8419"

            price_feed = self.w3.eth.contract(
                address=Web3.to_checksum_address(feed_address), abi=PRICE_FEED_ABI
            )

            _, answer, _, _, _ = price_feed.functions.latestRoundData().call()
            return answer / 1e8  # 8 decimals

        except Exception:
            # Fallback price
            return 3000.0

    # ==================== CRE WORKFLOWS ====================

    def register_cre_workflow(
        self, workflow_id: str, name: str, trigger: CREWorkflowTrigger, actions: List[Dict]
    ) -> Dict:
        """
        Register a CRE workflow for AI agent automation
        @requirement: REQ-CRE-003 - CRE workflow registration
        """
        try:
            workflow = {
                "workflow_id": workflow_id,
                "name": name,
                "trigger": {
                    "type": trigger.trigger_type,
                    "contract_address": trigger.contract_address,
                    "event_signature": trigger.event_signature,
                    "cron_schedule": trigger.cron_schedule,
                    "webhook_url": trigger.webhook_url,
                    "conditions": trigger.conditions,
                },
                "actions": actions,
                "status": "registered",
                "created_at": datetime.now().isoformat(),
                "executions": 0,
                "last_execution": None,
            }

            self.workflows[workflow_id] = workflow
            self._save_state()

            print(f"CRE workflow registered: {workflow_id}")
            print(f"   Name: {name}")
            print(f"   Trigger: {trigger.trigger_type}")

            return workflow

        except Exception as e:
            print(f"Workflow registration failed: {str(e)}")
            raise

    async def execute_cre_workflow(self, workflow_id: str, trigger_data: Dict) -> Dict:
        """
        Execute a CRE workflow
        @requirement: REQ-CRE-003 - CRE workflow execution
        """
        try:
            workflow = self.workflows.get(workflow_id)
            if not workflow:
                raise ValueError(f"Workflow {workflow_id} not found")

            execution_id = hashlib.sha256(
                f"{workflow_id}:{datetime.now().isoformat()}".encode()
            ).hexdigest()[:16]

            print(f"Executing CRE workflow: {workflow['name']}")
            print(f"   Execution ID: {execution_id}")

            results = []
            context = {"trigger_data": trigger_data}

            for i, action in enumerate(workflow["actions"]):
                action_type = action.get("type")
                print(f"   Action {i+1}: {action_type}")

                try:
                    if action_type == "evm_read":
                        result = await self._execute_evm_read(action, context)
                    elif action_type == "evm_write":
                        result = await self._execute_evm_write(action, context)
                    elif action_type == "http_request":
                        result = await self._execute_http_request(action, context)
                    elif action_type == "ai_inference":
                        result = await self._execute_ai_inference(action, context)
                    elif action_type == "create_escrow":
                        result = await self._execute_create_escrow(action, context)
                    elif action_type == "release_payment":
                        result = await self._execute_release_payment(action, context)
                    else:
                        result = {
                            "status": "skipped",
                            "reason": f"Unknown action type: {action_type}",
                        }

                    results.append({"action": action_type, "result": result})
                    context[f"action_{i}_result"] = result

                except Exception as e:
                    results.append({"action": action_type, "error": str(e)})
                    if action.get("fail_on_error", True):
                        raise

            # Update workflow stats
            workflow["executions"] += 1
            workflow["last_execution"] = datetime.now().isoformat()
            self._save_state()

            execution_result = {
                "execution_id": execution_id,
                "workflow_id": workflow_id,
                "status": "completed",
                "results": results,
                "timestamp": datetime.now().isoformat(),
            }

            print(f"Workflow execution completed: {execution_id}")
            return execution_result

        except Exception as e:
            print(f"Workflow execution failed: {str(e)}")
            print(f"   Full traceback: {traceback.format_exc()}")
            raise

    async def _execute_evm_read(self, action: Dict, context: Dict) -> Dict:
        """
        Execute EVM read action
        PRODUCTION: Requires ABI for contract interaction
        """
        contract_address = action.get("contract_address")
        method_name = action.get("method_name")
        args = action.get("args", [])
        abi = action.get("abi")

        if not contract_address or not abi:
            print(f"   ⚠️ [PENDING] EVM read requires contract_address and abi")
            return {
                "status": "pending",
                "reason": "Contract ABI required for EVM reads",
                "contract": contract_address,
                "method": method_name,
            }

        try:
            contract = self.w3.eth.contract(
                address=Web3.to_checksum_address(contract_address), abi=abi
            )
            method = getattr(contract.functions, method_name)
            result = method(*args).call()
            print(f"   ✅ [LIVE] EVM read: {method_name} = {result}")
            return {"status": "success", "result": result, "method": method_name}
        except Exception as e:
            print(f"   ❌ EVM read failed: {e}")
            return {"status": "error", "error": str(e)}

    async def _execute_evm_write(self, action: Dict, context: Dict) -> Dict:
        """
        Execute EVM write action
        PRODUCTION: Requires ETH_PRIVATE_KEY and ABI for contract interaction
        """
        if not self.account:
            print(f"   ⚠️ [PENDING] EVM write requires ETH_PRIVATE_KEY")
            return {"status": "pending", "reason": "ETH_PRIVATE_KEY required for EVM writes"}

        contract_address = action.get("contract_address")
        method_name = action.get("method_name")
        args = action.get("args", [])
        abi = action.get("abi")
        value = action.get("value", 0)  # ETH value in wei

        if not contract_address or not abi:
            return {"status": "pending", "reason": "Contract ABI required"}

        try:
            contract = self.w3.eth.contract(
                address=Web3.to_checksum_address(contract_address), abi=abi
            )
            method = getattr(contract.functions, method_name)

            tx = method(*args).build_transaction(
                {
                    "from": self.address,
                    "value": value,
                    "gas": action.get("gas", 200000),
                    "gasPrice": self.w3.eth.gas_price,
                    "nonce": self.w3.eth.get_transaction_count(self.address),
                    "chainId": self.network_config["chain_id"],
                }
            )

            signed_tx = self.account.sign_transaction(tx)
            tx_hash = self.w3.eth.send_raw_transaction(signed_tx.rawTransaction)
            receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

            print(f"   ✅ [LIVE] EVM write: {method_name} - {tx_hash.hex()}")
            return {"status": "success", "tx_hash": tx_hash.hex(), "method": method_name}

        except Exception as e:
            print(f"   ❌ EVM write failed: {e}")
            return {"status": "error", "error": str(e)}

    async def _execute_http_request(self, action: Dict, context: Dict) -> Dict:
        """
        Execute HTTP request action
        PRODUCTION: Makes real HTTP requests to specified endpoints
        """
        import aiohttp

        url = action.get("url")
        method = action.get("method", "GET").upper()
        headers = action.get("headers", {})
        body = action.get("body")
        timeout = action.get("timeout", 30)

        if not url:
            return {"status": "error", "reason": "URL required"}

        try:
            async with aiohttp.ClientSession() as session:
                kwargs = {"headers": headers, "timeout": timeout}
                if body and method in ["POST", "PUT", "PATCH"]:
                    kwargs["json"] = body

                async with session.request(method, url, **kwargs) as response:
                    result = {"status": "success", "http_status": response.status, "url": url}

                    if response.status < 400:
                        try:
                            result["data"] = await response.json()
                        except:
                            result["data"] = await response.text()

                    print(f"   ✅ [LIVE] HTTP {method} {url} - {response.status}")
                    return result

        except Exception as e:
            print(f"   ❌ HTTP request failed: {e}")
            return {"status": "error", "error": str(e)}

    async def _execute_ai_inference(self, action: Dict, context: Dict) -> Dict:
        """
        Execute AI inference action
        PRODUCTION: Requires OPENAI_API_KEY or ANTHROPIC_API_KEY
        """
        model = action.get("model", "gpt-3.5-turbo")
        prompt = action.get("prompt", "")
        timeout_minutes = action.get("timeout_minutes", 5)

        # Check for API keys
        openai_key = os.getenv("OPENAI_API_KEY")
        anthropic_key = os.getenv("ANTHROPIC_API_KEY")

        if not openai_key and not anthropic_key:
            print(f"   ⚠️ [PENDING] AI inference requires OPENAI_API_KEY or ANTHROPIC_API_KEY")
            return {"status": "pending", "reason": "LLM API key required for AI inference"}

        try:
            if openai_key:
                import openai

                client = openai.OpenAI()
                response = client.chat.completions.create(
                    model=model if "gpt" in model else "gpt-3.5-turbo",
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=1000,
                    timeout=timeout_minutes * 60,
                )
                result_text = response.choices[0].message.content
                print(f"   ✅ [LIVE] AI inference via OpenAI")
                return {"status": "success", "result": result_text, "model": model}

            elif anthropic_key:
                import anthropic

                client = anthropic.Anthropic()
                response = client.messages.create(
                    model="claude-3-haiku-20240307",
                    max_tokens=1000,
                    messages=[{"role": "user", "content": prompt}],
                )
                result_text = response.content[0].text
                print(f"   ✅ [LIVE] AI inference via Anthropic")
                return {"status": "success", "result": result_text, "model": "claude-3-haiku"}

        except Exception as e:
            print(f"   ❌ AI inference failed: {e}")
            return {"status": "error", "error": str(e)}

    async def _execute_create_escrow(self, action: Dict, context: Dict) -> Dict:
        """Execute create escrow action"""
        task_id = action.get("task_id", context.get("trigger_data", {}).get("task_id"))
        agent_address = action.get("agent_address")
        amount_eth = action.get("amount_eth", 0.01)

        escrow = await self.create_escrow(task_id, agent_address, amount_eth)
        return escrow.to_dict()

    async def _execute_release_payment(self, action: Dict, context: Dict) -> Dict:
        """Execute release payment action"""
        escrow_id = action.get("escrow_id") or context.get("escrow_id")
        if escrow_id:
            success, tx_hash = await self.release_payment(escrow_id)
            return {"success": success, "tx_hash": tx_hash}
        return {"status": "skipped", "reason": "No escrow_id provided"}

    # ==================== RESEARCH JOB INTEGRATION ====================

    async def create_research_job_escrow(
        self, job_id: str, research_agents: List[str], total_payment_usd: float
    ) -> Dict[str, AIPaymentEscrow]:
        """
        Create escrows for all research agents in a job
        Integrates with Research Agent Marketplace
        """
        try:
            eth_price = self._get_eth_price()
            total_payment_eth = total_payment_usd / eth_price

            # Split payment among agents
            payment_per_agent = total_payment_eth / len(research_agents)

            escrows = {}
            for agent_id in research_agents:
                # Use agent's registered address (or placeholder)
                agent_address = self._get_agent_address(agent_id)

                escrow = await self.create_escrow(
                    task_id=f"{job_id}:{agent_id}",
                    ai_agent_address=agent_address,
                    amount_eth=payment_per_agent,
                )
                escrows[agent_id] = escrow

            print(f"Created {len(escrows)} escrows for research job {job_id}")
            print(f"   Total: ${total_payment_usd:.2f} ({total_payment_eth:.6f} ETH)")

            return escrows

        except Exception as e:
            print(f"Research job escrow creation failed: {str(e)}")
            raise

    def _get_agent_address(self, agent_id: str) -> str:
        """Get agent's Ethereum address from registry"""
        # Agent address registry (would be loaded from config)
        agent_addresses = {
            "evidence_gatherer": "0x1111111111111111111111111111111111111111",
            "fact_checker": "0x2222222222222222222222222222222222222222",
            "devils_advocate": "0x3333333333333333333333333333333333333333",
            "domain_expert": "0x4444444444444444444444444444444444444444",
            "bias_detector": "0x5555555555555555555555555555555555555555",
            "synthesis_coordinator": "0x6666666666666666666666666666666666666666",
        }
        return agent_addresses.get(agent_id, self.address)

    # ==================== STATE MANAGEMENT ====================

    def _save_state(self) -> None:
        """Save state to disk"""
        try:
            state = {
                "active_escrows": {k: v.to_dict() for k, v in self.active_escrows.items()},
                "workflows": self.workflows,
                "timestamp": datetime.now().isoformat(),
            }

            state_file = self.state_dir / "cre_state.json"
            with open(state_file, "w") as f:
                json.dump(state, f, indent=2)

        except Exception as e:
            print(f"State save failed: {str(e)}")

    def _load_state(self) -> None:
        """Load state from disk"""
        try:
            state_file = self.state_dir / "cre_state.json"
            if state_file.exists():
                with open(state_file, "r") as f:
                    state = json.load(f)

                self.workflows = state.get("workflows", {})
                # Escrows would need reconstruction from dicts

        except Exception as e:
            print(f"State load failed: {str(e)}")

    def get_status(self) -> Dict:
        """Get CRE integration status"""
        return {
            "network": self.network,
            "chain_id": self.network_config["chain_id"],
            "wallet_address": self.address,
            "escrow_contract_deployed": self.escrow_contract is not None,
            "active_escrows": len(self.active_escrows),
            "registered_workflows": len(self.workflows),
            "payment_requests": len(self.payment_requests),
            "eth_price_usd": self._get_eth_price(),
            "features": {
                "payment_escrow": True,
                "x402_standard": True,
                "cre_workflows": True,
                "research_job_integration": True,
            },
        }


# ==================== AI RESEARCH JOB CRE WORKFLOW ====================


def create_ai_research_workflow(cre_manager: CRESmartContractManager) -> str:
    """
    Create a CRE workflow for AI research job execution
    This workflow:
    1. Listens for new research job events
    2. Creates escrow for payment
    3. Triggers AI agent research
    4. Verifies output and releases payment
    """

    workflow_id = "ai_research_job_v1"

    trigger = CREWorkflowTrigger(
        trigger_type="EVM_LOG",
        contract_address=cre_manager.ESCROW_CONTRACTS.get(cre_manager.network),
        event_signature="JobRequested(bytes32 jobId, address client, uint256 budget)",
        conditions={"min_budget_usd": 10.0, "job_types": ["research", "analysis", "consensus"]},
    )

    actions = [
        {
            "type": "create_escrow",
            "task_id": "{{trigger_data.job_id}}",
            "agent_address": "{{trigger_data.selected_agent}}",
            "amount_eth": "{{trigger_data.budget_eth}}",
        },
        {
            "type": "http_request",
            "url": "http://localhost:8080/api/research/start",
            "method": "POST",
            "body": {
                "job_id": "{{trigger_data.job_id}}",
                "escrow_id": "{{action_0_result.escrow_id}}",
                "requirements": "{{trigger_data.requirements}}",
            },
        },
        {
            "type": "ai_inference",
            "model": "research_agent_marketplace",
            "prompt": "Execute research job {{trigger_data.job_id}}",
            "timeout_minutes": 30,
        },
        {
            "type": "release_payment",
            "escrow_id": "{{action_0_result.escrow_id}}",
            "condition": "{{action_2_result.consensus_score > 0.67}}",
        },
    ]

    workflow = cre_manager.register_cre_workflow(
        workflow_id=workflow_id, name="AI Research Job Execution", trigger=trigger, actions=actions
    )

    return workflow_id


# ==================== MAIN ENTRY POINT ====================


async def main():
    """Test CRE Smart Contract Integration"""
    print("\n" + "=" * 60)
    print("CHAINLINK CRE SMART CONTRACT INTEGRATION")
    print("AI Monetization Platform")
    print("=" * 60 + "\n")

    # Initialize manager
    cre = CRESmartContractManager(network="ethereum_mainnet")

    # Show status
    status = cre.get_status()
    print("\n CRE Status:")
    for key, value in status.items():
        print(f"   {key}: {value}")

    # Create test escrow
    print("\n Testing Payment Escrow...")
    escrow = await cre.create_escrow(
        task_id="research_001",
        ai_agent_address="0x1234567890123456789012345678901234567890",
        amount_eth=0.01,
    )
    print(f"   Created: {escrow.escrow_id}")

    # Create x402 payment request
    print("\n Testing x402 Payment Request...")
    payment_req = cre.create_payment_request(endpoint="/api/research/execute", price_usd=5.00)
    print(f"   Request ID: {payment_req.request_id}")
    print(f"   Headers: {payment_req.to_header()}")

    # Register workflow
    print("\n Registering CRE Workflow...")
    workflow_id = create_ai_research_workflow(cre)
    print(f"   Workflow: {workflow_id}")

    print("\n CRE Integration Tests Complete!")
    return cre


if __name__ == "__main__":
    asyncio.run(main())
