# UC11 — Topological Market Resolver Workflow

**RQ-166 | CRE Workflow | Port 8402**

Propagates resolution confidence from a resolved market through its correlation
graph, updating all downstream markets via BFS with exponential decay.

## Trigger

**Cron (every 15 min)**

    */15 * * * * flock -n /tmp/rq166_resolver.lock python3 scripts/rq166_resolver_runner.py --once

**x402 HTTP (paid)**

    POST /v2/market-graph/resolve

## Endpoints

| Method | Path | Auth | Price |
|------|-----|-----|-----|
| GET | /v2/market-graph | Free | \$0.00 |
| GET | /v2/market-graph/neighbors/MARKET_ID | Free | \$0.00 |
| POST | /v2/market-graph/resolve | x402 | \$0.01 USDC |
| POST | /v2/market-graph/edges | Operator key | \$0.00 |

## Resolution Flow

    rq166_resolver_runner.py
      -> TopologicalResolverHandler.run_workflow(event)
           -> MarketCorrelationGraph.load(data/market_correlation_graph.json)
           -> ConfidencePropagator.propagate(root, conf, max_hops=3)
                -> BFS with exponential decay: decay(d) = exp(-0.5 * d)
                -> Opposing edges invert: conf = 1 - conf  [REQ-RQ166-004]
           -> TopologicalMarketResolver.resolve()
                -> Mutates data/market_correlation_graph.json
                -> Mutates data/active_markets.json
                -> Appends data/propagation_audit.jsonl
           -> emit_proof() -> ProofDB kind 30015
                -> Appends data/agent_proofs/index.jsonl

## Requirements Coverage

| REQ-ID | Status |
|--------|--------|
| REQ-RQ166-001 through REQ-RQ166-015 | All satisfied |
| REQ-RQ166-009 | REST endpoints wired via MarketGraphGatewayHandler |
| REQ-RQ166-010 | x402 gate at \$0.01 USDC on /v2/market-graph/resolve |
| REQ-RQ166-011 | Cron entry added to blindoracle-cron-schedule-v3.sh |
| REQ-RQ166-014 | 44 unit/integration tests (>=40 requirement met) |

## Key Files

    chainlink-prediction-markets-mcp-enhanced/
      services/market_graph/
        model.py        -- MarketCorrelationGraph
        propagator.py   -- ConfidencePropagator (BFS)
        resolver.py     -- TopologicalMarketResolver
        api.py          -- MarketGraphAPI (REST handlers)
      cre-workflows/marketplace/
        topological_market_resolver_v1.yaml
        handlers/topological_resolver_handler.py
        README_UC11.md  -- this file
      scripts/rq166_resolver_runner.py    -- cron entry point (G1 fixed)
      tests/test_rq166_market_graph.py    -- 44 tests (G4 +5)
    blindoracle-hub/services/x402_payments/
      gateway.py  -- MarketGraphGatewayHandler (G2 x402 wiring)
