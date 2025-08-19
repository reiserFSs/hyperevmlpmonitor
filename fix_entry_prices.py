#!/usr/bin/env python3
"""
Fix Entry Prices Script

This script recalculates and fixes entry prices for positions by:
1. Finding the NFT mint/first liquidity event
2. Fetching the actual pool price at that block
3. Calculating proper entry value based on actual historical prices
4. Updating the database with corrected values

Usage:
    python3 fix_entry_prices.py
    python3 fix_entry_prices.py --wallet YOUR_WALLET
    python3 fix_entry_prices.py --token 176 --debug
"""

import argparse
import sqlite3
from web3 import Web3
from datetime import datetime
import sys
import os

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from blockchain import BlockchainManager
from config import load_config
from price_utils import is_stablecoin
from utils import tick_to_price


def get_args():
    parser = argparse.ArgumentParser(description="Fix entry prices for LP positions")
    parser.add_argument("--wallet", help="Filter by wallet address")
    parser.add_argument("--token", type=int, help="Filter by token ID")
    parser.add_argument("--dex", default="HX Finance", help="DEX name")
    parser.add_argument("--debug", action="store_true", help="Enable debug output")
    parser.add_argument("--dry-run", action="store_true", help="Don't update database")
    return parser.parse_args()


def get_position_creation_block(blockchain, position_manager, token_id, debug=False):
    """Find the block where the position was created (minted) with rate-limited search"""
    import time
    
    try:
        current_block = blockchain._rl_call(lambda: blockchain.w3.eth.block_number)
    except Exception as e:
        if debug:
            print(f"  Error getting current block: {e}")
        return None
    # For recent positions, search with conservative range to stay under RPC limit
    search_range = 200  # Conservative block range to avoid rate limiting
    
    transfer_topic = blockchain.w3.keccak(text="Transfer(address,address,uint256)").hex()
    token_id_topic = '0x' + int(token_id).to_bytes(32, 'big').hex()
    
    try:
        if debug:
            print(f"  Searching for mint of token {token_id} in last {search_range} blocks...")
        
        logs = blockchain._rl_call(blockchain.w3.eth.get_logs, {
            'fromBlock': max(0, current_block - search_range),
            'toBlock': 'latest',
            'address': Web3.to_checksum_address(position_manager),
            'topics': [transfer_topic, 
                      '0x0000000000000000000000000000000000000000000000000000000000000000',  # from = 0 (mint)
                      None, 
                      token_id_topic]
        })
        
        if logs:
            mint_block = logs[0]['blockNumber']
            if debug:
                print(f"  Found mint at block {mint_block}")
            return mint_block
            
    except Exception as e:
        if debug:
            print(f"  Error finding mint: {e}")
    
    # Fallback to IncreaseLiquidity
    try:
        if debug:
            print(f"  Searching for IncreaseLiquidity events...")
        
        increase_topic = blockchain.w3.keccak(text="IncreaseLiquidity(uint256,uint128,uint256,uint256)").hex()
        logs = blockchain._rl_call(blockchain.w3.eth.get_logs, {
            'fromBlock': max(0, current_block - search_range),
            'toBlock': 'latest',
            'address': Web3.to_checksum_address(position_manager),
            'topics': [increase_topic, token_id_topic]
        })
        
        if logs:
            if debug:
                print(f"  Found IncreaseLiquidity at block {logs[0]['blockNumber']}")
            return logs[0]['blockNumber']
                
    except Exception as e:
        if debug:
            print(f"  Error finding IncreaseLiquidity: {e}")
            
    return None


