"""
SQLAlchemy ORM Models for Chainlink Job Marketplace

# REQ-DB-003: SQLAlchemy async ORM with type hints
# REQ-DB-004: JSONB columns for flexible job parameters
# BLP-021: Durability - Persistent data models
"""

import traceback
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import uuid4

try:
    from sqlalchemy import (
        Boolean,
        DateTime,
        Enum as SQLEnum,
        Float,
        ForeignKey,
        Index,
        Integer,
        String,
        Text,
        func,
    )
    from sqlalchemy.dialects.postgresql import JSONB, UUID
    from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

    SQLALCHEMY_AVAILABLE = True
except ImportError:
    SQLALCHEMY_AVAILABLE = False
    print("WARNING [models]: SQLAlchemy not installed")


# ============================================================================
# Enums
# ============================================================================


class JobStatus(str, Enum):
    """Job lifecycle status."""

    PENDING = "pending"
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobType(str, Enum):
    """Types of Chainlink jobs."""

    ORACLE_FEED = "oracle_feed"
    VRF_RANDOM = "vrf_random"
    AUTOMATION = "automation"
    CCIP_TRANSFER = "ccip_transfer"
    FUNCTIONS = "functions"
    CUSTOM = "custom"


class PaymentStatus(str, Enum):
    """Payment lifecycle status."""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    REFUNDED = "refunded"


class PaymentMethod(str, Enum):
    """Supported payment methods."""

    ECASH = "ecash"  # Fedimint eCash
    LIGHTNING = "lightning"
    ONCHAIN = "onchain"
    LINK = "link"  # LINK token


# ============================================================================
# Base Model
# ============================================================================

