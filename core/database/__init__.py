"""
Database Package for Chainlink Job Marketplace

# REQ-DB-001: Alembic-managed migrations
# REQ-DB-002: Connection pooling with health checks
# REQ-DB-003: SQLAlchemy async ORM with type hints
# REQ-DB-004: JSONB columns for flexible job parameters
# REQ-DB-005: Rollback procedures documented
"""

from .config import (
    DatabaseConfig,
    get_database_url,
    get_async_engine,
    get_async_session,
    AsyncSessionLocal,
)
from .models import Base, Job, User, Payment, JobResult
from .repository import JobRepository, UserRepository, PaymentRepository

__all__ = [
    # Config
    "DatabaseConfig",
    "get_database_url",
    "get_async_engine",
    "get_async_session",
    "AsyncSessionLocal",
    # Models
    "Base",
    "Job",
    "User",
    "Payment",
    "JobResult",
    # Repositories
    "JobRepository",
    "UserRepository",
    "PaymentRepository",
]