def get_entry_price_from_first_snapshot(conn, wallet, dex, token_id, debug=False):
    """Get entry price from the first RELIABLE snapshot data (with validation)"""
    try:
        if debug:
            print(f"  Attempting to get entry price from early snapshots...")
        
        # Get the first few snapshots to find a reliable one
        cursor = conn.execute("""
            SELECT amount0, amount1, current_price, timestamp, in_range
            FROM position_snapshots 
            WHERE wallet_address = ? AND dex_name = ? AND token_id = ?
            ORDER BY timestamp ASC 
            LIMIT 10
        """, (wallet, dex, token_id))
        
        snapshots = cursor.fetchall()
        
        for snapshot in snapshots:
            if snapshot['amount0'] > 0 and snapshot['amount1'] > 0:
                amount0 = snapshot['amount0']
                amount1 = snapshot['amount1']
                current_price = snapshot['current_price']
                snapshot_time = snapshot['timestamp']
                in_range = snapshot['in_range']
                
                # Calculate ratio and check if it's reasonable
                amount_ratio = amount1 / amount0
                
                # Validate: amount ratio should be close to pool price (within 50% tolerance)
                # This catches corrupted data where amounts don't match market conditions
                if current_price and current_price > 0:
                    price_diff_pct = abs(amount_ratio - current_price) / current_price
                    
                    if debug:
                        print(f"  Checking snapshot from {snapshot_time}")
                        print(f"    Amount ratio: {amount_ratio:.6f}")
                        print(f"    Pool price: {current_price:.6f}")
                        print(f"    Difference: {price_diff_pct:.1%}")
                        print(f"    In range: {in_range}")
                    
                    # Accept if ratio is reasonably close to pool price (< 15% difference)
                    if price_diff_pct < 0.15:  # 15% tolerance - stricter validation
                        if debug:
                            print(f"  ✅ Found reliable snapshot from {snapshot_time}")
                            print(f"  ✅ Validated amounts: {amount0:.6f} token0, {amount1:.6f} token1")
                            print(f"  ✅ Entry price from snapshot: {amount_ratio:.6f}")
                        
                        return amount_ratio, amount0, amount1, snapshot_time
                    else:
                        if debug:
                            print(f"  ❌ Snapshot rejected - ratio too far from pool price")
                else:
                    # If no pool price to validate against, use first available
                    if debug:
                        print(f"  ⚠️  No pool price to validate, using first snapshot")
                        print(f"  ✅ Entry price from snapshot: {amount_ratio:.6f}")
                    
                    return amount_ratio, amount0, amount1, snapshot_time
            
    except Exception as e:
        if debug:
            print(f"  ⚠️  Could not get snapshot data: {e}")
    
    return None, None, None, None


def calculate_entry_price_from_actual_amounts(blockchain, position_manager, token_id, token0_info, token1_info, debug=False):
    """Calculate entry price from actual IncreaseLiquidity event data (MOST ACCURATE)"""
    try:
        if debug:
            print(f"  Attempting to get actual entry amounts from IncreaseLiquidity event...")
        
        # Get the actual entry data from blockchain
        # This uses the main system's proven approach
        position_data = {
            'token_id': token_id,
            'position_manager': position_manager,
            'token0_info': token0_info,
            'token1_info': token1_info,
            'token0_symbol': token0_info.get('display_symbol', ''),
            'token1_symbol': token1_info.get('display_symbol', ''),
        }
        
        entry_data = blockchain.get_initial_position_entry(position_data, "")
        
        if entry_data and entry_data.get('amount0') and entry_data.get('amount1'):
            amount0 = entry_data['amount0']
            amount1 = entry_data['amount1']
            
            # Calculate the actual entry price from the ratio of deposited amounts
            # This is the REAL price when the position was created
            actual_entry_price = amount1 / amount0  # token0 price in terms of token1
            
            if debug:
                print(f"  ✅ Found actual entry amounts: {amount0:.6f} token0, {amount1:.6f} token1")
                print(f"  ✅ Actual entry price from amounts: {actual_entry_price:.6f}")
            
            return actual_entry_price, amount0, amount1, entry_data
            
    except Exception as e:
        if debug:
            print(f"  ⚠️  Could not get actual entry data: {e}")
    
    return None, None, None, None


