#!/usr/bin/env python3
"""
Phase 6: Enhanced Notification System for Chainlink Job Runner
Supports: WhatsApp, Slack, Nostr DM, Email alerts
Integrates with: Security system, Payment system, Job runner
"""

import json
import os
import urllib.request
import hashlib
import secrets
import time
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Any

# Optional dependencies
try:
    from coincurve import PrivateKey, PublicKey

    SECP256K1_AVAILABLE = True
except ImportError:
    SECP256K1_AVAILABLE = False

try:
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import pad
    import base64

    NIP04_AVAILABLE = True
except ImportError:
    NIP04_AVAILABLE = False

try:
    import websockets
    import asyncio

    WS_AVAILABLE = True
except ImportError:
    WS_AVAILABLE = False


class AlertLevel(Enum):
    """Alert severity levels"""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class NotificationChannel(Enum):
    """Available notification channels"""

    WHATSAPP = "whatsapp"
    SLACK = "slack"
    NOSTR = "nostr"
    LOG = "log"


@dataclass
class NotificationConfig:
    """Configuration for notifications"""

    whatsapp_enabled: bool = True
    whatsapp_number: str = os.environ.get("BLINDORACLE_OPERATOR_WHATSAPP", "")
    whatsapp_api_url: str = "http://localhost:8082/api/send"

    slack_enabled: bool = True
    slack_webhook_url: str = ""

    nostr_enabled: bool = True
    nostr_target_pubkey: str = "83a02ac310cc2385d4ebe0e49b46f7b29c29c2f20b181b7396e50b3d35b0f112"
    nostr_relays: List[str] = field(
        default_factory=lambda: ["wss://relay.damus.io", "wss://nos.lol", "wss://relay.primal.net"]
    )
    nostr_identity_path: str = "/home/craigmbrown/.config/fedimint-nostr-identity.json"

    # Alert thresholds
    critical_sats_threshold: int = 10000  # Alert if single payment > 10k sats
    error_rate_threshold: float = 0.2  # Alert if error rate > 20%
    security_alert_enabled: bool = True

    # Rate limiting
    min_notification_interval_secs: int = 60  # Don't spam

    project_dir: Path = Path("/home/craigmbrown/Project/chainlink-prediction-markets-mcp-enhanced")


@dataclass
class Notification:
    """A notification to be sent"""

    title: str
    message: str
    level: AlertLevel
    channels: List[NotificationChannel]
    data: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.utcnow)