if SQLALCHEMY_AVAILABLE:

    class Base(DeclarativeBase):
        """
        Base class for all SQLAlchemy models.

        # REQ-DB-003: SQLAlchemy async ORM with type hints
        """

        pass

    # ============================================================================
    # User Model
    # ============================================================================

    class User(Base):
        """
        User model for the marketplace.

        # REQ-DB-003: SQLAlchemy async ORM with type hints
        # BLP-001: Alignment - User identity management
        """

        __tablename__ = "users"

        id: Mapped[str] = mapped_column(
            UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
        )
        email: Mapped[Optional[str]] = mapped_column(String(255), unique=True, nullable=True)
        wallet_address: Mapped[Optional[str]] = mapped_column(
            String(42), unique=True, nullable=True
        )
        fedimint_pubkey: Mapped[Optional[str]] = mapped_column(
            String(66), unique=True, nullable=True
        )

        # Tier for rate limiting
        tier: Mapped[str] = mapped_column(String(20), default="free")

        # Metadata
        created_at: Mapped[datetime] = mapped_column(
            DateTime(timezone=True), server_default=func.now()
        )
        updated_at: Mapped[datetime] = mapped_column(
            DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
        )
        is_active: Mapped[bool] = mapped_column(Boolean, default=True)

        # JSONB for flexible settings
        # REQ-DB-004: JSONB columns for flexible job parameters
        settings: Mapped[Dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

        # Relationships
        jobs: Mapped[List["Job"]] = relationship("Job", back_populates="user")
        payments: Mapped[List["Payment"]] = relationship("Payment", back_populates="user")

        # Indexes
        __table_args__ = (
            Index("ix_users_email", "email"),
            Index("ix_users_wallet", "wallet_address"),
            Index("ix_users_tier", "tier"),
        )

        def __repr__(self) -> str:
            return f"<User(id={self.id}, email={self.email}, tier={self.tier})>"

    # ============================================================================
    # Job Model
    # ============================================================================

    class Job(Base):
        """
        Chainlink job model.

        # REQ-DB-003: SQLAlchemy async ORM with type hints
        # REQ-DB-004: JSONB columns for flexible job parameters
        # BLP-011: Autonomy - Self-managed job lifecycle
        """

        __tablename__ = "jobs"

        id: Mapped[str] = mapped_column(
            UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
        )
        user_id: Mapped[str] = mapped_column(
            UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        )

        # Job type and status
        job_type: Mapped[str] = mapped_column(
            SQLEnum(JobType, name="job_type_enum"), nullable=False
        )
        status: Mapped[str] = mapped_column(
            SQLEnum(JobStatus, name="job_status_enum"), default=JobStatus.PENDING.value
        )

        # Job details
        name: Mapped[str] = mapped_column(String(255), nullable=False)
        description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

        # JSONB for flexible parameters
        # REQ-DB-004: JSONB columns for flexible job parameters
        parameters: Mapped[Dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

        # Chainlink-specific
        oracle_address: Mapped[Optional[str]] = mapped_column(String(42), nullable=True)
        job_spec_id: Mapped[Optional[str]] = mapped_column(String(66), nullable=True)
        chain_id: Mapped[int] = mapped_column(Integer, default=1)  # Ethereum mainnet

        # Pricing
        price_sats: Mapped[int] = mapped_column(Integer, default=0)
        fee_sats: Mapped[int] = mapped_column(Integer, default=0)

        # Timestamps
        created_at: Mapped[datetime] = mapped_column(
            DateTime(timezone=True), server_default=func.now()
        )
        updated_at: Mapped[datetime] = mapped_column(
            DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
        )
        started_at: Mapped[Optional[datetime]] = mapped_column(
            DateTime(timezone=True), nullable=True
        )
        completed_at: Mapped[Optional[datetime]] = mapped_column(
            DateTime(timezone=True), nullable=True
        )

        # Error handling
        error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
        retry_count: Mapped[int] = mapped_column(Integer, default=0)
        max_retries: Mapped[int] = mapped_column(Integer, default=3)

        # Relationships
        user: Mapped["User"] = relationship("User", back_populates="jobs")
        results: Mapped[List["JobResult"]] = relationship("JobResult", back_populates="job")
        payment: Mapped[Optional["Payment"]] = relationship(
            "Payment", back_populates="job", uselist=False
        )

        # Indexes for common queries
        __table_args__ = (
            Index("ix_jobs_user_id", "user_id"),
            Index("ix_jobs_status", "status"),
            Index("ix_jobs_type", "job_type"),
            Index("ix_jobs_created_at", "created_at"),
            Index("ix_jobs_user_status", "user_id", "status"),
        )

        def __repr__(self) -> str:
            return f"<Job(id={self.id}, type={self.job_type}, status={self.status})>"

    # ============================================================================
    # JobResult Model
    # ============================================================================

    class JobResult(Base):
        """
        Job execution result model.

        # REQ-DB-003: SQLAlchemy async ORM with type hints
        # REQ-DB-004: JSONB columns for flexible job parameters
        """

        __tablename__ = "job_results"

        id: Mapped[str] = mapped_column(
            UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
        )
        job_id: Mapped[str] = mapped_column(
            UUID(as_uuid=False), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
        )

        # Result data (JSONB for flexibility)
        # REQ-DB-004: JSONB columns for flexible job parameters
        data: Mapped[Dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

        # Chainlink response data
        tx_hash: Mapped[Optional[str]] = mapped_column(String(66), nullable=True)
        block_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
        gas_used: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

        # Timing
        execution_time_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
        created_at: Mapped[datetime] = mapped_column(
            DateTime(timezone=True), server_default=func.now()
        )

        # Relationships
        job: Mapped["Job"] = relationship("Job", back_populates="results")

        # Indexes
        __table_args__ = (
            Index("ix_job_results_job_id", "job_id"),
            Index("ix_job_results_tx_hash", "tx_hash"),
        )

        def __repr__(self) -> str:
            return f"<JobResult(id={self.id}, job_id={self.job_id})>"

    # ============================================================================
    # Payment Model
    # ============================================================================

    class Payment(Base):
        """
        Payment model for Fedimint eCash and other methods.

        # REQ-DB-003: SQLAlchemy async ORM with type hints
        # REQ-DB-004: JSONB columns for flexible job parameters
        # BLP-021: Durability - Payment audit trail
        """

        __tablename__ = "payments"

        id: Mapped[str] = mapped_column(
            UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
        )
        user_id: Mapped[str] = mapped_column(
            UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        )
        job_id: Mapped[Optional[str]] = mapped_column(
            UUID(as_uuid=False), ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True
        )

        # Payment details
        method: Mapped[str] = mapped_column(
            SQLEnum(PaymentMethod, name="payment_method_enum"), nullable=False
        )
        status: Mapped[str] = mapped_column(
            SQLEnum(PaymentStatus, name="payment_status_enum"), default=PaymentStatus.PENDING.value
        )

        # Amounts (in satoshis for precision)
        amount_sats: Mapped[int] = mapped_column(Integer, nullable=False)
        fee_sats: Mapped[int] = mapped_column(Integer, default=0)

        # Fedimint eCash specific
        ecash_token: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
        federation_id: Mapped[Optional[str]] = mapped_column(String(66), nullable=True)

        # Lightning specific
        lightning_invoice: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
        payment_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
        preimage: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

        # JSONB for additional metadata
        # REQ-DB-004: JSONB columns for flexible job parameters
        metadata: Mapped[Dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

        # Timestamps
        created_at: Mapped[datetime] = mapped_column(
            DateTime(timezone=True), server_default=func.now()
        )
        updated_at: Mapped[datetime] = mapped_column(
            DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
        )
        completed_at: Mapped[Optional[datetime]] = mapped_column(
            DateTime(timezone=True), nullable=True
        )

        # Error handling
        error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

        # Relationships
        user: Mapped["User"] = relationship("User", back_populates="payments")
        job: Mapped[Optional["Job"]] = relationship("Job", back_populates="payment")

        # Indexes
        __table_args__ = (
            Index("ix_payments_user_id", "user_id"),
            Index("ix_payments_job_id", "job_id"),
            Index("ix_payments_status", "status"),
            Index("ix_payments_method", "method"),
            Index("ix_payments_payment_hash", "payment_hash"),
        )

        def __repr__(self) -> str:
            return f"<Payment(id={self.id}, method={self.method}, amount={self.amount_sats} sats)>"

else:
    # Fallback when SQLAlchemy not available
    Base = None
    User = None
    Job = None
    JobResult = None
    Payment = None


if __name__ == "__main__":
    if SQLALCHEMY_AVAILABLE:
        print("Testing SQLAlchemy models...")

        # Verify all models are defined
        assert Base is not None
        assert User is not None
        assert Job is not None
        assert JobResult is not None
        assert Payment is not None

        # Check table names
        print(f"User table: {User.__tablename__}")
        print(f"Job table: {Job.__tablename__}")
        print(f"JobResult table: {JobResult.__tablename__}")
        print(f"Payment table: {Payment.__tablename__}")

        print("SUCCESS [models_test]: All models defined correctly")
    else:
        print("ERROR [models_test]: SQLAlchemy not available")
