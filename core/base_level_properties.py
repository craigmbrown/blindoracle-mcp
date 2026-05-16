#!/usr/bin/env python3
"""
Base Level Properties Tracking System
@requirement: REQ-BLP-001 through REQ-BLP-006 - All property tracking
@requirement: REQ-CA-001 through REQ-CA-004 - Compute advantage calculation

This module implements the 6 Base Level Properties of Agentic Agents:
1. Alignment - Understanding domain-specific problems (reduces effort)
2. Autonomy - Operating independently (reduces time)
3. Durability - Continuous operation (increases compute scaling)
4. Self-Improvement - Learning and refining (reduces time/effort)
5. Self-Replication - Creating copies/variants (increases compute scaling)
6. Self-Organization - Restructuring for efficiency (reduces all costs)
"""

import json
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass, field, asdict
from pathlib import Path


@dataclass
class PropertyMetrics:
    """Metrics for a single Base Level Property"""

    name: str
    current_value: float = 0.5  # 0.0 to 1.0 scale
    target_value: float = 0.8
    history: List[Tuple[datetime, float]] = field(default_factory=list)
    impact_on_compute: Dict[str, float] = field(default_factory=dict)

    def update(self, value: float) -> None:
        """Update property value and track history"""
        self.current_value = max(0.0, min(1.0, value))
        self.history.append((datetime.now(), self.current_value))
        # Keep only last 100 entries
        if len(self.history) > 100:
            self.history = self.history[-100:]


