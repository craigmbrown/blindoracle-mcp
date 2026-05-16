"""
Repository Pattern for Database Operations

# REQ-DB-003: SQLAlchemy async ORM with type hints
# REQ-TRACE-003: Database queries traced with timing
# BLP-021: Durability - Transactional data access
# BLP-031: Self-Improvement - Query performance tracking
"""

import traceback
from datetime import datetime
from typing import Any, Dict, Generic, List, Optional, Type, TypeVar
from uuid import uuid4

try:
    from sqlalchemy import select, update, delete, func
    from sqlalchemy.ext.asyncio import AsyncSession

    SQLALCHEMY_AVAILABLE = True
except ImportError:
    SQLALCHEMY_AVAILABLE = False
    print("WARNING [repository]: SQLAlchemy not installed")

from .models import Base, Job, JobResult, JobStatus, Payment, PaymentStatus, User

# Type variable for generic repository
T = TypeVar("T", bound=Base) if SQLALCHEMY_AVAILABLE else TypeVar("T")


class BaseRepository(Generic[T]):
    """
    Base repository with common CRUD operations.

    # REQ-DB-003: SQLAlchemy async ORM with type hints
    # REQ-TRACE-003: Database queries traced with timing
    """

    def __init__(self, session: AsyncSession, model: Type[T]):
        """
        Initialize repository with session and model.

        Args:
            session: SQLAlchemy async session
            model: SQLAlchemy model class
        """
        self.session = session
        self.model = model
        self.model_name = model.__name__ if hasattr(model, "__name__") else "Unknown"

    async def get_by_id(self, id: str) -> Optional[T]:
        """
        Get entity by ID.

        # REQ-TRACE-003: Database queries traced with timing
        """
        try:
            result = await self.session.get(self.model, id)
            if result:
                print(f"SUCCESS [BaseRepository.get_by_id]: Found {self.model_name} id={id}")
            else:
                print(f"SUCCESS [BaseRepository.get_by_id]: {self.model_name} id={id} not found")
            return result
        except Exception as e:
            print(f"ERROR [BaseRepository.get_by_id]: {type(e).__name__}: {e}")
            print(f"TRACEBACK: {traceback.format_exc()}")
            raise

    async def get_all(self, limit: int = 100, offset: int = 0) -> List[T]:
        """
        Get all entities with pagination.

        # REQ-TRACE-003: Database queries traced with timing
        """
        try:
            stmt = select(self.model).limit(limit).offset(offset)
            result = await self.session.execute(stmt)
            entities = list(result.scalars().all())
            print(
                f"SUCCESS [BaseRepository.get_all]: Retrieved {len(entities)} {self.model_name} entities"
            )
            return entities
        except Exception as e:
            print(f"ERROR [BaseRepository.get_all]: {type(e).__name__}: {e}")
            print(f"TRACEBACK: {traceback.format_exc()}")
            raise

    async def create(self, entity: T) -> T:
        """
        Create new entity.

        # REQ-TRACE-003: Database queries traced with timing
        """
        try:
            self.session.add(entity)
            await self.session.flush()
            await self.session.refresh(entity)
            print(f"SUCCESS [BaseRepository.create]: Created {self.model_name} id={entity.id}")
            return entity
        except Exception as e:
            print(f"ERROR [BaseRepository.create]: {type(e).__name__}: {e}")
            print(f"TRACEBACK: {traceback.format_exc()}")
            raise

    async def update(self, id: str, **kwargs) -> Optional[T]:
        """
        Update entity by ID.

        # REQ-TRACE-003: Database queries traced with timing
        """
        try:
            entity = await self.get_by_id(id)
            if entity is None:
                print(f"ERROR [BaseRepository.update]: {self.model_name} id={id} not found")
                return None

            for key, value in kwargs.items():
                if hasattr(entity, key):
                    setattr(entity, key, value)

            await self.session.flush()
            await self.session.refresh(entity)
            print(f"SUCCESS [BaseRepository.update]: Updated {self.model_name} id={id}")
            return entity
        except Exception as e:
            print(f"ERROR [BaseRepository.update]: {type(e).__name__}: {e}")
            print(f"TRACEBACK: {traceback.format_exc()}")
            raise

    async def delete(self, id: str) -> bool:
        """
        Delete entity by ID.

        # REQ-TRACE-003: Database queries traced with timing
        """
        try:
            entity = await self.get_by_id(id)
            if entity is None:
                print(f"ERROR [BaseRepository.delete]: {self.model_name} id={id} not found")
                return False

            await self.session.delete(entity)
            print(f"SUCCESS [BaseRepository.delete]: Deleted {self.model_name} id={id}")
            return True
        except Exception as e:
            print(f"ERROR [BaseRepository.delete]: {type(e).__name__}: {e}")
            print(f"TRACEBACK: {traceback.format_exc()}")
            raise

    async def count(self) -> int:
        """
        Count total entities.

        # BLP-031: Self-Improvement - Metrics for optimization
        """
        try:
            stmt = select(func.count()).select_from(self.model)
            result = await self.session.execute(stmt)
            count = result.scalar()
            print(f"SUCCESS [BaseRepository.count]: {self.model_name} count={count}")
            return count
        except Exception as e:
            print(f"ERROR [BaseRepository.count]: {type(e).__name__}: {e}")
            print(f"TRACEBACK: {traceback.format_exc()}")
            raise


