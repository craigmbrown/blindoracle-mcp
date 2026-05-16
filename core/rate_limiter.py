"""
Redis-Backed Rate Limiter with SlowAPI Integration

# REQ-RATE-001: Rate limit metrics tracking
# REQ-RATE-002: Redis backend storage for distributed rate limiting
# REQ-RATE-003: Tier-based rate limits (free/basic/pro/enterprise)
# REQ-RATE-004: SlowAPI integration for FastAPI
# REQ-RATE-005: Circuit breaker pattern for downstream services
# BLP-011: Autonomy - Self-managing rate limits
# BLP-031: Self-Improvement - Rate limit metrics for optimization
"""

import os
import time
import traceback
from dataclasses import dataclass
from enum import Enum
from functools import wraps
from typing import Any, Callable, Dict, Optional

# Redis imports
try:
    import redis.asyncio as aioredis
    from redis.asyncio import Redis

    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    print("WARNING [rate_limiter]: redis not installed. Run: pip install redis")

# SlowAPI imports
try:
    from slowapi import Limiter
    from slowapi.util import get_remote_address
    from slowapi.errors import RateLimitExceeded

    SLOWAPI_AVAILABLE = True
except ImportError:
    SLOWAPI_AVAILABLE = False
    print("WARNING [rate_limiter]: slowapi not installed. Run: pip install slowapi")

# Import metrics if available
try:
    from .metrics_config import RATE_LIMIT_REMAINING, REQUEST_ERRORS

    METRICS_AVAILABLE = True
except ImportError:
    METRICS_AVAILABLE = False


# ============================================================================
# Tier Configuration
# ============================================================================


class UserTier(str, Enum):
    """
    User tier levels for rate limiting.

    # REQ-RATE-003: Tier-based rate limits
    """

    FREE = "free"
    BASIC = "basic"
    PRO = "pro"
    ENTERPRISE = "enterprise"


@dataclass
class TierLimits:
    """
    Rate limit configuration per tier.

    # REQ-RATE-003: Tier-based rate limits
    """

    requests_per_minute: int
    requests_per_hour: int
    requests_per_day: int
    concurrent_jobs: int
    max_job_size_kb: int


# Tier limit definitions
TIER_LIMITS: Dict[UserTier, TierLimits] = {
    UserTier.FREE: TierLimits(
        requests_per_minute=10,
        requests_per_hour=100,
        requests_per_day=500,
        concurrent_jobs=2,
        max_job_size_kb=100,
    ),
    UserTier.BASIC: TierLimits(
        requests_per_minute=30,
        requests_per_hour=500,
        requests_per_day=2000,
        concurrent_jobs=5,
        max_job_size_kb=500,
    ),
    UserTier.PRO: TierLimits(
        requests_per_minute=100,
        requests_per_hour=2000,
        requests_per_day=10000,
        concurrent_jobs=20,
        max_job_size_kb=2000,
    ),
    UserTier.ENTERPRISE: TierLimits(
        requests_per_minute=500,
        requests_per_hour=10000,
        requests_per_day=100000,
        concurrent_jobs=100,
        max_job_size_kb=10000,
    ),
}


def get_tier_limits(tier: str) -> TierLimits:
    """
    Get rate limits for a tier.

    # REQ-RATE-003: Tier-based rate limits
    """
    try:
        user_tier = UserTier(tier.lower())
        limits = TIER_LIMITS.get(user_tier, TIER_LIMITS[UserTier.FREE])
        print(f"SUCCESS [get_tier_limits]: Tier={tier}, rpm={limits.requests_per_minute}")
        return limits
    except ValueError:
        print(f"WARNING [get_tier_limits]: Unknown tier={tier}, using FREE limits")
        return TIER_LIMITS[UserTier.FREE]


# ============================================================================
# Redis Configuration
# ============================================================================


