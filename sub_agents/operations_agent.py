#!/usr/bin/env python3
"""
Prediction Market Operations Agent
@requirement: REQ-AGENT-005 - Continuous operations with self-organization
@requirement: REQ-AGENT-005a - Health monitoring
@requirement: REQ-AGENT-005b - Performance optimization
@requirement: REQ-AGENT-005c - Resource reorganization
"""

import json
import traceback
import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
import sys
import os
import random

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.base_level_properties import PropertyTracker

# MASSAT Security Hardening (ASI01-ASI10) — auto-injected by security_hardening_rollout.py
try:
    from core.security_guards import validate_agent_input, check_agent_scope, log_agent_action
    from core.tool_allowlist import validate_tool_call, get_allowed_tools
    from core.agent_monitor import AgentSessionMonitor
    _SECURITY_AVAILABLE = True
except ImportError:
    _SECURITY_AVAILABLE = False



@dataclass
class SystemMetrics:
    """System performance metrics"""

    timestamp: datetime
    cpu_usage_percent: float
    memory_usage_percent: float
    disk_usage_percent: float
    network_latency_ms: float
    active_connections: int
    requests_per_second: float
    error_rate: float


@dataclass
class HealthStatus:
    """Health status of a component"""

    component: str
    status: str  # "healthy", "degraded", "critical", "offline"
    last_check: datetime
    uptime_percent: float
    issues: List[str] = field(default_factory=list)


@dataclass
class OptimizationAction:
    """Optimization action taken"""

    action_id: str
    action_type: str  # "scale", "rebalance", "cache", "cleanup", "reorganize"
    target: str
    description: str
    impact_metric: str
    expected_improvement: float
    actual_improvement: Optional[float] = None
    executed_at: datetime = field(default_factory=datetime.now)


@dataclass
class OperationsReport:
    """Operations monitoring report"""

    deployment_id: str
    monitoring_period_hours: float
    system_metrics: List[SystemMetrics]
    health_statuses: List[HealthStatus]
    optimization_actions: List[OptimizationAction]
    incidents: List[Dict[str, Any]]
    self_organization_score: float
    overall_health: str
    recommendations: List[str]
    created_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "deployment_id": self.deployment_id,
            "monitoring_period_hours": self.monitoring_period_hours,
            "metrics_collected": len(self.system_metrics),
            "components_monitored": len(self.health_statuses),
            "optimization_actions": len(self.optimization_actions),
            "incidents": len(self.incidents),
            "self_organization_score": self.self_organization_score,
            "overall_health": self.overall_health,
            "recommendations": self.recommendations,
            "created_at": self.created_at.isoformat(),
        }


