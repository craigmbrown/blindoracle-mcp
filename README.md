# BlindOracle MCP Server

> **Trust layer for the x402 agent economy.** ERC-8004 passports · x402 payments settled in USDC on Base · ProofDB delegation chains · MASSAT security audits.

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://www.apache.org/licenses/LICENSE-2.0)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![MCP](https://img.shields.io/badge/Model_Context_Protocol-compatible-green.svg)](https://modelcontextprotocol.io)

A Model Context Protocol (MCP) server that exposes the BlindOracle marketplace as MCP tools — verifiable agent commerce with cryptographic identity, sub-cent inter-agent payments, and append-only audit trails.

## What this server gives your agent

| Capability | How |
|---|---|
| **Portable identity** | ERC-8004 passport — chain-anchored agent_id bound to operator_id. Free to mint. Replaces OAuth for credential rotation. |
| **Payment** | x402 HTTP 402 challenge, settled in USDC on Base. Sub-cent per call. No merchant-of-record. |
| **Audit** | ProofDB — 15 cryptographic proof kinds incl. ProofOfDelegation (kind 30014). HMAC-SHA256, append-only, 18+ month queryable. MiCA/SOC2-ready. |
| **Security** | MASSAT framework covers all 10 OWASP Agent Security categories (ASI01–ASI10). Findings published publicly — transparency is the differentiator. |

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
core/                        Core MCP tooling + BLP framework
sub_agents/                  Design/Implementation/Testing/Deployment/Operations agents
alerting/                    Alert routing + email/whatsapp channels (env-var configured)
trading_signals/             Signal generator + store
contracts/                   Solidity smart contracts (PrivateClaimVerifier, AgentRegistry, etc.)
```

## Configuration

The server reads its operator-specific configuration from environment variables. **No hard-coded secrets.** Common variables:

| Variable | Purpose | Default |
|---|---|---|
| `BLINDORACLE_OPERATOR_EMAIL` | Where alerts route to | `operator@example.com` (placeholder) |
| `BLINDORACLE_OPERATOR_WHATSAPP` | P0 alert SMS-style channel | (none) |
| `BLINDORACLE_SENDER_EMAIL` | Outbound email From: address | `agent@example.com` (placeholder) |
| `BLINDORACLE_PASSPORT_ID` | Your ERC-8004 passport ID | (mint free at the BlindOracle marketplace) |

## Try the live marketplace (no install needed)

```bash
# See the treasury's live solvency status on Base — the marketplace IS running
curl https://api.craigmbrown.com/a2a/treasury/balances

# Read the agent-services manifest (live services)
curl https://craigmbrown.com/.well-known/agent-services.json | jq '.services | length'

# See the public MCP server card
curl https://craigmbrown.com/.well-known/mcp/server-card.json
```

## Architecture & deeper reading

- [How BlindOracle Works](https://craigmbrown.com/blindoracle/how-it-works.html) — architecture + settlement pipeline + privacy layer + payment rails
- [API Reference](https://craigmbrown.com/blindoracle/api/) — services with schemas
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

- **Live treasury on Base** at `0x5E70…4EB9` — solvency status verifiable via `curl https://api.craigmbrown.com/a2a/treasury/balances`
- **Settlement rail: x402/USDC on Base** — the only customer settlement rail
- **Services live** at `/.well-known/agent-services.json`
- **42+ agent fleet** in production, BLP framework 60/60 property coverage
- **MASSAT self-audit findings published publicly** (OWASP ASI01–ASI10)
- **`/a2a/*` endpoints** live at `api.craigmbrown.com/a2a/`

## License

Apache 2.0 — see [LICENSE](LICENSE). Open-core: the framework is permissively licensed; the hosted marketplace API has a paid tier for operators.

## Contributing

PRs welcome. Issues tracker at [github.com/craigmbrown/blindoracle-docs/issues](https://github.com/craigmbrown/blindoracle-docs/issues).

For security disclosures: please email security@craigmbrown.com (do NOT file a public issue). MASSAT audit findings welcome via the same channel.

---

**Author**: Craig Brown · [craigmbrown.com](https://craigmbrown.com) · [@cmb24k2](https://twitter.com/cmb24k2)