class NotificationManager:
    """Enhanced notification management with multi-channel support"""

    def __init__(self, config: Optional[NotificationConfig] = None):
        self.config = config or NotificationConfig()
        self.last_notification_time: Dict[str, datetime] = {}
        self.log_file = self.config.project_dir / "logs/notifications.json"
        self._load_slack_webhook()

    def _load_slack_webhook(self):
        """Load Slack webhook from environment or .env file"""
        if self.config.slack_webhook_url:
            return

        webhook = os.environ.get("SLACK_WEBHOOK_URL", "")
        if not webhook:
            try:
                env_file = Path("/home/craigmbrown/Project/.env")
                if env_file.exists():
                    with open(env_file) as f:
                        for line in f:
                            if line.startswith("SLACK_WEBHOOK_URL="):
                                webhook = line.split("=", 1)[1].strip().strip('"')
                                break
            except Exception:
                pass
        self.config.slack_webhook_url = webhook

    def should_send(self, channel: NotificationChannel) -> bool:
        """Check if we should send to this channel (rate limiting)"""
        key = channel.value
        last_time = self.last_notification_time.get(key)

        if last_time:
            elapsed = (datetime.utcnow() - last_time).total_seconds()
            if elapsed < self.config.min_notification_interval_secs:
                return False

        return True

    def _record_sent(self, channel: NotificationChannel):
        """Record that we sent to this channel"""
        self.last_notification_time[channel.value] = datetime.utcnow()

    # ========== Channel Implementations ==========

    def _send_whatsapp(self, message: str) -> tuple:
        """Send via WhatsApp bridge"""
        if not self.config.whatsapp_enabled:
            return False, "Disabled"

        try:
            data = json.dumps(
                {"recipient": self.config.whatsapp_number, "message": message}
            ).encode("utf-8")

            req = urllib.request.Request(
                self.config.whatsapp_api_url,
                data=data,
                headers={"Content-Type": "application/json"},
            )
            resp = urllib.request.urlopen(req, timeout=10)
            result = json.loads(resp.read().decode("utf-8"))
            return result.get("success", False), json.dumps(result)
        except Exception as e:
            return False, str(e)

    def _send_slack(self, message: str) -> tuple:
        """Send via Slack webhook"""
        if not self.config.slack_enabled:
            return False, "Disabled"

        if not self.config.slack_webhook_url:
            return True, "Skipped (no webhook)"

        try:
            data = json.dumps({"text": message}).encode("utf-8")
            req = urllib.request.Request(
                self.config.slack_webhook_url,
                data=data,
                headers={"Content-Type": "application/json"},
            )
            resp = urllib.request.urlopen(req, timeout=10)
            return resp.status == 200, f"Status: {resp.status}"
        except Exception as e:
            return False, str(e)

    async def _send_nostr_async(self, message: str) -> tuple:
        """Send encrypted DM via Nostr (NIP-04)"""
        if not self.config.nostr_enabled:
            return False, "Disabled"

        if not all([SECP256K1_AVAILABLE, NIP04_AVAILABLE, WS_AVAILABLE]):
            return False, f"Missing deps"

        try:
            # Load identity
            with open(self.config.nostr_identity_path) as f:
                identity = json.load(f)

            private_key_hex = bytes(identity["secretKey"]).hex()
            pubkey_hex = identity["pubkey"]

            sk = PrivateKey(bytes.fromhex(private_key_hex))
            target_pubkey = self.config.nostr_target_pubkey

            # NIP-04 encryption
            target_pk_bytes = bytes.fromhex("02" + target_pubkey)
            target_pk = PublicKey(target_pk_bytes)
            shared_point = target_pk.multiply(bytes.fromhex(private_key_hex))
            shared_point_uncompressed = shared_point.format(compressed=False)
            shared_key = shared_point_uncompressed[1:33]

            # AES-256-CBC encryption
            iv = secrets.token_bytes(16)
            cipher = AES.new(shared_key, AES.MODE_CBC, iv)
            encrypted = cipher.encrypt(pad(message.encode(), AES.block_size))
            content = base64.b64encode(encrypted).decode() + "?iv=" + base64.b64encode(iv).decode()

            # Build event
            created_at = int(time.time())
            tags = [["p", target_pubkey]]
            serialized = json.dumps(
                [0, pubkey_hex, created_at, 4, tags, content], separators=(",", ":")
            )
            event_id = hashlib.sha256(serialized.encode()).hexdigest()
            sig = sk.sign_schnorr(bytes.fromhex(event_id)).hex()

            event = {
                "id": event_id,
                "pubkey": pubkey_hex,
                "created_at": created_at,
                "kind": 4,
                "tags": tags,
                "content": content,
                "sig": sig,
            }

            # Publish
            success_count = 0
            for relay in self.config.nostr_relays[:2]:
                try:
                    async with websockets.connect(relay, close_timeout=5) as ws:
                        await ws.send(json.dumps(["EVENT", event]))
                        response = await asyncio.wait_for(ws.recv(), timeout=5)
                        if "OK" in response or "true" in response.lower():
                            success_count += 1
                except Exception:
                    continue

            if success_count > 0:
                return True, f"Published to {success_count} relays"
            return False, "Failed all relays"

        except Exception as e:
            return False, str(e)[:100]

    def _send_nostr(self, message: str) -> tuple:
        """Sync wrapper for Nostr"""
        if WS_AVAILABLE:
            try:
                return asyncio.run(self._send_nostr_async(message))
            except Exception as e:
                return False, f"Async error: {e}"
        return False, "websockets not available"

    def _log_notification(self, notification: Notification, results: Dict[str, Any]):
        """Log notification to file"""
        log_entry = {
            "timestamp": notification.timestamp.isoformat(),
            "title": notification.title,
            "level": notification.level.value,
            "channels": [c.value for c in notification.channels],
            "results": results,
            "data": notification.data,
        }

        # Append to log file
        logs = []
        if self.log_file.exists():
            try:
                with open(self.log_file) as f:
                    logs = json.load(f)
            except Exception:
                logs = []

        logs.append(log_entry)

        # Keep last 100 entries
        logs = logs[-100:]

        with open(self.log_file, "w") as f:
            json.dump(logs, f, indent=2)

    # ========== Public API ==========

    def send(self, notification: Notification) -> Dict[str, Any]:
        """Send a notification to all specified channels"""
        results = {}

        for channel in notification.channels:
            if not self.should_send(channel):
                results[channel.value] = {"success": False, "reason": "Rate limited"}
                continue

            if channel == NotificationChannel.WHATSAPP:
                success, details = self._send_whatsapp(notification.message)
            elif channel == NotificationChannel.SLACK:
                success, details = self._send_slack(notification.message)
            elif channel == NotificationChannel.NOSTR:
                success, details = self._send_nostr(notification.message)
            elif channel == NotificationChannel.LOG:
                success, details = True, "Logged"
            else:
                success, details = False, "Unknown channel"

            results[channel.value] = {"success": success, "details": details}

            if success:
                self._record_sent(channel)

        self._log_notification(notification, results)
        return results

    def send_simple(
        self,
        message: str,
        level: AlertLevel = AlertLevel.INFO,
        channels: Optional[List[NotificationChannel]] = None,
    ) -> Dict[str, Any]:
        """Simple notification helper"""
        if channels is None:
            channels = [NotificationChannel.WHATSAPP, NotificationChannel.LOG]

        notification = Notification(
            title=f"{level.value.upper()} Alert", message=message, level=level, channels=channels
        )
        return self.send(notification)

    # ========== Job-Specific Notifications ==========

    def notify_job_complete(
        self, job_id: str, job_type: str, reward_sats: int, is_real: bool, duration_ms: int
    ) -> Dict[str, Any]:
        """Notify when a job completes"""
        emoji = "✅" if is_real else "📋"
        mode = "REAL" if is_real else "SIM"

        message = f"""{emoji} Job Complete [{mode}]
ID: {job_id}
Type: {job_type}
Reward: {reward_sats:,} sats
Duration: {duration_ms}ms"""

        # Determine alert level
        level = AlertLevel.INFO
        channels = [NotificationChannel.LOG]

        if is_real and reward_sats >= self.config.critical_sats_threshold:
            level = AlertLevel.WARNING
            channels = [NotificationChannel.WHATSAPP, NotificationChannel.LOG]

        return self.send_simple(message, level, channels)

    def notify_security_event(self, event_type: str, details: Dict[str, Any]) -> Dict[str, Any]:
        """Notify on security events"""
        if not self.config.security_alert_enabled:
            return {"skipped": "Security alerts disabled"}

        message = f"""🛡️ Security Event: {event_type}
Time: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}
Details: {json.dumps(details, indent=2)[:200]}"""

        return self.send_simple(
            message, AlertLevel.WARNING, [NotificationChannel.WHATSAPP, NotificationChannel.LOG]
        )

    def notify_payment_processed(
        self, job_id: str, amount_sats: int, payment_type: str, status: str
    ) -> Dict[str, Any]:
        """Notify when a payment is processed"""
        emoji = "💰" if status == "completed" else "⏳"

        message = f"""{emoji} Payment {status.title()}
Job: {job_id}
Amount: {amount_sats:,} sats
Type: {payment_type}"""

        level = AlertLevel.INFO
        channels = [NotificationChannel.LOG]

        if amount_sats >= self.config.critical_sats_threshold:
            level = AlertLevel.WARNING
            channels = [NotificationChannel.WHATSAPP, NotificationChannel.LOG]

        return self.send_simple(message, level, channels)

    def notify_escrow_created(
        self, escrow_id: str, job_id: str, amount_sats: int, hold_hours: int
    ) -> Dict[str, Any]:
        """Notify when escrow is created"""
        message = f"""🔒 Escrow Created
ID: {escrow_id}
Job: {job_id}
Amount: {amount_sats:,} sats
Hold Period: {hold_hours}h"""

        return self.send_simple(
            message, AlertLevel.WARNING, [NotificationChannel.WHATSAPP, NotificationChannel.LOG]
        )

    def notify_system_status(self, stats: Dict[str, Any]) -> Dict[str, Any]:
        """Send system status update"""
        uptime = stats.get("uptime_hours", 0)
        success_rate = stats.get("success_rate", 0)
        total_sats = stats.get("total_revenue", 0) + stats.get("total_data_value", 0)

        message = f"""⚡ Chainlink Jobs Status
🕐 {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}

📊 Performance:
• Uptime: {uptime:.1f}h
• Success Rate: {success_rate:.1f}%
• Completed: {stats.get('total_completed', 0)}
• Failed: {stats.get('total_failed', 0)}

💰 Earnings: {total_sats:,} sats"""

        return self.send_simple(
            message,
            AlertLevel.INFO,
            [NotificationChannel.WHATSAPP, NotificationChannel.NOSTR, NotificationChannel.LOG],
        )

    def notify_error(
        self, error_type: str, error_message: str, job_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Notify on errors"""
        message = f"""❌ Error: {error_type}
{f'Job: {job_id}' if job_id else ''}
Message: {error_message[:200]}
Time: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}"""

        return self.send_simple(
            message, AlertLevel.ERROR, [NotificationChannel.WHATSAPP, NotificationChannel.LOG]
        )

    def notify_critical(self, event: str, details: str) -> Dict[str, Any]:
        """Notify on critical events - sends to all channels"""
        message = f"""🚨 CRITICAL: {event}