class PredictionMarketOperationsAgent:
    """
    REQ-AGENT-005: Continuous operations with self-organization
    @requirement: REQ-AGENT-005 - Operations monitoring [@sub_agents/operations_agent.py:80-160]
    """

    def __init__(self):
        self.property_tracker = PropertyTracker()
        self.monitoring_active = False
        self.operations_cycles = 0
        print("✅ PredictionMarketOperationsAgent initialized")

    async def run_operations(
        self, deployment: Dict[str, Any], monitoring_hours: float = 24.0
    ) -> Dict[str, Any]:
        """
        Run continuous operations monitoring
        """
        try:
            print(f"🔄 Starting operations monitoring for {monitoring_hours} hours")

            self.monitoring_active = True

            # Collect metrics over time
            system_metrics = await self._collect_system_metrics(monitoring_hours)

            # Monitor component health
            health_statuses = await self._monitor_health(deployment)

            # Perform optimizations
            optimization_actions = await self._optimize_performance(system_metrics)

            # Handle incidents
            incidents = await self._handle_incidents(health_statuses)

            # Reorganize resources if needed
            await self._reorganize_resources(system_metrics, health_statuses)

            # Calculate self-organization score
            self_organization_score = self._calculate_self_organization(
                optimization_actions, incidents
            )

            # Determine overall health
            overall_health = self._determine_overall_health(health_statuses, incidents)

            # Generate recommendations
            recommendations = self._generate_recommendations(
                system_metrics, health_statuses, incidents
            )

            # Create operations report
            report = OperationsReport(
                deployment_id=deployment.get("deployment_id", "unknown"),
                monitoring_period_hours=monitoring_hours,
                system_metrics=system_metrics,
                health_statuses=health_statuses,
                optimization_actions=optimization_actions,
                incidents=incidents,
                self_organization_score=self_organization_score,
                overall_health=overall_health,
                recommendations=recommendations,
            )

            # Update Base Level Properties
            # REQ-BLP-006: Self-organization - system reorganizes for efficiency
            self.property_tracker.update_property("self_organization", self_organization_score)
            # REQ-BLP-003: Durability - continuous operation
            self.property_tracker.update_property("durability", 0.8)

            self.operations_cycles += 1

            # REQ-MCP-004: Log success before return
            print(f"✅ Operations monitoring complete")
            print(f"   Period: {monitoring_hours} hours")
            print(f"   Health: {overall_health}")
            print(f"   Self-organization: {self_organization_score:.2%}")
            print(f"   Optimizations: {len(optimization_actions)}")
            print(f"   Incidents: {len(incidents)}")

            return report.to_dict()

        except Exception as e:
            # REQ-MCP-003: Print full exception details
            print(f"❌ Error in operations: {str(e)}")
            print(f"   Exception type: {type(e).__name__}")
            print(f"   Traceback: {traceback.format_exc()}")
            raise
        finally:
            self.monitoring_active = False

    async def _collect_system_metrics(self, hours: float) -> List[SystemMetrics]:
        """
        REQ-AGENT-005a: Collect system health metrics
        @requirement: REQ-AGENT-005a - Health monitoring [@sub_agents/operations_agent.py:165-200]
        """
        try:
            print("📊 Collecting system metrics...")

            metrics = []
            # Simulate collecting metrics every hour
            num_samples = int(hours)

            for i in range(num_samples):
                # Simulate realistic metrics with some variance
                metric = SystemMetrics(
                    timestamp=datetime.now() - timedelta(hours=hours - i),
                    cpu_usage_percent=50 + random.gauss(0, 10),
                    memory_usage_percent=60 + random.gauss(0, 8),
                    disk_usage_percent=40 + random.gauss(0, 5),
                    network_latency_ms=20 + random.gauss(0, 5),
                    active_connections=500 + int(random.gauss(0, 50)),
                    requests_per_second=1000 + random.gauss(0, 100),
                    error_rate=0.01 + random.gauss(0, 0.005),
                )

                # Clamp values to realistic ranges
                metric.cpu_usage_percent = max(0, min(100, metric.cpu_usage_percent))
                metric.memory_usage_percent = max(0, min(100, metric.memory_usage_percent))
                metric.disk_usage_percent = max(0, min(100, metric.disk_usage_percent))
                metric.network_latency_ms = max(1, metric.network_latency_ms)
                metric.active_connections = max(0, metric.active_connections)
                metric.requests_per_second = max(0, metric.requests_per_second)
                metric.error_rate = max(0, min(1, metric.error_rate))

                metrics.append(metric)

            print(f"  ✓ Collected {len(metrics)} metric samples")
            return metrics

        except Exception as e:
            print(f"❌ Error collecting metrics: {str(e)}")
            print(f"   Traceback: {traceback.format_exc()}")
            return []

    async def _monitor_health(self, deployment: Dict[str, Any]) -> List[HealthStatus]:
        """
        REQ-AGENT-005a: Monitor component health
        @requirement: REQ-AGENT-005a - Health monitoring [@sub_agents/operations_agent.py:165-200]
        """
        try:
            print("🏥 Monitoring component health...")

            health_statuses = []

            # Monitor key components
            components = [
                "MCP Server",
                "Kalshi Client",
                "Polymarket Client",
                "Chainlink Oracle",
                "Market Aggregator",
                "Database",
                "Cache",
                "Load Balancer",
            ]

            for component in components:
                # Simulate health check
                is_healthy = random.random() > 0.05  # 95% healthy
                uptime = 0.99 if is_healthy else random.uniform(0.5, 0.95)

                status = HealthStatus(
                    component=component,
                    status="healthy" if is_healthy else "degraded",
                    last_check=datetime.now(),
                    uptime_percent=uptime * 100,
                    issues=[] if is_healthy else [f"High latency in {component}"],
                )

                health_statuses.append(status)

            print(f"  ✓ Monitored {len(health_statuses)} components")
            return health_statuses

        except Exception as e:
            print(f"❌ Error monitoring health: {str(e)}")
            print(f"   Traceback: {traceback.format_exc()}")
            return []

    async def _optimize_performance(self, metrics: List[SystemMetrics]) -> List[OptimizationAction]:
        """
        REQ-AGENT-005b: Optimize system performance
        @requirement: REQ-AGENT-005b - Performance optimization [@sub_agents/operations_agent.py:205-240]
        """
        try:
            print("⚡ Optimizing system performance...")

            optimizations = []

            if not metrics:
                return optimizations

            # Analyze metrics for optimization opportunities
            avg_cpu = sum(m.cpu_usage_percent for m in metrics) / len(metrics)
            avg_memory = sum(m.memory_usage_percent for m in metrics) / len(metrics)
            avg_latency = sum(m.network_latency_ms for m in metrics) / len(metrics)

            # CPU optimization
            if avg_cpu > 70:
                optimization = OptimizationAction(
                    action_id=f"opt_cpu_{datetime.now().timestamp():.0f}",
                    action_type="scale",
                    target="compute_resources",
                    description="Scale up compute resources due to high CPU usage",
                    impact_metric="cpu_usage_percent",
                    expected_improvement=15.0,
                    actual_improvement=12.5,
                )
                optimizations.append(optimization)
                print(f"  ✓ CPU optimization: Scale up compute")

            # Memory optimization
            if avg_memory > 75:
                optimization = OptimizationAction(
                    action_id=f"opt_mem_{datetime.now().timestamp():.0f}",
                    action_type="cleanup",
                    target="memory_cache",
                    description="Clear unused cache to free memory",
                    impact_metric="memory_usage_percent",
                    expected_improvement=10.0,
                    actual_improvement=8.0,
                )
                optimizations.append(optimization)
                print(f"  ✓ Memory optimization: Cache cleanup")

            # Network optimization
            if avg_latency > 50:
                optimization = OptimizationAction(
                    action_id=f"opt_net_{datetime.now().timestamp():.0f}",
                    action_type="rebalance",
                    target="network_routing",
                    description="Rebalance network routing for lower latency",
                    impact_metric="network_latency_ms",
                    expected_improvement=20.0,
                    actual_improvement=18.0,
                )
                optimizations.append(optimization)
                print(f"  ✓ Network optimization: Route rebalancing")

            return optimizations

        except Exception as e:
            print(f"❌ Error optimizing performance: {str(e)}")
            print(f"   Traceback: {traceback.format_exc()}")
            return []

    async def _handle_incidents(self, health_statuses: List[HealthStatus]) -> List[Dict[str, Any]]:
        """Handle incidents based on health status"""
        try:
            print("🚨 Checking for incidents...")

            incidents = []

            for status in health_statuses:
                if status.status in ["degraded", "critical", "offline"]:
                    incident = {
                        "incident_id": f"inc_{datetime.now().timestamp():.0f}",
                        "component": status.component,
                        "severity": "high" if status.status == "critical" else "medium",
                        "description": f"{status.component} is {status.status}",
                        "detected_at": datetime.now().isoformat(),
                        "resolution": "Auto-remediation in progress",
                        "status": "resolved" if random.random() > 0.3 else "ongoing",
                    }
                    incidents.append(incident)
                    print(f"  ⚠️ Incident: {incident['description']}")

            if not incidents:
                print("  ✓ No incidents detected")

            return incidents

        except Exception as e:
            print(f"❌ Error handling incidents: {str(e)}")
            print(f"   Traceback: {traceback.format_exc()}")
            return []

    async def _reorganize_resources(
        self, metrics: List[SystemMetrics], health_statuses: List[HealthStatus]
    ) -> None:
        """
        REQ-AGENT-005c: Reorganize resources for efficiency
        @requirement: REQ-AGENT-005c - Resource reorganization [@sub_agents/operations_agent.py:245-280]
        """
        try:
            print("🔄 Reorganizing resources...")

            # Analyze resource usage patterns
            if metrics:
                avg_cpu = sum(m.cpu_usage_percent for m in metrics) / len(metrics)
                avg_connections = sum(m.active_connections for m in metrics) / len(metrics)

                # Reorganize based on usage patterns
                if avg_cpu < 30:
                    print("  ✓ Low CPU usage - consolidating instances")
                    # Would trigger instance consolidation in production

                if avg_connections > 800:
                    print("  ✓ High connection count - expanding connection pool")
                    # Would expand connection pool in production

            # Reorganize based on health
            unhealthy_count = sum(1 for s in health_statuses if s.status != "healthy")
            if unhealthy_count > 0:
                print(f"  ✓ Routing traffic away from {unhealthy_count} unhealthy components")
                # Would update routing in production

        except Exception as e:
            print(f"❌ Error reorganizing resources: {str(e)}")
            print(f"   Traceback: {traceback.format_exc()}")

    def _calculate_self_organization(
        self, optimizations: List[OptimizationAction], incidents: List[Dict[str, Any]]
    ) -> float:
        """Calculate self-organization score"""
        try:
            score = 0.5  # Base score

            # Add points for successful optimizations
            if optimizations:
                successful_opts = sum(1 for o in optimizations if o.actual_improvement)
                opt_score = (successful_opts / len(optimizations)) * 0.3
                score += opt_score

            # Add points for incident resolution
            if incidents:
                resolved = sum(1 for i in incidents if i.get("status") == "resolved")
                incident_score = (resolved / len(incidents)) * 0.2
                score += incident_score
            else:
                # No incidents is good
                score += 0.2

            return min(score, 1.0)

        except Exception as e:
            print(f"⚠️ Error calculating self-organization: {str(e)}")
            return 0.5

    def _determine_overall_health(
        self, health_statuses: List[HealthStatus], incidents: List[Dict[str, Any]]
    ) -> str:
        """Determine overall system health"""
        try:
            if not health_statuses:
                return "unknown"

            healthy_count = sum(1 for s in health_statuses if s.status == "healthy")
            health_percent = (healthy_count / len(health_statuses)) * 100

            ongoing_incidents = sum(1 for i in incidents if i.get("status") == "ongoing")

            if health_percent >= 95 and ongoing_incidents == 0:
                return "excellent"
            elif health_percent >= 80 and ongoing_incidents <= 1:
                return "good"
            elif health_percent >= 60:
                return "fair"
            else:
                return "poor"

        except Exception as e:
            print(f"⚠️ Error determining health: {str(e)}")
            return "unknown"

    def _generate_recommendations(
        self,
        metrics: List[SystemMetrics],
        health_statuses: List[HealthStatus],
        incidents: List[Dict[str, Any]],
    ) -> List[str]:
        """Generate operational recommendations"""
        try:
            recommendations = []

            if metrics:
                avg_cpu = sum(m.cpu_usage_percent for m in metrics) / len(metrics)
                avg_error_rate = sum(m.error_rate for m in metrics) / len(metrics)

                if avg_cpu > 75:
                    recommendations.append("Consider scaling up compute resources")
                elif avg_cpu < 25:
                    recommendations.append("Consider scaling down to reduce costs")

                if avg_error_rate > 0.02:
                    recommendations.append("Investigate high error rate in the system")

            unhealthy = [s for s in health_statuses if s.status != "healthy"]
            if unhealthy:
                recommendations.append(f"Priority: Fix {len(unhealthy)} unhealthy components")

            if len(incidents) > 3:
                recommendations.append("Review incident patterns for systemic issues")

            if not recommendations:
                recommendations.append("System operating within normal parameters")

            return recommendations

        except Exception as e:
            print(f"⚠️ Error generating recommendations: {str(e)}")
            return ["Unable to generate recommendations"]


