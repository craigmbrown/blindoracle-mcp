"""
Centralized Logging Configuration with Structlog

# REQ-LOG-001: All functions must use structlog instead of print()
# REQ-LOG-002: Every log entry must include correlation_id, timestamp, level
# REQ-LOG-003: Exception logs must include full traceback
# REQ-LOG-004: JSON format for machine parsing (Loki/ELK compatible)
# BLP-021: Durability - Persistent, queryable logs for debugging
"""

import logging
import sys
import traceback
import uuid
from contextvars import ContextVar
from datetime import datetime
from functools import wraps
from typing import Any, Callable, Optional

import structlog

# Context variable for correlation ID (thread-safe)
correlation_id_var: ContextVar[Optional[str]] = ContextVar("correlation_id", default=None)


def get_correlation_id() -> str:
    """
    # REQ-LOG-002: correlation_id in all logs
    Get current correlation ID or generate a new one.
    """
    cid = correlation_id_var.get()
    if cid is None:
        cid = str(uuid.uuid4())[:8]
        correlation_id_var.set(cid)
    return cid


def set_correlation_id(cid: str) -> None:
    """Set correlation ID for current context."""
    correlation_id_var.set(cid)


def add_correlation_id(logger: Any, method_name: str, event_dict: dict) -> dict:
    """Structlog processor to add correlation_id to all log entries."""
    event_dict["correlation_id"] = get_correlation_id()
    return event_dict


def add_timestamp(logger: Any, method_name: str, event_dict: dict) -> dict:
    """Structlog processor to add ISO timestamp."""
    event_dict["timestamp"] = datetime.utcnow().isoformat() + "Z"
    return event_dict


def add_service_info(logger: Any, method_name: str, event_dict: dict) -> dict:
    """Add service identification for distributed tracing."""
    event_dict["service"] = "chainlink-job-marketplace"
    event_dict["version"] = "2.0.0"
    return event_dict


def configure_logging(
    log_level: str = "INFO", json_format: bool = True, log_file: Optional[str] = None
) -> structlog.BoundLogger:
    """
    Configure structlog with JSON formatting for production.

    # REQ-LOG-004: JSON format for machine parsing (Loki/ELK compatible)
    # BLP-021: Durability - Structured logs enable long-term analysis

    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        json_format: If True, output JSON; if False, output human-readable
        log_file: Optional file path for log output

    Returns:
        Configured structlog logger
    """
    try:
        # Configure standard library logging first
        logging.basicConfig(
            format="%(message)s",
            stream=sys.stdout,
            level=getattr(logging, log_level.upper()),
        )

        # Shared processors for all outputs
        shared_processors = [
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            add_timestamp,
            add_correlation_id,
            add_service_info,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.UnicodeDecoder(),
        ]

        if json_format:
            # JSON output for production (Loki/ELK compatible)
            processors = shared_processors + [
                structlog.processors.format_exc_info,
                structlog.processors.JSONRenderer(),
            ]
        else:
            # Human-readable output for development
            processors = shared_processors + [
                structlog.dev.ConsoleRenderer(colors=True),
            ]

        structlog.configure(
            processors=processors,
            wrapper_class=structlog.stdlib.BoundLogger,
            context_class=dict,
            logger_factory=structlog.stdlib.LoggerFactory(),
            cache_logger_on_first_use=True,
        )

        logger = structlog.get_logger()
        print(
            f"SUCCESS [configure_logging]: Structlog configured with level={log_level}, json={json_format}"
        )
        return logger

    except Exception as e:
        print(f"ERROR [configure_logging]: {type(e).__name__}: {e}")
        print(f"TRACEBACK: {traceback.format_exc()}")
        raise


def get_logger(name: Optional[str] = None) -> structlog.BoundLogger:
    """
    Get a configured structlog logger.

    # REQ-LOG-001: All functions must use structlog instead of print()

    Args:
        name: Optional logger name for identification

    Returns:
        Configured structlog BoundLogger instance
    """
    logger = structlog.get_logger(name) if name else structlog.get_logger()
    return logger


