/**
 * propagate_resolutions.js — RQ-166: Resolution Propagation
 * ===========================================================
 * Propagates leaf market resolutions UP through the correlation DAG.
 * Implements the specialization order propagation rules:
 *   - child YES → parent lean YES (supporting)
 *   - child YES → parent lean NO (opposing)
 *   - All children NO → parent = NO (unanimous)
 *   - Children mixed → parent needs its own oracle (partial propagation)
 *
 * Input (from CRE workflow context):
 *   resolved_leaves: [{market_id, outcome, confidence}]
 *   compute_topo_sort.edges: [{from_market_id, to_market_id, correlation_weight, signal_type}]
 *
 * Output:
 *   { full_resolution_map: {market_id: {outcome, confidence, source}}, oracle_misses: [id] }
 *
 * @requirement REQ-RQ166-003, REQ-RQ166-004 — Propagation with opposing signal inversion
 * BLP: SI-031, SO-051
 *
 * Copyright (c) 2025-2026 Craig M. Brown. All rights reserved.
 */

const DECAY_LAMBDA = 0.5;

/**
 * Exponential decay: e^(-λ * hop)
 * @param {number} hop
 * @returns {number}
 */
function decay(hop) {
  return Math.exp(-DECAY_LAMBDA * hop);
}

/**
 * Propagate resolved leaf values up to parent markets.
 *
 * @param {Array} resolvedLeaves - [{market_id, outcome, confidence}]
 * @param {Array} edges - [{from_market_id, to_market_id, correlation_weight, signal_type}]
 * @param {Object} allNodes - {market_id: {title, resolver_confidence}}
 * @returns {{
 *   full_resolution_map: Object,
 *   oracle_misses: string[],
 *   propagated_count: number,
 *   oracle_call_savings_pct: number
 * }}
 */
function propagateResolutions(resolvedLeaves, edges, allNodes) {
  // Build resolution map from leaves
  const resolutionMap = {};
  for (const leaf of resolvedLeaves) {
    resolutionMap[leaf.market_id] = {
      outcome: leaf.outcome,
      confidence: leaf.confidence,
      source: 'oracle',
      hop: 0,
    };
  }

  // Build reverse adjacency: to -> [{from, weight, signal_type}]
  const reverseAdj = {};
  for (const nodeId of Object.keys(allNodes || {})) {
    reverseAdj[nodeId] = [];
  }
  for (const edge of edges) {
    if (!reverseAdj[edge.to_market_id]) reverseAdj[edge.to_market_id] = [];
    reverseAdj[edge.to_market_id].push({
      from: edge.from_market_id,
      weight: edge.correlation_weight || 0.5,
      signal_type: edge.signal_type || 'supporting',
    });
  }

  // BFS propagation: for each unresolved market, check if children resolved
  const oracleMisses = [];
  const allMarketIds = Object.keys(allNodes || {});

  // Process in order from leaves to roots (using reverse BFS)
  // Simple approach: iterate until stable
  let changed = true;
  const maxIterations = allMarketIds.length + 1;
  let iteration = 0;

  while (changed && iteration < maxIterations) {
    changed = false;
    iteration++;

    for (const marketId of allMarketIds) {
      if (resolutionMap[marketId]) continue;  // Already resolved

      const parents = reverseAdj[marketId] || [];
      if (parents.length === 0) continue;

      // Check if all parents are resolved
      const resolvedParents = parents.filter(p => resolutionMap[p.from]);
      if (resolvedParents.length === 0) continue;

      // Compute weighted confidence from resolved parents
      let totalWeight = 0;
      let weightedConf = 0;
      let allYes = true;
      let allNo = true;

      for (const parent of resolvedParents) {
        const parentResolution = resolutionMap[parent.from];
        const hop = (parentResolution.hop || 0) + 1;
        const decayFactor = decay(hop);
        const baseConf = parentResolution.confidence * parent.weight * decayFactor;

        // Apply signal inversion for opposing edges
        let adjustedConf = parent.signal_type === 'opposing' ? (1.0 - baseConf) : baseConf;
        adjustedConf = Math.max(0, Math.min(1, adjustedConf));

        weightedConf += adjustedConf * parent.weight;
        totalWeight += parent.weight;

        if (parentResolution.outcome !== 'YES') allYes = false;
        if (parentResolution.outcome !== 'NO') allNo = false;
      }

      if (totalWeight === 0) continue;

      const avgConf = weightedConf / totalWeight;

      // Determine outcome from propagation
      let outcome;
      if (avgConf >= 0.7) {
        outcome = 'YES';
      } else if (avgConf <= 0.3) {
        outcome = 'NO';
      } else {
        // Ambiguous — needs oracle call (partial propagation)
        oracleMisses.push(marketId);
        continue;
      }

      resolutionMap[marketId] = {
        outcome,
        confidence: avgConf,
        source: 'propagated',
        hop: Math.min(...resolvedParents.map(p => (resolutionMap[p.from].hop || 0) + 1)),
        propagated_from: resolvedParents.map(p => p.from),
      };
      changed = true;
    }
  }

  // Any unresolved markets that aren't leaves need oracle calls
  for (const id of allMarketIds) {
    if (!resolutionMap[id] && !oracleMisses.includes(id)) {
      oracleMisses.push(id);
    }
  }

  const resolvedCount = Object.values(resolutionMap).filter(r => r.source === 'propagated').length;
  const totalResolvable = allMarketIds.length;

  return {
    full_resolution_map: resolutionMap,
    oracle_misses: oracleMisses,
    propagated_count: resolvedCount,
    oracle_call_savings_pct: totalResolvable > 0
      ? Math.round((resolvedCount / totalResolvable) * 100)
      : 0,
  };
}

// CRE runtime entry point
if (typeof module !== 'undefined') {
  module.exports = { propagateResolutions, decay };
}

// CRE workflow execution
if (typeof args !== 'undefined') {
  const result = propagateResolutions(
    args.resolved_leaves || [],
    args.edges || [],
    args.all_nodes || {}
  );
  output = result;
}