def calculate_entry_price_from_position_range(tick_lower, tick_upper, token0_decimals, token1_decimals, debug=False):
    """Calculate entry price from position's tick range using the geometric mean (FALLBACK METHOD)"""
    try:
        # Calculate prices at lower and upper bounds using 1.0001^tick formula
        lower_price = tick_to_price(tick_lower, token0_decimals, token1_decimals)
        upper_price = tick_to_price(tick_upper, token0_decimals, token1_decimals)
        
        # Use geometric mean of the range as the "entry price"
        # This represents the center of the range where the position was likely created
        entry_price = (lower_price * upper_price) ** 0.5
        
        if debug:
            print(f"  Tick range: {tick_lower} to {tick_upper}")
            print(f"  Lower price: {lower_price:.6f}")
            print(f"  Upper price: {upper_price:.6f}")
            print(f"  Entry price (geometric mean fallback): {entry_price:.6f}")
        
        return entry_price, lower_price, upper_price
        
    except Exception as e:
        if debug:
            print(f"  Error calculating entry price from ticks: {e}")
        return None, None, None


def calculate_entry_price_from_amounts(token0_amount, token1_amount, token0_symbol, token1_symbol, debug=False):
    """Calculate entry price from token amounts, assuming position was created in-range"""
    if token0_amount <= 0 or token1_amount <= 0:
        return None, None, None
        
    # Price of token0 in terms of token1
    price_token0_in_token1 = token1_amount / token0_amount
    
    # Determine USD prices
    token0_usd = None
    token1_usd = None
    
    if is_stablecoin(token1_symbol):
        token1_usd = 1.0
        token0_usd = price_token0_in_token1  # token0 price in USD
    elif is_stablecoin(token0_symbol):
        token0_usd = 1.0
        token1_usd = 1.0 / price_token0_in_token1  # token1 price in USD
    else:
        # Neither is a stablecoin, we can't determine USD prices
        if debug:
            print(f"  Neither token is a stablecoin, cannot determine USD prices")
        return price_token0_in_token1, None, None
        
    return price_token0_in_token1, token0_usd, token1_usd


