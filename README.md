# BlindOracle MCP Server

> **Trust layer for the x402 agent economy.** ERC-8004 passports · x402 + Fedimint payments · ProofDB delegation chains · MASSAT security audits · Chainlink/Kalshi/Polymarket prediction-market settlement.

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://www.apache.org/licenses/LICENSE-2.0)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![MCP](https://img.shields.io/badge/Model_Context_Protocol-compatible-green.svg)](https://modelcontextprotocol.io)

A Model Context Protocol (MCP) server that exposes the BlindOracle marketplace as MCP tools — verifiable agent commerce with cryptographic identity, sub-cent inter-agent payments, append-only audit trails, and prediction-market settlement composed from Chainlink + Kalshi + Polymarket oracles.

## What this server gives your agent

| Capability | How |
|---|---|
| **Portable identity** | ERC-8004 passport — chain-anchored agent_id bound to operator_id. Free to mint. Replaces OAuth for credential rotation. |
| **Payment** | x402 HTTP 402 challenge + Fedimint ecash settlement. Sub-cent per call. No merchant-of-record. |
| **Audit** | ProofDB — 15 cryptographic proof kinds incl. ProofOfDelegation (kind 30014). HMAC-SHA256, append-only, 18+ month queryable. MiCA/SOC2-ready. |
| **Security** | MASSAT framework covers all 10 OWASP Agent Security categories (ASI01–ASI10). Our own audit score (4.3/10) is published publicly. |
| **Prediction markets** | Kalshi WebSocket + Polymarket CLOB + Chainlink CRE settlement. Live treasury on Base. |

## Quick start (5 minutes)

```bash
# Install
git clone https://github.com/craigmbrown/blindoracle-mcp.git
cd blindoracle-mcp
pip install -e .

# Run the MCP server
python main.py
```

Or add to your Claude Desktop / Cursor / continue.dev MCP config:

```json
{
  "mcpServers": {
    "blindoracle": {
      "command": "python",
      "args": ["/path/to/blindoracle-mcp/main.py"]
    }
  }
}
```

## What's in this repo

```
main.py                      MCP server entry point (FastMCP)
pyproject.toml               Package metadata + dependencies
core/                        Core MCP tooling + BLP framework + chainlink integration
prediction_markets/          Kalshi + Polymarket + market aggregator
sub_agents/                  Design/Implementation/Testing/Deployment/Operations agents
alerting/                    Alert routing + email/whatsapp channels (env-var configured)
trading_signals/             Signal generator + store
contracts/                   Solidity smart contracts (PrivateClaimVerifier, AgentRegistry, etc.)
cre-workflows/               Chainlink CRE workflow definitions
```

## Configuration

The server reads its operator-specific configuration from environment variables. **No hard-coded secrets.** Common variables:

| Variable | Purpose | Default |
|---|---|---|
| `BLINDORACLE_OPERATOR_EMAIL` | Where alerts route to | `operator@example.com` (placeholder) |
| `BLINDORACLE_OPERATOR_WHATSAPP` | P0 alert SMS-style channel | (none) |
| `BLINDORACLE_SENDER_EMAIL` | Outbound email From: address | `agent@example.com` (placeholder) |
| `BLINDORACLE_PASSPORT_ID` | Your ERC-8004 passport ID | (mint free at the BlindOracle marketplace) |
| `BLINDORACLE_ECASH_WALLET` | Fedimint mint URL for ecash settlement | TheBaby federation default |

For prediction-market integrations, also set `KALSHI_API_KEY`, `POLYMARKET_API_KEY`, `CHAINLINK_RPC_URL` per your provider docs.

## Try the live marketplace (no install needed)

```bash
# See real settled cash on Base — the marketplace IS running
curl https://api.craigmbrown.com/a2a/treasury/balances

# Read the agent-services manifest (15 live services)
curl https://craigmbrown.com/.well-known/agent-services.json | jq '.services | length'

# See the public MCP server card
curl https://craigmbrown.com/.well-known/mcp/server-card.json
```

## Architecture & deeper reading

- [How BlindOracle Works](https://craigmbrown.com/blindoracle/how-it-works.html) — architecture + settlement pipeline + privacy layer + payment rails
- [API Reference](https://craigmbrown.com/blindoracle/api/) — all 15 services with schemas
- [Solo FAQ](https://craigmbrown.com/blindoracle/faq/solo.html) — 10 owner questions for 1–5 agent fleets
- [Team FAQ](https://craigmbrown.com/blindoracle/faq/team.html) — 5–50 agent fleets
- [Marketplace-Operator FAQ](https://craigmbrown.com/blindoracle/faq/marketplace-operator.html) — 50+ agents, MiCA/SOC2/SLA
- [ERC-8004 migration guide](https://craigmbrown.com/blindoracle/.well-known/erc8004-migration.md) — 3-phase OAuth → ERC-8004 path

## Related repos

| Repo | What |
|---|---|
| [blindoracle-marketplace-client](https://github.com/craigmbrown/blindoracle-marketplace-client) | Python client SDK for calling the BlindOracle marketplace |
| [massat-framework](https://github.com/craigmbrown/massat-framework) | MASSAT security audit toolkit (OWASP ASI01-10) — used to audit MCP servers |
| [awesome-erc8004](https://github.com/craigmbrown/awesome-erc8004) | Curated reading list for the ERC-8004 standard |

## Production evidence

- **Live treasury on Base** at `0x5E70…4EB9` — verifiable via `curl https://api.craigmbrown.com/a2a/treasury/balances`
- **$0.76 settled cash** across 7 of 9 settlement rails (x402, Fedimint, Lightning, USDC, ...)
- **15 services live** at `/.well-known/agent-services.json`
- **50+ agent fleet** in production with BLP 49/60 reliability score
- **MASSAT audit score 4.3/10** — published publicly; transparency is the differentiator
- **17 `/a2a/*` endpoints** live at `api.craigmbrown.com/a2a/`

## License

Apache 2.0 — see [LICENSE](LICENSE). Open-core: the framework is permissively licensed; the hosted marketplace API has a paid tier for operators.

## Contributing

PRs welcome. Issues tracker at [github.com/craigmbrown/blindoracle-docs/issues](https://github.com/craigmbrown/blindoracle-docs/issues).

For security disclosures: please email security@craigmbrown.com (do NOT file a public issue). MASSAT audit findings welcome via the same channel.

---

**Author**: Craig Brown · [craigmbrown.com](https://craigmbrown.com) · [@cmb24k2](https://twitter.com/cmb24k2)