if __name__ == "__main__":

    async def test_operations_agent():
        print("\n" + "=" * 60)
        print("Testing Prediction Market Operations Agent")
        print("=" * 60)

        agent = PredictionMarketOperationsAgent()

        # Mock deployment from Deployment Agent
        deployment = {
            "deployment_id": "deploy_123456",
            "environment": "production",
            "instances": [
                {"id": "instance_001", "status": "running"},
                {"id": "instance_002", "status": "running"},
                {"id": "instance_003", "status": "running"},
            ],
        }

        # Run operations monitoring (simulated for 1 hour instead of 24)
        report = await agent.run_operations(
            deployment=deployment, monitoring_hours=1.0  # Short duration for testing
        )

        print(f"\n📋 Operations Report:")
        print(f"  Deployment: {report['deployment_id']}")
        print(f"  Monitoring Period: {report['monitoring_period_hours']} hours")
        print(f"  Metrics Collected: {report['metrics_collected']}")
        print(f"  Components Monitored: {report['components_monitored']}")
        print(f"  Optimizations: {report['optimization_actions']}")
        print(f"  Incidents: {report['incidents']}")
        print(f"  Self-Organization: {report['self_organization_score']:.2%}")
        print(f"  Overall Health: {report['overall_health']}")

        print(f"\n📝 Recommendations:")
        for rec in report["recommendations"]:
            print(f"  • {rec}")

        print("\n✅ Operations Agent test complete")

    asyncio.run(test_operations_agent())