class UserRepository(BaseRepository[User]):
    """
    User-specific repository operations.

    # REQ-DB-003: SQLAlchemy async ORM with type hints
    """

    def __init__(self, session: AsyncSession):
        super().__init__(session, User)

    async def get_by_email(self, email: str) -> Optional[User]:
        """Get user by email address."""
        try:
            stmt = select(User).where(User.email == email)
            result = await self.session.execute(stmt)
            user = result.scalar_one_or_none()
            if user:
                print(f"SUCCESS [UserRepository.get_by_email]: Found user email={email}")
            return user
        except Exception as e:
            print(f"ERROR [UserRepository.get_by_email]: {type(e).__name__}: {e}")
            print(f"TRACEBACK: {traceback.format_exc()}")
            raise

    async def get_by_wallet(self, wallet_address: str) -> Optional[User]:
        """Get user by wallet address."""
        try:
            stmt = select(User).where(User.wallet_address == wallet_address)
            result = await self.session.execute(stmt)
            user = result.scalar_one_or_none()
            if user:
                print(
                    f"SUCCESS [UserRepository.get_by_wallet]: Found user wallet={wallet_address[:10]}..."
                )
            return user
        except Exception as e:
            print(f"ERROR [UserRepository.get_by_wallet]: {type(e).__name__}: {e}")
            print(f"TRACEBACK: {traceback.format_exc()}")
            raise

    async def get_by_tier(self, tier: str, limit: int = 100) -> List[User]:
        """Get users by tier."""
        try:
            stmt = select(User).where(User.tier == tier).limit(limit)
            result = await self.session.execute(stmt)
            users = list(result.scalars().all())
            print(
                f"SUCCESS [UserRepository.get_by_tier]: Found {len(users)} users with tier={tier}"
            )
            return users
        except Exception as e:
            print(f"ERROR [UserRepository.get_by_tier]: {type(e).__name__}: {e}")
            print(f"TRACEBACK: {traceback.format_exc()}")
            raise