def fix_position_entry(conn, blockchain, wallet, dex, token_id, position_manager, dex_type="uniswap_v3", debug=False, dry_run=False):
    """Fix entry data for a single position"""
    print(f"\nProcessing {dex} #{token_id}:")
    
    # Get current entry data
    cursor = conn.execute("""
        SELECT * FROM position_entries 
        WHERE wallet_address = ? AND dex_name = ? AND token_id = ?
    """, (wallet, dex, token_id))
    entry = cursor.fetchone()
    
    if not entry:
        print("  No entry found in database")
        return
        
    # Get position details
    cursor = conn.execute("""
        SELECT * FROM position_snapshots 
        WHERE wallet_address = ? AND dex_name = ? AND token_id = ?
        ORDER BY timestamp DESC LIMIT 1
    """, (wallet, dex, token_id))
    snapshot = cursor.fetchone()
    
    if not snapshot:
        print("  No snapshot found")
        return
        
    # Extract data
    entry_amount0 = entry['entry_amount0'] or 0
    entry_amount1 = entry['entry_amount1'] or 0
    current_entry_value = entry['entry_value_usd']
    token0_symbol = snapshot['token0_symbol']
    token1_symbol = snapshot['token1_symbol']
    
    print(f"  Pair: {token0_symbol}/{token1_symbol}")
    print(f"  Current entry: ${current_entry_value:.2f} ({entry_amount0:.6f}, {entry_amount1:.6f})")
    
    # Get position data to extract tick range and token information
    try:
        # Get pool data to find pool address
        position_manager_contract = blockchain.w3.eth.contract(
            address=Web3.to_checksum_address(position_manager),
            abi=[{
                "inputs": [{"name": "tokenId", "type": "uint256"}],
                "name": "positions",
                "outputs": [
                    {"name": "nonce", "type": "uint96"},
                    {"name": "operator", "type": "address"},
                    {"name": "token0", "type": "address"},
                    {"name": "token1", "type": "address"},
                    {"name": "fee", "type": "uint24"},
                    {"name": "tickLower", "type": "int24"},
                    {"name": "tickUpper", "type": "int24"},
                    {"name": "liquidity", "type": "uint128"},
                    {"name": "feeGrowthInside0LastX128", "type": "uint256"},
                    {"name": "feeGrowthInside1LastX128", "type": "uint256"},
                    {"name": "tokensOwed0", "type": "uint128"},
                    {"name": "tokensOwed1", "type": "uint128"}
                ],
                "stateMutability": "view",
                "type": "function"
            }]
        )
        
        position_data = position_manager_contract.functions.positions(token_id).call()
        token0 = position_data[2]
        token1 = position_data[3]
        fee = position_data[4]
        tick_lower = position_data[5]
        tick_upper = position_data[6]
        
        if debug:
            print(f"  Position data: token0={token0[:8]}..., token1={token1[:8]}..., fee={fee}")
            print(f"  Tick range: {tick_lower} to {tick_upper}")
        
        # Get factory address
        factory_contract = blockchain.w3.eth.contract(
            address=Web3.to_checksum_address(position_manager),
            abi=[{
                "inputs": [],
                "name": "factory",
                "outputs": [{"name": "", "type": "address"}],
                "stateMutability": "view",
                "type": "function"
            }]
        )
        factory_address = factory_contract.functions.factory().call()
        
        # Get token decimals for price calculations
        token0_info = blockchain.get_enhanced_token_info(token0)
        token1_info = blockchain.get_enhanced_token_info(token1)
        
        # METHOD 1: Try to get entry price from first snapshot (MOST ACCURATE)
        snapshot_entry_price, snapshot_amount0, snapshot_amount1, snapshot_time = get_entry_price_from_first_snapshot(
            conn, wallet, dex, token_id, debug
        )
        
        entry_price = None
        final_entry_amount0 = entry_amount0
        final_entry_amount1 = entry_amount1
        calculation_method = "unknown"
        
        if snapshot_entry_price and snapshot_amount0 and snapshot_amount1:
            # Use the MOST ACCURATE method: first snapshot data
            entry_price = snapshot_entry_price
            final_entry_amount0 = snapshot_amount0
            final_entry_amount1 = snapshot_amount1
            calculation_method = "first_snapshot_data"
            if debug:
                print(f"  ✅ Using first snapshot data from {snapshot_time}")
        else:
            # METHOD 2: Try to get actual entry price from IncreaseLiquidity event
            actual_entry_price, actual_amount0, actual_amount1, entry_data = calculate_entry_price_from_actual_amounts(
                blockchain, position_manager, token_id, token0_info, token1_info, debug
            )
            
            if actual_entry_price and actual_amount0 and actual_amount1:
                # Use blockchain event data
                entry_price = actual_entry_price
                final_entry_amount0 = actual_amount0
                final_entry_amount1 = actual_amount1
                calculation_method = "blockchain_event_data"
                if debug:
                    print(f"  ✅ Using actual entry data from blockchain")
            elif entry_amount0 > 0 and entry_amount1 > 0:
                # METHOD 3: Calculate from existing entry amounts in database
                entry_price = entry_amount1 / entry_amount0  # token0 price in terms of token1
                calculation_method = "database_amounts_ratio"
                if debug:
                    print(f"  ✅ Calculated entry price from database amounts: {entry_price:.6f}")
            else:
                # METHOD 4: Fallback to geometric mean of tick range
                if debug:
                    print(f"  ⚠️  Falling back to geometric mean calculation")
                entry_price, lower_price, upper_price = calculate_entry_price_from_position_range(
                    tick_lower, tick_upper, token0_info["decimals"], token1_info["decimals"], debug
                )
                calculation_method = "geometric_mean_fallback"
        
        if not entry_price:
            print("  Could not calculate entry price with any method")
            return
            
        print(f"  Entry price ({calculation_method}): {entry_price:.6f}")
        
        # Calculate USD values based on entry price
        token0_usd = None
        token1_usd = None
        
        if is_stablecoin(token1_symbol):
            token1_usd = 1.0
            token0_usd = entry_price
        elif is_stablecoin(token0_symbol):
            token0_usd = 1.0
            token1_usd = 1.0 / entry_price if entry_price > 0 else None
        else:
            print("  No stablecoin detected, cannot determine USD prices")
            return
            
        if token0_usd and token1_usd and final_entry_amount0 > 0 and final_entry_amount1 > 0:
            new_value = final_entry_amount0 * token0_usd + final_entry_amount1 * token1_usd
            print(f"  New entry value: ${new_value:.2f} (token0=${token0_usd:.4f}, token1=${token1_usd:.4f})")
            print(f"  Using amounts: {final_entry_amount0:.6f} token0, {final_entry_amount1:.6f} token1")
            
            if abs(new_value - current_entry_value) > 0.01:
                if not dry_run:
                    # Update with the corrected amounts as well
                    conn.execute("""
                        UPDATE position_entries
                        SET entry_value_usd = ?, entry_token0_price_usd = ?, entry_token1_price_usd = ?, 
                            entry_price = ?, entry_amount0 = ?, entry_amount1 = ?
                        WHERE wallet_address = ? AND dex_name = ? AND token_id = ?
                    """, (new_value, token0_usd, token1_usd, entry_price, final_entry_amount0, final_entry_amount1, wallet, dex, token_id))
                    conn.commit()
                    print("  ✅ Updated entry value and amounts")
            else:
                print("  Entry value already correct")
        else:
            print("  Missing entry amounts, cannot calculate value")
            
    except Exception as e:
        if debug:
            print(f"  Error getting position data: {e}")
        
        # Fallback to calculation from amounts if position data unavailable
        print("  Falling back to calculation from entry amounts...")
        if entry_amount0 > 0 and entry_amount1 > 0:
            price, token0_usd, token1_usd = calculate_entry_price_from_amounts(
                entry_amount0, entry_amount1, token0_symbol, token1_symbol, debug
            )
            if token0_usd and token1_usd:
                new_value = entry_amount0 * token0_usd + entry_amount1 * token1_usd
                print(f"  Calculated from amounts: ${new_value:.2f} (token0=${token0_usd:.4f}, token1=${token1_usd:.4f})")
                
                if not dry_run:
                    conn.execute("""
                        UPDATE position_entries
                        SET entry_value_usd = ?, entry_token0_price_usd = ?, entry_token1_price_usd = ?
                        WHERE wallet_address = ? AND dex_name = ? AND token_id = ?
                    """, (new_value, token0_usd, token1_usd, wallet, dex, token_id))
                    conn.commit()
                    print("  ✅ Updated entry value")


