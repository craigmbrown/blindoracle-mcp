#!/usr/bin/env python3
"""
handlers/topological_resolver_handler.py — RQ-166: CRE UC11 Handler
======================================================================
Python handler for the topological_market_resolver_v1 CRE workflow.
Wraps TopologicalMarketResolver for CRE runtime execution.

This is UC11 in the BlindOracle CRE marketplace workflow suite.

@requirement REQ-RQ166-005, REQ-RQ166-013 — CRE handler + workflow definition
BLP: [AU-011, SI-031]

Copyright (c) 2025-2026 Craig M. Brown. All rights reserved.
"""
from __future__ import annotations

import logging
import sys
from typing import Any, Dict, Optional

# Imports handled via __init__.py re-exports

logger = logging.getLogger(__name__)


class TopologicalResolverConfig:
    """Configuration for the topological market resolver CRE workflow."""
    max_hops: int = 3
    decay_lambda: float = 0.5
    min_correlation_weight: float = 0.1
    no_propagation: bool = False


class TopologicalResolverHandler:
    """
    CRE Handler (UC11): Topological Market Resolver.

    Entry point: run_workflow(event, config)

    Workflow steps:
      1. load_graph     — Load MarketCorrelationGraph from disk
      2. propagate      — BFS confidence propagation
      3. update_markets — Persist to active_markets.json + graph
      4. emit_proofs    — ProofDB kind 30015 events
      5. audit_log      — Write to propagation_audit.jsonl (always runs)

    @requirement REQ-RQ166-013
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        cfg = config or {}
        self.max_hops = cfg.get("max_hops", 3)
        self.decay_lambda = cfg.get("decay_lambda", 0.5)
        self.min_correlation_weight = cfg.get("min_correlation_weight", 0.1)
        self.no_propagation = cfg.get("no_propagation", False)

    def run_workflow(self, event: Dict[str, Any], config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Main CRE workflow entry point.

        Args:
            event: CRE trigger event with keys:
                   - market_id: resolved market ID
                   - outcome: "YES" | "NO"
                   - confidence: float 0-1
                   - source: str (e.g. "refresh_pipeline")
            config: Optional runtime config overrides.

        Returns:
            Workflow result dict.
        """
        if config:
            self.max_hops = config.get("max_hops", self.max_hops)
            self.decay_lambda = config.get("decay_lambda", self.decay_lambda)
            self.no_propagation = config.get("no_propagation", self.no_propagation)

        market_id = event.get("market_id", "")
        outcome = event.get("outcome", "YES")
        confidence = float(event.get("confidence", 0.8))
        source = event.get("source", "cre_workflow")

        if not market_id:
            return {"status": "error", "error": "market_id required in event", "rq": "RQ-166"}

        result = {"status": "ok", "rq": "RQ-166", "workflow": "UC11-topological-resolver"}

        # Step 1: Load graph
        try:
            from services.market_graph import (
                TopologicalMarketResolver,
                ConfidencePropagator,
            )

            propagator = ConfidencePropagator(
                decay_lambda=self.decay_lambda,
                min_correlation_weight=self.min_correlation_weight,
            )
            resolver = TopologicalMarketResolver(
                decay_lambda=self.decay_lambda,
                max_hops=self.max_hops,
                propagator=propagator,
                no_propagation=self.no_propagation,
                min_correlation_weight=self.min_correlation_weight,
            )
            result["step_load_graph"] = "ok"
        except Exception as e:
            result["status"] = "error"
            result["step_load_graph"] = f"error: {e}"
            logger.error("Failed to load graph: %s", e)
            return result

        # Steps 2-5: Resolve (propagate + update + emit proofs + audit log)
        try:
            prop_result = resolver.resolve(market_id, outcome, confidence, source)
            result["step_propagate"] = "ok"
            result["step_update_markets"] = "ok"
            result["step_emit_proofs"] = "ok"
            result["step_audit_log"] = "ok"
            result["propagation"] = prop_result
            result["markets_updated"] = len(prop_result.get("affected_markets", []))
        except Exception as e:
            logger.error("RQ-166 TopologicalResolverHandler error: %s", e)
            result["status"] = "error"
            result["error"] = str(e)
            result["step_audit_log"] = "ok"  # audit_log always runs

        return result