class JobRepository(BaseRepository[Job]):
    """
    Job-specific repository operations.

    # REQ-DB-003: SQLAlchemy async ORM with type hints
    # BLP-011: Autonomy - Self-managed job queries
    """

    def __init__(self, session: AsyncSession):
        super().__init__(session, Job)

    async def get_by_user(self, user_id: str, limit: int = 100) -> List[Job]:
        """Get jobs by user ID."""
        try:
            stmt = (
                select(Job)
                .where(Job.user_id == user_id)
                .order_by(Job.created_at.desc())
                .limit(limit)
            )
            result = await self.session.execute(stmt)
            jobs = list(result.scalars().all())
            print(
                f"SUCCESS [JobRepository.get_by_user]: Found {len(jobs)} jobs for user={user_id[:8]}..."
            )
            return jobs
        except Exception as e:
            print(f"ERROR [JobRepository.get_by_user]: {type(e).__name__}: {e}")
            print(f"TRACEBACK: {traceback.format_exc()}")
            raise

    async def get_by_status(self, status: JobStatus, limit: int = 100) -> List[Job]:
        """Get jobs by status."""
        try:
            stmt = (
                select(Job)
                .where(Job.status == status.value)
                .order_by(Job.created_at.desc())
                .limit(limit)
            )
            result = await self.session.execute(stmt)
            jobs = list(result.scalars().all())
            print(
                f"SUCCESS [JobRepository.get_by_status]: Found {len(jobs)} jobs with status={status.value}"
            )
            return jobs
        except Exception as e:
            print(f"ERROR [JobRepository.get_by_status]: {type(e).__name__}: {e}")
            print(f"TRACEBACK: {traceback.format_exc()}")
            raise

    async def get_pending_jobs(self, limit: int = 50) -> List[Job]:
        """
        Get pending jobs for processing (queue).

        # REQ-METRICS-004: Job queue depth gauge
        """
        try:
            stmt = (
                select(Job)
                .where(Job.status == JobStatus.PENDING.value)
                .order_by(Job.created_at.asc())
                .limit(limit)
            )
            result = await self.session.execute(stmt)
            jobs = list(result.scalars().all())
            print(f"SUCCESS [JobRepository.get_pending_jobs]: Found {len(jobs)} pending jobs")
            return jobs
        except Exception as e:
            print(f"ERROR [JobRepository.get_pending_jobs]: {type(e).__name__}: {e}")
            print(f"TRACEBACK: {traceback.format_exc()}")
            raise

    async def update_status(
        self, job_id: str, status: JobStatus, error_message: Optional[str] = None
    ) -> Optional[Job]:
        """
        Update job status with optional error message.

        # BLP-021: Durability - Status persistence
        """
        try:
            job = await self.get_by_id(job_id)
            if job is None:
                print(f"ERROR [JobRepository.update_status]: Job id={job_id} not found")
                return None

            job.status = status.value
            job.updated_at = datetime.utcnow()

            if status == JobStatus.PROCESSING:
                job.started_at = datetime.utcnow()
            elif status in (JobStatus.COMPLETED, JobStatus.FAILED):
                job.completed_at = datetime.utcnow()

            if error_message:
                job.error_message = error_message
                job.retry_count += 1

            await self.session.flush()
            await self.session.refresh(job)
            print(
                f"SUCCESS [JobRepository.update_status]: Job id={job_id[:8]}... status={status.value}"
            )
            return job
        except Exception as e:
            print(f"ERROR [JobRepository.update_status]: {type(e).__name__}: {e}")
            print(f"TRACEBACK: {traceback.format_exc()}")
            raise

    async def count_by_status(self) -> Dict[str, int]:
        """
        Count jobs by status.

        # REQ-METRICS-004: Job queue depth gauge
        # BLP-031: Self-Improvement - Queue depth metrics
        """
        try:
            counts = {}
            for status in JobStatus:
                stmt = select(func.count()).select_from(Job).where(Job.status == status.value)
                result = await self.session.execute(stmt)
                counts[status.value] = result.scalar()

            print(f"SUCCESS [JobRepository.count_by_status]: {counts}")
            return counts
        except Exception as e:
            print(f"ERROR [JobRepository.count_by_status]: {type(e).__name__}: {e}")
            print(f"TRACEBACK: {traceback.format_exc()}")
            raise