def main():
    args = get_args()
    
    # Load config and initialize blockchain
    config = load_config()
    blockchain = BlockchainManager(config["rpc_url"], debug_mode=args.debug)
    
    # Open database
    conn = sqlite3.connect("lp_positions.db")
    conn.row_factory = sqlite3.Row
    
    # Get positions to fix
    if args.token:
        positions = [(args.wallet or config["wallet_address"], args.dex, args.token)]
    else:
        query = "SELECT DISTINCT wallet_address, dex_name, token_id FROM position_entries"
        params = []
        if args.wallet:
            query += " WHERE wallet_address = ?"
            params.append(args.wallet)
        elif not args.wallet and "wallet_address" in config:
            query += " WHERE wallet_address = ?"
            params.append(config["wallet_address"])
            
        cursor = conn.execute(query, params)
        positions = cursor.fetchall()
    
    print(f"Checking {len(positions)} positions...")
    
    # Get position manager address and DEX type
    position_manager = None
    dex_type = "uniswap_v3"  # Default
    for dex in config.get("dexes", []):
        if dex["name"] == args.dex:
            position_manager = dex["position_manager"]
            dex_type = dex.get("type", "uniswap_v3")
            break
            
    if not position_manager:
        print(f"Could not find position manager for {args.dex}")
        return
        
    # Process each position with error handling
    for wallet, dex, token_id in positions:
        if dex != args.dex:
            continue
        try:
            fix_position_entry(conn, blockchain, wallet, dex, token_id, position_manager, dex_type,
                              debug=args.debug, dry_run=args.dry_run)
        except Exception as e:
            print(f"❌ Error processing {dex} #{token_id}: {e}")
            if args.debug:
                import traceback
                traceback.print_exc()
            # Continue with next position
    
    conn.close()
    print("\nDone!")


if __name__ == "__main__":
    main()
