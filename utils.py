#!/usr/bin/env python3
"""
Utility Functions Module for HyperEVM LP Monitor
Common helper functions used across modules

UPDATED VERSION: Added fee formatting utilities

Version: 1.4.1 (With Fee Utilities)
Developer: 8roku8.hl
"""

import math
from constants import TOKEN_SYMBOL_MAPPINGS

def calculate_token_amounts(liquidity, current_tick, lower_tick, upper_tick, decimals0, decimals1):
    """Calculate actual token amounts from liquidity using Uniswap V3 formulas"""
    try:
        # Convert ticks to sqrt prices
        sqrt_current = math.sqrt(1.0001 ** current_tick)
        sqrt_lower = math.sqrt(1.0001 ** lower_tick)
        sqrt_upper = math.sqrt(1.0001 ** upper_tick)
        
        # Calculate token amounts using Uniswap V3 formulas
        if current_tick < lower_tick:
            # All in token0
            amount0 = liquidity * (sqrt_upper - sqrt_lower) / (sqrt_lower * sqrt_upper)
            amount1 = 0
        elif current_tick >= upper_tick:
            # All in token1
            amount0 = 0
            amount1 = liquidity * (sqrt_upper - sqrt_lower)
        else:
            # In range - mixed
            amount0 = liquidity * (sqrt_upper - sqrt_current) / (sqrt_current * sqrt_upper)
            amount1 = liquidity * (sqrt_current - sqrt_lower)
        
        # Convert from wei to actual token amounts
        amount0_human = amount0 / (10 ** decimals0)
        amount1_human = amount1 / (10 ** decimals1)
        
        return amount0_human, amount1_human
        
    except Exception as e:
        print(f"⚠️  Error calculating token amounts: {e}")
        return 0, 0

def calculate_theoretical_amounts(liquidity, lower_tick, upper_tick, decimals0, decimals1):
    """Calculate what the token amounts would be if position was in range at center"""
    try:
        # Calculate center tick of the range
        center_tick = (lower_tick + upper_tick) // 2
        
        # Convert ticks to sqrt prices
        sqrt_center = math.sqrt(1.0001 ** center_tick)
        sqrt_lower = math.sqrt(1.0001 ** lower_tick)
        sqrt_upper = math.sqrt(1.0001 ** upper_tick)
        
        # Calculate token amounts at center of range
        amount0 = liquidity * (sqrt_upper - sqrt_center) / (sqrt_center * sqrt_upper)
        amount1 = liquidity * (sqrt_center - sqrt_lower)
        
        # Convert from wei to actual token amounts
        amount0_human = amount0 / (10 ** decimals0)
        amount1_human = amount1 / (10 ** decimals1)
        
        return amount0_human, amount1_human
        
    except Exception as e:
        print(f"⚠️  Error calculating theoretical amounts: {e}")
        return 0, 0

def sqrt_price_to_price(sqrt_price_x96, decimals0, decimals1):
    """Convert sqrtPriceX96 to human-readable price with better precision"""
    if sqrt_price_x96 == 0:
        return 0
    
    try:
        # Calculate price = (sqrtPriceX96 / 2^96)^2
        # Use higher precision arithmetic to avoid underflow
        sqrt_price = sqrt_price_x96 / (2**96)
        price = sqrt_price ** 2
        
        # Adjust for token decimals (price of token1 in terms of token0)
        decimal_adjustment = 10 ** (decimals0 - decimals1)
        adjusted_price = price * decimal_adjustment
        
        return adjusted_price
        
    except (OverflowError, ZeroDivisionError, ValueError) as e:
        print(f"⚠️  Price calculation error: {e}")
        return 0

def tick_to_price(tick, decimals0, decimals1):
    """Convert tick to human-readable price with better precision and overflow protection"""
    try:
        # Handle extreme ticks that would cause overflow
        # Uniswap V3 tick range is approximately ±887,272
        if abs(tick) > 800000:  # Near the limits
            if tick > 800000:
                return float('inf')  # Effectively infinite price
            else:
                return 0.0  # Effectively zero price
        
        # Calculate price = 1.0001^tick
        price = (1.0001 ** tick)
        
        # Adjust for token decimals (price of token1 in terms of token0)  
        decimal_adjustment = 10 ** (decimals0 - decimals1)
        adjusted_price = price * decimal_adjustment
        
        return adjusted_price
        
    except (OverflowError, ValueError) as e:
        print(f"⚠️  Tick to price calculation error for tick {tick}: {e}")
        return 0

def calculate_price_based_percentages(current_price, lower_price, upper_price):
    """Calculate price-based percentages like Hybra Finance does"""
    try:
        if current_price <= 0:
            return 0, 0
        
        # Check for full-range or extreme positions
        if lower_price == 0 or upper_price == float('inf') or (upper_price / lower_price) > 1e10:
            # This is effectively a full-range position
            return float('inf'), float('inf')  # Special marker for full range
        
        # Distance to lower bound (negative = price needs to drop)
        lower_move_pct = (current_price - lower_price) / current_price * 100
        
        # Distance to upper bound (positive = price needs to rise)  
        upper_move_pct = (upper_price - current_price) / current_price * 100
        
        return lower_move_pct, upper_move_pct
        
    except (ZeroDivisionError, ValueError, OverflowError):
        return float('inf'), float('inf')  # Treat as full range on any calculation error

