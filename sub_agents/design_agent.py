#!/usr/bin/env python3
"""
Prediction Market Design Agent
@requirement: REQ-AGENT-001 - Design phase automation with alignment focus
@requirement: REQ-AGENT-001a - Architecture design generation
@requirement: REQ-AGENT-001b - Data flow optimization
@requirement: REQ-AGENT-001c - Security layer integration
"""

import hashlib
import json
import logging
import traceback
from datetime import datetime
from typing import Dict, List, Any, Optional, Set
from dataclasses import dataclass, field
import sys
import os

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.base_level_properties import PropertyTracker
# MASSAT remediation: security infrastructure (ASI01-ASI10)
from core.security_guards import validate_agent_input, check_agent_scope, log_agent_action
from core.tool_allowlist import validate_tool_call, get_allowed_tools
from core.agent_monitor import AgentSessionMonitor

logger = logging.getLogger("bo.design_agent")


@dataclass
class DesignSpecification:
    """Design specification for prediction market system"""

    project_name: str
    architecture: Dict[str, Any]
    data_flows: List[Dict[str, Any]]
    security_layers: List[Dict[str, Any]]
    integration_points: List[Dict[str, Any]]
    requirements: List[Dict[str, Any]]
    created_at: datetime = field(default_factory=datetime.now)
    version: str = "1.0.0"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "project_name": self.project_name,
            "architecture": self.architecture,
            "data_flows": self.data_flows,
            "security_layers": self.security_layers,
            "integration_points": self.integration_points,
            "requirements": self.requirements,
            "created_at": self.created_at.isoformat(),
            "version": self.version,
        }