Time: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}
Details: {details}

Immediate attention required!"""

        return self.send(
            Notification(
                title=f"CRITICAL: {event}",
                message=message,
                level=AlertLevel.CRITICAL,
                channels=[
                    NotificationChannel.WHATSAPP,
                    NotificationChannel.SLACK,
                    NotificationChannel.NOSTR,
                    NotificationChannel.LOG,
                ],
            )
        )


# ========== Singleton Pattern ==========

_notification_manager: Optional[NotificationManager] = None


def get_notification_manager(config: Optional[NotificationConfig] = None) -> NotificationManager:
    """Get or create the notification manager singleton"""
    global _notification_manager
    if _notification_manager is None:
        _notification_manager = NotificationManager(config)
    return _notification_manager


# ========== Test ==========

if __name__ == "__main__":
    print("=" * 70)
    print("PHASE 6: ENHANCED NOTIFICATION SYSTEM TEST")
    print("=" * 70)

    manager = get_notification_manager()

    # Test 1: Simple notification
    print("\n--- Test 1: Simple Notification (Log only) ---")
    result = manager.send_simple(
        "Test notification from Phase 6 system", AlertLevel.INFO, [NotificationChannel.LOG]
    )
    print(f"Result: {result}")

    # Test 2: Job completion notification
    print("\n--- Test 2: Job Completion Notification ---")
    result = manager.notify_job_complete(
        job_id="job_test_001",
        job_type="oracle_feed",
        reward_sats=50,
        is_real=True,
        duration_ms=1500,
    )
    print(f"Result: {result}")

    # Test 3: Security event
    print("\n--- Test 3: Security Event Notification ---")
    result = manager.notify_security_event(
        "rate_limit_warning", {"jobs_this_hour": 95, "limit": 100}
    )
    print(f"Result: {result}")

    # Test 4: Escrow created
    print("\n--- Test 4: Escrow Created Notification ---")
    result = manager.notify_escrow_created(
        escrow_id="escrow_001", job_id="job_big_001", amount_sats=5000, hold_hours=24
    )
    print(f"Result: {result}")

    # Test 5: System status (sends to WhatsApp)
    print("\n--- Test 5: System Status Notification ---")
    test_stats = {
        "uptime_hours": 48.5,
        "success_rate": 98.7,
        "total_completed": 524,
        "total_failed": 3,
        "total_revenue": 270,
        "total_data_value": 12250,
    }
    result = manager.notify_system_status(test_stats)
    print(f"Result: {result}")

    # Verify log file
    print("\n--- Verification ---")
    log_file = manager.log_file
    if log_file.exists():
        with open(log_file) as f:
            logs = json.load(f)
        print(f"Log entries: {len(logs)}")
        print(f"Latest entry: {logs[-1]['title']}")

    print("\n" + "=" * 70)
    print("PHASE 6 NOTIFICATION SYSTEM TEST COMPLETE")
    print("=" * 70)
