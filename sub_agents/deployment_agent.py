#!/usr/bin/env python3
"""
Prediction Market Deployment Agent
@requirement: REQ-AGENT-004 - Deployment with self-replication capabilities
@requirement: REQ-AGENT-004a - Multi-instance deployment
@requirement: REQ-AGENT-004b - Load balancer configuration
@requirement: REQ-AGENT-004c - Auto-scaling setup
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
class DeploymentInstance:
    """Individual deployment instance"""

    instance_id: str
    instance_type: str  # "primary", "replica", "backup"
    host: str
    port: int
    status: str = "pending"  # "pending", "deploying", "running", "failed"
    health_check_url: str = ""
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class LoadBalancerConfig:
    """Load balancer configuration"""

    lb_id: str
    algorithm: str  # "round-robin", "least-connections", "weighted"
    health_check_interval: int  # seconds
    instances: List[str]  # instance IDs
    sticky_sessions: bool = False


@dataclass
class AutoScalingConfig:
    """Auto-scaling configuration"""

    min_instances: int
    max_instances: int
    target_cpu_percent: float
    target_memory_percent: float
    scale_up_threshold: float
    scale_down_threshold: float
    cooldown_period: int  # seconds


@dataclass
class DeploymentResult:
    """Deployment operation result"""

    deployment_id: str
    environment: str  # "development", "staging", "production"
    instances: List[DeploymentInstance]
    load_balancer: LoadBalancerConfig
    auto_scaling: AutoScalingConfig
    deployment_status: str
    health_checks_passed: int
    replication_factor: int
    created_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "deployment_id": self.deployment_id,
            "environment": self.environment,
            "instances": [
                {
                    "id": inst.instance_id,
                    "type": inst.instance_type,
                    "host": inst.host,
                    "port": inst.port,
                    "status": inst.status,
                    "health_check": inst.health_check_url,
                }
                for inst in self.instances
            ],
            "load_balancer": {
                "id": self.load_balancer.lb_id,
                "algorithm": self.load_balancer.algorithm,
                "instances": self.load_balancer.instances,
            },
            "auto_scaling": {
                "min": self.auto_scaling.min_instances,
                "max": self.auto_scaling.max_instances,
                "target_cpu": self.auto_scaling.target_cpu_percent,
            },
            "deployment_status": self.deployment_status,
            "health_checks_passed": self.health_checks_passed,
            "replication_factor": self.replication_factor,
            "created_at": self.created_at.isoformat(),
        }


class PredictionMarketDeploymentAgent:
    """
    REQ-AGENT-004: Deployment with self-replication capabilities
    @requirement: REQ-AGENT-004 - Deployment automation [@sub_agents/deployment_agent.py:70-150]
    """

    def __init__(self):
        self.property_tracker = PropertyTracker()
        self.deployments_completed = 0
        print("✅ PredictionMarketDeploymentAgent initialized")

    async def deploy_system(
        self,
        implementation: Dict[str, Any],
        environment: str = "staging",
        replication_factor: int = 3,
    ) -> Dict[str, Any]:
        """
        Deploy the system with replication
        @requirement: REQ-AGENT-004a - Multi-instance deployment [@sub_agents/deployment_agent.py:155-190]
        """
        try:
            print(f"🚀 Starting deployment to {environment} environment")

            # Deploy instances
            instances = await self._deploy_instances(implementation, replication_factor)

            # Configure load balancer
            load_balancer = await self._configure_load_balancer(instances)

            # Setup auto-scaling
            auto_scaling = await self._setup_auto_scaling(environment)

            # Run health checks
            health_checks_passed = await self._run_health_checks(instances)

            # Determine deployment status
            deployment_status = "success" if health_checks_passed == len(instances) else "partial"

            # Create deployment result
            result = DeploymentResult(
                deployment_id=f"deploy_{datetime.now().timestamp():.0f}",
                environment=environment,
                instances=instances,
                load_balancer=load_balancer,
                auto_scaling=auto_scaling,
                deployment_status=deployment_status,
                health_checks_passed=health_checks_passed,
                replication_factor=replication_factor,
            )

            # Update Base Level Properties
            # REQ-BLP-005: Self-replication - creating multiple instances
            self.property_tracker.update_property("self_replication", replication_factor / 10)
            # REQ-BLP-004: Self-improvement - learning from deployment
            self.property_tracker.update_property("self_improvement", 0.3)

            self.deployments_completed += 1

            # REQ-MCP-004: Log success before return
            print(f"✅ Deployment complete: {result.deployment_id}")
            print(f"   Environment: {environment}")
            print(f"   Instances: {len(instances)} deployed")
            print(f"   Health checks: {health_checks_passed}/{len(instances)} passed")
            print(f"   Replication factor: {replication_factor}x")

            return result.to_dict()

        except Exception as e:
            # REQ-MCP-003: Print full exception details
            print(f"❌ Error in deployment: {str(e)}")
            print(f"   Exception type: {type(e).__name__}")
            print(f"   Traceback: {traceback.format_exc()}")
            raise

    async def _deploy_instances(
        self, implementation: Dict[str, Any], replication_factor: int
    ) -> List[DeploymentInstance]:
        """
        REQ-AGENT-004a: Deploy multiple instances
        @requirement: REQ-AGENT-004a - Multi-instance [@sub_agents/deployment_agent.py:155-190]
        """
        try:
            print(f"📦 Deploying {replication_factor} instances...")

            instances = []
            base_port = 8000

            for i in range(replication_factor):
                instance_type = "primary" if i == 0 else "replica"

                instance = DeploymentInstance(
                    instance_id=f"instance_{i:03d}",
                    instance_type=instance_type,
                    host=f"node{i}.prediction-markets.local",
                    port=base_port + i,
                    health_check_url=f"http://node{i}.prediction-markets.local:{base_port + i}/health",
                )

                # Simulate deployment process
                await asyncio.sleep(0.1)  # Simulate deployment time

                # 90% success rate for deployment
                instance.status = "running" if random.random() > 0.1 else "failed"

                instances.append(instance)
                print(
                    f"  ✓ Deployed {instance.instance_id} ({instance.instance_type}) - {instance.status}"
                )

            return instances

        except Exception as e:
            print(f"❌ Error deploying instances: {str(e)}")
            print(f"   Traceback: {traceback.format_exc()}")
            raise

    async def _configure_load_balancer(
        self, instances: List[DeploymentInstance]
    ) -> LoadBalancerConfig:
        """
        REQ-AGENT-004b: Configure load balancer
        @requirement: REQ-AGENT-004b - Load balancer [@sub_agents/deployment_agent.py:195-230]
        """
        try:
            print("⚖️ Configuring load balancer...")

            # Filter running instances
            running_instances = [inst for inst in instances if inst.status == "running"]

            load_balancer = LoadBalancerConfig(
                lb_id=f"lb_{datetime.now().timestamp():.0f}",
                algorithm="round-robin",
                health_check_interval=30,
                instances=[inst.instance_id for inst in running_instances],
                sticky_sessions=True,
            )

            # Simulate configuration
            await asyncio.sleep(0.1)

            print(f"  ✓ Load balancer configured with {len(running_instances)} instances")
            print(f"    Algorithm: {load_balancer.algorithm}")
            print(f"    Health check interval: {load_balancer.health_check_interval}s")

            return load_balancer

        except Exception as e:
            print(f"❌ Error configuring load balancer: {str(e)}")
            print(f"   Traceback: {traceback.format_exc()}")
            raise

    async def _setup_auto_scaling(self, environment: str) -> AutoScalingConfig:
        """
        REQ-AGENT-004c: Setup auto-scaling
        @requirement: REQ-AGENT-004c - Auto-scaling [@sub_agents/deployment_agent.py:235-270]
        """
        try:
            print("📈 Setting up auto-scaling...")

            # Environment-specific scaling configs
            configs = {
                "development": {"min": 1, "max": 3, "target_cpu": 70.0, "target_memory": 80.0},
                "staging": {"min": 2, "max": 10, "target_cpu": 60.0, "target_memory": 75.0},
                "production": {"min": 3, "max": 50, "target_cpu": 50.0, "target_memory": 70.0},
            }

            config = configs.get(environment, configs["staging"])

            auto_scaling = AutoScalingConfig(
                min_instances=config["min"],
                max_instances=config["max"],
                target_cpu_percent=config["target_cpu"],
                target_memory_percent=config["target_memory"],
                scale_up_threshold=config["target_cpu"] + 10,
                scale_down_threshold=config["target_cpu"] - 20,
                cooldown_period=300,  # 5 minutes
            )

            # Simulate configuration
            await asyncio.sleep(0.1)

            print(f"  ✓ Auto-scaling configured")
            print(f"    Instances: {auto_scaling.min_instances} - {auto_scaling.max_instances}")
            print(f"    Target CPU: {auto_scaling.target_cpu_percent}%")
            print(f"    Target Memory: {auto_scaling.target_memory_percent}%")

            return auto_scaling

        except Exception as e:
            print(f"❌ Error setting up auto-scaling: {str(e)}")
            print(f"   Traceback: {traceback.format_exc()}")
            raise

    async def _run_health_checks(self, instances: List[DeploymentInstance]) -> int:
        """Run health checks on deployed instances"""
        try:
            print("🏥 Running health checks...")

            healthy_count = 0

            for instance in instances:
                if instance.status == "running":
                    # Simulate health check
                    await asyncio.sleep(0.05)

                    # 95% of running instances are healthy
                    is_healthy = random.random() > 0.05

                    if is_healthy:
                        healthy_count += 1
                        print(f"  ✓ {instance.instance_id}: Healthy")
                    else:
                        print(f"  ✗ {instance.instance_id}: Unhealthy")
                else:
                    print(f"  ⚠️ {instance.instance_id}: Not running")

            return healthy_count

        except Exception as e:
            print(f"❌ Error running health checks: {str(e)}")
            print(f"   Traceback: {traceback.format_exc()}")
            return 0

    async def rollback_deployment(self, deployment_id: str) -> Dict[str, Any]:
        """Rollback a deployment if needed"""
        try:
            print(f"⏮️ Rolling back deployment {deployment_id}...")

            # Simulate rollback process
            await asyncio.sleep(0.5)

            result = {
                "deployment_id": deployment_id,
                "rollback_status": "success",
                "rollback_time": datetime.now().isoformat(),
                "message": "Deployment rolled back successfully",
            }

            # REQ-MCP-004: Log success before return
            print(f"✅ Rollback complete for {deployment_id}")
            return result

        except Exception as e:
            # REQ-MCP-003: Print full exception details
            print(f"❌ Error in rollback: {str(e)}")
            print(f"   Exception type: {type(e).__name__}")
            print(f"   Traceback: {traceback.format_exc()}")
            raise

    async def scale_deployment(self, deployment_id: str, target_instances: int) -> Dict[str, Any]:
        """Scale deployment up or down"""
        try:
            print(f"📊 Scaling deployment {deployment_id} to {target_instances} instances...")

            # Simulate scaling operation
            await asyncio.sleep(0.3)

            result = {
                "deployment_id": deployment_id,
                "previous_count": 3,  # Simulated
                "target_count": target_instances,
                "scaling_status": "success",
                "scaling_time": datetime.now().isoformat(),
            }

            # Update self-replication property based on scaling
            self.property_tracker.update_property("self_replication", target_instances / 10)

            # REQ-MCP-004: Log success before return
            print(f"✅ Scaled to {target_instances} instances")
            return result

        except Exception as e:
            # REQ-MCP-003: Print full exception details
            print(f"❌ Error scaling deployment: {str(e)}")
            print(f"   Exception type: {type(e).__name__}")
            print(f"   Traceback: {traceback.format_exc()}")
            raise


if __name__ == "__main__":

    async def test_deployment_agent():
        print("\n" + "=" * 60)
        print("Testing Prediction Market Deployment Agent")
        print("=" * 60)

        agent = PredictionMarketDeploymentAgent()

        # Mock implementation from previous agents
        implementation = {
            "design_id": "Chainlink Prediction Markets MCP",
            "artifacts": [
                {"type": "code", "path": "main.py"},
                {"type": "config", "path": "config.json"},
            ],
            "test_coverage": 0.85,
        }

        # Deploy to staging
        deployment = await agent.deploy_system(
            implementation=implementation, environment="staging", replication_factor=3
        )

        print(f"\n📋 Deployment Complete:")
        print(f"  Deployment ID: {deployment['deployment_id']}")
        print(f"  Environment: {deployment['environment']}")
        print(f"  Instances: {len(deployment['instances'])}")
        print(f"  Status: {deployment['deployment_status']}")
        print(
            f"  Health Checks: {deployment['health_checks_passed']}/{len(deployment['instances'])}"
        )

        print(f"\n⚖️ Load Balancer:")
        print(f"  Algorithm: {deployment['load_balancer']['algorithm']}")
        print(f"  Active Instances: {len(deployment['load_balancer']['instances'])}")

        print(f"\n📈 Auto-Scaling:")
        print(f"  Min/Max: {deployment['auto_scaling']['min']}-{deployment['auto_scaling']['max']}")
        print(f"  Target CPU: {deployment['auto_scaling']['target_cpu']}%")

        # Test scaling
        scale_result = await agent.scale_deployment(deployment["deployment_id"], 5)
        print(f"\n🔄 Scaling Result: {scale_result['scaling_status']}")

        print("\n✅ Deployment Agent test complete")

    asyncio.run(test_deployment_agent())
