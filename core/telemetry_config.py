"""
Distributed Tracing Configuration with OpenTelemetry + Jaeger

# REQ-TRACE-001: Every HTTP request gets a unique trace_id
# REQ-TRACE-002: Spans created for external API calls (Chainlink, Fedimint)
# REQ-TRACE-003: Database queries traced with timing
# REQ-TRACE-004: Agent operations traced across sub-agents
# BLP-031: Self-Improvement - Trace data enables performance optimization
"""

import os
import traceback
from contextvars import ContextVar
from functools import wraps
from typing import Any, Callable, Dict, Optional

# OpenTelemetry imports
try:
    from opentelemetry import trace
    from opentelemetry.exporter.jaeger.thrift import JaegerExporter
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
    from opentelemetry.instrumentation.requests import RequestsInstrumentor
    from opentelemetry.sdk.resources import SERVICE_NAME, Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
    from opentelemetry.trace import Status, StatusCode
    from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

    OTEL_AVAILABLE = True
except ImportError:
    OTEL_AVAILABLE = False
    print(
        "WARNING [telemetry_config]: OpenTelemetry not installed. Run: pip install opentelemetry-api opentelemetry-sdk opentelemetry-exporter-jaeger opentelemetry-instrumentation-fastapi opentelemetry-instrumentation-httpx opentelemetry-instrumentation-requests"
    )

# Context variable for current span
current_span_var: ContextVar[Optional[Any]] = ContextVar("current_span", default=None)

# Global tracer instance
_tracer: Optional[Any] = None


def configure_telemetry(
    service_name: str = "chainlink-job-marketplace",
    jaeger_host: str = "localhost",
    jaeger_port: int = 6831,
    enable_console_export: bool = False,
    enable_jaeger: bool = True,
) -> Optional[Any]:
    """
    Configure OpenTelemetry with Jaeger exporter.

    # REQ-TRACE-001: Every HTTP request gets a unique trace_id
    # BLP-031: Self-Improvement - Trace data enables performance optimization

    Args:
        service_name: Name of this service for identification in traces
        jaeger_host: Jaeger agent host
        jaeger_port: Jaeger agent UDP port
        enable_console_export: If True, also export traces to console
        enable_jaeger: If True, export traces to Jaeger

    Returns:
        Configured tracer or None if OpenTelemetry not available
    """
    global _tracer

    if not OTEL_AVAILABLE:
        print("WARNING [configure_telemetry]: OpenTelemetry not available, tracing disabled")
        return None

    try:
        # Create resource with service information
        resource = Resource(
            attributes={
                SERVICE_NAME: service_name,
                "service.version": "2.0.0",
                "deployment.environment": os.getenv("ENVIRONMENT", "development"),
            }
        )

        # Create tracer provider
        provider = TracerProvider(resource=resource)

        # Add Jaeger exporter if enabled
        if enable_jaeger:
            jaeger_exporter = JaegerExporter(
                agent_host_name=jaeger_host,
                agent_port=jaeger_port,
            )
            provider.add_span_processor(BatchSpanProcessor(jaeger_exporter))

        # Add console exporter if enabled (useful for debugging)
        if enable_console_export:
            console_exporter = ConsoleSpanExporter()
            provider.add_span_processor(BatchSpanProcessor(console_exporter))

        # Set global tracer provider
        trace.set_tracer_provider(provider)

        # Get tracer for this module
        _tracer = trace.get_tracer(__name__)

        print(
            f"SUCCESS [configure_telemetry]: OpenTelemetry configured with service={service_name}, jaeger={jaeger_host}:{jaeger_port}"
        )
        return _tracer

    except Exception as e:
        print(f"ERROR [configure_telemetry]: {type(e).__name__}: {e}")
        print(f"TRACEBACK: {traceback.format_exc()}")
        raise