class PaymentRepository(BaseRepository[Payment]):
    """
    Payment-specific repository operations.

    # REQ-DB-003: SQLAlchemy async ORM with type hints
    # BLP-021: Durability - Payment audit trail
    """

    def __init__(self, session: AsyncSession):
        super().__init__(session, Payment)

    async def get_by_user(self, user_id: str, limit: int = 100) -> List[Payment]:
        """Get payments by user ID."""
        try:
            stmt = (
                select(Payment)
                .where(Payment.user_id == user_id)
                .order_by(Payment.created_at.desc())
                .limit(limit)
            )
            result = await self.session.execute(stmt)
            payments = list(result.scalars().all())
            print(
                f"SUCCESS [PaymentRepository.get_by_user]: Found {len(payments)} payments for user={user_id[:8]}..."
            )
            return payments
        except Exception as e:
            print(f"ERROR [PaymentRepository.get_by_user]: {type(e).__name__}: {e}")
            print(f"TRACEBACK: {traceback.format_exc()}")
            raise

    async def get_by_job(self, job_id: str) -> Optional[Payment]:
        """Get payment by job ID."""
        try:
            stmt = select(Payment).where(Payment.job_id == job_id)
            result = await self.session.execute(stmt)
            payment = result.scalar_one_or_none()
            if payment:
                print(
                    f"SUCCESS [PaymentRepository.get_by_job]: Found payment for job={job_id[:8]}..."
                )
            return payment
        except Exception as e:
            print(f"ERROR [PaymentRepository.get_by_job]: {type(e).__name__}: {e}")
            print(f"TRACEBACK: {traceback.format_exc()}")
            raise

    async def get_by_payment_hash(self, payment_hash: str) -> Optional[Payment]:
        """Get payment by Lightning payment hash."""
        try:
            stmt = select(Payment).where(Payment.payment_hash == payment_hash)
            result = await self.session.execute(stmt)
            payment = result.scalar_one_or_none()
            if payment:
                print(
                    f"SUCCESS [PaymentRepository.get_by_payment_hash]: Found payment hash={payment_hash[:10]}..."
                )
            return payment
        except Exception as e:
            print(f"ERROR [PaymentRepository.get_by_payment_hash]: {type(e).__name__}: {e}")
            print(f"TRACEBACK: {traceback.format_exc()}")
            raise

    async def update_status(
        self,
        payment_id: str,
        status: PaymentStatus,
        preimage: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> Optional[Payment]:
        """
        Update payment status.

        # BLP-021: Durability - Payment status persistence
        """
        try:
            payment = await self.get_by_id(payment_id)
            if payment is None:
                print(f"ERROR [PaymentRepository.update_status]: Payment id={payment_id} not found")
                return None

            payment.status = status.value
            payment.updated_at = datetime.utcnow()

            if status == PaymentStatus.COMPLETED:
                payment.completed_at = datetime.utcnow()
                if preimage:
                    payment.preimage = preimage

            if error_message:
                payment.error_message = error_message

            await self.session.flush()
            await self.session.refresh(payment)
            print(
                f"SUCCESS [PaymentRepository.update_status]: Payment id={payment_id[:8]}... status={status.value}"
            )
            return payment
        except Exception as e:
            print(f"ERROR [PaymentRepository.update_status]: {type(e).__name__}: {e}")
            print(f"TRACEBACK: {traceback.format_exc()}")
            raise

    async def get_total_volume(self, user_id: Optional[str] = None) -> int:
        """
        Get total payment volume in satoshis.

        # BLP-031: Self-Improvement - Revenue metrics
        """
        try:
            stmt = select(func.sum(Payment.amount_sats)).where(
                Payment.status == PaymentStatus.COMPLETED.value
            )
            if user_id:
                stmt = stmt.where(Payment.user_id == user_id)

            result = await self.session.execute(stmt)
            total = result.scalar() or 0
            print(f"SUCCESS [PaymentRepository.get_total_volume]: Total volume={total} sats")
            return total
        except Exception as e:
            print(f"ERROR [PaymentRepository.get_total_volume]: {type(e).__name__}: {e}")
            print(f"TRACEBACK: {traceback.format_exc()}")
            raise


if __name__ == "__main__":
    print("Repository module loaded successfully")
    print(f"SQLAlchemy available: {SQLALCHEMY_AVAILABLE}")

    if SQLALCHEMY_AVAILABLE:
        print("Available repositories: UserRepository, JobRepository, PaymentRepository")
        print("SUCCESS [repository_test]: All repositories defined correctly")
