#!/usr/bin/env python3
"""
Event-Driven Alerting System
@requirement: REQ-ALERT-001 through REQ-ALERT-006
@BLP: BLP-004 (Alignment), BLP-011 (Autonomy), BLP-021 (Durability)
"""

from .config import AlertConfig, ConfigManager
from .event_detector import EventDetector, EventType, EventPriority, MarketEvent
from .router import AlertRouter
from .history import AlertHistoryStore
from .email_channel import EmailChannel

__all__ = [
    "AlertConfig",
    "ConfigManager",
    "EventDetector",
    "EventType",
    "EventPriority",
    "MarketEvent",
    "AlertRouter",
    "AlertHistoryStore",
    "EmailChannel",
]