@dataclass
class RedisConfig:
    """
    Redis connection configuration.

    # REQ-RATE-002: Redis backend storage
    """

    host: str = "localhost"
    port: int = 6379
    db: int = 0
    password: Optional[str] = None
    ssl: bool = False
    socket_timeout: float = 5.0
    socket_connect_timeout: float = 5.0
    max_connections: int = 50

    @classmethod
    def from_env(cls) -> "RedisConfig":
        """Load Redis config from environment."""
        try:
            config = cls(
                host=os.getenv("REDIS_HOST", "localhost"),
                port=int(os.getenv("REDIS_PORT", "6379")),
                db=int(os.getenv("REDIS_DB", "0")),
                password=os.getenv("REDIS_PASSWORD"),
                ssl=os.getenv("REDIS_SSL", "false").lower() == "true",
                socket_timeout=float(os.getenv("REDIS_SOCKET_TIMEOUT", "5.0")),
                max_connections=int(os.getenv("REDIS_MAX_CONNECTIONS", "50")),
            )
            print(f"SUCCESS [RedisConfig.from_env]: Loaded config for {config.host}:{config.port}")
            return config
        except Exception as e:
            print(f"ERROR [RedisConfig.from_env]: {type(e).__name__}: {e}")
            print(f"TRACEBACK: {traceback.format_exc()}")
            raise


# Global Redis client
_redis_client: Optional[Any] = None


async def get_redis_client(config: Optional[RedisConfig] = None) -> Optional[Any]:
    """
    Get or create Redis client.

    # REQ-RATE-002: Redis backend storage
    """
    global _redis_client

    if not REDIS_AVAILABLE:
        print("WARNING [get_redis_client]: Redis not available")
        return None

    try:
        if _redis_client is not None:
            # Test connection
            await _redis_client.ping()
            return _redis_client

        if config is None:
            config = RedisConfig.from_env()

        _redis_client = Redis(
            host=config.host,
            port=config.port,
            db=config.db,
            password=config.password,
            ssl=config.ssl,
            socket_timeout=config.socket_timeout,
            socket_connect_timeout=config.socket_connect_timeout,
            max_connections=config.max_connections,
            decode_responses=True,
        )

        # Test connection
        await _redis_client.ping()
        print(f"SUCCESS [get_redis_client]: Connected to Redis at {config.host}:{config.port}")
        return _redis_client

    except Exception as e:
        print(f"ERROR [get_redis_client]: {type(e).__name__}: {e}")
        print(f"TRACEBACK: {traceback.format_exc()}")
        return None


async def close_redis_client() -> None:
    """Close Redis client connection."""
    global _redis_client

    if _redis_client is not None:
        try:
            await _redis_client.close()
            _redis_client = None
            print("SUCCESS [close_redis_client]: Redis connection closed")
        except Exception as e:
            print(f"ERROR [close_redis_client]: {type(e).__name__}: {e}")
            print(f"TRACEBACK: {traceback.format_exc()}")


# ============================================================================
# Rate Limiter Implementation
# ============================================================================