class PredictionMarketDesignAgent:
    """
    REQ-AGENT-001: Design phase automation with alignment focus
    @requirement: REQ-AGENT-001 - Design automation [@sub_agents/design_agent.py:40-120]
    """

    # MASSAT: Allowed input keys for this agent (ASI01)
    ALLOWED_INPUT_KEYS: Set[str] = {"markets", "oracles", "features", "requirements", "config"}

    def __init__(self):
        self.property_tracker = PropertyTracker()
        self.designs_created = 0
        # MASSAT: Initialize behavioral monitor (ASI10)
        self.monitor = AgentSessionMonitor("design_agent")
        log_agent_action("design_agent", "initialize")
        print("✅ PredictionMarketDesignAgent initialized (security-hardened)")

    async def design_system(self, requirements: Dict[str, Any]) -> Dict[str, Any]:
        """
        Design the prediction market system architecture
        @requirement: REQ-AGENT-001a - Architecture design [@sub_agents/design_agent.py:125-160]
        """
        try:
            print("🎨 Starting system design phase")

            # MASSAT ASI01: Validate and sanitize input
            validation = validate_agent_input(
                "design_agent", requirements, self.ALLOWED_INPUT_KEYS
            )
            if not validation["valid"]:
                logger.warning("Input validation failed: %s", validation["violations"])
                print(f"⚠️ Input sanitized: {len(validation['violations'])} violations")
            requirements = validation["sanitized"]

            # MASSAT ASI03: Check scope
            if not check_agent_scope("design_agent", "design_system"):
                raise PermissionError("design_agent not authorized for design_system")

            # MASSAT ASI02: Validate tool call
            tool_check = validate_tool_call("design_agent", "generate_architecture", requirements)
            if not tool_check["allowed"]:
                logger.warning("Tool validation: %s", tool_check["violations"])

            # MASSAT ASI10: Record action
            inputs_hash = hashlib.sha256(json.dumps(requirements, default=str, sort_keys=True).encode()).hexdigest()[:16]
            log_agent_action("design_agent", "design_system", inputs_hash=inputs_hash)
            self.monitor.record_tool_call("design_system")

            # Extract requirements
            markets = requirements.get("markets", ["kalshi", "polymarket"])
            oracles = requirements.get("oracles", ["chainlink"])
            features = requirements.get("features", ["arbitrage", "streaming", "cre"])

            # Generate architecture
            architecture = await self._design_architecture(markets, oracles, features)

            # Design data flows
            data_flows = await self._design_data_flows(markets, oracles)

            # Design security layers
            security_layers = await self._design_security_layers()

            # Define integration points
            integration_points = await self._design_integration_points(markets, oracles)

            # Create design specification
            design = DesignSpecification(
                project_name="Chainlink Prediction Markets MCP",
                architecture=architecture,
                data_flows=data_flows,
                security_layers=security_layers,
                integration_points=integration_points,
                requirements=self._generate_requirements(markets, oracles, features),
            )

            # Update Base Level Properties
            # REQ-BLP-001: Alignment - focusing on correct solution
            self.property_tracker.update_property("alignment", 0.8)
            # REQ-BLP-006: Self-organization - designing efficient structure
            self.property_tracker.update_property("self_organization", 0.5)

            self.designs_created += 1

            # REQ-MCP-004: Log success before return
            print(f"✅ System design complete: {design.project_name} v{design.version}")
            print(f"   Architecture layers: {len(architecture.get('layers', []))}")
            print(f"   Data flows: {len(data_flows)}")
            print(f"   Security layers: {len(security_layers)}")

            return design.to_dict()

        except Exception as e:
            # REQ-MCP-003: Print full exception details
            print(f"❌ Error in system design: {str(e)}")
            print(f"   Exception type: {type(e).__name__}")
            print(f"   Traceback: {traceback.format_exc()}")
            raise

    async def _design_architecture(
        self, markets: List[str], oracles: List[str], features: List[str]
    ) -> Dict[str, Any]:
        """
        REQ-AGENT-001a: Generate system architecture
        @requirement: REQ-AGENT-001a - Architecture design [@sub_agents/design_agent.py:125-160]
        """
        try:
            architecture = {
                "layers": [
                    {
                        "name": "MCP Interface Layer",
                        "components": ["FastMCP Server", "Tool Registry", "Request Handler"],
                        "responsibilities": ["External API", "Tool management", "Request routing"],
                    },
                    {
                        "name": "Aggregation Layer",
                        "components": ["Market Aggregator", "Data Normalizer", "Arbitrage Engine"],
                        "responsibilities": [
                            "Cross-market data",
                            "Opportunity detection",
                            "Data normalization",
                        ],
                    },
                    {
                        "name": "Market Integration Layer",
                        "components": [f"{market.title()} Client" for market in markets],
                        "responsibilities": [
                            "Market connections",
                            "Order management",
                            "Position tracking",
                        ],
                    },
                    {
                        "name": "Oracle Layer",
                        "components": [f"{oracle.title()} Connector" for oracle in oracles],
                        "responsibilities": ["Price feeds", "VRF", "CCIP", "Keepers", "CRE"],
                    },
                    {
                        "name": "Smart Contract Layer",
                        "components": ["CTF Exchange", "Market Maker", "Arbitrage Bot"],
                        "responsibilities": [
                            "On-chain execution",
                            "Token management",
                            "DeFi integration",
                        ],
                    },
                    {
                        "name": "Security Layer",
                        "components": [
                            "Byzantine Consensus",
                            "CaMel Architecture",
                            "Validation Engine",
                        ],
                        "responsibilities": [
                            "Request validation",
                            "Anti-manipulation",
                            "Audit logging",
                        ],
                    },
                ],
                "patterns": [
                    "Repository Pattern for market data",
                    "Strategy Pattern for arbitrage algorithms",
                    "Observer Pattern for real-time updates",
                    "Adapter Pattern for market integrations",
                ],
                "deployment": {
                    "type": "Microservices",
                    "orchestration": "Kubernetes",
                    "scaling": "Horizontal auto-scaling",
                    "monitoring": "Prometheus + Grafana",
                },
            }

            print(f"✅ Architecture designed with {len(architecture['layers'])} layers")
            return architecture

        except Exception as e:
            print(f"❌ Error designing architecture: {str(e)}")
            print(f"   Traceback: {traceback.format_exc()}")
            raise

    async def _design_data_flows(
        self, markets: List[str], oracles: List[str]
    ) -> List[Dict[str, Any]]:
        """
        REQ-AGENT-001b: Design data flow optimization
        @requirement: REQ-AGENT-001b - Data flow optimization [@sub_agents/design_agent.py:165-200]
        """
        try:
            data_flows = [
                {
                    "name": "Market Data Ingestion",
                    "source": markets,
                    "destination": "Aggregator",
                    "type": "Real-time streaming",
                    "format": "JSON",
                    "frequency": "Continuous",
                    "processing": "Normalization → Validation → Storage",
                },
                {
                    "name": "Arbitrage Detection",
                    "source": "Aggregator",
                    "destination": "Arbitrage Engine",
                    "type": "Event-driven",
                    "format": "Opportunity objects",
                    "frequency": "On price change",
                    "processing": "Compare → Calculate → Rank → Execute",
                },
                {
                    "name": "Oracle Price Feeds",
                    "source": oracles,
                    "destination": "Validation Engine",
                    "type": "Pull-based",
                    "format": "Price data",
                    "frequency": "Every block",
                    "processing": "Fetch → Verify → Update",
                },
                {
                    "name": "Order Execution",
                    "source": "MCP Interface",
                    "destination": markets,
                    "type": "Synchronous",
                    "format": "Order objects",
                    "frequency": "On demand",
                    "processing": "Validate → Route → Execute → Confirm",
                },
                {
                    "name": "CRE Workflow",
                    "source": "Chainlink CRE",
                    "destination": "Smart Contracts",
                    "type": "Trigger-and-callback",
                    "format": "Workflow definitions",
                    "frequency": "Scheduled/Event-based",
                    "processing": "Trigger → Execute → Callback → Update",
                },
            ]

            print(f"✅ Designed {len(data_flows)} optimized data flows")
            return data_flows

        except Exception as e:
            print(f"❌ Error designing data flows: {str(e)}")
            print(f"   Traceback: {traceback.format_exc()}")
            raise

    async def _design_security_layers(self) -> List[Dict[str, Any]]:
        """
        REQ-AGENT-001c: Design security layer integration
        @requirement: REQ-AGENT-001c - Security layers [@sub_agents/design_agent.py:205-240]
        """
        try:
            security_layers = [
                {
                    "layer": "CaMel Layer 1",
                    "name": "Public Interface",
                    "features": ["Rate limiting", "Input validation", "API authentication"],
                    "threats_mitigated": ["DDoS", "Injection attacks", "Unauthorized access"],
                },
                {
                    "layer": "CaMel Layer 2",
                    "name": "Verification",
                    "features": [
                        "Byzantine consensus",
                        "Multi-validator agreement",
                        "67% threshold",
                    ],
                    "threats_mitigated": [
                        "Single point of failure",
                        "Malicious validators",
                        "Split-brain",
                    ],
                },
                {
                    "layer": "CaMel Layer 3",
                    "name": "Processing",
                    "features": [
                        "Anti-persuasion defenses",
                        "Pattern deviation detection",
                        "Audit logging",
                    ],
                    "threats_mitigated": ["Prompt injection", "Data manipulation", "Logic bombs"],
                },
                {
                    "layer": "CaMel Layer 4",
                    "name": "Authority",
                    "features": [
                        "Final validation",
                        "Cryptographic signing",
                        "Immutable audit trail",
                    ],
                    "threats_mitigated": ["Repudiation", "Tampering", "Privilege escalation"],
                },
                {
                    "layer": "Network Security",
                    "name": "Infrastructure",
                    "features": ["TLS 1.3", "VPN tunnels", "Firewall rules", "DDoS protection"],
                    "threats_mitigated": ["MITM attacks", "Network intrusion", "Data exfiltration"],
                },
            ]

            print(f"✅ Designed {len(security_layers)} security layers")
            return security_layers

        except Exception as e:
            print(f"❌ Error designing security layers: {str(e)}")
            print(f"   Traceback: {traceback.format_exc()}")
            raise

    async def _design_integration_points(
        self, markets: List[str], oracles: List[str]
    ) -> List[Dict[str, Any]]:
        """
        Design integration points for external services
        """
        try:
            integration_points = []

            # Market integrations
            for market in markets:
                integration_points.append(
                    {
                        "service": market.title(),
                        "type": "Prediction Market",
                        "protocol": "REST API" if market == "kalshi" else "WebSocket + REST",
                        "authentication": "API Key",
                        "endpoints": ["markets", "orders", "positions", "streaming"],
                        "rate_limits": "100 req/s" if market == "kalshi" else "1000 req/s",
                    }
                )

            # Oracle integrations
            for oracle in oracles:
                integration_points.append(
                    {
                        "service": oracle.title(),
                        "type": "Oracle Network",
                        "protocol": "JSON-RPC",
                        "authentication": "Node credentials",
                        "endpoints": ["price-feeds", "vrf", "ccip", "keepers", "cre"],
                        "rate_limits": "Unlimited (self-hosted)",
                    }
                )

            # MetaMask integration
            integration_points.append(
                {
                    "service": "MetaMask",
                    "type": "Wallet",
                    "protocol": "ethereum-provider",
                    "authentication": "User approval",
                    "endpoints": ["eth_requestAccounts", "eth_sendTransaction", "personal_sign"],
                    "rate_limits": "User-initiated",
                }
            )

            print(f"✅ Designed {len(integration_points)} integration points")
            return integration_points

        except Exception as e:
            print(f"❌ Error designing integration points: {str(e)}")
            print(f"   Traceback: {traceback.format_exc()}")
            raise

    def _generate_requirements(
        self, markets: List[str], oracles: List[str], features: List[str]
    ) -> List[Dict[str, Any]]:
        """Generate detailed requirements from inputs"""
        requirements = [
            {
                "id": "REQ-FUNC-001",
                "category": "Functional",
                "description": f"Support {', '.join(markets)} prediction markets",
                "priority": "P0",
                "status": "Designed",
            },
            {
                "id": "REQ-FUNC-002",
                "category": "Functional",
                "description": f"Integrate {', '.join(oracles)} oracle networks",
                "priority": "P0",
                "status": "Designed",
            },
        ]

        for i, feature in enumerate(features, 3):
            requirements.append(
                {
                    "id": f"REQ-FUNC-{i:03d}",
                    "category": "Functional",
                    "description": f"Implement {feature} capability",
                    "priority": "P1",
                    "status": "Designed",
                }
            )

        # Add non-functional requirements
        requirements.extend(
            [
                {
                    "id": "REQ-PERF-001",
                    "category": "Performance",
                    "description": "Response time < 500ms for 95th percentile",
                    "priority": "P1",
                    "status": "Designed",
                },
                {
                    "id": "REQ-SCALE-001",
                    "category": "Scalability",
                    "description": "Handle 1000+ concurrent connections",
                    "priority": "P1",
                    "status": "Designed",
                },
                {
                    "id": "REQ-SEC-001",
                    "category": "Security",
                    "description": "Byzantine fault tolerance with 67% consensus",
                    "priority": "P0",
                    "status": "Designed",
                },
            ]
        )

        return requirements

    async def validate_design(self, design: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate the design for completeness and consistency
        """
        try:
            validation_results = {
                "valid": True,
                "checks": [],
                "warnings": [],
                "alignment_score": 0.0,
            }

            # Check architecture completeness
            if "architecture" in design and "layers" in design["architecture"]:
                validation_results["checks"].append("✓ Architecture layers defined")
            else:
                validation_results["valid"] = False
                validation_results["checks"].append("✗ Missing architecture layers")

            # Check data flows
            if "data_flows" in design and len(design["data_flows"]) > 0:
                validation_results["checks"].append(
                    f"✓ {len(design['data_flows'])} data flows defined"
                )
            else:
                validation_results["warnings"].append("⚠️ No data flows defined")

            # Check security
            if "security_layers" in design and len(design["security_layers"]) >= 4:
                validation_results["checks"].append("✓ Comprehensive security layers")
            else:
                validation_results["warnings"].append("⚠️ Insufficient security layers")

            # Calculate alignment score
            checks_passed = sum(
                1 for check in validation_results["checks"] if check.startswith("✓")
            )
            total_checks = len(validation_results["checks"])
            validation_results["alignment_score"] = (
                checks_passed / total_checks if total_checks > 0 else 0.0
            )

            # Update alignment property based on validation
            self.property_tracker.update_property(
                "alignment", validation_results["alignment_score"]
            )

            # REQ-MCP-004: Log success before return
            print(
                f"✅ Design validation complete: {'Valid' if validation_results['valid'] else 'Invalid'}"
            )
            print(f"   Alignment score: {validation_results['alignment_score']:.2%}")

            return validation_results

        except Exception as e:
            # REQ-MCP-003: Print full exception details
            print(f"❌ Error validating design: {str(e)}")
            print(f"   Exception type: {type(e).__name__}")
            print(f"   Traceback: {traceback.format_exc()}")
            raise


if __name__ == "__main__":
    import asyncio

# MASSAT Security Hardening (ASI01-ASI10) — auto-injected by security_hardening_rollout.py
try:
    from core.security_guards import validate_agent_input, check_agent_scope, log_agent_action
    from core.tool_allowlist import validate_tool_call, get_allowed_tools
    from core.agent_monitor import AgentSessionMonitor
    _SECURITY_AVAILABLE = True
except ImportError:
    _SECURITY_AVAILABLE = False


    async def test_design_agent():
        print("\n" + "=" * 60)
        print("Testing Prediction Market Design Agent")
        print("=" * 60)

        agent = PredictionMarketDesignAgent()

        # Define requirements
        requirements = {
            "markets": ["kalshi", "polymarket"],
            "oracles": ["chainlink", "uma"],
            "features": ["arbitrage", "streaming", "cre", "metamask"],
        }

        # Run design phase
        design = await agent.design_system(requirements)

        print(f"\n📋 Design Created:")
        print(f"  Project: {design['project_name']}")
        print(f"  Version: {design['version']}")
        print(f"  Architecture Layers: {len(design['architecture']['layers'])}")
        print(f"  Data Flows: {len(design['data_flows'])}")
        print(f"  Security Layers: {len(design['security_layers'])}")
        print(f"  Integration Points: {len(design['integration_points'])}")

        # Validate design
        validation = await agent.validate_design(design)
        print(f"\n✅ Validation Results:")
        for check in validation["checks"]:
            print(f"  {check}")
        for warning in validation["warnings"]:
            print(f"  {warning}")

        print("\n✅ Design Agent test complete")

    asyncio.run(test_design_agent())
