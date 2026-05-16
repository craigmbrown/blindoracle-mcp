#!/usr/bin/env python3
"""
Payment System for Chainlink AI Monetization
@requirement: REQ-PAY-001 - Blockchain payment processing
@requirement: REQ-PAY-002 - Escrow management
@requirement: REQ-PAY-003 - Automated payment claims
@requirement: REQ-MCP-003 - All exceptions print full details
@requirement: REQ-MCP-004 - Success responses logged before return
"""

import os
import json
import asyncio
import traceback
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from pathlib import Path
from decimal import Decimal
import sys

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.whatsapp_notifier import WhatsAppNotifier

# Web3 imports (will need to be installed)
try:
    from web3 import Web3
    from web3.contract import Contract
    from eth_account import Account

    HAS_WEB3 = True
except ImportError:
    HAS_WEB3 = False
    print("⚠️ Web3 not installed. Run: pip install web3 eth-account")


class PaymentSystem:
    """
    Blockchain payment system with escrow management
    @requirement: REQ-PAY-001 - Payment processing [@core/payment_system.py:35-500]
    @requirement: REQ-PAY-002 - Escrow verification [@core/payment_system.py:100-200]
    @requirement: REQ-PAY-003 - Payment claims [@core/payment_system.py:205-300]
    """

    def __init__(self, notifier: Optional[WhatsAppNotifier] = None):
        """Initialize payment system"""
        self.notifier = notifier or WhatsAppNotifier()

        # Wallet configuration
        self.wallet_address = os.getenv("CHAINLINK_WALLET_ADDRESS", "")
        self.private_key = os.getenv("CHAINLINK_PRIVATE_KEY", "")

        # Network configuration
        self.rpc_url = os.getenv("ETH_RPC_URL", "https://eth-mainnet.g.alchemy.com/v2/YOUR-API-KEY")
        self.chain_id = int(os.getenv("CHAIN_ID", "1"))  # 1=mainnet, 5=goerli, 137=polygon

        # Smart contract addresses
        self.escrow_contract_address = os.getenv("ESCROW_CONTRACT_ADDRESS", "")
        self.payment_token_address = os.getenv("PAYMENT_TOKEN_ADDRESS", "")  # USDC, DAI, etc.

        # Web3 connection
        self.w3 = None
        self.account = None
        self.escrow_contract = None

        # Payment tracking
        self.pending_payments = {}
        self.completed_payments = []
        self.total_revenue = Decimal("0")

        # Initialize if configured
        if self.wallet_address and self.private_key and HAS_WEB3:
            self.initialize_web3()
        else:
            print("⚠️ Payment system in DEMO MODE - no blockchain connection")

    def initialize_web3(self) -> bool:
        """
        Initialize Web3 connection and contracts
        @requirement: REQ-PAY-001 - Blockchain connection
        """
        try:
            # Connect to blockchain
            self.w3 = Web3(Web3.HTTPProvider(self.rpc_url))

            if not self.w3.is_connected():
                raise Exception("Failed to connect to blockchain")

            # Load account from private key
            self.account = Account.from_key(self.private_key)

            # Verify wallet address matches
            if self.account.address.lower() != self.wallet_address.lower():
                raise Exception("Wallet address mismatch")

            # Load escrow contract ABI (simplified for now)
            self.escrow_abi = self._get_escrow_abi()

            if self.escrow_contract_address:
                self.escrow_contract = self.w3.eth.contract(
                    address=Web3.to_checksum_address(self.escrow_contract_address),
                    abi=self.escrow_abi,
                )

            # Get network info
            network_id = self.w3.net.version
            latest_block = self.w3.eth.block_number
            balance_wei = self.w3.eth.get_balance(self.wallet_address)
            balance_eth = self.w3.from_wei(balance_wei, "ether")

            # REQ-MCP-004: Log success before return
            print(f"✅ Web3 initialized:")
            print(f"   Network: {network_id}")
            print(f"   Latest Block: {latest_block}")
            print(f"   Wallet: {self.wallet_address[:10]}...{self.wallet_address[-6:]}")
            print(f"   Balance: {balance_eth:.4f} ETH")

            return True

        except Exception as e:
            # REQ-MCP-003: Print full exception details
            print(f"❌ Web3 initialization failed: {str(e)}")
            print(f"   Exception type: {type(e).__name__}")
            print(f"   Full traceback: {traceback.format_exc()}")
            return False

    async def verify_escrow(self, job_id: str, expected_amount: float) -> bool:
        """
        Verify payment is in escrow for a job
        @requirement: REQ-PAY-002 - Escrow verification [@core/payment_system.py:120-180]
        """
        try:
            # Demo mode - simulate verification
            if not self.w3 or not self.escrow_contract:
                print(f"⚠️ DEMO MODE: Simulating escrow verification for job {job_id}")

                # Simulate 90% success rate
                import random

                success = random.random() < 0.9

                if success:
                    self.pending_payments[job_id] = {
                        "amount": expected_amount,
                        "verified_at": datetime.now().isoformat(),
                        "escrow_address": f"0x{'0'*40}",  # Demo address
                        "status": "verified",
                    }

                    await self.notifier.notify_payment_received(
                        job_id, expected_amount, "0xDEMO" + job_id[:8]
                    )

                    print(f"✅ [DEMO] Escrow verified: ${expected_amount} for job {job_id}")
                else:
                    print(f"❌ [DEMO] Escrow not found for job {job_id}")

                return success

            # Real blockchain verification
            print(f"🔍 Verifying escrow for job {job_id}...")

            # Call escrow contract to check locked amount
            job_id_bytes = Web3.keccak(text=job_id)
            escrow_info = self.escrow_contract.functions.getEscrow(job_id_bytes).call()

            # Parse escrow info (structure depends on contract)
            depositor = escrow_info[0]
            amount = escrow_info[1]
            is_locked = escrow_info[2]

            # Convert amount from wei to ETH (or token decimals)
            amount_eth = self.w3.from_wei(amount, "ether")

            # Verify amount matches and is locked
            if amount_eth >= Decimal(str(expected_amount)) and is_locked:
                self.pending_payments[job_id] = {
                    "amount": float(amount_eth),
                    "depositor": depositor,
                    "verified_at": datetime.now().isoformat(),
                    "escrow_address": self.escrow_contract_address,
                    "status": "verified",
                }

                # Get transaction hash for reference
                tx_hash = "0x" + job_id_bytes.hex()[:64]

                await self.notifier.notify_payment_received(job_id, float(amount_eth), tx_hash)

                # REQ-MCP-004: Log success
                print(f"✅ Escrow verified: {amount_eth} ETH for job {job_id}")
                return True
            else:
                print(f"❌ Escrow verification failed:")
                print(f"   Expected: {expected_amount} ETH")
                print(f"   Found: {amount_eth} ETH")
                print(f"   Locked: {is_locked}")
                return False

        except Exception as e:
            # REQ-MCP-003: Print full exception details
            print(f"❌ Escrow verification error: {str(e)}")
            print(f"   Exception type: {type(e).__name__}")
            print(f"   Full traceback: {traceback.format_exc()}")
            return False

    async def claim_payment(self, job_id: str, completion_proof: Dict[str, Any]) -> Optional[str]:
        """
        Claim payment after job completion
        @requirement: REQ-PAY-003 - Payment claims [@core/payment_system.py:205-300]
        """
        try:
            # Check if payment was verified
            if job_id not in self.pending_payments:
                print(f"⚠️ No verified payment for job {job_id}")
                return None

            payment_info = self.pending_payments[job_id]

            # Demo mode - simulate claim
            if not self.w3 or not self.escrow_contract:
                print(f"⚠️ DEMO MODE: Simulating payment claim for job {job_id}")

                # Update payment status
                payment_info["status"] = "claimed"
                payment_info["claimed_at"] = datetime.now().isoformat()
                payment_info["tx_hash"] = f"0xDEMO{job_id[:56]}"

                # Move to completed
                self.completed_payments.append(payment_info)
                del self.pending_payments[job_id]

                # Update total revenue
                self.total_revenue += Decimal(str(payment_info["amount"]))

                await self.notifier.send_critical(
                    f"💰 PAYMENT CLAIMED [DEMO]\n"
                    f"Job: {job_id}\n"
                    f"Amount: ${payment_info['amount']:.2f}\n"
                    f"Total Revenue: ${self.total_revenue:.2f}"
                )

                print(f"✅ [DEMO] Payment claimed: ${payment_info['amount']} for job {job_id}")
                return payment_info["tx_hash"]

            # Real blockchain claim
            print(f"💰 Claiming payment for job {job_id}...")

            # Prepare completion proof for smart contract
            job_id_bytes = Web3.keccak(text=job_id)
            proof_hash = Web3.keccak(text=json.dumps(completion_proof))

            # Build transaction
            claim_function = self.escrow_contract.functions.claimPayment(
                job_id_bytes,
                proof_hash,
                completion_proof.get("ipfs_hash", ""),
                completion_proof.get("output_hash", "0x" + "0" * 64),
            )

            # Estimate gas
            gas_estimate = claim_function.estimate_gas({"from": self.wallet_address})

            # Get current gas price
            gas_price = self.w3.eth.gas_price

            # Build transaction
            transaction = claim_function.build_transaction(
                {
                    "from": self.wallet_address,
                    "gas": int(gas_estimate * 1.1),  # 10% buffer
                    "gasPrice": gas_price,
                    "nonce": self.w3.eth.get_transaction_count(self.wallet_address),
                    "chainId": self.chain_id,
                }
            )

            # Sign transaction
            signed_txn = self.w3.eth.account.sign_transaction(
                transaction, private_key=self.private_key
            )

            # Send transaction
            tx_hash = self.w3.eth.send_raw_transaction(signed_txn.rawTransaction)

            print(f"📤 Transaction sent: {tx_hash.hex()}")

            # Wait for confirmation
            receipt = await self._wait_for_receipt(tx_hash)

            if receipt and receipt["status"] == 1:
                # Success - update records
                payment_info["status"] = "claimed"
                payment_info["claimed_at"] = datetime.now().isoformat()
                payment_info["tx_hash"] = tx_hash.hex()
                payment_info["gas_used"] = receipt["gasUsed"]
                payment_info["block_number"] = receipt["blockNumber"]

                # Move to completed
                self.completed_payments.append(payment_info)
                del self.pending_payments[job_id]

                # Update total revenue
                self.total_revenue += Decimal(str(payment_info["amount"]))

                # Calculate gas cost
                gas_cost_wei = receipt["gasUsed"] * gas_price
                gas_cost_eth = self.w3.from_wei(gas_cost_wei, "ether")

                await self.notifier.send_critical(
                    f"💰 PAYMENT CLAIMED\n"
                    f"Job: {job_id}\n"
                    f"Amount: {payment_info['amount']} ETH\n"
                    f"Gas Cost: {gas_cost_eth:.6f} ETH\n"
                    f"TX: {tx_hash.hex()[:10]}...{tx_hash.hex()[-6:]}\n"
                    f"Block: {receipt['blockNumber']}\n"
                    f"Total Revenue: {self.total_revenue} ETH"
                )

                # REQ-MCP-004: Log success
                print(f"✅ Payment claimed successfully:")
                print(f"   Amount: {payment_info['amount']} ETH")
                print(f"   TX Hash: {tx_hash.hex()}")
                print(f"   Block: {receipt['blockNumber']}")

                return tx_hash.hex()
            else:
                raise Exception(f"Transaction failed: {receipt}")

        except Exception as e:
            # REQ-MCP-003: Print full exception details
            print(f"❌ Payment claim error: {str(e)}")
            print(f"   Exception type: {type(e).__name__}")
            print(f"   Full traceback: {traceback.format_exc()}")

            await self.notifier.notify_error(
                "payment_claim", f"Failed to claim payment for {job_id}: {str(e)}", "critical"
            )

            return None

    async def _wait_for_receipt(self, tx_hash, timeout: int = 120) -> Optional[Dict]:
        """Wait for transaction receipt with timeout"""
        try:
            start_time = datetime.now()

            while (datetime.now() - start_time).seconds < timeout:
                try:
                    receipt = self.w3.eth.get_transaction_receipt(tx_hash)
                    if receipt:
                        return receipt
                except Exception:
                    pass  # Transaction not yet mined

                await asyncio.sleep(2)  # Check every 2 seconds

            print(f"⚠️ Transaction receipt timeout: {tx_hash.hex()}")
            return None

        except Exception as e:
            print(f"❌ Error waiting for receipt: {str(e)}")
            return None

    def _get_escrow_abi(self) -> List[Dict]:
        """
        Get escrow contract ABI
        This is a simplified example - real ABI would be loaded from file
        """
        return [
            {
                "name": "getEscrow",
                "type": "function",
                "stateMutability": "view",
                "inputs": [{"name": "jobId", "type": "bytes32"}],
                "outputs": [
                    {"name": "depositor", "type": "address"},
                    {"name": "amount", "type": "uint256"},
                    {"name": "isLocked", "type": "bool"},
                ],
            },
            {
                "name": "claimPayment",
                "type": "function",
                "stateMutability": "nonpayable",
                "inputs": [
                    {"name": "jobId", "type": "bytes32"},
                    {"name": "proofHash", "type": "bytes32"},
                    {"name": "ipfsHash", "type": "string"},
                    {"name": "outputHash", "type": "bytes32"},
                ],
                "outputs": [{"name": "success", "type": "bool"}],
            },
            {
                "name": "deposit",
                "type": "function",
                "stateMutability": "payable",
                "inputs": [
                    {"name": "jobId", "type": "bytes32"},
                    {"name": "recipient", "type": "address"},
                ],
                "outputs": [],
            },
            {
                "name": "refund",
                "type": "function",
                "stateMutability": "nonpayable",
                "inputs": [{"name": "jobId", "type": "bytes32"}],
                "outputs": [],
            },
        ]

    async def get_balance(self) -> Dict[str, Any]:
        """Get wallet balance and payment statistics"""
        try:
            if self.w3 and self.w3.is_connected():
                # Get ETH balance
                balance_wei = self.w3.eth.get_balance(self.wallet_address)
                balance_eth = self.w3.from_wei(balance_wei, "ether")

                # Get token balances if configured
                token_balances = {}
                if self.payment_token_address:
                    # Would need ERC20 ABI and contract instance
                    pass  # TODO: Implement token balance checking

                return {
                    "eth_balance": float(balance_eth),
                    "token_balances": token_balances,
                    "total_revenue": float(self.total_revenue),
                    "pending_payments": len(self.pending_payments),
                    "completed_payments": len(self.completed_payments),
                    "wallet": self.wallet_address,
                }
            else:
                # Demo mode
                return {
                    "eth_balance": 0.0,
                    "token_balances": {},
                    "total_revenue": float(self.total_revenue),
                    "pending_payments": len(self.pending_payments),
                    "completed_payments": len(self.completed_payments),
                    "wallet": "DEMO_MODE",
                }

        except Exception as e:
            print(f"❌ Balance check error: {str(e)}")
            return {}

    async def monitor_payments(self) -> None:
        """Monitor blockchain for payment events"""
        if not self.w3 or not self.escrow_contract:
            print("⚠️ Payment monitoring not available in demo mode")
            return

        try:
            # Set up event filter for payment events
            event_filter = self.escrow_contract.events.PaymentDeposited.create_filter(
                fromBlock="latest"
            )

            print("👁️ Monitoring blockchain for payment events...")

            while True:
                try:
                    for event in event_filter.get_new_entries():
                        await self._handle_payment_event(event)
                except Exception as e:
                    print(f"⚠️ Event monitoring error: {str(e)}")

                await asyncio.sleep(10)  # Check every 10 seconds

        except Exception as e:
            print(f"❌ Payment monitoring setup failed: {str(e)}")

    async def _handle_payment_event(self, event: Dict) -> None:
        """Handle incoming payment event from blockchain"""
        try:
            job_id = event["args"].get("jobId", "").hex()
            amount = event["args"].get("amount", 0)
            depositor = event["args"].get("depositor", "")

            amount_eth = self.w3.from_wei(amount, "ether")

            print(f"💰 New payment detected:")
            print(f"   Job ID: {job_id}")
            print(f"   Amount: {amount_eth} ETH")
            print(f"   From: {depositor}")

            await self.notifier.send_critical(
                f"💰 NEW PAYMENT DETECTED\n"
                f"Job: {job_id[:16]}...\n"
                f"Amount: {amount_eth} ETH\n"
                f"From: {depositor[:10]}...{depositor[-6:]}"
            )

        except Exception as e:
            print(f"❌ Payment event handling error: {str(e)}")


