#!/usr/bin/env python3
"""
BlindOracle Balance Manager - Multi-Rail Balance Aggregation

Aggregates balance information across all payment rails (ecash, lightning,
stablecoin, fiat, ccip) and on-chain wallet inventory. This module is the
single source of truth for the check_balance / check_account capability.

Used by:
  - distribution/clawhub_skill/handler.py (Brand B: check_balance)
  - distribution/clawhub_skill_brand_a/handler.py (Brand A: check_account)
  - distribution/a2a_server.py (A2A protocol)

@requirement: REQ-PAY-002 - Balance tracking and reporting
@requirement: REQ-PAY-010 - Payment rail abstraction
@blp: BLP-021 Durability - Persistent balance tracking across rails
@blp: BLP-001 Alignment - Returns data in format matching caller's brand context

Copyright (c) 2025 Craig M. Brown. All rights reserved.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("blindoracle.balance_manager")

PROJECT_ROOT = Path(__file__).parent.parent
WALLET_INVENTORY = PROJECT_ROOT / "config" / "wallet_inventory.json"
FEDIMINT_BALANCES = PROJECT_ROOT / "logs" / "fedimint_balances.json"


def _load_wallet_inventory() -> Dict[str, Any]:
    """Load static wallet inventory from config."""
    try:
        if WALLET_INVENTORY.exists():
            return json.loads(WALLET_INVENTORY.read_text())
    except Exception as e:
        logger.warning("Could not load wallet inventory: %s", e)
    return {}


def _load_fedimint_balances() -> Dict[str, Any]:
    """Load Fedimint federation balances from ledger state."""
    try:
        if FEDIMINT_BALANCES.exists():
            return json.loads(FEDIMINT_BALANCES.read_text())
    except Exception as e:
        logger.warning("Could not load Fedimint balances: %s", e)
    return {}


def _get_rail_balance(rail_type: str, agent_id: str = "default") -> Dict[str, Any]:
    """Get balance for a specific rail via the settlement engine."""
    try:
        from services.payments.settlement_engine import get_payment_rail
        rail = get_payment_rail(rail_type)
        return rail.get_balance(agent_id)
    except (ImportError, ValueError) as e:
        logger.warning("Rail %s unavailable: %s", rail_type, e)
        return {"rail": rail_type, "balance_units": 0, "status": "unavailable"}


def check_balance(
    rail: str = "all",
    agent_id: str = "default",
) -> Dict[str, Any]:
    """Check balances across one or all payment rails.

    This is the main entry point called by handler.py for both Brand A
    (check_account) and Brand B (check_balance) capabilities.

    Args:
        rail: Rail to query. "all" returns all rails. Other valid values:
              ecash, private, lightning, instant, stablecoin, usdc, fiat, ccip.
        agent_id: Agent identifier for per-agent balance lookup.

    Returns:
        Dictionary with balance information per rail, plus aggregate totals.
    """
    timestamp = datetime.now(timezone.utc).isoformat()

    if rail == "all":
        # Query all unique rail types
        rail_types = ["ecash", "lightning", "stablecoin", "fiat", "ccip"]
        balances = {}
        for rt in rail_types:
            balances[rt] = _get_rail_balance(rt, agent_id)

        # Enrich with wallet inventory data
        inventory = _load_wallet_inventory()
        wallets = inventory.get("wallets", [])

        on_chain = {}
        for wallet in wallets:
            name = wallet.get("name", "unknown")
            if "chains" in wallet:
                total_usd = wallet.get("total_usd", 0)
                on_chain[name] = {
                    "total_usd": total_usd,
                    "chains": {
                        k: v for k, v in wallet["chains"].items()
                        if v.get("balance_usd", 0) > 0 or v.get("balance_eth", 0) > 0
                    },
                }
            elif "balance_sats" in wallet:
                on_chain[name] = {
                    "balance_sats": wallet["balance_sats"],
                    "agent_wallets": wallet.get("agent_wallets", {}),
                }

        # Compute aggregate
        total_ecash_units = balances.get("ecash", {}).get("balance_units", 0)
        total_lightning_units = balances.get("lightning", {}).get("balance_units", 0)
        total_stablecoin_units = balances.get("stablecoin", {}).get("balance_units", 0)

        # Add Fedimint balance from inventory if available
        fedimint_sats = 0
        for wallet in wallets:
            if wallet.get("name") == "Fedimint Federation":
                fedimint_sats = wallet.get("balance_sats", 0)
                break

        return {
            "agent_id": agent_id,
            "timestamp": timestamp,
            "rails": balances,
            "on_chain": on_chain,
            "summary": {
                "ecash_units": total_ecash_units,
                "lightning_units": total_lightning_units,
                "stablecoin_units": total_stablecoin_units,
                "fedimint_sats": fedimint_sats,
                "rails_queried": len(rail_types),
                "rails_available": sum(
                    1 for b in balances.values()
                    if b.get("status") != "unavailable"
                ),
            },
            "fee": 0.0,
            "fee_currency": "USDC",
            "note": "check_balance is FREE (no x402 payment required)",
        }
    else:
        # Single rail query
        balance = _get_rail_balance(rail, agent_id)
        return {
            "agent_id": agent_id,
            "timestamp": timestamp,
            "rail": rail,
            "balance": balance,
            "fee": 0.0,
            "fee_currency": "USDC",
            "note": "check_balance is FREE (no x402 payment required)",
        }