class PropertyTracker:
    """
    REQ-BLP-001 through REQ-BLP-006: Track all Base Level Properties
    @requirement: REQ-BLP-001 - Alignment tracking (reduces effort) [@core/base_level_properties.py:30-60]
    @requirement: REQ-BLP-002 - Autonomy measurement (reduces time) [@core/base_level_properties.py:65-95]
    @requirement: REQ-BLP-003 - Durability monitoring (continuous) [@core/base_level_properties.py:100-130]
    @requirement: REQ-BLP-004 - Self-improvement tracking [@core/base_level_properties.py:135-165]
    @requirement: REQ-BLP-005 - Self-replication metrics [@core/base_level_properties.py:170-200]
    @requirement: REQ-BLP-006 - Self-organization measurement [@core/base_level_properties.py:205-235]
    """

    def __init__(self, storage_path: Optional[Path] = None):
        self.storage_path = storage_path or Path("/home/craigmbrown/Project/logs/blp_metrics.json")
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)

        # Initialize all 6 Base Level Properties
        self.properties = {
            "alignment": PropertyMetrics(
                name="alignment", impact_on_compute={"effort_reduction": 0.4, "time_reduction": 0.2}
            ),
            "autonomy": PropertyMetrics(
                name="autonomy", impact_on_compute={"effort_reduction": 0.6, "time_reduction": 0.4}
            ),
            "durability": PropertyMetrics(
                name="durability", impact_on_compute={"compute_boost": 0.3, "cost_increase": 0.1}
            ),
            "self_improvement": PropertyMetrics(
                name="self_improvement",
                impact_on_compute={
                    "compute_boost": 0.4,
                    "effort_reduction": 0.3,
                    "time_reduction": 0.2,
                },
            ),
            "self_replication": PropertyMetrics(
                name="self_replication",
                impact_on_compute={"compute_boost": 0.6, "cost_increase": 0.3},
            ),
            "self_organization": PropertyMetrics(
                name="self_organization",
                impact_on_compute={
                    "effort_reduction": 0.4,
                    "time_reduction": 0.3,
                    "compute_boost": 0.2,
                },
            ),
        }

        # Load existing metrics if available
        self.load_metrics()

        print(f"✅ PropertyTracker initialized with {len(self.properties)} properties")

    def update_property(self, property_name: str, delta: float, source: str = "unknown") -> None:
        """
        Update a property value with required source attribution.

        Args:
            property_name: Name of the BLP property to update.
            delta: Value change (positive or negative).
            source: Required attribution for the update (e.g., "settlement_engine",
                    "accuracy_tracker", "uptime_monitor"). Updates without a meaningful
                    source are logged as warnings.

        @requirement: REQ-CA-002 - Real-time metric collection [@core/base_level_properties.py:285-320]
        """
        if property_name not in self.properties:
            print(f"⚠️ Unknown property: {property_name}")
            return

        if source == "unknown":
            print(f"⚠️ BLP update for {property_name} has no source attribution — "
                  "this may indicate an unvalidated metric update")

        # Clamp delta to prevent unrealistic jumps (max ±0.1 per update)
        MAX_DELTA = 0.1
        if abs(delta) > MAX_DELTA:
            print(f"⚠️ BLP delta {delta:.3f} for {property_name} exceeds max {MAX_DELTA} — clamping")
            delta = max(-MAX_DELTA, min(MAX_DELTA, delta))

        prop = self.properties[property_name]
        new_value = max(0.0, min(1.0, prop.current_value + delta))  # Clamp to [0, 1]
        prop.update(new_value)

        # Save metrics after update
        self.save_metrics()

        print(f"📊 {property_name}: {prop.current_value:.3f} (target: {prop.target_value}) [source: {source}]")

    def get_property(self, property_name: str) -> Optional[PropertyMetrics]:
        """Get metrics for a specific property"""
        return self.properties.get(property_name)

    def get_all_metrics(self) -> Dict[str, float]:
        """Get current values for all properties"""
        metrics = {name: prop.current_value for name, prop in self.properties.items()}

        # Add derived metrics for compute advantage calculation
        metrics.update(
            {
                "compute_scaling": 1.0
                + sum(
                    prop.current_value * prop.impact_on_compute.get("compute_boost", 0)
                    for prop in self.properties.values()
                ),
                "autonomy": self.properties["autonomy"].current_value,
                "time": 1.0,  # Base time cost
                "effort": 1.0,  # Base effort cost
                "monetary_cost": 1.0,  # Base monetary cost
            }
        )

        return metrics

    def save_metrics(self) -> None:
        """Save metrics to disk"""
        try:
            data = {"timestamp": datetime.now().isoformat(), "properties": {}}

            for name, prop in self.properties.items():
                data["properties"][name] = {
                    "current_value": prop.current_value,
                    "target_value": prop.target_value,
                    "impact_on_compute": prop.impact_on_compute,
                    "recent_history": [
                        {"timestamp": ts.isoformat(), "value": val}
                        for ts, val in prop.history[-10:]  # Save last 10 entries
                    ],
                }

            with open(self.storage_path, "w") as f:
                json.dump(data, f, indent=2)

        except Exception as e:
            print(f"⚠️ Failed to save metrics: {str(e)}")

    def load_metrics(self) -> None:
        """Load metrics from disk"""
        try:
            if self.storage_path.exists():
                with open(self.storage_path, "r") as f:
                    data = json.load(f)

                for name, prop_data in data.get("properties", {}).items():
                    if name in self.properties:
                        self.properties[name].current_value = prop_data.get("current_value", 0.5)
                        self.properties[name].target_value = prop_data.get("target_value", 0.8)

                print(f"📂 Loaded metrics from {self.storage_path}")

        except Exception as e:
            print(f"⚠️ Failed to load metrics: {str(e)}")


