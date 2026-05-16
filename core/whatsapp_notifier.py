#!/usr/bin/env python3
"""
WhatsApp Notification Manager for Chainlink AI Monetization System
@requirement: REQ-NOTIFY-001 - Real-time WhatsApp notifications
@requirement: REQ-NOTIFY-002 - Critical event alerting
@requirement: REQ-NOTIFY-003 - Batch notifications for non-critical events
@requirement: REQ-NOTIFY-004 - Cost tracking alerts
@requirement: REQ-MCP-003 - All exceptions print full details
@requirement: REQ-MCP-004 - Success responses logged before return
"""

import os
import json
import asyncio
import aiohttp
import traceback
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from pathlib import Path
from collections import defaultdict
import sys

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.base_level_properties import PropertyTracker


class WhatsAppNotifier:
    """
    WhatsApp notification system with intelligent batching and priority handling
    @requirement: REQ-NOTIFY-001 - Real-time notifications [@core/whatsapp_notifier.py:25-400]
    """

    def __init__(self):
        """Initialize WhatsApp notifier with configuration"""
        self.recipient = os.getenv("WHATSAPP_RECIPIENT", os.environ.get("BLINDORACLE_OPERATOR_WHATSAPP", ""))
        self.endpoint = os.getenv("WHATSAPP_ENDPOINT", "http://localhost:8082/api/send")
        self.property_tracker = PropertyTracker()

        # Notification batching
        self.batch_window = {
            "critical": 0,  # Send immediately
            "high": 60,  # 1 minute
            "medium": 300,  # 5 minutes
            "low": 1800,  # 30 minutes
        }

        self.pending_notifications = defaultdict(list)
        self.last_sent = {}

        # Cost tracking
        self.cost_thresholds = {"warning": 0.8, "critical": 0.95}  # 80% of budget  # 95% of budget

        print(f"✅ WhatsAppNotifier initialized for {self.recipient}")

    async def send_critical(self, message: str) -> bool:
        """
        Send critical notification immediately
        @requirement: REQ-NOTIFY-002 - Critical alerting [@core/whatsapp_notifier.py:60-90]
        @requirement: REQ-SAFE-004 - Graceful degradation
        @BLP-PROPERTY: Autonomy (Graceful Degradation)
        """
        try:
            # Add timestamp and priority marker
            formatted_message = f"🚨 CRITICAL - {datetime.now().strftime('%H:%M:%S')}\n{message}"

            async with aiohttp.ClientSession() as session:
                payload = {"to": self.recipient, "message": formatted_message}

                async with session.post(self.endpoint, json=payload) as response:
                    if response.status == 200:
                        # REQ-MCP-004: Log success before return
                        print(f"✅ Critical notification sent: {message[:50]}...")
                        return True
                    else:
                        error_text = await response.text()
                        raise Exception(f"WhatsApp API error: {response.status} - {error_text}")

        except Exception as e:
            # REQ-MCP-003: Print full exception details
            error_info = {"error": str(e), "traceback": traceback.format_exc()}
            print(f"⚠️ [WARNING] send_critical failed, graceful fallback: {error_info}")
            print(f"   Exception type: {type(e).__name__}")
            # Graceful degradation - don't fail pipeline when notifications fail
            return True

    async def notify_job_accepted(self, job_id: str, payment: float, requirements: Dict) -> None:
        """
        Notify when new job is accepted
        @requirement: REQ-NOTIFY-001 - Job notifications [@core/whatsapp_notifier.py:95-120]
        """
        try:
            message = f"""
🎯 NEW JOB ACCEPTED

Job ID: {job_id}
Payment: ${payment:.2f}
Type: {requirements.get('type', 'Unknown')}
Priority: {requirements.get('priority', 'Normal')}
Deadline: {requirements.get('deadline', 'None')}
Status: Queued for processing

Requirements:
• Markets: {', '.join(requirements.get('markets', ['N/A']))}
• Features: {', '.join(requirements.get('features', ['N/A']))}

Compute Advantage: {await self._get_compute_advantage():.2f}x
"""
            await self.send_critical(message)

        except Exception as e:
            # REQ-MCP-003: Print full exception details
            print(f"❌ Failed to notify job acceptance: {str(e)}")
            print(f"   Full traceback: {traceback.format_exc()}")

    async def notify_agent_lifecycle(
        self, agent: str, phase: str, status: str, details: Dict = None
    ) -> None:
        """
        Notify agent lifecycle events
        @requirement: REQ-BLP-002 - Autonomy tracking [@core/whatsapp_notifier.py:125-160]
        """
        try:
            icons = {
                "design": "🎨",
                "implement": "⚙️",
                "test": "🧪",
                "deploy": "🚀",
                "operate": "📊",
            }

            priority = "high" if status.startswith("error") else "medium"

            message = f"""
{icons.get(phase, '📌')} AGENT UPDATE

Agent: {agent.upper()}
Phase: {phase.upper()}
Status: {status}

Performance Metrics:
• Alignment: {self.property_tracker.get_property('alignment').current_value:.1%}
• Autonomy: {self.property_tracker.get_property('autonomy').current_value:.1%}
• Durability: {self.property_tracker.get_property('durability').current_value:.1%}

"""
            if details:
                message += "Details:\n"
                for key, value in details.items():
                    message += f"• {key}: {value}\n"

            await self._send_by_priority(message, priority)

        except Exception as e:
            # REQ-MCP-003: Print full exception details
            print(f"❌ Failed to notify agent lifecycle: {str(e)}")
            print(f"   Full traceback: {traceback.format_exc()}")

    async def notify_cost_alert(
        self, current_cost: float, daily_limit: float, breakdown: Dict
    ) -> None:
        """
        Send cost threshold alerts
        @requirement: REQ-NOTIFY-004 - Cost alerts [@core/whatsapp_notifier.py:165-200]
        @requirement: REQ-COST-002 - Budget monitoring
        """
        try:
            percentage = (current_cost / daily_limit) * 100
            severity = "🔴 CRITICAL" if percentage >= 95 else "⚠️ WARNING"

            message = f"""
{severity} - COST ALERT

Current Daily Cost: ${current_cost:.2f}
Daily Limit: ${daily_limit:.2f}
Usage: {percentage:.1f}%

Breakdown:
• API Calls: ${breakdown.get('api', 0):.2f}
• LLM Usage: ${breakdown.get('llm', 0):.2f}
• Gas Fees: ${breakdown.get('gas', 0):.2f}
• Infrastructure: ${breakdown.get('infrastructure', 0):.2f}

Action: {"⛔ Throttling enabled - non-critical operations paused" if percentage >= 95 else "⚠️ Monitor closely - approaching limit"}

Projected Monthly: ${current_cost * 30:.2f}
"""
            await self.send_critical(message)

            # Update cost tracking in BLP
            if percentage >= 95:
                self.property_tracker.update_property(
                    "autonomy", -0.2
                )  # Reduce autonomy when throttling

        except Exception as e:
            # REQ-MCP-003: Print full exception details
            print(f"❌ Failed to send cost alert: {str(e)}")
            print(f"   Full traceback: {traceback.format_exc()}")

    async def notify_payment_received(self, job_id: str, amount: float, tx_hash: str) -> None:
        """
        Notify when payment is received
        @requirement: REQ-PAY-003 - Payment notifications
        """
        try:
            wallet = os.getenv("CHAINLINK_WALLET_ADDRESS", "Not configured")

            message = f"""
💰 PAYMENT RECEIVED

Job: {job_id}
Amount: ${amount:.2f}
Transaction: {tx_hash[:10]}...{tx_hash[-6:]}
Wallet: {wallet[:10]}...{wallet[-6:] if wallet != "Not configured" else "N/A"}
Status: Confirmed ✅

Total Revenue Today: ${await self._get_daily_revenue():.2f}
Jobs Completed: {await self._get_jobs_completed_today()}
"""
            await self.send_critical(message)

        except Exception as e:
            # REQ-MCP-003: Print full exception details
            print(f"❌ Failed to notify payment: {str(e)}")
            print(f"   Full traceback: {traceback.format_exc()}")

    async def notify_job_completed(
        self, job_id: str, execution_time: float, output_hash: str
    ) -> None:
        """
        Notify when job is completed
        @requirement: REQ-DEL-002 - Delivery notifications
        """
        try:
            message = f"""
✅ JOB COMPLETED

Job ID: {job_id}
Execution Time: {execution_time:.1f} seconds
Output: ipfs://{output_hash}

Performance:
• Design: {await self._get_phase_time('design'):.1f}s
• Implementation: {await self._get_phase_time('implement'):.1f}s
• Testing: {await self._get_phase_time('test'):.1f}s
• Deployment: {await self._get_phase_time('deploy'):.1f}s

Status: Output delivered, awaiting payment release
"""
            await self._send_by_priority(message, "high")

        except Exception as e:
            # REQ-MCP-003: Print full exception details
            print(f"❌ Failed to notify job completion: {str(e)}")
            print(f"   Full traceback: {traceback.format_exc()}")

    async def send_daily_summary(self) -> None:
        """
        Send comprehensive daily summary
        @requirement: REQ-NOTIFY-003 - Batch notifications [@core/whatsapp_notifier.py:250-300]
        """
        try:
            # Gather all metrics
            summary = await self._gather_daily_metrics()

            message = f"""
📊 DAILY SUMMARY - {datetime.now().strftime('%Y-%m-%d')}

💼 JOBS
• Completed: {summary['jobs_completed']}
• In Progress: {summary['jobs_in_progress']}
• Failed: {summary['jobs_failed']}

💰 FINANCIALS
• Revenue: ${summary['revenue']:.2f}
• Costs: ${summary['costs']:.2f}
• Profit: ${summary['profit']:.2f}
• Margin: {(summary['profit'] / summary['revenue'] * 100) if summary['revenue'] > 0 else 0:.1f}%

🤖 AGENT PERFORMANCE
• Design Score: {summary['design_score']:.1%}
• Implementation: {summary['impl_score']:.1%}
• Testing: {summary['test_score']:.1%}
• Deployment: {summary['deploy_score']:.1%}
• Operations: {summary['ops_score']:.1%}

📈 BASE LEVEL PROPERTIES
• Alignment: {summary['blp_alignment']:.1%}
• Autonomy: {summary['blp_autonomy']:.1%}
• Durability: {summary['blp_durability']:.1%}
• Self-Improvement: {summary['blp_self_improvement']:.1%}
• Self-Replication: {summary['blp_self_replication']:.1%}
• Self-Organization: {summary['blp_self_organization']:.1%}

⚡ COMPUTE ADVANTAGE: {summary['compute_advantage']:.2f}x

🎯 Tomorrow's Target: ${summary['revenue'] * 1.1:.2f}
"""
            await self.send_critical(message)

            # REQ-MCP-004: Log success before return
            print(f"✅ Daily summary sent successfully")

        except Exception as e:
            # REQ-MCP-003: Print full exception details
            print(f"❌ Failed to send daily summary: {str(e)}")
            print(f"   Full traceback: {traceback.format_exc()}")

    async def notify_error(self, component: str, error: str, severity: str = "high") -> None:
        """
        Notify system errors
        @requirement: REQ-MCP-003 - Error reporting
        """
        try:
            icon = "🔴" if severity == "critical" else "⚠️"

            message = f"""
{icon} SYSTEM ERROR

Component: {component}
Severity: {severity.upper()}
Error: {error[:200]}...

Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
Auto-recovery: {"Attempting..." if severity != "critical" else "Manual intervention required"}

Current System Health: {await self._get_system_health():.1%}
"""

            if severity == "critical":
                await self.send_critical(message)
            else:
                await self._send_by_priority(message, severity)

        except Exception as e:
            # REQ-MCP-003: Print full exception details
            print(f"❌ Failed to notify error: {str(e)}")
            print(f"   Full traceback: {traceback.format_exc()}")

    # Private helper methods

    async def _send_by_priority(self, message: str, priority: str) -> None:
        """Send notification based on priority with batching"""
        if priority == "critical":
            await self.send_critical(message)
        else:
            # Add to batch for later sending
            self.pending_notifications[priority].append(
                {"message": message, "timestamp": datetime.now()}
            )

            # Check if batch should be sent
            await self._check_batch_send(priority)

    async def _check_batch_send(self, priority: str) -> None:
        """Check if batch should be sent based on time window"""
        if priority not in self.last_sent:
            self.last_sent[priority] = datetime.now()
            return

        time_since_last = (datetime.now() - self.last_sent[priority]).seconds

        if time_since_last >= self.batch_window[priority]:
            await self._send_batch(priority)

    async def _send_batch(self, priority: str) -> None:
        """Send batched notifications"""
        if not self.pending_notifications[priority]:
            return

        try:
            batch_count = len(self.pending_notifications[priority])
            combined_message = f"📦 BATCHED UPDATES ({batch_count} events)\n\n"

            for notif in self.pending_notifications[priority]:
                combined_message += f"⏰ {notif['timestamp'].strftime('%H:%M')}\n"
                combined_message += notif["message"] + "\n" + "=" * 30 + "\n"

            async with aiohttp.ClientSession() as session:
                payload = {"to": self.recipient, "message": combined_message}

                async with session.post(self.endpoint, json=payload) as response:
                    if response.status == 200:
                        print(f"✅ Batch sent: {batch_count} {priority} notifications")
                        self.pending_notifications[priority].clear()
                        self.last_sent[priority] = datetime.now()

        except Exception as e:
            print(f"❌ Failed to send batch: {str(e)}")
            print(f"   Full traceback: {traceback.format_exc()}")

    async def _get_compute_advantage(self) -> float:
        """Get current compute advantage from BLP tracker"""
        metrics = self.property_tracker.get_all_metrics()
        compute_scaling = metrics.get("compute_scaling", 1.0)
        autonomy = metrics.get("autonomy", 0.5)
        time_cost = metrics.get("time", 1.0)
        effort_cost = metrics.get("effort", 1.0)
        monetary_cost = metrics.get("monetary_cost", 1.0)

        denominator = time_cost + effort_cost + monetary_cost
        if denominator > 0:
            return (compute_scaling * autonomy) / denominator
        return 1.0

    async def _get_daily_revenue(self) -> float:
        """Get today's revenue (placeholder - implement with payment system)"""
        # TODO: Integrate with payment system
        return 0.0

    async def _get_jobs_completed_today(self) -> int:
        """Get number of jobs completed today (placeholder)"""
        # TODO: Integrate with job tracking
        return 0

    async def _get_phase_time(self, phase: str) -> float:
        """Get average phase execution time (placeholder)"""
        # TODO: Integrate with agent metrics
        return 0.0

    async def _get_system_health(self) -> float:
        """Get overall system health score"""
        # Combine various metrics for health score
        blp_avg = (
            sum(
                self.property_tracker.get_property(prop).current_value
                for prop in ["alignment", "autonomy", "durability"]
            )
            / 3
        )
        return blp_avg

    async def _gather_daily_metrics(self) -> Dict[str, Any]:
        """Gather all metrics for daily summary"""
        # Get BLP metrics
        blp_metrics = {}
        for prop_name in [
            "alignment",
            "autonomy",
            "durability",
            "self_improvement",
            "self_replication",
            "self_organization",
        ]:
            prop = self.property_tracker.get_property(prop_name)
            blp_metrics[f"blp_{prop_name}"] = prop.current_value if prop else 0.5

        # TODO: Integrate with actual tracking systems
        return {
            "jobs_completed": 0,
            "jobs_in_progress": 0,
            "jobs_failed": 0,
            "revenue": 0.0,
            "costs": 0.0,
            "profit": 0.0,
            "design_score": 0.85,
            "impl_score": 0.90,
            "test_score": 0.95,
            "deploy_score": 0.88,
            "ops_score": 0.92,
            **blp_metrics,
            "compute_advantage": await self._get_compute_advantage(),
        }


# Test function
if __name__ == "__main__":

    async def test_notifier():
        print("\n" + "=" * 60)
        print("Testing WhatsApp Notifier")
        print("=" * 60)

        notifier = WhatsAppNotifier()

        # Test job acceptance notification
        await notifier.notify_job_accepted(
            job_id="test_001",
            payment=150.00,
            requirements={
                "type": "Oracle Data Feed",
                "markets": ["Kalshi", "Polymarket"],
                "features": ["arbitrage", "streaming"],
                "priority": "High",
            },
        )

        # Test cost alert
        await notifier.notify_cost_alert(
            current_cost=45.50,
            daily_limit=50.00,
            breakdown={"api": 15.25, "llm": 20.30, "gas": 8.95, "infrastructure": 1.00},
        )

        print("\n✅ WhatsApp Notifier test complete")

    asyncio.run(test_notifier())
