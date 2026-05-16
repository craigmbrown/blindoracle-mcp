#!/usr/bin/env python3
"""
handlers/ccip_conditional_handler.py — RQ-172: CRE UC12 Handler
=========================================================================
Python handler for the cross_chain_conditional_v1 CRE workflow.
Wraps the RQ-172 CCIP runner for CRE runtime execution.

This is UC12 in the BlindOracle CRE marketplace workflow suite.

@requirement REQ-RQ172-003: CRE handler binding cross_chain_conditional_v1.yaml to Python
BLP: Self-Organization (BLP-051)

Copyright (c) 2025-2026 Craig M. Brown. All rights reserved.
"""

from __future__ import annotations

import logging
import sys
from typing import Any, Dict, Optional
from pathlib import Path

logger = logging.getLogger(__name__)


class CCIPConditionalConfig:
    """Configuration for the cross-chain conditional markets CRE workflow."""
    registry_path: Optional[str] = None
    simulate: bool = True


class CCIPConditionalHandler:
    """
    CRE Handler (UC12): Cross-Chain Conditional Markets (CCIP).

    Entry point: run_workflow(event, config)

    Workflow steps:
      1. load_registry — Load conditional markets from disk
      2. match_conditionals — Find conditionals for resolved market
      3. format_payload — Create CCIP message
      4. send_ccip — Dispatch via engine (simulated by default)
      5. emit_proof — Write ProofOfCrossChainSettlement to ProofDB
      6. audit_log — Append to ccip_settlement_audit.jsonl

    @requirement REQ-RQ172-003
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        cfg = config or {}
        self.registry_path = cfg.get("registry_path")
        self.simulate = cfg.get("simulate", True)

    def run_workflow(self, event: Dict[str, Any], config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Main CRE workflow entry point.

        Args:
            event: CRE trigger event with keys:
                   - market_id: resolved market ID
                   - outcome: 0 (NO) or 1 (YES)
                   - resolved_at: ISO timestamp
                   - confidence: float 0-1 (optional)
            config: Optional runtime config overrides.

        Returns:
            Workflow result dict.
        """
        if config:
            self.registry_path = config.get("registry_path", self.registry_path)
            self.simulate = config.get("simulate", self.simulate)

        market_id = event.get("market_id", "")
        outcome = event.get("outcome", 0)
        resolved_at = event.get("resolved_at", "")

        try:
            # Import runner to process the event
            PROJECT_ROOT = Path(__file__).parent.parent.parent
            sys.path.insert(0, str(PROJECT_ROOT))
            sys.path.insert(0, str(PROJECT_ROOT / "chainlink-prediction-markets-mcp-enhanced"))

            from scripts.rq172_ccip_runner import process_event as ccip_process_event

            # Enrich event with conditional lookup
            result = ccip_process_event(
                {
                    "market_id": market_id,
                    "outcome": outcome,
                    "resolved_at": resolved_at,
                },
                dry_run=False,
                registry_path=self.registry_path
            )

            return {
                "status": result.get("status"),
                "rq": "RQ-172",
                "workflow": "UC12-cross-chain-conditional-v1",
                "market_id": market_id,
                "message_id": result.get("message_id"),
                "proof_id": result.get("proof_id"),
            }

        except Exception as exc:
            logger.error("CRE handler invocation failed: %s", exc, exc_info=True)
            return {
                "status": "error",
                "error": str(exc),
                "rq": "RQ-172",
                "workflow": "UC12-cross-chain-conditional-v1",
            }
