#!/usr/bin/env python3
"""
Impermanent Loss Calculator Module for HyperEVM LP Monitor
Calculates IL and provides intelligent rebalancing recommendations

Version: 1.5.0 (IL Detection)
Developer: 8roku8.hl
"""

import math
import json
import os
from datetime import datetime
from utils import tick_to_price, calculate_token_amounts, is_full_range_position

class ILCalculator:
    """Calculates Impermanent Loss and provides rebalancing recommendations"""
    
    def __init__(self, config):
        self.config = config
        self.position_history_file = "position_history.json"
        self.debug_mode = config.get("display_settings", {}).get("debug_mode", False)
        
        # Option to reset IL tracking (useful for testing)
        reset_il_tracking = config.get("il_thresholds", {}).get("reset_tracking_on_start", False)
        if reset_il_tracking and os.path.exists(self.position_history_file):
            os.remove(self.position_history_file)
            if self.debug_mode:
                print("🔄 Reset IL tracking history")
        
        self.position_history = self.load_position_history()
    
    def load_position_history(self):
        """Load position creation history for IL calculations"""
        try:
            if os.path.exists(self.position_history_file):
                with open(self.position_history_file, 'r') as f:
                    return json.load(f)
        except Exception as e:
            if self.debug_mode:
                print(f"⚠️  Could not load position history: {e}")
        return {}
    
    def save_position_history(self):
        """Save position history for persistence"""
        try:
            with open(self.position_history_file, 'w') as f:
                json.dump(self.position_history, f, indent=2)
        except Exception as e:
            if self.debug_mode:
                print(f"⚠️  Could not save position history: {e}")
    
    def get_position_key(self, position):
        """Generate unique key for position tracking"""
        return f"{position['dex_name']}_{position['token_id']}"
    
    def estimate_initial_position_data(self, position, current_price):
        """Estimate initial position data if not tracked - assume created at range center"""
        # Calculate the center tick and corresponding price
        center_tick = (position['tick_lower'] + position['tick_upper']) // 2
        decimals0 = position["token0_info"]["decimals"]
        decimals1 = position["token1_info"]["decimals"]
        
        estimated_initial_price = tick_to_price(center_tick, decimals0, decimals1)
        
        # Calculate what the token amounts would have been at center
        initial_amount0, initial_amount1 = calculate_token_amounts(
            position["liquidity"], center_tick, 
            position['tick_lower'], position['tick_upper'], 
            decimals0, decimals1
        )
        
        if self.debug_mode:
            print(f"🔍 Estimating initial data for {position['name']}:")
            print(f"    Range center tick: {center_tick} (price: ${estimated_initial_price:.4f})")
            print(f"    Estimated initial amounts: {initial_amount0:.6f} + {initial_amount1:.6f}")
        
        return {
            "initial_price": estimated_initial_price,
            "initial_amount0": initial_amount0,
            "initial_amount1": initial_amount1,
            "estimated": True,
            "timestamp": datetime.now().isoformat()
        }
    
    def track_new_position(self, position, current_status):
        """Track a new position for IL calculations"""
        position_key = self.get_position_key(position)
        
        if position_key not in self.position_history:
            # For new positions, estimate they were created at range center
            # This is more realistic than assuming current price
            initial_data = self.estimate_initial_position_data(position, current_status["current_price"])
            initial_data.update({
                "timestamp": datetime.now().isoformat(),
                "position_name": position["name"],
                "dex_name": position["dex_name"],
                "tick_lower": position["tick_lower"],
                "tick_upper": position["tick_upper"]
            })
            
            self.position_history[position_key] = initial_data
            self.save_position_history()
            
            if self.debug_mode:
                print(f"🔍 Started tracking position: {position['name']} (estimated initial price: ${initial_data['initial_price']:.4f})")
    
    def calculate_position_value(self, amount0, amount1, current_price):
        """Calculate total position value in terms of token1 (usually the stable asset)"""
        # Convert everything to token1 terms:
        # - amount0 (token0) gets converted using current_price
        # - amount1 (token1) stays as-is
        # 
        # current_price represents: 1 token0 = X token1
        # So: token0_value_in_token1 = amount0 * current_price
        
        value_in_token1 = (amount0 * current_price) + amount1
        return value_in_token1
    
    def calculate_hodl_value(self, initial_amount0, initial_amount1, initial_price, current_price):
        """Calculate value if tokens were held separately (HODL value)"""
        # HODL means keeping the exact same amounts of each token
        # Value both at current price in token1 terms
        
        hodl_token0_value = initial_amount0 * current_price  # Convert token0 to token1 at current price
        hodl_token1_value = initial_amount1  # Token1 amount stays the same
        
        total_hodl_value = hodl_token0_value + hodl_token1_value
        return total_hodl_value
    
    def calculate_impermanent_loss(self, position, current_status):
        """Calculate impermanent loss for a position"""
        position_key = self.get_position_key(position)
        
        # Get or estimate initial position data
        if position_key in self.position_history:
            initial_data = self.position_history[position_key]
        else:
            # First time seeing this position - estimate initial data
            initial_data = self.estimate_initial_position_data(position, current_status["current_price"])
            self.position_history[position_key] = initial_data
            self.save_position_history()
        
        # Skip IL calculation for full-range positions (IL is minimal)
        if is_full_range_position(position['tick_lower'], position['tick_upper']):
            return {
                "il_percentage": 0.0,
                "il_absolute": 0.0,
                "current_value": self.calculate_position_value(
                    current_status["amount0"], current_status["amount1"], 
                    current_status["current_price"]
                ),
                "hodl_value": 0.0,  # Not meaningful for full range
                "price_change_pct": 0.0,
                "is_full_range": True,
                "estimated": initial_data.get("estimated", False)
            }
        
        # Calculate current position value
        current_value = self.calculate_position_value(
            current_status["amount0"], current_status["amount1"], 
            current_status["current_price"]
        )
        
        # Calculate HODL value (if tokens were held separately)
        hodl_value = self.calculate_hodl_value(
            initial_data["initial_amount0"], initial_data["initial_amount1"],
            initial_data["initial_price"], current_status["current_price"]
        )
        
        # Calculate IL - make sure we handle edge cases
        il_absolute = hodl_value - current_value
        il_percentage = (il_absolute / hodl_value) * 100 if hodl_value > 0 else 0
        
        # Calculate price change
        initial_price = initial_data["initial_price"]
        current_price = current_status["current_price"]
        price_change_pct = ((current_price - initial_price) / initial_price) * 100 if initial_price > 0 else 0
        
        # Debug output
        if self.debug_mode:
            print(f"🔍 IL Debug for {position['name']}:")
            print(f"    Initial: {initial_data['initial_amount0']:.6f} + {initial_data['initial_amount1']:.6f} @ ${initial_price:.4f}")
            print(f"    Current: {current_status['amount0']:.6f} + {current_status['amount1']:.6f} @ ${current_price:.4f}")
            print(f"    HODL value: ${hodl_value:.4f}, Current value: ${current_value:.4f}")
            print(f"    IL: {il_percentage:.2f}%, Price change: {price_change_pct:+.1f}%")
        
        return {
            "il_percentage": il_percentage,
            "il_absolute": il_absolute,
            "current_value": current_value,
            "hodl_value": hodl_value,
            "price_change_pct": price_change_pct,
            "initial_price": initial_price,
            "is_full_range": False,
            "estimated": initial_data.get("estimated", False)
        }
    
    def get_rebalancing_recommendation(self, position, current_status, il_data):
        """Provide intelligent rebalancing recommendations"""
        if il_data["is_full_range"]:
            return {
                "should_rebalance": False,
                "reason": "Full-range position - IL is minimal",
                "urgency": "none",
                "recommendation": "Consider if you want more concentrated liquidity for higher fees"
            }
        
        recommendations = []
        urgency = "none"
        should_rebalance = False
        
        # Check IL thresholds
        il_threshold_warning = self.config.get("il_thresholds", {}).get("warning_pct", 2.0)
        il_threshold_critical = self.config.get("il_thresholds", {}).get("critical_pct", 5.0)
        
        if il_data["il_percentage"] > il_threshold_critical:
            should_rebalance = True
            urgency = "high"
            recommendations.append(f"🚨 HIGH IL: {il_data['il_percentage']:.2f}% loss vs HODL")
            recommendations.append("Consider rebalancing to reduce further IL")
        elif il_data["il_percentage"] > il_threshold_warning:
            urgency = "medium"
            recommendations.append(f"⚠️ Moderate IL: {il_data['il_percentage']:.2f}% loss vs HODL")
            recommendations.append("Monitor closely, consider rebalancing if IL increases")
        
        # Check position range efficiency
        if not current_status["in_range"]:
            should_rebalance = True
            urgency = "high" if urgency != "high" else urgency
            recommendations.append("❌ Position is OUT OF RANGE - not earning fees!")
            recommendations.append("Immediate rebalancing recommended to resume fee collection")
        
        # Check if position is close to range edge
        range_size = position['tick_upper'] - position['tick_lower']
        closer_distance_pct = min(current_status["distance_to_lower"], current_status["distance_to_upper"]) / range_size * 100
        
        danger_threshold = self.config.get("dynamic_thresholds", {}).get("danger_threshold_pct", 5.0)
        if current_status["in_range"] and closer_distance_pct < danger_threshold:
            urgency = "medium" if urgency == "none" else urgency
            recommendations.append(f"🚨 Near range edge: {closer_distance_pct:.1f}% from boundary")
            recommendations.append("Consider expanding range or recentering position")
        
        # Check price deviation from range center
        center_tick = (position['tick_lower'] + position['tick_upper']) // 2
        current_tick = current_status["current_tick"]
        deviation_from_center = abs(current_tick - center_tick) / (range_size / 2) * 100
        
        if deviation_from_center > 70:  # More than 70% away from center
            urgency = "medium" if urgency == "none" else urgency
            recommendations.append(f"📊 Price deviated {deviation_from_center:.1f}% from range center")
            recommendations.append("Consider recentering position around current price")
        
        # Fee opportunity cost
        if not current_status["in_range"]:
            recommendations.append("💰 Missing fee collection opportunities while out of range")
        
        # Default recommendation if no issues
        if not recommendations:
            recommendations.append("✅ Position looks healthy - no immediate rebalancing needed")
        
        return {
            "should_rebalance": should_rebalance,
            "urgency": urgency,  # none, low, medium, high
            "recommendations": recommendations,
            "il_loss_usd": il_data["il_absolute"],  # Could convert to USD if prices available
            "efficiency_score": self.calculate_position_efficiency(position, current_status, il_data)
        }
    
    def calculate_position_efficiency(self, position, current_status, il_data):
        """Calculate position efficiency score (0-100)"""
        score = 100
        
        # Deduct for IL
        score -= min(il_data["il_percentage"] * 2, 30)  # Max 30 point deduction for IL
        
        # Deduct for being out of range
        if not current_status["in_range"]:
            score -= 40
        
        # Deduct for being close to edges
        range_size = position['tick_upper'] - position['tick_lower']
        closer_distance_pct = min(current_status["distance_to_lower"], current_status["distance_to_upper"]) / range_size * 100
        if closer_distance_pct < 10:
            score -= (10 - closer_distance_pct) * 2
        
        # Bonus for full range (stable but lower fee potential)
        if is_full_range_position(position['tick_lower'], position['tick_upper']):
            score = max(score, 75)  # Full range gets at least 75/100
        
        return max(0, min(100, score))

    def cleanup_position_history(self, current_positions):
        """Clean up history for positions that no longer exist"""
        current_keys = set()
        for position in current_positions:
            position_key = self.get_position_key(position)
            current_keys.add(position_key)
        
        # Find orphaned keys
        stored_keys = set(self.position_history.keys())
        orphaned_keys = stored_keys - current_keys
        
        if orphaned_keys:
            for key in orphaned_keys:
                removed_position = self.position_history.pop(key, None)
                if self.debug_mode and removed_position:
                    print(f"🗑️  Removed IL history for: {removed_position.get('position_name', key)}")
            
            self.save_position_history()
            if self.debug_mode:
                print(f"🧹 Cleaned up IL history ({len(orphaned_keys)} removed)")
