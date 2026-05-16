"""
Circuit Breaker Pattern for Downstream Service Protection

# REQ-RATE-005: Circuit breaker pattern for downstream services
# REQ-TRACE-002: Spans created for external API calls
# BLP-011: Autonomy - Self-protecting against cascading failures
# BLP-021: Durability - Resilient service calls
# BLP-031: Self-Improvement - Failure metrics for optimization
"""

import asyncio
import time
import traceback
from dataclasses import dataclass, field
from enum import Enum
from functools import wraps
from typing import Any, Callable, Dict, List, Optional, TypeVar

# Import metrics if available
try:
    from .metrics_config import CIRCUIT_BREAKER_STATE, EXTERNAL_SERVICE_ERRORS

    METRICS_AVAILABLE = True
except ImportError:
    METRICS_AVAILABLE = False


# ============================================================================
# Circuit Breaker States
# ============================================================================


class CircuitState(Enum):
    """
    Circuit breaker states.

    # REQ-RATE-005: Circuit breaker pattern
    """

    CLOSED = 0  # Normal operation, requests pass through
    OPEN = 1  # Failing, requests are blocked
    HALF_OPEN = 2  # Testing, limited requests allowed


# ============================================================================
# Configuration
# ============================================================================


@dataclass
class CircuitBreakerConfig:
    """
    Circuit breaker configuration.

    # REQ-RATE-005: Circuit breaker pattern
    """

    # Failure threshold to open circuit
    failure_threshold: int = 5

    # Time window for counting failures (seconds)
    failure_window: float = 60.0

    # Time to wait before testing (seconds)
    recovery_timeout: float = 30.0

    # Number of successes needed in half-open to close
    success_threshold: int = 2

    # Maximum consecutive failures before permanent open
    max_failures: int = 100

    # Timeout for individual calls (seconds)
    call_timeout: float = 30.0

    # Exceptions to count as failures
    expected_exceptions: tuple = (Exception,)


# ============================================================================
# Circuit Breaker Implementation
# ============================================================================