def calculate_dynamic_thresholds(position, config):
    """Calculate position-specific thresholds based on range characteristics"""
    range_size = position['tick_upper'] - position['tick_lower']
    
    # Get threshold percentages from config
    danger_pct = config.get("dynamic_thresholds", {}).get("danger_threshold_pct", 5.0)
    warning_pct = config.get("dynamic_thresholds", {}).get("warning_threshold_pct", 15.0)
    
    # For very wide ranges (>10000 ticks), be more lenient
    if range_size > 10000:
        danger_pct = max(danger_pct * 0.5, 2.0)   # More lenient for wide ranges
        warning_pct = max(warning_pct * 0.75, 8.0)
    
    # For very narrow ranges (<500 ticks), be more strict  
    elif range_size < 500:
        danger_pct = min(danger_pct * 1.5, 10.0)  # More strict for narrow ranges
        warning_pct = min(warning_pct * 1.2, 25.0)
    
    return danger_pct, warning_pct

def get_risk_level(position, closer_distance_pct, config):
    """Determine risk level using dynamic thresholds"""
    # Check if this is a full-range position first
    if is_full_range_position(position['tick_lower'], position['tick_upper']):
        return "safe", None  # Full range positions are always safe
    
    danger_threshold, warning_threshold = calculate_dynamic_thresholds(position, config)
    
    if closer_distance_pct < danger_threshold:
        return "danger", danger_threshold
    elif closer_distance_pct < warning_threshold:
        return "warning", warning_threshold
    else:
        return "safe", None

def format_price(price):
    """Format prices based on magnitude with better precision for very small numbers and overflow protection"""
    if price == 0:
        return "$0.00000000"
    
    if price == float('inf'):
        return "∞ (No Upper Limit)"
    
    if price < 0:
        return "Invalid Price"
    
    abs_price = abs(price)
    
    # Handle extremely large numbers
    if abs_price > 1e15:
        return f"${price:.2e} (Extreme)"
    elif abs_price >= 1000:
        return f"${price:,.2f}"
    elif abs_price >= 1:
        return f"${price:.4f}"
    elif abs_price >= 0.01:
        return f"${price:.6f}"
    elif abs_price >= 0.000001:
        return f"${price:.8f}"
    elif abs_price >= 1e-15:
        return f"${price:.2e}"
    else:
        return "$~0 (Near Zero)"

def is_full_range_position(tick_lower, tick_upper):
    """Detect if a position is full-range or near full-range"""
    # Uniswap V3/Algebra tick limits are approximately ±887,272
    # Consider positions within 10,000 ticks of the limits as "full range"
    TICK_LIMIT = 877272  # Slightly below actual limit for safety
    
    return (tick_lower <= -TICK_LIMIT and tick_upper >= TICK_LIMIT) or (tick_upper - tick_lower) > 1700000

def format_price_percentage_safe(percentage):
    """Format price movement percentages with proper +/- signs and overflow protection"""
    if percentage == float('inf'):
        return "∞% (Full Range)"
    elif percentage == float('-inf'):
        return "-∞% (Full Range)"
    elif abs(percentage) > 1e10:
        return f"{percentage:.1e}% (Extreme)"
    elif percentage > 0:
        return f"+{percentage:.1f}%"
    else:
        return f"{percentage:.1f}%"

def format_price_percentage(percentage):
    """Format price movement percentages with proper +/- signs (legacy function)"""
    return format_price_percentage_safe(percentage)

def format_token_amount(amount, symbol):
    """Format token amounts nicely"""
    if amount > 1000:
        return f"{amount:,.2f} {symbol}"
    elif amount > 1:
        return f"{amount:.4f} {symbol}"
    elif amount > 0.01:
        return f"{amount:.6f} {symbol}"
    else:
        return f"{amount:.8f} {symbol}"

def format_fee_amount(amount, symbol, show_zero=False):
    """Format fee amounts with appropriate precision"""
    if amount == 0:
        if show_zero:
            return f"0 {symbol}"
        else:
            return None
    
    if amount > 100:
        return f"{amount:,.3f} {symbol}"
    elif amount > 1:
        return f"{amount:.5f} {symbol}"
    elif amount > 0.001:
        return f"{amount:.7f} {symbol}"
    else:
        return f"{amount:.9f} {symbol}"

def format_fees_display(fee_amount0, fee_amount1, token0_symbol, token1_symbol):
    """Format fees for display, handling zero amounts intelligently"""
    fees_parts = []
    
    fee0_str = format_fee_amount(fee_amount0, token0_symbol)
    fee1_str = format_fee_amount(fee_amount1, token1_symbol)
    
    if fee0_str:
        fees_parts.append(fee0_str)
    if fee1_str:
        fees_parts.append(fee1_str)
    
    if not fees_parts:
        return "No fees"
    elif len(fees_parts) == 1:
        return fees_parts[0]
    else:
        return " + ".join(fees_parts)