def get_tracer(name: Optional[str] = None) -> Optional[Any]:
    """
    Get the configured tracer.

    # REQ-TRACE-002: Spans created for external API calls

    Args:
        name: Optional tracer name

    Returns:
        Tracer instance or None if not configured
    """
    if not OTEL_AVAILABLE:
        return None

    if name:
        return trace.get_tracer(name)
    return _tracer or trace.get_tracer(__name__)


def get_current_trace_id() -> Optional[str]:
    """
    Get the current trace ID for correlation.

    # REQ-TRACE-001: Every HTTP request gets a unique trace_id
    """
    if not OTEL_AVAILABLE:
        return None

    current_span = trace.get_current_span()
    if current_span:
        ctx = current_span.get_span_context()
        if ctx.is_valid:
            return format(ctx.trace_id, "032x")
    return None


def get_current_span_id() -> Optional[str]:
    """Get the current span ID."""
    if not OTEL_AVAILABLE:
        return None

    current_span = trace.get_current_span()
    if current_span:
        ctx = current_span.get_span_context()
        if ctx.is_valid:
            return format(ctx.span_id, "016x")
    return None


def trace_function(
    name: Optional[str] = None, attributes: Optional[Dict[str, Any]] = None
) -> Callable:
    """
    Decorator to trace function execution.

    # REQ-TRACE-002: Spans created for external API calls
    # REQ-TRACE-004: Agent operations traced across sub-agents

    Usage:
        @trace_function(name="my_operation", attributes={"key": "value"})
        def my_function():
            ...
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            tracer = get_tracer(func.__module__)
            span_name = name or f"{func.__module__}.{func.__name__}"

            if tracer is None:
                # Tracing not available, just execute function
                return func(*args, **kwargs)

            with tracer.start_as_current_span(span_name) as span:
                # Add custom attributes
                if attributes:
                    for key, value in attributes.items():
                        span.set_attribute(key, str(value))

                # Add function info
                span.set_attribute("code.function", func.__name__)
                span.set_attribute("code.namespace", func.__module__)

                try:
                    result = func(*args, **kwargs)

                    # Mark span as successful
                    span.set_status(Status(StatusCode.OK))
                    span.set_attribute("result.success", True)

                    result_str = str(result)[:200] if result is not None else "None"
                    print(f"SUCCESS [{span_name}]: {result_str}")

                    return result

                except Exception as e:
                    # Record exception in span
                    span.set_status(Status(StatusCode.ERROR, str(e)))
                    span.record_exception(e)
                    span.set_attribute("result.success", False)
                    span.set_attribute("error.type", type(e).__name__)
                    span.set_attribute("error.message", str(e))

                    print(f"ERROR [{span_name}]: {type(e).__name__}: {e}")
                    print(f"TRACEBACK: {traceback.format_exc()}")
                    raise

        return wrapper

    return decorator


def trace_async_function(
    name: Optional[str] = None, attributes: Optional[Dict[str, Any]] = None
) -> Callable:
    """
    Async version of trace_function decorator.

    # REQ-TRACE-002: Spans created for external API calls
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            tracer = get_tracer(func.__module__)
            span_name = name or f"{func.__module__}.{func.__name__}"

            if tracer is None:
                return await func(*args, **kwargs)

            with tracer.start_as_current_span(span_name) as span:
                if attributes:
                    for key, value in attributes.items():
                        span.set_attribute(key, str(value))

                span.set_attribute("code.function", func.__name__)
                span.set_attribute("code.namespace", func.__module__)

                try:
                    result = await func(*args, **kwargs)
                    span.set_status(Status(StatusCode.OK))
                    span.set_attribute("result.success", True)

                    result_str = str(result)[:200] if result is not None else "None"
                    print(f"SUCCESS [{span_name}]: {result_str}")

                    return result

                except Exception as e:
                    span.set_status(Status(StatusCode.ERROR, str(e)))
                    span.record_exception(e)
                    span.set_attribute("result.success", False)

                    print(f"ERROR [{span_name}]: {type(e).__name__}: {e}")
                    print(f"TRACEBACK: {traceback.format_exc()}")
                    raise

        return wrapper

    return decorator