@dataclass
class CircuitBreaker:
    """
    Circuit breaker for protecting downstream service calls.

    # REQ-RATE-005: Circuit breaker pattern for downstream services
    # BLP-011: Autonomy - Self-protecting against cascading failures
    # BLP-021: Durability - Resilient service calls

    Usage:
        breaker = CircuitBreaker("chainlink-oracle")

        @breaker
        async def call_chainlink_api():
            ...

        # Or manually:
        async with breaker:
            result = await external_call()
    """

    name: str
    config: CircuitBreakerConfig = field(default_factory=CircuitBreakerConfig)

    # State tracking
    _state: CircuitState = field(default=CircuitState.CLOSED, init=False)
    _failures: List[float] = field(default_factory=list, init=False)
    _successes_in_half_open: int = field(default=0, init=False)
    _last_failure_time: float = field(default=0.0, init=False)
    _opened_at: float = field(default=0.0, init=False)

    def __post_init__(self):
        """Initialize circuit breaker."""
        print(f"SUCCESS [CircuitBreaker.__init__]: Initialized circuit breaker '{self.name}'")

    @property
    def state(self) -> CircuitState:
        """
        Get current circuit state, handling state transitions.

        # REQ-RATE-005: Circuit breaker pattern
        """
        if self._state == CircuitState.OPEN:
            # Check if recovery timeout has passed
            if time.time() - self._opened_at >= self.config.recovery_timeout:
                self._transition_to(CircuitState.HALF_OPEN)

        return self._state

    @property
    def is_closed(self) -> bool:
        """Check if circuit is closed (normal operation)."""
        return self.state == CircuitState.CLOSED

    @property
    def is_open(self) -> bool:
        """Check if circuit is open (blocking requests)."""
        return self.state == CircuitState.OPEN

    @property
    def is_half_open(self) -> bool:
        """Check if circuit is half-open (testing)."""
        return self.state == CircuitState.HALF_OPEN

    def _transition_to(self, new_state: CircuitState) -> None:
        """
        Transition to a new state with logging.

        # BLP-031: Self-Improvement - State transitions logged for analysis
        """
        old_state = self._state
        self._state = new_state

        if new_state == CircuitState.OPEN:
            self._opened_at = time.time()
        elif new_state == CircuitState.HALF_OPEN:
            self._successes_in_half_open = 0
        elif new_state == CircuitState.CLOSED:
            self._failures.clear()

        # Update metrics
        if METRICS_AVAILABLE:
            CIRCUIT_BREAKER_STATE.labels(service=self.name).set(new_state.value)

        print(
            f"SUCCESS [CircuitBreaker._transition_to]: {self.name}: {old_state.name} -> {new_state.name}"
        )

    def _record_failure(self, exception: Exception) -> None:
        """
        Record a failure and potentially open the circuit.

        # REQ-RATE-005: Circuit breaker pattern
        """
        current_time = time.time()

        # Remove old failures outside the window
        self._failures = [
            t for t in self._failures if current_time - t < self.config.failure_window
        ]

        # Add new failure
        self._failures.append(current_time)
        self._last_failure_time = current_time

        # Update metrics
        if METRICS_AVAILABLE:
            EXTERNAL_SERVICE_ERRORS.labels(
                service=self.name, operation="call", error_type=type(exception).__name__
            ).inc()

        failure_count = len(self._failures)
        print(
            f"WARNING [CircuitBreaker._record_failure]: {self.name}: Failure {failure_count}/{self.config.failure_threshold}"
        )

        # Check if we should open the circuit
        if self._state == CircuitState.CLOSED:
            if failure_count >= self.config.failure_threshold:
                self._transition_to(CircuitState.OPEN)
        elif self._state == CircuitState.HALF_OPEN:
            # Any failure in half-open reopens the circuit
            self._transition_to(CircuitState.OPEN)

    def _record_success(self) -> None:
        """
        Record a success and potentially close the circuit.

        # BLP-031: Self-Improvement - Success metrics
        """
        if self._state == CircuitState.HALF_OPEN:
            self._successes_in_half_open += 1
            print(
                f"SUCCESS [CircuitBreaker._record_success]: {self.name}: Half-open success {self._successes_in_half_open}/{self.config.success_threshold}"
            )

            if self._successes_in_half_open >= self.config.success_threshold:
                self._transition_to(CircuitState.CLOSED)

    def can_execute(self) -> bool:
        """
        Check if a request can be executed.

        # REQ-RATE-005: Circuit breaker pattern
        """
        state = self.state  # This handles state transitions

        if state == CircuitState.CLOSED:
            return True
        elif state == CircuitState.OPEN:
            return False
        elif state == CircuitState.HALF_OPEN:
            return True  # Allow limited requests to test

        return False

    async def __aenter__(self):
        """Async context manager entry."""
        if not self.can_execute():
            raise CircuitBreakerOpen(
                f"Circuit breaker '{self.name}' is OPEN. "
                f"Try again after {self.config.recovery_timeout - (time.time() - self._opened_at):.1f}s"
            )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        if exc_type is None:
            self._record_success()
        elif isinstance(exc_val, self.config.expected_exceptions):
            self._record_failure(exc_val)
        return False  # Don't suppress exceptions

    def __call__(self, func: Callable) -> Callable:
        """
        Decorator for protecting async functions.

        # REQ-RATE-005: Circuit breaker pattern

        Usage:
            @circuit_breaker
            async def call_external_api():
                ...
        """

        @wraps(func)
        async def wrapper(*args, **kwargs):
            if not self.can_execute():
                raise CircuitBreakerOpen(f"Circuit breaker '{self.name}' is OPEN")

            try:
                # Apply timeout
                result = await asyncio.wait_for(
                    func(*args, **kwargs), timeout=self.config.call_timeout
                )
                self._record_success()
                return result

            except asyncio.TimeoutError as e:
                self._record_failure(e)
                print(
                    f"ERROR [CircuitBreaker.{self.name}]: Timeout after {self.config.call_timeout}s"
                )
                raise CircuitBreakerTimeout(
                    f"Call to '{self.name}' timed out after {self.config.call_timeout}s"
                ) from e

            except self.config.expected_exceptions as e:
                self._record_failure(e)
                print(f"ERROR [CircuitBreaker.{self.name}]: {type(e).__name__}: {e}")
                print(f"TRACEBACK: {traceback.format_exc()}")
                raise

        return wrapper

    def reset(self) -> None:
        """
        Manually reset the circuit breaker.

        # BLP-011: Autonomy - Manual override capability
        """
        self._failures.clear()
        self._successes_in_half_open = 0
        self._transition_to(CircuitState.CLOSED)
        print(f"SUCCESS [CircuitBreaker.reset]: {self.name} manually reset")

    def force_open(self) -> None:
        """
        Force the circuit breaker open.

        # BLP-011: Autonomy - Manual override capability
        """
        self._transition_to(CircuitState.OPEN)
        print(f"SUCCESS [CircuitBreaker.force_open]: {self.name} forced OPEN")

    def get_stats(self) -> Dict[str, Any]:
        """
        Get circuit breaker statistics.

        # BLP-031: Self-Improvement - Statistics for optimization
        """
        current_time = time.time()
        recent_failures = len(
            [t for t in self._failures if current_time - t < self.config.failure_window]
        )

        stats = {
            "name": self.name,
            "state": self.state.name,
            "state_value": self.state.value,
            "recent_failures": recent_failures,
            "failure_threshold": self.config.failure_threshold,
            "successes_in_half_open": self._successes_in_half_open,
            "success_threshold": self.config.success_threshold,
            "recovery_timeout": self.config.recovery_timeout,
            "time_since_last_failure": (
                current_time - self._last_failure_time if self._last_failure_time > 0 else None
            ),
        }

        if self._state == CircuitState.OPEN:
            stats["time_until_half_open"] = max(
                0, self.config.recovery_timeout - (current_time - self._opened_at)
            )

        return stats


