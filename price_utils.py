#!/usr/bin/env python3
"""
Price Utilities for USD Value Calculation
Helper functions for calculating USD values from LP positions

Version: 1.5.0
"""

def is_stablecoin(token_symbol):
    """Check if a token is a stablecoin"""
    stablecoins = [
        'USDC', 'USDT', 'USD₮0', 'USDe', 'DAI', 'BUSD', 'TUSD', 'FRAX',
        'USDD', 'GUSD', 'USDP', 'SUSD', 'LUSD', 'UST', 'CUSD', 'USDN',
        'RSV', 'MUSD', 'USDX', 'USDK', 'USDS', 'DUSD', 'USD', 'USDJ'
    ]
    return token_symbol.upper() in [s.upper() for s in stablecoins]

def extract_token_prices_from_positions(positions_with_status):
    """Extract approximate USD prices for tokens from position data"""
    token_prices = {}
    
    # First pass: Direct stablecoin pairs
    for position, status in positions_with_status:
        if not status:
            continue
            
        token0 = status.get('token0_symbol', '')
        token1 = status.get('token1_symbol', '')
        current_price = status.get('current_price', 0)
        
        if current_price <= 0:
            continue
        
        # If token1 is a stablecoin, token0 price = current_price
        if is_stablecoin(token1):
            token_prices[token0] = current_price
            token_prices[token1] = 1.0
        # If token0 is a stablecoin, token1 price = 1/current_price
        elif is_stablecoin(token0):
            token_prices[token0] = 1.0
            token_prices[token1] = 1.0 / current_price
    
    # Second pass: Try to derive prices through common pairs
    # For example, if we know HYPE/USDC and WETH/HYPE, we can calculate WETH/USD
    for position, status in positions_with_status:
        if not status:
            continue
            
        token0 = status.get('token0_symbol', '')
        token1 = status.get('token1_symbol', '')
        current_price = status.get('current_price', 0)
        
        if current_price <= 0:
            continue
        
        # If we know the price of token1 but not token0
        if token1 in token_prices and token0 not in token_prices:
            token_prices[token0] = current_price * token_prices[token1]
        # If we know the price of token0 but not token1
        elif token0 in token_prices and token1 not in token_prices:
            token_prices[token1] = token_prices[token0] / current_price
    
    return token_prices

def calculate_fees_usd_value(total_fees, token_prices):
    """Calculate USD value of fees"""
    total_usd = 0
    fees_with_usd = []
    
    for token, amount in total_fees.items():
        if amount <= 0:
            continue
            
        usd_value = None
        if token in token_prices:
            usd_value = amount * token_prices[token]
            total_usd += usd_value
        
        fees_with_usd.append({
            'token': token,
            'amount': amount,
            'usd_value': usd_value
        })
    
    # Sort by USD value (highest first) or amount if no USD value
    fees_with_usd.sort(
        key=lambda x: x['usd_value'] if x['usd_value'] is not None else x['amount'],
        reverse=True
    )
    
    return total_usd, fees_with_usd

def format_fee_with_usd(amount, token, usd_value=None):
    """Format a fee amount with optional USD value"""
    if usd_value is not None and usd_value > 0.01:  # Only show USD if > $0.01
        return f"{amount:.6f} {token} (${usd_value:,.2f})"
    else:
        return f"{amount:.6f} {token}"

def calculate_position_value_usd(position, status, token_prices):
    """Calculate total position value in USD"""
    if not status:
        return None
    
    token0 = status.get('token0_symbol', '')
    token1 = status.get('token1_symbol', '')
    amount0 = status.get('amount0', 0)
    amount1 = status.get('amount1', 0)
    
    total_usd = 0
    has_price = False
    
    if token0 in token_prices:
        total_usd += amount0 * token_prices[token0]
        has_price = True
    
    if token1 in token_prices:
        total_usd += amount1 * token_prices[token1]
        has_price = True
    
    return total_usd if has_price else None

def format_usd_value(value):
    """Format USD value with appropriate precision"""
    if value is None:
        return ""
    elif value >= 1000000:
        return f"${value/1000000:.2f}M"
    elif value >= 1000:
        return f"${value:,.0f}"
    elif value >= 1:
        return f"${value:,.2f}"
    elif value >= 0.01:
        return f"${value:.4f}"
    else:
        return f"${value:.6f}"