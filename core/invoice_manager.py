#!/usr/bin/env python3
"""
BlindOracle Invoice Manager - Payment Request Generation

Creates payment invoices/requests for the instant settlement rail.
Wraps the settlement engine's LightningRail for BOLT11-style invoices
and the StablecoinRail for x402 payment requests.

Used by:
  - distribution/clawhub_skill/handler.py (Brand B: create_invoice)
  - distribution/clawhub_skill_brand_a/handler.py (Brand A: create_settlement_request)

@requirement: REQ-PAY-001 - Payment request generation
@requirement: REQ-PAY-010 - Payment rail abstraction
@blp: BLP-011 Autonomy - Generates invoices without human intervention
@blp: BLP-021 Durability - Persists invoice state for later verification

Copyright (c) 2025 Craig M. Brown. All rights reserved.
"""

import hashlib
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("blindoracle.invoice_manager")

PROJECT_ROOT = Path(__file__).parent.parent
INVOICE_LOG = PROJECT_ROOT / "logs" / "invoices.json"


def _load_invoices() -> list:
    """Load invoice history."""
    try:
        if INVOICE_LOG.exists():
            return json.loads(INVOICE_LOG.read_text())
    except Exception:
        pass
    return []


def _save_invoice(invoice: Dict[str, Any]):
    """Append invoice to log."""
    try:
        INVOICE_LOG.parent.mkdir(parents=True, exist_ok=True)
        invoices = _load_invoices()
        invoices.append(invoice)
        # Keep last 1000 invoices
        if len(invoices) > 1000:
            invoices = invoices[-1000:]
        INVOICE_LOG.write_text(json.dumps(invoices, indent=2))
    except Exception as e:
        logger.warning("Could not save invoice: %s", e)


def create_invoice(
    amount_sats: int,
    description: str = "",
    expiry_seconds: int = 3600,
    rail: str = "instant",
) -> Dict[str, Any]:
    """Create a payment invoice/request.

    For Brand B callers this creates a Lightning-style BOLT11 invoice.
    For Brand A callers (via handler translation) this creates a
    settlement request on the instant rail.

    Args:
        amount_sats: Amount in satoshi-equivalent units.
        description: Human-readable invoice description.
        expiry_seconds: Invoice validity period in seconds (default 1h).
        rail: Payment rail to use (instant, private, on_ledger).

    Returns:
        Dictionary with invoice details including payment hash and encoded invoice.
    """
    timestamp = datetime.now(timezone.utc)
    expires_at = timestamp.timestamp() + expiry_seconds

    # Generate deterministic invoice ID from params + timestamp
    invoice_seed = f"{amount_sats}:{description}:{timestamp.isoformat()}:{rail}"
    payment_hash = hashlib.sha256(invoice_seed.encode()).hexdigest()
    invoice_id = f"inv_{payment_hash[:16]}"

    # Map rail to settlement type
    rail_map = {
        "instant": "bolt11",
        "lightning": "bolt11",
        "private": "ecash_request",
        "ecash": "ecash_request",
        "on_ledger": "x402_request",
        "stablecoin": "x402_request",
    }
    invoice_type = rail_map.get(rail, "x402_request")

    # Build encoded invoice (simulated BOLT11 / x402 format)
    if invoice_type == "bolt11":
        # BOLT11-style encoded invoice
        encoded = f"lnbc{amount_sats}n1p{payment_hash[:20]}"
    elif invoice_type == "ecash_request":
        # eCash request via guardian federation
        encoded = f"ecash:{payment_hash[:32]}"
    else:
        # x402 payment request
        encoded = f"x402:{payment_hash[:32]}"

    invoice = {
        "invoice_id": invoice_id,
        "payment_hash": payment_hash,
        "amount_sats": amount_sats,
        "description": description,
        "rail": rail,
        "invoice_type": invoice_type,
        "encoded_invoice": encoded,
        "created_at": timestamp.isoformat(),
        "expires_at": datetime.fromtimestamp(expires_at, tz=timezone.utc).isoformat(),
        "expiry_seconds": expiry_seconds,
        "status": "pending",
    }

    _save_invoice(invoice)
    logger.info(
        "Invoice created: %s, %d sats, rail=%s, expires=%ds",
        invoice_id, amount_sats, rail, expiry_seconds,
    )

    return invoice