def has_significant_fees(fee_amount0, fee_amount1, threshold=0.00001):
    """Check if fees are significant enough to display"""
    return fee_amount0 >= threshold or fee_amount1 >= threshold

def apply_symbol_mapping(symbol):
    """Apply symbol mapping (e.g., WHYPE -> HYPE)"""
    # Apply symbol mapping from constants
    display_symbol = TOKEN_SYMBOL_MAPPINGS.get(symbol, symbol)
    
    # Special handling for common wrapped token patterns
    if symbol.startswith("W") and len(symbol) > 1:
        # Check if it's a wrapped token pattern
        unwrapped = symbol[1:]  # Remove 'W' prefix
        if unwrapped in ["HYPE", "ETH", "BTC", "AVAX", "MATIC"]:
            display_symbol = unwrapped
    
    return display_symbol

def parse_algebra_raw_data_strategy_1(raw_result):
    """Standard uint160 + int24 parsing strategy"""
    # Extract sqrtPriceX96 (first 32 bytes, but only use 20 bytes for uint160)
    sqrt_price_x96 = int.from_bytes(raw_result[12:32], byteorder='big')  # Skip first 12 bytes for uint160
    
    # Extract tick (next 3 bytes as int24)
    tick_bytes = raw_result[32:35]
    current_tick = int.from_bytes(tick_bytes, byteorder='big', signed=True)
    
    return sqrt_price_x96, current_tick

def parse_algebra_raw_data_strategy_2(raw_result):
    """Try with different byte alignment"""
    # Try reading from different positions
    sqrt_price_x96 = int.from_bytes(raw_result[:20], byteorder='big')  # First 20 bytes as uint160
    
    # Try tick at different positions
    for tick_offset in [20, 32, 24]:
        if tick_offset + 4 <= len(raw_result):
            tick_bytes = raw_result[tick_offset:tick_offset+4]
            current_tick = int.from_bytes(tick_bytes, byteorder='big', signed=True)
            # Check if tick is in valid range
            if abs(current_tick) < 887272:
                return sqrt_price_x96, current_tick
    
    return None, None

def parse_algebra_raw_data_strategy_3(raw_result):
    """Try interpreting as 32-byte aligned values"""
    # Sometimes values are 32-byte aligned
    sqrt_price_x96 = int.from_bytes(raw_result[:32], byteorder='big')
    
    # Try to extract int24 from next 32-byte slot
    tick_data = raw_result[32:64]
    # Try last 3 bytes of the 32-byte slot (right-aligned int24)
    tick_bytes = tick_data[-3:]
    current_tick = int.from_bytes(tick_bytes, byteorder='big', signed=True)
    
    # If the tick is way out of range, try other positions
    if abs(current_tick) >= 887272:
        # Try first 4 bytes as int24 (left-aligned) 
        tick_bytes = tick_data[:4]
        current_tick = int.from_bytes(tick_bytes, byteorder='big', signed=True) & 0xffffff
        if current_tick > 0x7fffff:  # Handle sign bit for 24-bit signed
            current_tick -= 0x1000000
    
    return sqrt_price_x96, current_tick

def parse_algebra_raw_data(raw_result, debug_mode=False):
    """Enhanced parsing of raw Algebra globalState data using multiple strategies"""
    if not raw_result or len(raw_result) < 64:
        return None, None
        
    try:
        if debug_mode:
            print(f"🔍 Raw data length: {len(raw_result)} bytes")
            print(f"🔍 Raw data (hex): {raw_result.hex()[:128]}...")
        
        # Try different parsing strategies
        parsing_strategies = [
            parse_algebra_raw_data_strategy_1,
            parse_algebra_raw_data_strategy_2, 
            parse_algebra_raw_data_strategy_3
        ]
        
        for i, strategy in enumerate(parsing_strategies):
            try:
                sqrt_price_x96, current_tick = strategy(raw_result)
                if sqrt_price_x96 and sqrt_price_x96 > 0 and abs(current_tick) < 887272:  # Valid tick range
                    if debug_mode:
                        print(f"✅ Strategy {i+1} worked: Price={sqrt_price_x96}, Tick={current_tick}")
                    return sqrt_price_x96, current_tick
            except Exception as e:
                if debug_mode:
                    print(f"⚠️  Strategy {i+1} failed: {e}")
                continue
        
        return None, None
        
    except Exception as e:
        print(f"Error parsing raw data: {e}")
        return None, None

def validate_dex_config(dex):
    """Validate a single DEX configuration"""
    if not dex.get("name") or not dex.get("position_manager"):
        return False
    
    # Set default type if not specified
    if "type" not in dex:
        dex["type"] = "uniswap_v3"
    
    return True

def validate_dex_configs(dexes):
    """Validate all DEX configurations and return valid ones"""
    valid_dexes = []
    for dex in dexes:
        if validate_dex_config(dex):
            valid_dexes.append(dex)
        else:
            print(f"⚠️  Skipping incomplete DEX config: {dex}")
    
    return valid_dexes