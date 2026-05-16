"""
PostgreSQL Database Configuration with SQLAlchemy Async

# REQ-DB-001: Alembic-managed migrations
# REQ-DB-002: Connection pooling with health checks
# REQ-DB-003: SQLAlchemy async ORM with type hints
# BLP-021: Durability - Persistent database connections
"""

import os
import traceback
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, AsyncGenerator, Optional

# SQLAlchemy async imports
try:
    from sqlalchemy.ext.asyncio import (
        AsyncEngine,
        AsyncSession,
        async_sessionmaker,
        create_async_engine,
    )
    from sqlalchemy.pool import NullPool, QueuePool
    from sqlalchemy import text

    SQLALCHEMY_AVAILABLE = True
except ImportError:
    SQLALCHEMY_AVAILABLE = False
    print(
        "WARNING [database_config]: SQLAlchemy not installed. Run: pip install sqlalchemy[asyncio] asyncpg"
    )


@dataclass
class DatabaseConfig:
    """
    Database configuration with connection pooling settings.

    # REQ-DB-002: Connection pooling with health checks
    """

    host: str = "localhost"
    port: int = 5432
    database: str = "chainlink_marketplace"
    user: str = "postgres"
    password: str = ""

    # Connection pool settings
    pool_size: int = 10
    max_overflow: int = 20
    pool_timeout: int = 30
    pool_recycle: int = 1800  # 30 minutes
    pool_pre_ping: bool = True  # Health check before each connection

    # SSL settings
    ssl_mode: str = "prefer"

    @classmethod
    def from_env(cls) -> "DatabaseConfig":
        """
        Load database configuration from environment variables.

        # BLP-011: Autonomy - Self-configuring from environment
        """
        try:
            config = cls(
                host=os.getenv("DB_HOST", "localhost"),
                port=int(os.getenv("DB_PORT", "5432")),
                database=os.getenv("DB_NAME", "chainlink_marketplace"),
                user=os.getenv("DB_USER", "postgres"),
                password=os.getenv("DB_PASSWORD", ""),
                pool_size=int(os.getenv("DB_POOL_SIZE", "10")),
                max_overflow=int(os.getenv("DB_MAX_OVERFLOW", "20")),
                pool_timeout=int(os.getenv("DB_POOL_TIMEOUT", "30")),
                pool_recycle=int(os.getenv("DB_POOL_RECYCLE", "1800")),
                pool_pre_ping=os.getenv("DB_POOL_PRE_PING", "true").lower() == "true",
                ssl_mode=os.getenv("DB_SSL_MODE", "prefer"),
            )
            print(
                f"SUCCESS [DatabaseConfig.from_env]: Loaded config for {config.host}:{config.port}/{config.database}"
            )
            return config
        except Exception as e:
            print(f"ERROR [DatabaseConfig.from_env]: {type(e).__name__}: {e}")
            print(f"TRACEBACK: {traceback.format_exc()}")
            raise


def get_database_url(config: Optional[DatabaseConfig] = None, async_driver: bool = True) -> str:
    """
    Build PostgreSQL connection URL.

    # REQ-DB-003: SQLAlchemy async ORM with type hints

    Args:
        config: Database configuration (defaults to env-based config)
        async_driver: If True, use asyncpg driver; if False, use psycopg2

    Returns:
        PostgreSQL connection URL string
    """
    try:
        if config is None:
            config = DatabaseConfig.from_env()

        driver = "postgresql+asyncpg" if async_driver else "postgresql+psycopg2"

        # Build URL with optional password
        if config.password:
            url = f"{driver}://{config.user}:{config.password}@{config.host}:{config.port}/{config.database}"
        else:
            url = f"{driver}://{config.user}@{config.host}:{config.port}/{config.database}"

        # Add SSL mode for asyncpg
        if async_driver and config.ssl_mode != "disable":
            url += f"?ssl={config.ssl_mode}"

        print(
            f"SUCCESS [get_database_url]: Built URL for {config.host}:{config.port}/{config.database}"
        )
        return url

    except Exception as e:
        print(f"ERROR [get_database_url]: {type(e).__name__}: {e}")
        print(f"TRACEBACK: {traceback.format_exc()}")
        raise


# Global engine instance
_engine: Optional[Any] = None