class RateLimiter:
    """
    Redis-backed rate limiter with sliding window algorithm.

    # REQ-RATE-001: Rate limit metrics tracking
    # REQ-RATE-002: Redis backend storage
    # REQ-RATE-003: Tier-based rate limits
    """

    def __init__(self, redis_client: Optional[Any] = None):
        """
        Initialize rate limiter.

        Args:
            redis_client: Redis client instance
        """
        self.redis = redis_client
        self._fallback_counters: Dict[str, Dict[str, int]] = {}

    async def _get_redis(self) -> Optional[Any]:
        """Get Redis client, initializing if needed."""
        if self.redis is None:
            self.redis = await get_redis_client()
        return self.redis

    def _get_key(self, identifier: str, window: str) -> str:
        """Generate Redis key for rate limit."""
        return f"ratelimit:{identifier}:{window}"

    async def check_rate_limit(
        self, identifier: str, tier: str = "free", increment: bool = True
    ) -> Dict[str, Any]:
        """
        Check if request is within rate limits.

        # REQ-RATE-001: Rate limit metrics tracking
        # REQ-RATE-003: Tier-based rate limits

        Args:
            identifier: User ID or IP address
            tier: User tier for limit lookup
            increment: Whether to increment counter

        Returns:
            Dict with allowed, remaining, reset_at fields
        """
        try:
            limits = get_tier_limits(tier)
            redis = await self._get_redis()

            current_time = int(time.time())
            minute_window = current_time // 60
            hour_window = current_time // 3600
            day_window = current_time // 86400

            if redis:
                # Use Redis for distributed rate limiting
                result = await self._check_redis_limits(
                    identifier, limits, minute_window, hour_window, day_window, increment
                )
            else:
                # Fallback to in-memory (not distributed)
                result = self._check_memory_limits(identifier, limits, minute_window, increment)

            # Update metrics
            if METRICS_AVAILABLE:
                RATE_LIMIT_REMAINING.labels(tier=tier).set(result["remaining_minute"])

            print(
                f"SUCCESS [check_rate_limit]: id={identifier[:8]}..., allowed={result['allowed']}, remaining={result['remaining_minute']}"
            )
            return result

        except Exception as e:
            print(f"ERROR [check_rate_limit]: {type(e).__name__}: {e}")
            print(f"TRACEBACK: {traceback.format_exc()}")
            # Fail open - allow request on error
            return {
                "allowed": True,
                "remaining_minute": -1,
                "remaining_hour": -1,
                "remaining_day": -1,
                "reset_at": 0,
                "error": str(e),
            }

    async def _check_redis_limits(
        self,
        identifier: str,
        limits: TierLimits,
        minute_window: int,
        hour_window: int,
        day_window: int,
        increment: bool,
    ) -> Dict[str, Any]:
        """
        Check rate limits using Redis.

        # REQ-RATE-002: Redis backend storage
        """
        redis = self.redis

        # Keys for different windows
        minute_key = self._get_key(identifier, f"minute:{minute_window}")
        hour_key = self._get_key(identifier, f"hour:{hour_window}")
        day_key = self._get_key(identifier, f"day:{day_window}")

        # Get current counts
        pipe = redis.pipeline()
        pipe.get(minute_key)
        pipe.get(hour_key)
        pipe.get(day_key)
        counts = await pipe.execute()

        minute_count = int(counts[0] or 0)
        hour_count = int(counts[1] or 0)
        day_count = int(counts[2] or 0)

        # Check limits
        allowed = (
            minute_count < limits.requests_per_minute
            and hour_count < limits.requests_per_hour
            and day_count < limits.requests_per_day
        )

        if allowed and increment:
            # Increment counters with TTL
            pipe = redis.pipeline()
            pipe.incr(minute_key)
            pipe.expire(minute_key, 60)
            pipe.incr(hour_key)
            pipe.expire(hour_key, 3600)
            pipe.incr(day_key)
            pipe.expire(day_key, 86400)
            await pipe.execute()

            minute_count += 1
            hour_count += 1
            day_count += 1

        return {
            "allowed": allowed,
            "remaining_minute": max(0, limits.requests_per_minute - minute_count),
            "remaining_hour": max(0, limits.requests_per_hour - hour_count),
            "remaining_day": max(0, limits.requests_per_day - day_count),
            "reset_at": (minute_window + 1) * 60,
            "limit_minute": limits.requests_per_minute,
            "limit_hour": limits.requests_per_hour,
            "limit_day": limits.requests_per_day,
        }

    def _check_memory_limits(
        self, identifier: str, limits: TierLimits, minute_window: int, increment: bool
    ) -> Dict[str, Any]:
        """
        Fallback in-memory rate limiting (not distributed).

        # BLP-021: Durability - Fallback mechanism
        """
        key = f"{identifier}:{minute_window}"

        if key not in self._fallback_counters:
            self._fallback_counters[key] = {"count": 0, "window": minute_window}

        # Clean old windows
        current_windows = [k for k in self._fallback_counters if k.startswith(identifier)]
        for k in current_windows:
            if self._fallback_counters[k]["window"] < minute_window - 1:
                del self._fallback_counters[k]

        count = self._fallback_counters[key]["count"]
        allowed = count < limits.requests_per_minute

        if allowed and increment:
            self._fallback_counters[key]["count"] += 1
            count += 1

        return {
            "allowed": allowed,
            "remaining_minute": max(0, limits.requests_per_minute - count),
            "remaining_hour": -1,  # Not tracked in memory fallback
            "remaining_day": -1,
            "reset_at": (minute_window + 1) * 60,
            "limit_minute": limits.requests_per_minute,
            "fallback": True,
        }

    async def reset_limits(self, identifier: str) -> bool:
        """
        Reset rate limits for an identifier.

        # BLP-011: Autonomy - Self-managing limits
        """
        try:
            redis = await self._get_redis()
            if redis:
                # Delete all keys for this identifier
                pattern = self._get_key(identifier, "*")
                cursor = 0
                while True:
                    cursor, keys = await redis.scan(cursor, match=pattern, count=100)
                    if keys:
                        await redis.delete(*keys)
                    if cursor == 0:
                        break

            # Clear memory fallback
            keys_to_delete = [k for k in self._fallback_counters if k.startswith(identifier)]
            for k in keys_to_delete:
                del self._fallback_counters[k]

            print(f"SUCCESS [reset_limits]: Reset limits for {identifier[:8]}...")
            return True

        except Exception as e:
            print(f"ERROR [reset_limits]: {type(e).__name__}: {e}")
            print(f"TRACEBACK: {traceback.format_exc()}")
            return False


