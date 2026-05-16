#!/usr/bin/env python3
"""
Agent Coordinator for DITD+O Pipeline
Orchestrates Design, Implement, Test, Deploy, Operate agents
@requirement: REQ-COORD-001 - Agent coordination with DITD+O pipeline
@property: Self-Organization - Optimize agent assignment and workflow
@compute_advantage: ↑Autonomy ↓Time (automated multi-agent coordination)
"""

import asyncio
import json
import logging
import traceback
import time
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass, field
from enum import Enum
import uuid

logger = logging.getLogger(__name__)


class JobPhase(Enum):
    """DITD+O pipeline phases"""

    PENDING = "pending"
    DESIGN = "design"
    IMPLEMENT = "implement"
    TEST = "test"
    DEPLOY = "deploy"
    OPERATE = "operate"
    COMPLETED = "completed"
    FAILED = "failed"


class AgentType(Enum):
    """Available agent types"""

    DESIGNER = "designer"
    IMPLEMENTER = "implementer"
    TESTER = "tester"
    DEPLOYER = "deployer"
    OPERATOR = "operator"


@dataclass
class AgentInstance:
    """Individual agent instance"""

    id: str
    type: AgentType
    status: str
    current_job: Optional[str] = None
    jobs_completed: int = 0
    success_rate: float = 1.0
    last_activity: datetime = field(default_factory=datetime.now)
    performance_score: float = 1.0


@dataclass
class JobExecution:
    """Job execution context through DITD+O pipeline"""

    job_id: str
    current_phase: JobPhase
    assigned_agents: Dict[JobPhase, str] = field(default_factory=dict)
    phase_results: Dict[JobPhase, Any] = field(default_factory=dict)
    started_at: datetime = field(default_factory=datetime.now)
    phase_started_at: Optional[datetime] = None
    estimated_completion: Optional[datetime] = None
    compute_advantage_score: float = 0.0