class ComputeAdvantageOptimizer:
    """
    REQ-CA-001: Compute Advantage calculation and optimization
    Formula: CA = (Compute_Scaling * Autonomy) / (Time + Effort + Monetary_Cost)

    @requirement: REQ-CA-001 - Compute advantage formula [@core/base_level_properties.py:240-280]
    @requirement: REQ-CA-003 - Property impact calculation [@core/base_level_properties.py:325-360]
    @requirement: REQ-CA-004 - Optimization suggestions [@core/base_level_properties.py:365-400]
    """

    def __init__(self):
        self.target_advantage = 10.0  # 10x improvement target
        self.calculation_history = []

    def calculate_system_advantage(self, metrics: Dict[str, float]) -> Dict[str, float]:
        """
        Calculate overall Compute Advantage
        @requirement: REQ-CA-001 - Formula implementation
        """
        try:
            # Base metrics
            compute_scaling = metrics.get("compute_scaling", 1.0)
            autonomy = metrics.get("autonomy", 0.5)
            time_cost = metrics.get("time", 1.0)
            effort_cost = metrics.get("effort", 1.0)
            monetary_cost = metrics.get("monetary_cost", 1.0)

            # REQ-CA-003: Apply property impacts [@core/base_level_properties.py:325-360]
            # Alignment reduces effort and time
            alignment_score = metrics.get("alignment", 0.5)
            effort_cost *= 1 - 0.4 * alignment_score
            time_cost *= 1 - 0.2 * alignment_score

            # Autonomy reduces effort and time
            autonomy_score = metrics.get("autonomy", 0.5)
            effort_cost *= 1 - 0.6 * autonomy_score
            time_cost *= 1 - 0.4 * autonomy_score

            # Durability increases compute but adds cost
            durability_score = metrics.get("durability", 0.5)
            compute_scaling *= 1 + 0.3 * durability_score
            monetary_cost *= 1 + 0.1 * durability_score

            # Self-improvement boosts everything
            improvement_score = metrics.get("self_improvement", 0.5)
            compute_scaling *= 1 + 0.4 * improvement_score
            effort_cost *= 1 - 0.3 * improvement_score
            time_cost *= 1 - 0.2 * improvement_score

            # Self-replication scales compute but costs more
            replication_score = metrics.get("self_replication", 0.5)
            compute_scaling *= 1 + 0.6 * replication_score
            monetary_cost *= 1 + 0.3 * replication_score

            # Self-organization optimizes everything
            organization_score = metrics.get("self_organization", 0.5)
            compute_scaling *= 1 + 0.2 * organization_score
            effort_cost *= 1 - 0.4 * organization_score
            time_cost *= 1 - 0.3 * organization_score

            # Calculate final advantage
            numerator = compute_scaling * autonomy
            denominator = time_cost + effort_cost + monetary_cost

            if denominator > 0:
                advantage = numerator / denominator
            else:
                advantage = 0.0

            result = {
                "compute_advantage": advantage,
                "compute_scaling": compute_scaling,
                "autonomy": autonomy,
                "time_cost": time_cost,
                "effort_cost": effort_cost,
                "monetary_cost": monetary_cost,
                "target_advantage": self.target_advantage,
                "performance_ratio": advantage / self.target_advantage,
                "timestamp": datetime.now().isoformat(),
            }

            # Track history
            self.calculation_history.append(result)
            if len(self.calculation_history) > 100:
                self.calculation_history = self.calculation_history[-100:]

            print(
                f"📈 Compute Advantage: {advantage:.3f} / {self.target_advantage:.1f} target ({result['performance_ratio']*100:.1f}%)"
            )

            return result

        except Exception as e:
            print(f"❌ Error calculating compute advantage: {str(e)}")
            import traceback

            print(f"   Traceback: {traceback.format_exc()}")
            return {"compute_advantage": 0.0, "error": str(e)}

    def get_optimization_suggestions(self, metrics: Dict[str, float]) -> List[Dict[str, str]]:
        """
        REQ-CA-004: Generate optimization suggestions [@core/base_level_properties.py:365-400]
        """
        suggestions = []

        # Check each property against target
        if metrics.get("alignment", 0) < 0.7:
            suggestions.append(
                {
                    "property": "alignment",
                    "current": f"{metrics.get('alignment', 0):.2f}",
                    "target": "0.70",
                    "action": "Improve domain understanding through market analysis",
                    "impact": "40% effort reduction, 20% time reduction",
                }
            )

        if metrics.get("autonomy", 0) < 0.8:
            suggestions.append(
                {
                    "property": "autonomy",
                    "current": f"{metrics.get('autonomy', 0):.2f}",
                    "target": "0.80",
                    "action": "Reduce human intervention requirements",
                    "impact": "60% effort reduction, 40% time reduction",
                }
            )

        if metrics.get("durability", 0) < 0.95:
            suggestions.append(
                {
                    "property": "durability",
                    "current": f"{metrics.get('durability', 0):.2f}",
                    "target": "0.95",
                    "action": "Implement fault tolerance and auto-recovery",
                    "impact": "30% compute scaling increase",
                }
            )

        if metrics.get("self_improvement", 0) < 0.4:
            suggestions.append(
                {
                    "property": "self_improvement",
                    "current": f"{metrics.get('self_improvement', 0):.2f}",
                    "target": "0.40",
                    "action": "Add learning from market outcomes",
                    "impact": "40% compute boost, 30% effort reduction",
                }
            )

        if metrics.get("self_replication", 0) < 0.3:
            suggestions.append(
                {
                    "property": "self_replication",
                    "current": f"{metrics.get('self_replication', 0):.2f}",
                    "target": "0.30",
                    "action": "Enable parallel market analysis instances",
                    "impact": "60% compute scaling increase",
                }
            )

        if metrics.get("self_organization", 0) < 0.5:
            suggestions.append(
                {
                    "property": "self_organization",
                    "current": f"{metrics.get('self_organization', 0):.2f}",
                    "target": "0.50",
                    "action": "Optimize workflow and resource allocation",
                    "impact": "40% effort reduction, 30% time reduction",
                }
            )

        # Overall compute advantage suggestion
        current_ca = metrics.get("compute_advantage", 0)
        if current_ca < self.target_advantage:
            suggestions.insert(
                0,
                {
                    "property": "overall",
                    "current": f"{current_ca:.2f}",
                    "target": f"{self.target_advantage:.1f}",
                    "action": "Focus on autonomy and self-improvement for maximum impact",
                    "impact": f"{(self.target_advantage - current_ca):.1f}x improvement potential",
                },
            )

        return suggestions

    def get_trend_analysis(self) -> Dict[str, Any]:
        """Analyze trends in compute advantage over time"""
        if len(self.calculation_history) < 2:
            return {"status": "insufficient_data"}

        # Calculate trend over last 10 calculations
        recent = self.calculation_history[-10:]
        values = [r["compute_advantage"] for r in recent]

        # Simple linear trend
        avg_early = sum(values[: len(values) // 2]) / (len(values) // 2)
        avg_late = sum(values[len(values) // 2 :]) / (len(values) - len(values) // 2)
        trend = "improving" if avg_late > avg_early else "declining"

        return {
            "trend": trend,
            "current_value": values[-1],
            "average_value": sum(values) / len(values),
            "min_value": min(values),
            "max_value": max(values),
            "improvement_rate": (avg_late - avg_early) / avg_early if avg_early > 0 else 0,
            "samples": len(values),
        }


# Utility function for property impact visualization
def visualize_property_impacts() -> str:
    """
    Create a text visualization of property impacts on compute advantage
    """
    visualization = """
    Base Level Properties → Compute Advantage Impact Map
    =====================================================
    
    Property            | ↑ Numerator      | ↓ Denominator    | Net Impact
    --------------------|------------------|------------------|------------
    Alignment (0.7)     | -                | Effort -40%      | High
                        |                  | Time -20%        |
    Autonomy (0.8)      | Autonomy +100%   | Effort -60%      | Very High
                        |                  | Time -40%        |
    Durability (0.95)   | Compute +30%     | Cost +10%        | Medium
    Self-Improve (0.4)  | Compute +40%     | Effort -30%      | High
                        |                  | Time -20%        |
    Self-Replicate (0.3)| Compute +60%     | Cost +30%        | Medium
    Self-Organize (0.5) | Compute +20%     | Effort -40%      | High
                        |                  | Time -30%        |
    
    Target Compute Advantage: 10.0x
    Formula: CA = (Compute * Autonomy) / (Time + Effort + Cost)
    """
    return visualization


if __name__ == "__main__":
    # Test the property tracking system
    print("\n" + "=" * 60)
    print("Base Level Properties Test")
    print("=" * 60)

    tracker = PropertyTracker()
    optimizer = ComputeAdvantageOptimizer()

    # Simulate property updates
    tracker.update_property("alignment", 0.2)
    tracker.update_property("autonomy", 0.3)
    tracker.update_property("durability", 0.4)

    # Calculate compute advantage
    metrics = tracker.get_all_metrics()
    advantage = optimizer.calculate_system_advantage(metrics)

    # Get suggestions
    suggestions = optimizer.get_optimization_suggestions(metrics)

    print("\n📋 Optimization Suggestions:")
    for s in suggestions:
        print(f"  • {s['property']}: {s['current']} → {s['target']}")
        print(f"    Action: {s['action']}")
        print(f"    Impact: {s['impact']}")

    # Show visualization
    print(visualize_property_impacts())

    print("✅ Base Level Properties system test complete")
