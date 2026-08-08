# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in BlindOracle (this MCP server, the
x402 API gateway at `api.craigmbrown.com`, the SDK, or any published agent
service), please report it privately:

- **Email:** craigmbrown@gmail.com (subject line: `[SECURITY] blindoracle-mcp`)
- Please include: affected component, reproduction steps, and impact assessment.
- Do **not** open a public GitHub issue for security reports.

## Response SLA

- **Acknowledgement:** within 72 hours.
- **Triage + severity assessment:** within 7 days.
- **Fix or mitigation for confirmed High/Critical issues:** targeted within 30 days,
  with status updates to the reporter.

## Scope

In scope:
- This repository (`blindoracle-mcp`): MCP server, sub-agents, core, prediction
  markets, trading signals modules.
- The live x402 service endpoints at `api.craigmbrown.com` (payment handling,
  proof emission, agent onboarding).
- `blindoracle-sdk` (PyPI).

Out of scope:
- Third-party dependencies (report upstream; we still appreciate a heads-up).
- Denial-of-service via volume against paid endpoints (rate limits apply).
- Social engineering of the operator.

## Disclosure

We practice coordinated disclosure: please give us the opportunity to remediate
before public disclosure. We credit reporters in release notes unless anonymity
is requested.

## Security Architecture

BlindOracle publishes verifiable security artifacts for its own services:
multi-agent MASSAT audits (OWASP ASI01–10), Merkle-committed findings as
`ProofOfAuditReport` (kind 30105), witness attestation, and on-chain anchoring
(Base) + Nostr. See https://craigmbrown.com/blindoracle/ for the trust
architecture.