def get_async_engine(config: Optional[DatabaseConfig] = None, echo: bool = False) -> Any:
    """
    Get or create async SQLAlchemy engine with connection pooling.

    # REQ-DB-002: Connection pooling with health checks
    # BLP-021: Durability - Reusable connection pool

    Args:
        config: Database configuration
        echo: If True, log SQL statements

    Returns:
        AsyncEngine instance
    """
    global _engine

    if not SQLALCHEMY_AVAILABLE:
        print("ERROR [get_async_engine]: SQLAlchemy not available")
        return None

    try:
        if _engine is not None:
            return _engine

        if config is None:
            config = DatabaseConfig.from_env()

        database_url = get_database_url(config, async_driver=True)

        _engine = create_async_engine(
            database_url,
            echo=echo,
            # Connection pool settings
            poolclass=QueuePool,
            pool_size=config.pool_size,
            max_overflow=config.max_overflow,
            pool_timeout=config.pool_timeout,
            pool_recycle=config.pool_recycle,
            pool_pre_ping=config.pool_pre_ping,  # Health check
        )

        print(
            f"SUCCESS [get_async_engine]: Created engine with pool_size={config.pool_size}, max_overflow={config.max_overflow}"
        )
        return _engine

    except Exception as e:
        print(f"ERROR [get_async_engine]: {type(e).__name__}: {e}")
        print(f"TRACEBACK: {traceback.format_exc()}")
        raise


# Async session factory
AsyncSessionLocal: Optional[Any] = None

if SQLALCHEMY_AVAILABLE:

    def _create_session_factory() -> async_sessionmaker:
        """Create async session factory."""
        engine = get_async_engine()
        if engine is None:
            return None
        return async_sessionmaker(
            engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autocommit=False,
            autoflush=False,
        )


@asynccontextmanager
async def get_async_session() -> AsyncGenerator[Any, None]:
    """
    Async context manager for database sessions.

    # REQ-DB-003: SQLAlchemy async ORM with type hints
    # BLP-021: Durability - Proper session lifecycle management

    Usage:
        async with get_async_session() as session:
            result = await session.execute(query)
    """
    if not SQLALCHEMY_AVAILABLE:
        print("ERROR [get_async_session]: SQLAlchemy not available")
        yield None
        return

    session_factory = _create_session_factory()
    if session_factory is None:
        print("ERROR [get_async_session]: Could not create session factory")
        yield None
        return

    async with session_factory() as session:
        try:
            yield session
            await session.commit()
            print("SUCCESS [get_async_session]: Session committed")
        except Exception as e:
            await session.rollback()
            print(f"ERROR [get_async_session]: {type(e).__name__}: {e}")
            print(f"TRACEBACK: {traceback.format_exc()}")
            raise


async def check_database_health() -> dict:
    """
    Check database connectivity and pool status.

    # REQ-DB-002: Connection pooling with health checks
    # BLP-031: Self-Improvement - Health monitoring for optimization

    Returns:
        Dictionary with health status and pool metrics
    """
    if not SQLALCHEMY_AVAILABLE:
        return {
            "healthy": False,
            "error": "SQLAlchemy not available",
            "pool_size": 0,
            "checked_out": 0,
            "overflow": 0,
        }

    try:
        engine = get_async_engine()
        if engine is None:
            return {
                "healthy": False,
                "error": "Engine not initialized",
                "pool_size": 0,
                "checked_out": 0,
                "overflow": 0,
            }

        # Test connection
        async with engine.connect() as conn:
            result = await conn.execute(text("SELECT 1"))
            result.scalar()

        # Get pool status
        pool = engine.pool
        status = {
            "healthy": True,
            "pool_size": pool.size(),
            "checked_out": pool.checkedout(),
            "overflow": pool.overflow(),
            "checked_in": pool.checkedin(),
        }

        print(f"SUCCESS [check_database_health]: Database healthy, pool_size={status['pool_size']}")
        return status

    except Exception as e:
        error_msg = f"{type(e).__name__}: {e}"
        print(f"ERROR [check_database_health]: {error_msg}")
        print(f"TRACEBACK: {traceback.format_exc()}")
        return {
            "healthy": False,
            "error": error_msg,
            "pool_size": 0,
            "checked_out": 0,
            "overflow": 0,
        }


async def close_database() -> None:
    """
    Close database engine and all connections.

    # BLP-021: Durability - Clean shutdown
    """
    global _engine

    if _engine is not None:
        try:
            await _engine.dispose()
            _engine = None
            print("SUCCESS [close_database]: Database engine closed")
        except Exception as e:
            print(f"ERROR [close_database]: {type(e).__name__}: {e}")
            print(f"TRACEBACK: {traceback.format_exc()}")
            raise


if __name__ == "__main__":
    import asyncio

    async def test_database():
        """Test database configuration."""
        print("Testing PostgreSQL database configuration...")

        # Test config loading
        config = DatabaseConfig.from_env()
        print(f"Config: {config.host}:{config.port}/{config.database}")

        # Test URL generation
        url = get_database_url(config)
        print(
            f"URL generated (masked): postgresql+asyncpg://...@{config.host}:{config.port}/{config.database}"
        )

        # Test health check (will fail without actual PostgreSQL)
        health = await check_database_health()
        print(f"Health check: {health}")

        print("SUCCESS [database_config_test]: All database config tests completed")

    asyncio.run(test_database())