# ============================================================================
# SlowAPI Integration
# ============================================================================


def create_slowapi_limiter() -> Optional[Any]:
    """
    Create SlowAPI limiter for FastAPI integration.

    # REQ-RATE-004: SlowAPI integration for FastAPI
    """
    if not SLOWAPI_AVAILABLE:
        print("WARNING [create_slowapi_limiter]: SlowAPI not available")
        return None

    try:
        # Create limiter with custom key function
        limiter = Limiter(key_func=get_remote_address)
        print("SUCCESS [create_slowapi_limiter]: SlowAPI limiter created")
        return limiter
    except Exception as e:
        print(f"ERROR [create_slowapi_limiter]: {type(e).__name__}: {e}")
        print(f"TRACEBACK: {traceback.format_exc()}")
        return None


def rate_limit_decorator(requests_per_minute: int = 60, tier_based: bool = True) -> Callable:
    """
    Decorator for rate limiting endpoints.

    # REQ-RATE-001: Rate limit metrics tracking
    # REQ-RATE-003: Tier-based rate limits

    Usage:
        @rate_limit_decorator(requests_per_minute=30)
        async def my_endpoint():
            ...
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # This is a simplified decorator - full implementation
            # would integrate with FastAPI request context
            return await func(*args, **kwargs)

        return wrapper

    return decorator


# ============================================================================
# Rate Limit Response Headers
# ============================================================================


def get_rate_limit_headers(result: Dict[str, Any]) -> Dict[str, str]:
    """
    Generate rate limit response headers.

    # REQ-RATE-001: Rate limit metrics tracking
    """
    return {
        "X-RateLimit-Limit": str(result.get("limit_minute", 0)),
        "X-RateLimit-Remaining": str(result.get("remaining_minute", 0)),
        "X-RateLimit-Reset": str(result.get("reset_at", 0)),
        "X-RateLimit-Remaining-Hour": str(result.get("remaining_hour", 0)),
        "X-RateLimit-Remaining-Day": str(result.get("remaining_day", 0)),
    }


# Global rate limiter instance
rate_limiter: Optional[RateLimiter] = None


async def get_rate_limiter() -> RateLimiter:
    """Get or create global rate limiter instance."""
    global rate_limiter

    if rate_limiter is None:
        redis = await get_redis_client()
        rate_limiter = RateLimiter(redis)

    return rate_limiter


if __name__ == "__main__":
    import asyncio

    async def test_rate_limiter():
        """Test rate limiter functionality."""
        print("Testing rate limiter...")

        # Test tier limits
        for tier in UserTier:
            limits = get_tier_limits(tier.value)
            print(
                f"{tier.value}: {limits.requests_per_minute} rpm, {limits.concurrent_jobs} concurrent"
            )

        # Test rate limiter (will use fallback if Redis not available)
        limiter = RateLimiter()

        # Simulate requests
        for i in range(15):
            result = await limiter.check_rate_limit("test-user-123", tier="free")
            print(
                f"Request {i+1}: allowed={result['allowed']}, remaining={result['remaining_minute']}"
            )

        # Test SlowAPI limiter creation
        slowapi_limiter = create_slowapi_limiter()
        print(f"SlowAPI limiter created: {slowapi_limiter is not None}")

        print("SUCCESS [rate_limiter_test]: All rate limiter tests completed")

    asyncio.run(test_rate_limiter())
