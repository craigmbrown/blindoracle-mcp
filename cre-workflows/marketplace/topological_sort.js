/**
 * topological_sort.js — RQ-166: Market Taxonomy Topological Sort
 * ================================================================
 * Kahn's BFS-based topological sort for the market correlation DAG.
 * Identifies leaf nodes (most specific markets) that need direct oracle calls.
 *
 * Input (from CRE workflow context):
 *   markets_list: Array of { id, title, parent_ids }
 *   market_dag: { nodes: {id: {...}}, edges: [{from, to, weight, signal_type}] }
 *
 * Output:
 *   { resolution_order: [id, ...], leaves: [id, ...], layers: [[...], [...]] }
 *
 * @requirement REQ-RQ166-002 — Kahn's algorithm for cycle detection and ordering
 * BLP: AU-011, SO-051
 *
 * Copyright (c) 2025-2026 Craig M. Brown. All rights reserved.
 */

/**
 * Compute topological ordering and identify leaf nodes.
 *
 * @param {Object} marketDag - { nodes: {id: {...}}, edges: [{from_market_id, to_market_id, correlation_weight, signal_type}] }
 * @returns {{ resolution_order: string[], leaves: string[], layers: string[][], cycle_detected: boolean }}
 */
function topologicalSort(marketDag) {
  const nodes = marketDag.nodes || {};
  const edges = marketDag.edges || [];

  const allIds = Object.keys(nodes);
  if (allIds.length === 0) {
    return { resolution_order: [], leaves: [], layers: [], cycle_detected: false };
  }

  // Build adjacency and in-degree maps
  const adj = {};  // from -> [to, ...]
  const inDegree = {};

  for (const id of allIds) {
    adj[id] = [];
    inDegree[id] = 0;
  }

  for (const edge of edges) {
    const from = edge.from_market_id;
    const to = edge.to_market_id;
    if (adj[from] !== undefined) {
      adj[from].push(to);
    }
    if (inDegree[to] !== undefined) {
      inDegree[to]++;
    }
  }

  // Identify leaves = nodes with no outgoing edges
  const hasOutgoing = new Set(edges.map(e => e.from_market_id));
  const leaves = allIds.filter(id => !hasOutgoing.has(id));

  // Kahn's BFS topological sort
  const queue = allIds.filter(id => inDegree[id] === 0);
  const resolutionOrder = [];
  const layers = [];  // Markets at the same BFS level (can resolve in parallel)

  let processed = 0;
  let currentQueue = [...queue];

  while (currentQueue.length > 0) {
    const nextQueue = [];
    layers.push([...currentQueue]);

    for (const node of currentQueue) {
      resolutionOrder.push(node);
      processed++;
      for (const neighbor of (adj[node] || [])) {
        inDegree[neighbor]--;
        if (inDegree[neighbor] === 0) {
          nextQueue.push(neighbor);
        }
      }
    }
    currentQueue = nextQueue;
  }

  const cycleDetected = processed !== allIds.length;

  return {
    resolution_order: resolutionOrder,
    leaves: leaves,
    layers: layers,
    cycle_detected: cycleDetected,
    stats: {
      total_markets: allIds.length,
      leaf_count: leaves.length,
      layer_count: layers.length,
      oracle_call_savings_pct: allIds.length > 0
        ? Math.round((1 - leaves.length / allIds.length) * 100)
        : 0,
    }
  };
}

// CRE runtime entry point
if (typeof module !== 'undefined') {
  module.exports = { topologicalSort };
}

// CRE workflow execution
if (typeof args !== 'undefined') {
  const result = topologicalSort(args.market_dag || { nodes: {}, edges: [] });
  output = result;
}