# ============================================================================
# Custom Exceptions
# ============================================================================


class CircuitBreakerError(Exception):
    """Base exception for circuit breaker errors."""

    pass


class CircuitBreakerOpen(CircuitBreakerError):
    """Raised when circuit is open and blocking requests."""

    pass


class CircuitBreakerTimeout(CircuitBreakerError):
    """Raised when a call times out."""

    pass


# ============================================================================
# Circuit Breaker Registry
# ============================================================================


class CircuitBreakerRegistry:
    """
    Registry for managing multiple circuit breakers.

    # BLP-051: Self-Organization - Centralized breaker management
    """

    def __init__(self):
        self._breakers: Dict[str, CircuitBreaker] = {}

    def get_or_create(
        self, name: str, config: Optional[CircuitBreakerConfig] = None
    ) -> CircuitBreaker:
        """
        Get existing or create new circuit breaker.

        # BLP-011: Autonomy - Auto-creation of breakers
        """
        if name not in self._breakers:
            self._breakers[name] = CircuitBreaker(
                name=name, config=config or CircuitBreakerConfig()
            )
            print(f"SUCCESS [CircuitBreakerRegistry.get_or_create]: Created breaker '{name}'")

        return self._breakers[name]

    def get(self, name: str) -> Optional[CircuitBreaker]:
        """Get circuit breaker by name."""
        return self._breakers.get(name)

    def get_all_stats(self) -> Dict[str, Dict[str, Any]]:
        """
        Get stats for all circuit breakers.

        # BLP-031: Self-Improvement - Aggregated statistics
        """
        return {name: breaker.get_stats() for name, breaker in self._breakers.items()}

    def reset_all(self) -> None:
        """Reset all circuit breakers."""
        for breaker in self._breakers.values():
            breaker.reset()
        print(f"SUCCESS [CircuitBreakerRegistry.reset_all]: Reset {len(self._breakers)} breakers")


# Global registry
circuit_registry = CircuitBreakerRegistry()


def get_circuit_breaker(name: str, config: Optional[CircuitBreakerConfig] = None) -> CircuitBreaker:
    """
    Get or create a circuit breaker from the global registry.

    # REQ-RATE-005: Circuit breaker pattern

    Usage:
        chainlink_breaker = get_circuit_breaker("chainlink-oracle")

        @chainlink_breaker
        async def call_chainlink():
            ...
    """
    return circuit_registry.get_or_create(name, config)


# ============================================================================
# Pre-configured Circuit Breakers for Common Services
# ============================================================================

# Chainlink Oracle calls
chainlink_circuit = get_circuit_breaker(
    "chainlink-oracle",
    CircuitBreakerConfig(
        failure_threshold=3,
        recovery_timeout=60.0,
        call_timeout=30.0,
    ),
)

# Fedimint eCash calls
fedimint_circuit = get_circuit_breaker(
    "fedimint-ecash",
    CircuitBreakerConfig(
        failure_threshold=5,
        recovery_timeout=30.0,
        call_timeout=15.0,
    ),
)

# Database calls
database_circuit = get_circuit_breaker(
    "database",
    CircuitBreakerConfig(
        failure_threshold=10,
        recovery_timeout=10.0,
        call_timeout=5.0,
    ),
)


if __name__ == "__main__":
    import asyncio

    async def test_circuit_breaker():
        """Test circuit breaker functionality."""
        print("Testing circuit breaker...")

        # Create a test breaker with low threshold
        breaker = CircuitBreaker(
            name="test-service",
            config=CircuitBreakerConfig(
                failure_threshold=3,
                recovery_timeout=5.0,
                call_timeout=2.0,
            ),
        )

        # Test successful calls
        @breaker
        async def successful_call():
            await asyncio.sleep(0.1)
            return "success"

        result = await successful_call()
        print(f"Successful call result: {result}")
        print(f"Stats: {breaker.get_stats()}")

        # Test failing calls
        @breaker
        async def failing_call():
            raise ValueError("Simulated failure")

        # Trigger failures to open circuit
        for i in range(4):
            try:
                await failing_call()
            except (ValueError, CircuitBreakerOpen) as e:
                print(f"Call {i+1} failed: {type(e).__name__}")

        print(f"Stats after failures: {breaker.get_stats()}")

        # Test that circuit is open
        try:
            await failing_call()
        except CircuitBreakerOpen as e:
            print(f"Circuit is open: {e}")

        # Wait for recovery
        print("Waiting for recovery timeout...")
        await asyncio.sleep(6)

        # Test half-open state
        print(f"Stats after recovery: {breaker.get_stats()}")

        # Successful call should close circuit
        result = await successful_call()
        print(f"Call after recovery: {result}")
        print(f"Final stats: {breaker.get_stats()}")

        # Test registry
        print(f"Registry stats: {circuit_registry.get_all_stats()}")

        print("SUCCESS [circuit_breaker_test]: All circuit breaker tests completed")

    asyncio.run(test_circuit_breaker())
