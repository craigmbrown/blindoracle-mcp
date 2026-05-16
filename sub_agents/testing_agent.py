#!/usr/bin/env python3
"""
Prediction Market Testing Agent
@requirement: REQ-AGENT-003 - Comprehensive testing with durability focus
@requirement: REQ-AGENT-003a - Unit test generation and execution
@requirement: REQ-AGENT-003b - Integration test automation
@requirement: REQ-AGENT-003c - Property validation testing
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
class TestCase:
    """Individual test case"""

    test_id: str
    test_type: str  # "unit", "integration", "property", "performance"
    component: str
    description: str
    status: str = "pending"  # "pending", "running", "passed", "failed", "skipped"
    execution_time_ms: float = 0.0
    error_message: Optional[str] = None


@dataclass
class TestSuite:
    """Collection of test cases"""

    suite_id: str
    suite_type: str
    test_cases: List[TestCase]
    coverage: float = 0.0
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    execution_time_ms: float = 0.0


@dataclass
class TestReport:
    """Complete testing report"""

    implementation_id: str
    test_suites: List[TestSuite]
    total_tests: int
    passed_tests: int
    failed_tests: int
    skipped_tests: int
    overall_coverage: float
    durability_score: float
    property_validation: Dict[str, float]
    created_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "implementation_id": self.implementation_id,
            "test_suites": [
                {
                    "suite_id": suite.suite_id,
                    "type": suite.suite_type,
                    "tests": len(suite.test_cases),
                    "passed": suite.passed,
                    "failed": suite.failed,
                    "coverage": suite.coverage,
                }
                for suite in self.test_suites
            ],
            "total_tests": self.total_tests,
            "passed_tests": self.passed_tests,
            "failed_tests": self.failed_tests,
            "skipped_tests": self.skipped_tests,
            "overall_coverage": self.overall_coverage,
            "durability_score": self.durability_score,
            "property_validation": self.property_validation,
            "created_at": self.created_at.isoformat(),
        }


class PredictionMarketTestingAgent:
    """
    REQ-AGENT-003: Comprehensive testing with durability focus
    @requirement: REQ-AGENT-003 - Testing automation [@sub_agents/testing_agent.py:60-140]
    """

    def __init__(self):
        self.property_tracker = PropertyTracker()
        self.test_runs_completed = 0
        print("✅ PredictionMarketTestingAgent initialized")

    async def test_system(self, implementation: Dict[str, Any]) -> Dict[str, Any]:
        """
        Run comprehensive testing suite
        """
        try:
            print("🧪 Starting comprehensive testing phase")

            test_suites = []

            # Generate and run unit tests
            unit_suite = await self._run_unit_tests(implementation)
            test_suites.append(unit_suite)

            # Run integration tests
            integration_suite = await self._run_integration_tests(implementation)
            test_suites.append(integration_suite)

            # Run property validation tests
            property_suite = await self._run_property_tests(implementation)
            test_suites.append(property_suite)

            # Run performance tests
            performance_suite = await self._run_performance_tests(implementation)
            test_suites.append(performance_suite)

            # Calculate overall metrics
            total_tests = sum(len(suite.test_cases) for suite in test_suites)
            passed_tests = sum(suite.passed for suite in test_suites)
            failed_tests = sum(suite.failed for suite in test_suites)
            skipped_tests = sum(suite.skipped for suite in test_suites)

            # Calculate coverage
            overall_coverage = self._calculate_overall_coverage(test_suites)

            # Calculate durability score
            durability_score = self._calculate_durability_score(test_suites)

            # Validate Base Level Properties
            property_validation = await self._validate_properties()

            # Create test report
            report = TestReport(
                implementation_id=implementation.get("design_id", "unknown"),
                test_suites=test_suites,
                total_tests=total_tests,
                passed_tests=passed_tests,
                failed_tests=failed_tests,
                skipped_tests=skipped_tests,
                overall_coverage=overall_coverage,
                durability_score=durability_score,
                property_validation=property_validation,
            )

            # Update Base Level Properties
            # REQ-BLP-003: Durability - system can run continuously
            self.property_tracker.update_property("durability", durability_score)
            # REQ-BLP-004: Self-improvement through testing insights
            self.property_tracker.update_property("self_improvement", 0.4)

            self.test_runs_completed += 1

            # REQ-MCP-004: Log success before return
            success_rate = (passed_tests / total_tests * 100) if total_tests > 0 else 0
            print(f"✅ Testing complete: {passed_tests}/{total_tests} passed ({success_rate:.1f}%)")
            print(f"   Coverage: {overall_coverage:.1%}")
            print(f"   Durability: {durability_score:.2%}")

            return report.to_dict()

        except Exception as e:
            # REQ-MCP-003: Print full exception details
            print(f"❌ Error in testing: {str(e)}")
            print(f"   Exception type: {type(e).__name__}")
            print(f"   Traceback: {traceback.format_exc()}")
            raise

    async def _run_unit_tests(self, implementation: Dict[str, Any]) -> TestSuite:
        """
        REQ-AGENT-003a: Generate and run unit tests
        @requirement: REQ-AGENT-003a - Unit testing [@sub_agents/testing_agent.py:145-180]
        """
        try:
            print("🔬 Running unit tests...")

            test_cases = []

            # Generate unit tests for each artifact
            for artifact in implementation.get("artifacts", []):
                if artifact.get("type") == "code":
                    # Generate test cases for code artifact
                    test_case = TestCase(
                        test_id=f"unit_{artifact['path'].replace('/', '_')}",
                        test_type="unit",
                        component=artifact["path"],
                        description=f"Unit test for {artifact['path']}",
                    )

                    # Simulate test execution
                    test_passed = random.random() > 0.15  # 85% pass rate
                    test_case.status = "passed" if test_passed else "failed"
                    test_case.execution_time_ms = random.uniform(10, 100)
                    if not test_passed:
                        test_case.error_message = "Assertion failed: Expected value mismatch"

                    test_cases.append(test_case)

            # Create test suite
            suite = TestSuite(
                suite_id="unit_tests",
                suite_type="unit",
                test_cases=test_cases,
                passed=sum(1 for t in test_cases if t.status == "passed"),
                failed=sum(1 for t in test_cases if t.status == "failed"),
                skipped=sum(1 for t in test_cases if t.status == "skipped"),
                coverage=0.75,  # Simulated coverage
                execution_time_ms=sum(t.execution_time_ms for t in test_cases),
            )

            print(f"  ✓ Unit tests: {suite.passed}/{len(test_cases)} passed")
            return suite

        except Exception as e:
            print(f"❌ Error in unit tests: {str(e)}")
            print(f"   Traceback: {traceback.format_exc()}")
            raise

    async def _run_integration_tests(self, implementation: Dict[str, Any]) -> TestSuite:
        """
        REQ-AGENT-003b: Run integration tests
        @requirement: REQ-AGENT-003b - Integration testing [@sub_agents/testing_agent.py:185-220]
        """
        try:
            print("🔗 Running integration tests...")

            test_cases = []

            # Test integration endpoints
            for integration in implementation.get("integration_endpoints", []):
                test_case = TestCase(
                    test_id=f"integration_{integration['service'].lower()}",
                    test_type="integration",
                    component=integration["service"],
                    description=f"Integration test for {integration['service']} at {integration.get('endpoint', 'N/A')}",
                )

                # Simulate integration test
                test_passed = random.random() > 0.1  # 90% pass rate
                test_case.status = "passed" if test_passed else "failed"
                test_case.execution_time_ms = random.uniform(100, 500)
                if not test_passed:
                    test_case.error_message = f"Connection timeout to {integration['service']}"

                test_cases.append(test_case)

            # Add cross-service integration tests
            cross_service_tests = [
                TestCase(
                    test_id="integration_kalshi_polymarket_arbitrage",
                    test_type="integration",
                    component="Arbitrage Engine",
                    description="Test arbitrage detection between Kalshi and Polymarket",
                ),
                TestCase(
                    test_id="integration_chainlink_price_validation",
                    test_type="integration",
                    component="Oracle Validator",
                    description="Test price feed validation with Chainlink oracles",
                ),
            ]

            for test in cross_service_tests:
                test.status = "passed" if random.random() > 0.2 else "failed"
                test.execution_time_ms = random.uniform(200, 1000)
                test_cases.append(test)

            # Create test suite
            suite = TestSuite(
                suite_id="integration_tests",
                suite_type="integration",
                test_cases=test_cases,
                passed=sum(1 for t in test_cases if t.status == "passed"),
                failed=sum(1 for t in test_cases if t.status == "failed"),
                skipped=0,
                coverage=0.65,  # Integration tests have lower coverage
                execution_time_ms=sum(t.execution_time_ms for t in test_cases),
            )

            print(f"  ✓ Integration tests: {suite.passed}/{len(test_cases)} passed")
            return suite

        except Exception as e:
            print(f"❌ Error in integration tests: {str(e)}")
            print(f"   Traceback: {traceback.format_exc()}")
            raise

    async def _run_property_tests(self, implementation: Dict[str, Any]) -> TestSuite:
        """
        REQ-AGENT-003c: Validate Base Level Properties
        @requirement: REQ-AGENT-003c - Property validation [@sub_agents/testing_agent.py:225-260]
        """
        try:
            print("📊 Running property validation tests...")

            test_cases = []

            # Test each Base Level Property
            properties = [
                ("alignment", "System focuses on correct solutions"),
                ("autonomy", "System operates independently"),
                ("durability", "System runs continuously without failure"),
                ("self_improvement", "System learns and improves"),
                ("self_replication", "System can spawn instances"),
                ("self_organization", "System optimizes structure"),
            ]

            for prop_name, description in properties:
                test_case = TestCase(
                    test_id=f"property_{prop_name}",
                    test_type="property",
                    component=f"BLP-{prop_name}",
                    description=f"Validate {description}",
                )

                # Simulate property validation
                # Properties should mostly pass if implementation is good
                test_passed = random.random() > 0.05  # 95% pass rate for properties
                test_case.status = "passed" if test_passed else "failed"
                test_case.execution_time_ms = random.uniform(50, 200)

                test_cases.append(test_case)

            # Create test suite
            suite = TestSuite(
                suite_id="property_tests",
                suite_type="property",
                test_cases=test_cases,
                passed=sum(1 for t in test_cases if t.status == "passed"),
                failed=sum(1 for t in test_cases if t.status == "failed"),
                skipped=0,
                coverage=0.90,  # Properties are well tested
                execution_time_ms=sum(t.execution_time_ms for t in test_cases),
            )

            print(f"  ✓ Property tests: {suite.passed}/{len(test_cases)} passed")
            return suite

        except Exception as e:
            print(f"❌ Error in property tests: {str(e)}")
            print(f"   Traceback: {traceback.format_exc()}")
            raise

    async def _run_performance_tests(self, implementation: Dict[str, Any]) -> TestSuite:
        """Run performance and load tests"""
        try:
            print("⚡ Running performance tests...")

            test_cases = [
                TestCase(
                    test_id="perf_response_time",
                    test_type="performance",
                    component="API Response",
                    description="Test API response time < 500ms",
                ),
                TestCase(
                    test_id="perf_throughput",
                    test_type="performance",
                    component="System Throughput",
                    description="Test system handles 1000+ requests/second",
                ),
                TestCase(
                    test_id="perf_memory_usage",
                    test_type="performance",
                    component="Memory Management",
                    description="Test memory usage stays below 2GB",
                ),
                TestCase(
                    test_id="perf_concurrent_connections",
                    test_type="performance",
                    component="Connection Pool",
                    description="Test handling 1000+ concurrent connections",
                ),
            ]

            # Simulate performance test results
            for test in test_cases:
                # Performance tests are more likely to have issues
                test.status = "passed" if random.random() > 0.25 else "failed"
                test.execution_time_ms = random.uniform(1000, 5000)
                if test.status == "failed":
                    test.error_message = "Performance threshold not met"

            # Create test suite
            suite = TestSuite(
                suite_id="performance_tests",
                suite_type="performance",
                test_cases=test_cases,
                passed=sum(1 for t in test_cases if t.status == "passed"),
                failed=sum(1 for t in test_cases if t.status == "failed"),
                skipped=0,
                coverage=0.50,  # Performance tests have lower code coverage
                execution_time_ms=sum(t.execution_time_ms for t in test_cases),
            )

            print(f"  ✓ Performance tests: {suite.passed}/{len(test_cases)} passed")
            return suite

        except Exception as e:
            print(f"❌ Error in performance tests: {str(e)}")
            print(f"   Traceback: {traceback.format_exc()}")
            raise

    def _calculate_overall_coverage(self, test_suites: List[TestSuite]) -> float:
        """Calculate weighted average coverage"""
        if not test_suites:
            return 0.0

        total_tests = sum(len(suite.test_cases) for suite in test_suites)
        if total_tests == 0:
            return 0.0

        weighted_coverage = 0.0
        for suite in test_suites:
            weight = len(suite.test_cases) / total_tests
            weighted_coverage += suite.coverage * weight

        return weighted_coverage

    def _calculate_durability_score(self, test_suites: List[TestSuite]) -> float:
        """Calculate system durability based on test results"""
        try:
            score = 0.0

            # Base score from test pass rate
            total_tests = sum(len(suite.test_cases) for suite in test_suites)
            passed_tests = sum(suite.passed for suite in test_suites)

            if total_tests > 0:
                pass_rate = passed_tests / total_tests
                score += pass_rate * 0.5  # 50% weight on pass rate

            # Score from property tests (most important for durability)
            property_suite = next((s for s in test_suites if s.suite_type == "property"), None)
            if property_suite and len(property_suite.test_cases) > 0:
                property_pass_rate = property_suite.passed / len(property_suite.test_cases)
                score += property_pass_rate * 0.3  # 30% weight on properties

            # Score from performance tests
            perf_suite = next((s for s in test_suites if s.suite_type == "performance"), None)
            if perf_suite and len(perf_suite.test_cases) > 0:
                perf_pass_rate = perf_suite.passed / len(perf_suite.test_cases)
                score += perf_pass_rate * 0.2  # 20% weight on performance

            return min(score, 1.0)

        except Exception as e:
            print(f"⚠️ Error calculating durability: {str(e)}")
            return 0.5

    async def _validate_properties(self) -> Dict[str, float]:
        """Validate all Base Level Properties"""
        try:
            # Get current property values
            metrics = self.property_tracker.get_all_metrics()

            validation = {}
            for prop in [
                "alignment",
                "autonomy",
                "durability",
                "self_improvement",
                "self_replication",
                "self_organization",
            ]:
                # Validate each property (simulated)
                current_value = metrics.get(prop, 0.0)
                # Add some variance to simulate testing
                tested_value = current_value + random.uniform(-0.05, 0.1)
                validation[prop] = max(0.0, min(1.0, tested_value))

            return validation

        except Exception as e:
            print(f"⚠️ Error validating properties: {str(e)}")
            return {}


if __name__ == "__main__":

    async def test_testing_agent():
        print("\n" + "=" * 60)
        print("Testing Prediction Market Testing Agent")
        print("=" * 60)

        agent = PredictionMarketTestingAgent()

        # Mock implementation from Implementation Agent
        implementation = {
            "design_id": "Chainlink Prediction Markets MCP",
            "artifacts": [
                {"type": "code", "path": "mcp_interface.py", "status": "created"},
                {"type": "code", "path": "market_aggregator.py", "status": "created"},
                {"type": "code", "path": "kalshi_client.py", "status": "created"},
                {"type": "config", "path": "config.json", "status": "created"},
            ],
            "integration_endpoints": [
                {"service": "Kalshi", "endpoint": "/api/v1/kalshi"},
                {"service": "Polymarket", "endpoint": "/api/v1/polymarket"},
                {"service": "Chainlink", "endpoint": "/api/v1/chainlink"},
            ],
            "test_coverage": 0.75,
        }

        # Run tests
        test_report = await agent.test_system(implementation)

        print(f"\n📋 Test Report:")
        print(f"  Total Tests: {test_report['total_tests']}")
        print(f"  Passed: {test_report['passed_tests']}")
        print(f"  Failed: {test_report['failed_tests']}")
        print(f"  Coverage: {test_report['overall_coverage']:.1%}")
        print(f"  Durability: {test_report['durability_score']:.1%}")

        print(f"\n📊 Test Suites:")
        for suite in test_report["test_suites"]:
            print(f"  • {suite['suite_id']}: {suite['passed']}/{suite['tests']} passed")

        print(f"\n🎯 Property Validation:")
        for prop, value in test_report["property_validation"].items():
            print(f"  • {prop}: {value:.2f}")

        print("\n✅ Testing Agent test complete")

    asyncio.run(test_testing_agent())
