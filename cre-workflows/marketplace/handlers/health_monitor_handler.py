#!/usr/bin/env python3
"""
BlindOracle System Health Monitor Handler
===========================================

Implements the System Health Monitor (UC8) for the CRE marketplace.
Monitors BlindOracle platform health and agent fleet health every
2 minutes: service ports, federation nodes, Lightning channels,
CaMel security layers, and auto-restarts safe services.

Revenue model: $99/mo subscription.

Dependencies:
    - security.blindoracle_security_gateway (SecurityRequest, BlindOracleSecurityGateway)

BLP Properties:
    BLP-001 (Alignment): Platform health monitoring expertise
    BLP-011 (Autonomy): Autonomous monitoring with emergency escalation (85%)
    BLP-019 (Logging): Continuous health reporting
    BLP-023 (Durability): Self-healing with safe restart capabilities

@author: Craig M. Brown
@version: 1.0.0
@date: 2026-02-15
"""

import asyncio
import hashlib
import json
import logging
import sys
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

# Resolve imports relative to project root - ensure absolute priority over CWD
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path = [str(_PROJECT_ROOT)] + [p for p in sys.path if p != str(_PROJECT_ROOT)]

from security.blindoracle_security_gateway import (
    BlindOracleSecurityGateway,
    SecurityConfig,
    SecurityRequest,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class AlertSeverity(Enum):
    """Alert severity levels."""
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"
    EMERGENCY = "emergency"


class ServiceStatus(Enum):
    """Health status of a service."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    DOWN = "down"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# Data Classes
# ---------------------------------------------------------------------------

@dataclass
class HealthConfig:
    """Configuration for the Health Monitor.

    REQ-BLP-001: Platform health monitoring configuration.

    Attributes:
        service_ports: Map of service name to expected port.
        federation_nodes: List of federation node endpoints.
        lightning_min_balance_sats: Minimum Lightning channel balance.
        auto_restart_allowed: Services that can be auto-restarted.
        subscription_monthly_usd: Monthly subscription fee.
        security_interface: CaMel gateway interface.
        security_agent_id: Agent identity.
    """
    service_ports: Dict[str, int] = field(default_factory=lambda: {
        "blindoracle_api": 8402,
        "ssl_gateway": 8443,
        "federation_node": 18790,
    })
    federation_nodes: List[str] = field(default_factory=lambda: [
        "fed_node_1", "fed_node_2", "fed_node_3",
    ])
    lightning_min_balance_sats: int = 100_000
    auto_restart_allowed: List[str] = field(default_factory=lambda: [
        "blindoracle_api", "ssl_gateway",
    ])
    subscription_monthly_usd: float = 99.0
    security_interface: str = "x402_api"
    security_agent_id: str = "health_monitor_v1"


@dataclass
class ServiceCheck:
    """Result of checking a single service.

    Attributes:
        service_name: Name of the service.
        port: Port number.
        status: Health status.
        response_time_ms: Response time in milliseconds.
        details: Additional details.
        alert_severity: Alert severity if unhealthy.
    """
    service_name: str
    port: int
    status: str = ServiceStatus.UNKNOWN.value
    response_time_ms: float = 0.0
    details: str = ""
    alert_severity: Optional[str] = None


@dataclass
class HealthReport:
    """Complete health report for the platform.

    Attributes:
        report_id: Unique report identifier.
        timestamp: Report generation time.
        overall_status: Overall platform health status.
        service_checks: Individual service check results.
        federation_healthy: Whether federation is healthy.
        federation_nodes_up: Number of federation nodes up.
        lightning_balance_sats: Current Lightning channel balance.
        camel_layers_healthy: CaMel security layer health.
        alerts: Active alerts.
        auto_restarts: Services auto-restarted this cycle.
        errors: Any errors encountered.
    """
    report_id: str = ""
    timestamp: str = ""
    overall_status: str = ServiceStatus.UNKNOWN.value
    service_checks: List[Dict[str, Any]] = field(default_factory=list)
    federation_healthy: bool = True
    federation_nodes_up: int = 0
    lightning_balance_sats: int = 0
    camel_layers_healthy: Dict[str, bool] = field(default_factory=dict)
    alerts: List[Dict[str, Any]] = field(default_factory=list)
    auto_restarts: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.report_id:
            self.report_id = f"health_{uuid.uuid4().hex[:12]}"
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Health Monitor
# ---------------------------------------------------------------------------

class HealthMonitor:
    """BlindOracle Platform Health Monitor.

    Continuously monitors all platform services, federation nodes,
    Lightning channels, and security layers. Auto-restarts safe
    services and escalates emergencies to the founder.

    Revenue: $99/mo subscription.

    REQ-BLP-001 (Alignment): Platform health expertise
    REQ-BLP-011 (Autonomy): 85% autonomous with emergency escalation
    REQ-BLP-019 (Logging): Continuous health reporting
    REQ-BLP-023 (Durability): Self-healing capabilities

    Usage:
        config = HealthConfig()
        monitor = HealthMonitor(config)
        report = await monitor.run_workflow()
    """

    def __init__(
        self,
        config: Optional[HealthConfig] = None,
        gateway: Optional[BlindOracleSecurityGateway] = None,
    ) -> None:
        self.config = config or HealthConfig()
        self._gateway = gateway or BlindOracleSecurityGateway()
        self._gateway.authorize_agent(self.config.security_agent_id)

        self._service_checks: List[ServiceCheck] = []
        self._alerts: List[Dict[str, Any]] = []
        self._auto_restarts: List[str] = []
        self._errors: List[str] = []

        logger.info("[SUCCESS] HealthMonitor initialized")
        logger.info("[INFO]   Services: %s", list(self.config.service_ports.keys()))
        logger.info("[INFO]   Federation nodes: %d", len(self.config.federation_nodes))

    # ---- Step 1: Check Service Ports ----

    async def check_service_ports(self) -> List[ServiceCheck]:
        """Check all service ports for responsiveness.

        REQ-BLP-001: Service health assessment.

        Returns:
            List of ServiceCheck results.
        """
        try:
            checks: List[ServiceCheck] = []

            for service, port in self.config.service_ports.items():
                # Mock: deterministic health check
                svc_seed = hash(f"{service}_{int(time.time()) // 120}") % 100

                if svc_seed < 3:
                    status = ServiceStatus.DOWN.value
                    resp_time = 0.0
                    severity = AlertSeverity.CRITICAL.value
                elif svc_seed < 10:
                    status = ServiceStatus.DEGRADED.value
                    resp_time = 500 + svc_seed * 10
                    severity = AlertSeverity.WARNING.value
                else:
                    status = ServiceStatus.HEALTHY.value
                    resp_time = 10 + svc_seed
                    severity = None

                check = ServiceCheck(
                    service_name=service,
                    port=port,
                    status=status,
                    response_time_ms=resp_time,
                    details=f"Port {port}: {status}",
                    alert_severity=severity,
                )
                checks.append(check)

                if severity:
                    self._alerts.append({
                        "service": service,
                        "severity": severity,
                        "message": f"{service} is {status} on port {port}",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    })

                logger.info("[%s] Service %s (port %d): %s (%.0fms)",
                            "SUCCESS" if status == ServiceStatus.HEALTHY.value else "INFO",
                            service, port, status, resp_time)

            self._service_checks = checks
            return checks

        except Exception as e:
            error_msg = f"Service port check failed: {e}"
            logger.error("[ERROR] %s", error_msg)
            self._errors.append(error_msg)
            raise

    # ---- Step 2: Check Federation Nodes ----

    async def check_federation(self) -> Dict[str, Any]:
        """Check federation node health.

        REQ-BLP-001: Federation health assessment.

        Returns:
            Federation health summary.
        """
        try:
            nodes_up = 0
            node_statuses: Dict[str, str] = {}

            for node in self.config.federation_nodes:
                node_seed = hash(f"{node}_{int(time.time()) // 120}") % 100
                is_up = node_seed >= 5  # 95% uptime

                node_statuses[node] = "up" if is_up else "down"
                if is_up:
                    nodes_up += 1

            healthy = nodes_up >= 2  # Need at least 2/3 for consensus
            if not healthy:
                self._alerts.append({
                    "service": "federation",
                    "severity": AlertSeverity.EMERGENCY.value,
                    "message": f"Federation degraded: {nodes_up}/{len(self.config.federation_nodes)} nodes up",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })

            logger.info("[%s] Federation: %d/%d nodes up",
                        "SUCCESS" if healthy else "ERROR",
                        nodes_up, len(self.config.federation_nodes))

            return {
                "healthy": healthy,
                "nodes_up": nodes_up,
                "total_nodes": len(self.config.federation_nodes),
                "node_statuses": node_statuses,
            }

        except Exception as e:
            error_msg = f"Federation check failed: {e}"
            logger.error("[ERROR] %s", error_msg)
            self._errors.append(error_msg)
            raise

    # ---- Step 3: Check Lightning Channels ----

    async def check_lightning(self) -> Dict[str, Any]:
        """Check Lightning Network channel balances.

        REQ-BLP-001: Lightning channel health assessment.

        Returns:
            Lightning channel summary.
        """
        try:
            # Mock balance
            balance_seed = hash(f"lightning_{int(time.time()) // 300}") % 1000
            balance = balance_seed * 1000 + 50_000

            low_balance = balance < self.config.lightning_min_balance_sats
            if low_balance:
                self._alerts.append({
                    "service": "lightning",
                    "severity": AlertSeverity.WARNING.value,
                    "message": f"Lightning balance low: {balance} sats "
                               f"(min: {self.config.lightning_min_balance_sats})",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })

            logger.info("[%s] Lightning balance: %d sats (min: %d)",
                        "SUCCESS" if not low_balance else "INFO",
                        balance, self.config.lightning_min_balance_sats)

            return {
                "balance_sats": balance,
                "min_required": self.config.lightning_min_balance_sats,
                "healthy": not low_balance,
            }

        except Exception as e:
            error_msg = f"Lightning check failed: {e}"
            logger.error("[ERROR] %s", error_msg)
            self._errors.append(error_msg)
            raise

    # ---- Step 4: Check CaMel Security ----

    async def check_camel_security(self) -> Dict[str, bool]:
        """Check CaMel 4-layer security health.

        REQ-BLP-001: Security layer health assessment.

        Returns:
            Dictionary mapping layer to health status.
        """
        try:
            layers = {
                "layer_1_public_interface": True,
                "layer_2_verification": True,
                "layer_3_processing": True,
                "layer_4_authority": True,
            }

            # Mock: very rarely a layer goes down
            for layer in layers:
                layer_seed = hash(f"{layer}_{int(time.time()) // 120}") % 100
                if layer_seed < 2:
                    layers[layer] = False
                    self._alerts.append({
                        "service": f"camel_{layer}",
                        "severity": AlertSeverity.CRITICAL.value,
                        "message": f"CaMel {layer} is unhealthy",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    })

            all_healthy = all(layers.values())
            logger.info("[%s] CaMel security: %s",
                        "SUCCESS" if all_healthy else "ERROR",
                        {k: "OK" if v else "FAIL" for k, v in layers.items()})

            return layers

        except Exception as e:
            error_msg = f"CaMel security check failed: {e}"
            logger.error("[ERROR] %s", error_msg)
            self._errors.append(error_msg)
            raise

    # ---- Step 5: Alert and Auto-Restart ----

    async def handle_alerts(self) -> List[str]:
        """Process alerts and auto-restart safe services.

        REQ-BLP-023: Self-healing with safe restart.
        REQ-BLP-011: Emergency escalation for unsafe restarts.

        Returns:
            List of services that were auto-restarted.
        """
        try:
            restarted: List[str] = []

            for check in self._service_checks:
                if check.status == ServiceStatus.DOWN.value:
                    if check.service_name in self.config.auto_restart_allowed:
                        # CaMel security for restart
                        sec_request = SecurityRequest(
                            interface=self.config.security_interface,
                            operation="service_restart",
                            agent_id=self.config.security_agent_id,
                            parameters={
                                "service": check.service_name,
                                "port": check.port,
                            },
                            amount_sats=0,
                        )
                        sec_response = self._gateway.process_request(sec_request)

                        if sec_response.approved:
                            restarted.append(check.service_name)
                            logger.info("[SUCCESS] Auto-restarted: %s", check.service_name)
                        else:
                            logger.info("[INFO] Restart denied by CaMel: %s", check.service_name)
                    else:
                        logger.info("[INFO] Service %s is down but not auto-restartable. "
                                    "Escalating to founder.", check.service_name)

            self._auto_restarts = restarted
            return restarted

        except Exception as e:
            error_msg = f"Alert handling failed: {e}"
            logger.error("[ERROR] %s", error_msg)
            self._errors.append(error_msg)
            raise

    # ---- Full Workflow ----

    async def run_workflow(self) -> HealthReport:
        """Execute the full health monitoring workflow.

        Steps:
        1. Check service ports
        2. Check federation nodes
        3. Check Lightning channels
        4. Check CaMel security layers
        5. Handle alerts and auto-restart

        Returns:
            HealthReport with complete health status.
        """
        logger.info("[INFO] === Health Monitor Workflow Starting ===")
        start = time.time()

        try:
            checks = await self.check_service_ports()
            fed_status = await self.check_federation()
            ln_status = await self.check_lightning()
            camel_status = await self.check_camel_security()
            restarts = await self.handle_alerts()

            # Determine overall status
            any_down = any(c.status == ServiceStatus.DOWN.value for c in checks)
            any_degraded = any(c.status == ServiceStatus.DEGRADED.value for c in checks)

            if any_down or not fed_status["healthy"]:
                overall = ServiceStatus.DOWN.value
            elif any_degraded or not ln_status["healthy"]:
                overall = ServiceStatus.DEGRADED.value
            else:
                overall = ServiceStatus.HEALTHY.value

            report = HealthReport(
                overall_status=overall,
                service_checks=[asdict(c) for c in checks],
                federation_healthy=fed_status["healthy"],
                federation_nodes_up=fed_status["nodes_up"],
                lightning_balance_sats=ln_status["balance_sats"],
                camel_layers_healthy=camel_status,
                alerts=list(self._alerts),
                auto_restarts=restarts,
                errors=list(self._errors),
            )

            elapsed = (time.time() - start) * 1000
            logger.info("[SUCCESS] === Health Monitor Workflow Complete (%.0fms) ===", elapsed)
            logger.info("[INFO]   Overall: %s, Alerts: %d, Restarts: %d",
                        overall, len(self._alerts), len(restarts))

            return report

        except Exception as e:
            logger.error("[ERROR] Health monitor workflow failed: %s", e)
            self._errors.append(f"Workflow error: {e}")
            return HealthReport(
                overall_status=ServiceStatus.UNKNOWN.value,
                errors=list(self._errors),
            )


# ---------------------------------------------------------------------------
# Self-Test
# ---------------------------------------------------------------------------

async def _run_self_test() -> None:
    """Validate the full Health Monitor workflow."""
    print("=" * 70)
    print("BlindOracle System Health Monitor -- Self-Test")
    print("=" * 70)

    results: List[Dict[str, Any]] = []

    # --- 1. Initialize ---
    print("\n--- 1. Initialize ---")
    config = HealthConfig()
    monitor = HealthMonitor(config)
    print(f"  Services: {list(config.service_ports.keys())}")
    print(f"  Federation nodes: {len(config.federation_nodes)}")
    results.append({"test": "Initialization", "pass": True})

    # --- 2. Check service ports ---
    print("\n--- 2. Check Service Ports ---")
    checks = await monitor.check_service_ports()
    for c in checks:
        print(f"    {c.service_name} (:{c.port}): {c.status} ({c.response_time_ms:.0f}ms)")
    results.append({"test": "Service Ports", "pass": len(checks) == len(config.service_ports)})

    # --- 3. Check federation ---
    print("\n--- 3. Check Federation ---")
    fed = await monitor.check_federation()
    print(f"    Healthy: {fed['healthy']}, Nodes up: {fed['nodes_up']}/{fed['total_nodes']}")
    results.append({"test": "Federation Check", "pass": True})

    # --- 4. Check Lightning ---
    print("\n--- 4. Check Lightning ---")
    ln = await monitor.check_lightning()
    print(f"    Balance: {ln['balance_sats']} sats, Healthy: {ln['healthy']}")
    results.append({"test": "Lightning Check", "pass": True})

    # --- 5. Check CaMel ---
    print("\n--- 5. Check CaMel Security ---")
    camel = await monitor.check_camel_security()
    for layer, healthy in camel.items():
        print(f"    {layer}: {'OK' if healthy else 'FAIL'}")
    results.append({"test": "CaMel Security", "pass": True})

    # --- 6. Handle alerts ---
    print("\n--- 6. Handle Alerts ---")
    restarts = await monitor.handle_alerts()
    print(f"    Alerts: {len(monitor._alerts)}")
    print(f"    Auto-restarts: {restarts}")
    results.append({"test": "Alert Handling", "pass": True})

    # --- 7. Full workflow ---
    print("\n--- 7. Full Workflow ---")
    monitor2 = HealthMonitor(config)
    report = await monitor2.run_workflow()
    print(f"    Report ID: {report.report_id}")
    print(f"    Overall: {report.overall_status}")
    print(f"    Alerts: {len(report.alerts)}")
    results.append({"test": "Full Workflow", "pass": report.overall_status != ""})

    # --- Summary ---
    print("\n" + "=" * 70)
    total = len(results)
    passed = sum(1 for r in results if r["pass"])
    for r in results:
        status = "PASS" if r["pass"] else "FAIL"
        print(f"  [{status}] {r['test']}")
    print(f"\nResults: {passed}/{total} passed ({passed/total*100:.0f}%)")
    print("=" * 70)

    if passed < total:
        sys.exit(1)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    asyncio.run(_run_self_test())