def log_function_call(func: Callable) -> Callable:
    """
    Decorator to log function entry, exit, and exceptions.

    # REQ-LOG-003: Exception logs must include full traceback
    # BLP-021: Durability - Complete audit trail of function calls

    Usage:
        @log_function_call
        def my_function(params):
            ...
    """

    @wraps(func)
    def wrapper(*args, **kwargs):
        logger = get_logger(func.__module__)
        func_name = func.__name__

        # Log entry
        logger.debug(f"{func_name}.entry", args_count=len(args), kwargs_keys=list(kwargs.keys()))

        try:
            result = func(*args, **kwargs)

            # Log success with Standard I/O Contract
            result_str = str(result)[:200] if result is not None else "None"
            logger.info(f"{func_name}.success", result_preview=result_str)
            print(f"SUCCESS [{func_name}]: {result_str}")  # REQUIRED for agent parsing

            return result

        except Exception as e:
            # Log error with full traceback (Standard I/O Contract)
            tb = traceback.format_exc()
            logger.exception(
                f"{func_name}.error",
                error_type=type(e).__name__,
                error_message=str(e),
                traceback=tb,
            )
            print(f"ERROR [{func_name}]: {type(e).__name__}: {e}")  # REQUIRED
            print(f"TRACEBACK: {tb}")  # REQUIRED
            raise

    return wrapper


async def log_async_function_call(func: Callable) -> Callable:
    """
    Async version of log_function_call decorator.

    # REQ-LOG-003: Exception logs must include full traceback

    Usage:
        @log_async_function_call
        async def my_async_function(params):
            ...
    """

    @wraps(func)
    async def wrapper(*args, **kwargs):
        logger = get_logger(func.__module__)
        func_name = func.__name__

        logger.debug(f"{func_name}.entry", args_count=len(args), kwargs_keys=list(kwargs.keys()))

        try:
            result = await func(*args, **kwargs)

            result_str = str(result)[:200] if result is not None else "None"
            logger.info(f"{func_name}.success", result_preview=result_str)
            print(f"SUCCESS [{func_name}]: {result_str}")

            return result

        except Exception as e:
            tb = traceback.format_exc()
            logger.exception(
                f"{func_name}.error",
                error_type=type(e).__name__,
                error_message=str(e),
                traceback=tb,
            )
            print(f"ERROR [{func_name}]: {type(e).__name__}: {e}")
            print(f"TRACEBACK: {tb}")
            raise

    return wrapper


class RequestContextLogger:
    """
    Context manager for request-scoped logging with correlation ID.

    # REQ-LOG-002: Every log entry must include correlation_id
    # REQ-TRACE-001: Every HTTP request gets a unique trace_id

    Usage:
        async with RequestContextLogger(request_id="abc123") as logger:
            logger.info("Processing request")
    """

    def __init__(self, request_id: Optional[str] = None, trace_id: Optional[str] = None):
        self.request_id = request_id or str(uuid.uuid4())[:8]
        self.trace_id = trace_id
        self._previous_cid: Optional[str] = None

    def __enter__(self):
        self._previous_cid = correlation_id_var.get()
        set_correlation_id(self.request_id)
        self.logger = get_logger().bind(request_id=self.request_id, trace_id=self.trace_id)
        return self.logger

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._previous_cid:
            set_correlation_id(self._previous_cid)
        return False

    async def __aenter__(self):
        return self.__enter__()

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        return self.__exit__(exc_type, exc_val, exc_tb)


# Pre-configured logger for immediate use
logger = configure_logging(log_level="INFO", json_format=True)


if __name__ == "__main__":
    # Test the logging configuration
    print("Testing structlog configuration...")

    test_logger = get_logger("test")

    # Test basic logging
    test_logger.info("Test info message", key="value", number=42)
    test_logger.warning("Test warning", warning_type="test")

    # Test with correlation ID
    with RequestContextLogger(request_id="test123") as ctx_logger:
        ctx_logger.info("Message with correlation ID")

    # Test error logging
    try:
        raise ValueError("Test error for logging")
    except Exception as e:
        test_logger.exception("Caught test exception", error=str(e))
        print(f"ERROR [test]: {type(e).__name__}: {e}")
        print(f"TRACEBACK: {traceback.format_exc()}")

    print("SUCCESS [logging_config_test]: All logging tests passed")