# Test function
if __name__ == "__main__":

    async def test_payment_system():
        print("\n" + "=" * 60)
        print("Testing Payment System")
        print("=" * 60)

        notifier = WhatsAppNotifier()
        payment_system = PaymentSystem(notifier)

        # Test escrow verification
        test_job_id = "test_job_001"
        test_amount = 25.0

        print(f"\n1. Testing escrow verification for job {test_job_id}")
        verified = await payment_system.verify_escrow(test_job_id, test_amount)
        print(f"   Result: {'✅ Verified' if verified else '❌ Not verified'}")

        if verified:
            # Test payment claim
            print(f"\n2. Testing payment claim for job {test_job_id}")

            completion_proof = {
                "job_id": test_job_id,
                "completed_at": datetime.now().isoformat(),
                "ipfs_hash": "QmTestHash123456789",
                "output_hash": "0x" + "1" * 64,
            }

            tx_hash = await payment_system.claim_payment(test_job_id, completion_proof)
            print(f"   Result: {tx_hash if tx_hash else 'Failed'}")

        # Get balance
        print(f"\n3. Checking balance")
        balance = await payment_system.get_balance()
        print(f"   Balance: {json.dumps(balance, indent=2)}")

        print("\n✅ Payment System test complete")

    asyncio.run(test_payment_system())
