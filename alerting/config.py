#!/usr/bin/env python3
"""
Alert Configuration System
@requirement: REQ-ALERT-004 - User-configurable alert settings
@BLP: BLP-004 (Alignment with user preferences)
"""

import json
import os
import traceback
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class PriceAlertRule:
    """A single user-configured price alert."""

    alert_id: str
    asset: str
    target_price: float
    direction: str  # "above" or "below"
    active: bool = True


@dataclass
class AlertConfig:
    """
    Configuration for the alert system.
    @requirement: REQ-ALERT-004 - Configurable thresholds and channel routing
    """

    # Monitoring settings
    poll_interval_seconds: int = 60
    markets_to_monitor: List[str] = field(default_factory=list)

    # Threshold settings
    arbitrage_threshold_percent: float = 2.0
    probability_shift_threshold_1h: float = 0.05
    probability_shift_threshold_24h: float = 0.10
    volume_spike_multiplier: float = 3.0

    # Channel enabled/disabled flags
    channels: Dict[str, bool] = field(
        default_factory=lambda: {
            "whatsapp": True,
            "nostr": True,
            "email": False,
            "slack": False,
        }
    )

    # Priority -> channel routing
    # WhatsApp is CRITICAL-only per project policy (feedback_whatsapp_p0_only)
    priority_channels: Dict[str, List[str]] = field(
        default_factory=lambda: {
            "critical": ["whatsapp", "nostr"],
            "high": ["nostr"],
            "medium": ["nostr"],
            "low": [],
        }
    )

    # Rate limiting
    max_alerts_per_hour: int = 20
    quiet_hours_start: int = 22  # 10 PM local
    quiet_hours_end: int = 7  # 7 AM local
    batch_low_priority: bool = True

    # Deduplication
    dedup_window_minutes: int = 30

    # User-defined price alerts
    price_alerts: List[Dict[str, Any]] = field(default_factory=list)

    def validate(self) -> List[str]:
        """Validate configuration and return list of errors."""
        errors: List[str] = []
        if self.poll_interval_seconds < 10:
            errors.append("poll_interval_seconds must be >= 10")
        if not 0.0 < self.arbitrage_threshold_percent <= 100.0:
            errors.append("arbitrage_threshold_percent must be in (0, 100]")
        if not 0.0 < self.probability_shift_threshold_1h <= 1.0:
            errors.append("probability_shift_threshold_1h must be in (0, 1]")
        if self.volume_spike_multiplier < 1.0:
            errors.append("volume_spike_multiplier must be >= 1.0")
        if not 0 <= self.quiet_hours_start <= 23:
            errors.append("quiet_hours_start must be 0-23")
        if not 0 <= self.quiet_hours_end <= 23:
            errors.append("quiet_hours_end must be 0-23")
        if self.max_alerts_per_hour < 1:
            errors.append("max_alerts_per_hour must be >= 1")
        for direction in [pa.get("direction") for pa in self.price_alerts]:
            if direction not in ("above", "below"):
                errors.append(f"price_alert direction must be 'above' or 'below', got: {direction}")
        return errors


class ConfigManager:
    """
    Manages alert configuration with JSON persistence.
    @requirement: REQ-ALERT-004 - Configuration management
    """

    _DEFAULT_CONFIG_PATH = str(
        Path(__file__).parent.parent / "config" / "alert_config.json"
    )

    def __init__(self, config_path: Optional[str] = None) -> None:
        self.config_path = config_path or self._DEFAULT_CONFIG_PATH
        self.config: AlertConfig = self._load_config()
        print(f"✅ ConfigManager initialized from: {self.config_path}")

    def _load_config(self) -> AlertConfig:
        """Load configuration from JSON file, falling back to defaults."""
        try:
            path = Path(self.config_path)
            if path.exists():
                with open(path, "r") as f:
                    data = json.load(f)
                config = AlertConfig(**data)
                errors = config.validate()
                if errors:
                    print(f"⚠️ Config validation warnings: {errors}")
                print(f"✅ Config loaded from {self.config_path}")
                return config
            else:
                print(f"ℹ️ No config file found at {self.config_path}, using defaults")
                return AlertConfig()
        except Exception as e:
            print(f"❌ Failed to load config: {e}")
            print(f"   Traceback: {traceback.format_exc()}")
            return AlertConfig()

    def save_config(self) -> bool:
        """Persist current configuration to disk."""
        try:
            path = Path(self.config_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w") as f:
                json.dump(asdict(self.config), f, indent=2)
            print(f"✅ Config saved to {self.config_path}")
            return True
        except Exception as e:
            print(f"❌ Failed to save config: {e}")
            print(f"   Traceback: {traceback.format_exc()}")
            return False

    def update_config(self, updates: Dict[str, Any]) -> AlertConfig:
        """
        Apply a partial update dict and persist.
        @requirement: REQ-ALERT-004 - Dynamic config updates
        """
        try:
            current = asdict(self.config)
            for key, value in updates.items():
                if key in current:
                    current[key] = value
                else:
                    print(f"⚠️ Unknown config key ignored: {key}")
            self.config = AlertConfig(**current)
            errors = self.config.validate()
            if errors:
                print(f"⚠️ Config validation warnings after update: {errors}")
            self.save_config()
            print(f"✅ Config updated: {list(updates.keys())}")
            return self.config
        except Exception as e:
            print(f"❌ update_config failed: {e}")
            print(f"   Traceback: {traceback.format_exc()}")
            return self.config

    def add_price_alert(
        self,
        asset: str,
        target_price: float,
        direction: str = "above",
    ) -> str:
        """
        Add a price alert rule.
        @requirement: REQ-ALERT-004 - User price alerts
        """
        if direction not in ("above", "below"):
            raise ValueError(f"direction must be 'above' or 'below', got: {direction}")

        alert_id = str(uuid.uuid4())[:8]
        rule = {
            "alert_id": alert_id,
            "asset": asset.upper(),
            "target_price": target_price,
            "direction": direction,
            "active": True,
        }
        self.config.price_alerts.append(rule)
        self.save_config()
        print(f"✅ Price alert added: {asset} {direction} {target_price} (id={alert_id})")
        return alert_id

    def remove_price_alert(self, alert_id: str) -> bool:
        """Remove a price alert by ID."""
        before = len(self.config.price_alerts)
        self.config.price_alerts = [
            pa for pa in self.config.price_alerts if pa.get("alert_id") != alert_id
        ]
        if len(self.config.price_alerts) < before:
            self.save_config()
            print(f"✅ Price alert removed: {alert_id}")
            return True
        print(f"⚠️ Price alert not found: {alert_id}")
        return False