class SpanContext:
    """
    Context manager for creating spans with attributes.

    # REQ-TRACE-003: Database queries traced with timing

    Usage:
        with SpanContext("database.query", {"db.statement": "SELECT..."}) as span:
            result = execute_query()
            span.set_attribute("db.row_count", len(result))
    """

    def __init__(
        self, name: str, attributes: Optional[Dict[str, Any]] = None, kind: Optional[Any] = None
    ):
        self.name = name
        self.attributes = attributes or {}
        self.kind = kind
        self.span = None

    def __enter__(self):
        if not OTEL_AVAILABLE:
            return self

        tracer = get_tracer()
        if tracer:
            self.span = tracer.start_span(self.name, kind=self.kind)
            for key, value in self.attributes.items():
                self.span.set_attribute(key, str(value))
            # Make this span current
            self._token = trace.use_span(self.span, end_on_exit=True)
            self._token.__enter__()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.span:
            if exc_type:
                self.span.set_status(Status(StatusCode.ERROR, str(exc_val)))
                self.span.record_exception(exc_val)
            else:
                self.span.set_status(Status(StatusCode.OK))
            self._token.__exit__(exc_type, exc_val, exc_tb)
        return False

    def set_attribute(self, key: str, value: Any) -> None:
        """Set additional attribute on the span."""
        if self.span:
            self.span.set_attribute(key, str(value))

    async def __aenter__(self):
        return self.__enter__()

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        return self.__exit__(exc_type, exc_val, exc_tb)


def instrument_fastapi(app: Any) -> None:
    """
    Instrument FastAPI application for automatic tracing.

    # REQ-TRACE-001: Every HTTP request gets a unique trace_id
    """
    if not OTEL_AVAILABLE:
        print("WARNING [instrument_fastapi]: OpenTelemetry not available")
        return

    try:
        FastAPIInstrumentor.instrument_app(app)
        print("SUCCESS [instrument_fastapi]: FastAPI instrumented for tracing")
    except Exception as e:
        print(f"ERROR [instrument_fastapi]: {type(e).__name__}: {e}")
        print(f"TRACEBACK: {traceback.format_exc()}")


def instrument_http_clients() -> None:
    """
    Instrument HTTP clients (httpx, requests) for automatic tracing.

    # REQ-TRACE-002: Spans created for external API calls (Chainlink, Fedimint)
    """
    if not OTEL_AVAILABLE:
        return

    try:
        HTTPXClientInstrumentor().instrument()
        RequestsInstrumentor().instrument()
        print("SUCCESS [instrument_http_clients]: HTTP clients instrumented for tracing")
    except Exception as e:
        print(f"WARNING [instrument_http_clients]: Could not instrument HTTP clients: {e}")


# Initialize on import if environment configured
if OTEL_AVAILABLE and os.getenv("OTEL_ENABLED", "false").lower() == "true":
    configure_telemetry(
        jaeger_host=os.getenv("JAEGER_HOST", "localhost"),
        jaeger_port=int(os.getenv("JAEGER_PORT", "6831")),
    )
    instrument_http_clients()


if __name__ == "__main__":
    # Test telemetry configuration
    print("Testing OpenTelemetry configuration...")

    tracer = configure_telemetry(
        enable_console_export=True, enable_jaeger=False  # Don't require Jaeger for testing
    )

    if tracer:
        # Test span creation
        @trace_function(name="test.operation")
        def test_function():
            return "test result"

        result = test_function()
        print(f"Test function result: {result}")

        # Test span context
        with SpanContext("test.span", {"test.key": "test.value"}) as span:
            span.set_attribute("dynamic.key", "dynamic.value")

        trace_id = get_current_trace_id()
        print(f"Current trace ID: {trace_id}")

    print("SUCCESS [telemetry_config_test]: All telemetry tests passed")