class AgentCoordinator:
    """
    Coordinates DITD+O pipeline execution across multiple agents
    @requirement: REQ-COORD-001 - Agent orchestration pipeline [@core/agent_coordinator.py:50-200]
    @property: Self-Organization - Optimize workflow and resource allocation
    @compute_advantage: ↑Compute Scaling ↑Autonomy ↓Time (parallel processing)
    """

    def __init__(self, config: Dict[str, Any]):
        """Initialize agent coordinator"""
        self.config = config

        # Agent management
        self.agents: Dict[str, AgentInstance] = {}
        self.active_jobs: Dict[str, JobExecution] = {}
        self.completed_jobs: List[JobExecution] = []

        # Performance tracking
        self.total_jobs_processed = 0
        self.average_completion_time = 0.0
        self.success_rate = 1.0

        # Configuration
        self.max_concurrent_jobs = config.get("max_concurrent_jobs", 20)
        self.agent_scaling_enabled = config.get("agent_scaling_enabled", True)
        self.performance_optimization = config.get("performance_optimization", True)

        # Dependencies (will be injected)
        self.whatsapp_notifier = None
        self.cost_monitor = None
        self.property_tracker = None

        # Initialize agents
        asyncio.create_task(self._initialize_agents())

        # @requirement: REQ-MCP-004 - Success response logging
        logger.info(
            f"✅ Agent coordinator initialized with max {self.max_concurrent_jobs} concurrent jobs"
        )
        print(
            f"✅ Agent coordinator initialized with max {self.max_concurrent_jobs} concurrent jobs"
        )

    def set_dependencies(self, whatsapp=None, cost_monitor=None, property_tracker=None):
        """Inject system dependencies"""
        self.whatsapp_notifier = whatsapp
        self.cost_monitor = cost_monitor
        self.property_tracker = property_tracker

        # @requirement: REQ-MCP-004 - Success response logging
        logger.info("✅ Agent coordinator dependencies injected")
        print("✅ Agent coordinator dependencies injected")

    async def _initialize_agents(self):
        """Initialize default agent instances"""
        try:
            # Create one agent of each type initially
            agent_types = [
                AgentType.DESIGNER,
                AgentType.IMPLEMENTER,
                AgentType.TESTER,
                AgentType.DEPLOYER,
                AgentType.OPERATOR,
            ]

            for agent_type in agent_types:
                agent_id = f"{agent_type.value}-{uuid.uuid4().hex[:8]}"
                agent = AgentInstance(id=agent_id, type=agent_type, status="ready")
                self.agents[agent_id] = agent

                logger.info(f"✅ Initialized {agent_type.value} agent: {agent_id}")

            # @requirement: REQ-MCP-004 - Success response logging
            print(f"✅ Initialized {len(self.agents)} agents for DITD+O pipeline")

        except Exception as e:
            # @requirement: REQ-MCP-003 - Full exception details
            logger.error(f"❌ Agent initialization error: {str(e)}")
            print(f"❌ Agent initialization error: {str(e)}")
            print(f"   Full traceback: {traceback.format_exc()}")
            raise

    async def execute_job(self, job: Any) -> Dict[str, Any]:
        """
        Execute job through complete DITD+O pipeline
        @requirement: REQ-COORD-001 - Complete pipeline execution [@core/agent_coordinator.py:50-200]
        @requirement: REQ-MCP-003 - Full exception details
        @requirement: REQ-MCP-004 - Success response logging
        """
        try:
            job_id = job.id if hasattr(job, "id") else str(uuid.uuid4())

            # Check capacity
            if len(self.active_jobs) >= self.max_concurrent_jobs:
                # @requirement: REQ-COORD-002 - Dynamic scaling
                if self.agent_scaling_enabled:
                    await self._scale_agents("up")
                else:
                    raise Exception(
                        f"At capacity: {len(self.active_jobs)}/{self.max_concurrent_jobs}"
                    )

            # Create job execution context
            execution = JobExecution(
                job_id=job_id,
                current_phase=JobPhase.PENDING,
                estimated_completion=datetime.now() + timedelta(minutes=30),
            )
            self.active_jobs[job_id] = execution

            logger.info(f"🚀 Starting DITD+O pipeline for job {job_id}")

            # Execute DITD+O phases sequentially
            phases = [
                (JobPhase.DESIGN, self._execute_design_phase),
                (JobPhase.IMPLEMENT, self._execute_implement_phase),
                (JobPhase.TEST, self._execute_test_phase),
                (JobPhase.DEPLOY, self._execute_deploy_phase),
                (JobPhase.OPERATE, self._execute_operate_phase),
            ]

            for phase, executor in phases:
                try:
                    execution.current_phase = phase
                    execution.phase_started_at = datetime.now()

                    logger.info(f"🔄 Executing {phase.value} phase for job {job_id}")

                    # Execute phase
                    result = await executor(job, execution)
                    execution.phase_results[phase] = result

                    # Track performance
                    if self.cost_monitor:
                        phase_duration = (
                            datetime.now() - execution.phase_started_at
                        ).total_seconds()
                        await self.cost_monitor.track_compute(
                            cpu_hours=phase_duration / 3600,
                            memory_gb_hours=2.0 * (phase_duration / 3600),
                            job_id=job_id,
                        )

                    # Update property tracker
                    if self.property_tracker:
                        await self.property_tracker.update_autonomy_success(
                            f"{phase.value}_completion"
                        )

                    logger.info(f"✅ {phase.value} phase completed for job {job_id}")

                except Exception as phase_error:
                    # @requirement: REQ-MCP-003 - Full exception details
                    logger.error(
                        f"❌ {phase.value} phase failed for job {job_id}: {str(phase_error)}"
                    )
                    print(f"❌ {phase.value} phase failed for job {job_id}: {str(phase_error)}")
                    print(
                        f"   Job details: {job.__dict__ if hasattr(job, '__dict__') else str(job)}"
                    )
                    print(f"   Execution context: {execution.__dict__}")
                    print(f"   Full traceback: {traceback.format_exc()}")

                    execution.current_phase = JobPhase.FAILED
                    await self._handle_job_failure(job_id, phase, phase_error)
                    raise

            # Job completed successfully
            execution.current_phase = JobPhase.COMPLETED
            self.completed_jobs.append(execution)
            del self.active_jobs[job_id]

            # Calculate metrics
            total_time = (datetime.now() - execution.started_at).total_seconds()
            execution.compute_advantage_score = await self._calculate_job_compute_advantage(
                execution
            )

            # Update statistics
            self.total_jobs_processed += 1
            self._update_success_rate(True)
            self._update_average_completion_time(total_time)

            # Send success notification
            if self.whatsapp_notifier:
                await self.whatsapp_notifier.notify_critical(
                    f"✅ DITD+O Pipeline Complete\n"
                    f"Job: {job_id}\n"
                    f"Duration: {total_time:.1f}s\n"
                    f"Compute Advantage: {execution.compute_advantage_score:.2f}\n"
                    f"All phases successful"
                )

            # @requirement: REQ-MCP-004 - Success response logging
            logger.info(f"✅ DITD+O pipeline completed for job {job_id} in {total_time:.1f}s")
            print(f"✅ DITD+O pipeline completed for job {job_id} in {total_time:.1f}s")
            print(f"   Phases completed: {len(execution.phase_results)}")
            print(f"   Compute advantage: {execution.compute_advantage_score:.2f}")
            print(f"   Total jobs processed: {self.total_jobs_processed}")

            return {
                "status": "completed",
                "job_id": job_id,
                "execution_time_seconds": total_time,
                "phases_completed": list(execution.phase_results.keys()),
                "compute_advantage_score": execution.compute_advantage_score,
                "results": execution.phase_results,
            }

        except Exception as e:
            # @requirement: REQ-MCP-003 - Full exception details
            logger.error(f"❌ DITD+O pipeline error for job {job_id}: {str(e)}")
            print(f"❌ DITD+O pipeline error for job {job_id}: {str(e)}")
            print(f"   Job: {job.__dict__ if hasattr(job, '__dict__') else str(job)}")
            print(f"   Active jobs: {len(self.active_jobs)}")
            print(f"   Full traceback: {traceback.format_exc()}")

            # Clean up failed job
            if job_id in self.active_jobs:
                del self.active_jobs[job_id]

            self._update_success_rate(False)

            raise

    async def _execute_design_phase(self, job: Any, execution: JobExecution) -> Dict[str, Any]:
        """
        Execute design phase with design agent
        @requirement: REQ-DESIGN-001 - Autonomous job requirement analysis
        """
        try:
            # Find available design agent
            agent = await self._find_available_agent(AgentType.DESIGNER)
            execution.assigned_agents[JobPhase.DESIGN] = agent.id

            # Import and use design agent
            from agents.designer import DesignAgent

            design_agent = DesignAgent()

            # Analyze job requirements and create execution plan
            result = await design_agent.analyze_requirements(job)

            # Update agent performance
            agent.jobs_completed += 1
            agent.last_activity = datetime.now()

            logger.info(f"✅ Design phase completed by {agent.id}")

            return result

        except Exception as e:
            # @requirement: REQ-MCP-003 - Full exception details
            logger.error(f"❌ Design phase error: {str(e)}")
            print(f"❌ Design phase error: {str(e)}")
            print(f"   Job: {job.__dict__ if hasattr(job, '__dict__') else str(job)}")
            print(f"   Full traceback: {traceback.format_exc()}")
            raise

    async def _execute_implement_phase(self, job: Any, execution: JobExecution) -> Dict[str, Any]:
        """
        Execute implementation phase with implementer agent
        @requirement: REQ-IMPL-001 - Multi-LLM job execution with cost tracking
        """
        try:
            # Find available implementation agent
            agent = await self._find_available_agent(AgentType.IMPLEMENTER)
            execution.assigned_agents[JobPhase.IMPLEMENT] = agent.id

            # Import and use implementation agent
            from agents.implementer import ImplementationAgent

            impl_agent = ImplementationAgent()

            # Get design from previous phase
            design_result = execution.phase_results[JobPhase.DESIGN]

            # Execute the job based on design
            result = await impl_agent.execute_job(job, design_result, self.cost_monitor)

            # Update agent performance
            agent.jobs_completed += 1
            agent.last_activity = datetime.now()

            logger.info(f"✅ Implementation phase completed by {agent.id}")

            return result

        except Exception as e:
            # @requirement: REQ-MCP-003 - Full exception details
            logger.error(f"❌ Implementation phase error: {str(e)}")
            print(f"❌ Implementation phase error: {str(e)}")
            print(f"   Full traceback: {traceback.format_exc()}")
            raise

    async def _execute_test_phase(self, job: Any, execution: JobExecution) -> Dict[str, Any]:
        """
        Execute testing phase with testing agent
        @requirement: REQ-TEST-001 - Output quality validation and scoring
        """
        try:
            # Find available testing agent
            agent = await self._find_available_agent(AgentType.TESTER)
            execution.assigned_agents[JobPhase.TEST] = agent.id

            # Import and use testing agent
            from agents.tester import TestingAgent

            testing_agent = TestingAgent()

            # Get implementation result from previous phase
            impl_result = execution.phase_results[JobPhase.IMPLEMENT]

            # Validate output quality and performance
            result = await testing_agent.validate_output(impl_result, job)

            # Update agent performance
            agent.jobs_completed += 1
            agent.last_activity = datetime.now()

            logger.info(f"✅ Testing phase completed by {agent.id}")

            return result

        except Exception as e:
            # @requirement: REQ-MCP-003 - Full exception details
            logger.error(f"❌ Testing phase error: {str(e)}")
            print(f"❌ Testing phase error: {str(e)}")
            print(f"   Full traceback: {traceback.format_exc()}")
            raise

    async def _execute_deploy_phase(self, job: Any, execution: JobExecution) -> Dict[str, Any]:
        """
        Execute deployment phase with deployment agent
        @requirement: REQ-DEPLOY-001 - IPFS content upload with verification proofs
        """
        try:
            # Find available deployment agent
            agent = await self._find_available_agent(AgentType.DEPLOYER)
            execution.assigned_agents[JobPhase.DEPLOY] = agent.id

            # Import and use deployment agent
            from agents.deployer import DeploymentAgent

            deploy_agent = DeploymentAgent()

            # Get validated result from testing phase
            test_result = execution.phase_results[JobPhase.TEST]

            # Deploy to IPFS and claim payment
            result = await deploy_agent.deploy_result(test_result, job)

            # Update agent performance
            agent.jobs_completed += 1
            agent.last_activity = datetime.now()

            logger.info(f"✅ Deployment phase completed by {agent.id}")

            return result

        except Exception as e:
            # @requirement: REQ-MCP-003 - Full exception details
            logger.error(f"❌ Deployment phase error: {str(e)}")
            print(f"❌ Deployment phase error: {str(e)}")
            print(f"   Full traceback: {traceback.format_exc()}")
            raise

    async def _execute_operate_phase(self, job: Any, execution: JobExecution) -> Dict[str, Any]:
        """
        Execute operations phase with operations agent
        @requirement: REQ-OPS-001 - 24/7 system monitoring and health checks
        """
        try:
            # Find available operations agent
            agent = await self._find_available_agent(AgentType.OPERATOR)
            execution.assigned_agents[JobPhase.OPERATE] = agent.id

            # Import and use operations agent
            from agents.operator import OperationsAgent


            ops_agent = OperationsAgent()

            # Get deployment result from previous phase
            deploy_result = execution.phase_results[JobPhase.DEPLOY]

            # Monitor and finalize operation
            result = await ops_agent.monitor_completion(deploy_result, job)

            # Update agent performance
            agent.jobs_completed += 1
            agent.last_activity = datetime.now()

            logger.info(f"✅ Operations phase completed by {agent.id}")

            return result

        except Exception as e:
            # @requirement: REQ-MCP-003 - Full exception details
            logger.error(f"❌ Operations phase error: {str(e)}")
            print(f"❌ Operations phase error: {str(e)}")
            print(f"   Full traceback: {traceback.format_exc()}")
            raise

    async def _find_available_agent(self, agent_type: AgentType) -> AgentInstance:
        """
        Find available agent of specified type
        @requirement: REQ-COORD-002 - Dynamic agent scaling
        """
        try:
            # Find available agent of the requested type
            available_agents = [
                agent
                for agent in self.agents.values()
                if agent.type == agent_type and agent.status == "ready"
            ]

            if available_agents:
                # Return the best performing available agent
                best_agent = max(available_agents, key=lambda a: a.performance_score)
                best_agent.status = "busy"

                logger.info(f"✅ Assigned {agent_type.value} agent: {best_agent.id}")
                return best_agent

            # No available agents - scale up if enabled
            if self.agent_scaling_enabled:
                new_agent = await self._spawn_agent(agent_type)
                new_agent.status = "busy"

                logger.info(f"✅ Spawned and assigned new {agent_type.value} agent: {new_agent.id}")
                return new_agent

            raise Exception(f"No available {agent_type.value} agents and scaling disabled")

        except Exception as e:
            # @requirement: REQ-MCP-003 - Full exception details
            logger.error(f"❌ Agent assignment error: {str(e)}")
            print(f"❌ Agent assignment error: {str(e)}")
            print(f"   Agent type: {agent_type.value}")
            print(f"   Total agents: {len(self.agents)}")
            print(f"   Full traceback: {traceback.format_exc()}")
            raise

    async def _spawn_agent(self, agent_type: AgentType) -> AgentInstance:
        """
        Spawn new agent instance
        @requirement: REQ-COORD-002 - Dynamic scaling [@core/agent_coordinator.py:250-300]
        @property: Self-Replication - Create agent instances for scaling
        """
        try:
            agent_id = f"{agent_type.value}-{uuid.uuid4().hex[:8]}"
            agent = AgentInstance(id=agent_id, type=agent_type, status="ready")
            self.agents[agent_id] = agent

            # Update property tracker for self-replication
            if self.property_tracker:
                await self.property_tracker.update_replication_count("agent_spawned")

            logger.info(f"✅ Spawned new {agent_type.value} agent: {agent_id}")
            print(f"✅ Spawned new {agent_type.value} agent: {agent_id}")

            return agent

        except Exception as e:
            # @requirement: REQ-MCP-003 - Full exception details
            logger.error(f"❌ Agent spawning error: {str(e)}")
            print(f"❌ Agent spawning error: {str(e)}")
            print(f"   Agent type: {agent_type.value}")
            print(f"   Full traceback: {traceback.format_exc()}")
            raise

    async def _scale_agents(self, direction: str):
        """
        Scale agents up or down based on demand
        @requirement: REQ-COORD-002 - Dynamic scaling
        """
        try:
            if direction == "up":
                # Scale up - add one agent of each type
                for agent_type in AgentType:
                    await self._spawn_agent(agent_type)

                logger.info(f"✅ Scaled up: Added {len(AgentType)} agents")

            elif direction == "down":
                # Scale down - remove idle agents (keep at least one of each type)
                for agent_type in AgentType:
                    type_agents = [a for a in self.agents.values() if a.type == agent_type]
                    if len(type_agents) > 1:
                        # Remove least performing idle agent
                        idle_agents = [a for a in type_agents if a.status == "ready"]
                        if idle_agents:
                            worst_agent = min(idle_agents, key=lambda a: a.performance_score)
                            del self.agents[worst_agent.id]
                            logger.info(
                                f"✅ Removed idle {agent_type.value} agent: {worst_agent.id}"
                            )

        except Exception as e:
            # @requirement: REQ-MCP-003 - Full exception details
            logger.error(f"❌ Agent scaling error: {str(e)}")
            print(f"❌ Agent scaling error: {str(e)}")
            print(f"   Direction: {direction}")
            print(f"   Full traceback: {traceback.format_exc()}")

    async def _calculate_job_compute_advantage(self, execution: JobExecution) -> float:
        """Calculate compute advantage for completed job"""
        try:
            # Basic compute advantage calculation
            total_time = (datetime.now() - execution.started_at).total_seconds()
            phases_completed = len(execution.phase_results)

            # Compute scaling (based on phases completed)
            compute_scaling = phases_completed / 5.0  # 5 total phases

            # Autonomy (95% target autonomy)
            autonomy = 0.95

            # Time cost (lower is better)
            time_cost = total_time / 3600  # Convert to hours

            # Effort cost (minimal human intervention)
            effort_cost = 0.1  # Very low effort

            # Monetary cost (track actual costs)
            monetary_cost = 1.0  # Default $1 if not tracked
            if self.cost_monitor:
                monetary_cost = await self.cost_monitor.get_job_cost(execution.job_id)

            # Calculate advantage
            advantage = (compute_scaling * autonomy) / (time_cost + effort_cost + monetary_cost)

            return advantage

        except Exception as e:
            logger.error(f"❌ Compute advantage calculation error: {str(e)}")
            return 0.0

    def _update_success_rate(self, success: bool):
        """Update overall success rate"""
        if self.total_jobs_processed == 0:
            self.success_rate = 1.0 if success else 0.0
        else:
            # Moving average
            self.success_rate = (
                self.success_rate * self.total_jobs_processed + (1.0 if success else 0.0)
            ) / (self.total_jobs_processed + 1)

    def _update_average_completion_time(self, completion_time: float):
        """Update average job completion time"""
        if self.total_jobs_processed == 0:
            self.average_completion_time = completion_time
        else:
            # Moving average
            self.average_completion_time = (
                self.average_completion_time * self.total_jobs_processed + completion_time
            ) / (self.total_jobs_processed + 1)

    async def _handle_job_failure(self, job_id: str, failed_phase: JobPhase, error: Exception):
        """Handle job failure with notification and cleanup"""
        try:
            if self.whatsapp_notifier:
                await self.whatsapp_notifier.notify_error(
                    f"❌ DITD+O Pipeline Failed\n"
                    f"Job: {job_id}\n"
                    f"Failed Phase: {failed_phase.value}\n"
                    f"Error: {str(error)}"
                )

            # Clean up and mark agents as available
            if job_id in self.active_jobs:
                execution = self.active_jobs[job_id]
                for agent_id in execution.assigned_agents.values():
                    if agent_id in self.agents:
                        self.agents[agent_id].status = "ready"

                del self.active_jobs[job_id]

        except Exception as e:
            logger.error(f"❌ Job failure handling error: {str(e)}")

    def get_system_status(self) -> Dict[str, Any]:
        """Get current system status and metrics"""
        try:
            agent_stats = {}
            for agent_type in AgentType:
                type_agents = [a for a in self.agents.values() if a.type == agent_type]
                agent_stats[agent_type.value] = {
                    "total": len(type_agents),
                    "busy": len([a for a in type_agents if a.status == "busy"]),
                    "ready": len([a for a in type_agents if a.status == "ready"]),
                }

            status = {
                "total_agents": len(self.agents),
                "agent_breakdown": agent_stats,
                "active_jobs": len(self.active_jobs),
                "completed_jobs": len(self.completed_jobs),
                "total_jobs_processed": self.total_jobs_processed,
                "success_rate": self.success_rate,
                "average_completion_time_seconds": self.average_completion_time,
                "max_concurrent_jobs": self.max_concurrent_jobs,
                "scaling_enabled": self.agent_scaling_enabled,
            }

            logger.info(f"✅ System status retrieved: {self.total_jobs_processed} jobs processed")

            return status

        except Exception as e:
            logger.error(f"❌ System status error: {str(e)}")
            return {"error": str(e)}


async def main():
    """Test agent coordinator"""
    logging.basicConfig(level=logging.INFO)

    # Test configuration
    config = {
        "max_concurrent_jobs": 5,
        "agent_scaling_enabled": True,
        "performance_optimization": True,
    }

    # Initialize coordinator
    coordinator = AgentCoordinator(config)

    # Wait for initialization
    await asyncio.sleep(1)

    # Check system status
    status = coordinator.get_system_status()
    print(f"System Status: {json.dumps(status, indent=2)}")


if __name__ == "__main__":
    asyncio.run(main())
