#!/usr/bin/env python3
"""
Position Database Module for HyperEVM LP Monitor
Tracks historical position data for PnL and IL calculations

Version: 1.6.0
Developer: 8roku8.hl
"""

import sqlite3
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import os

class PositionDatabase:
    """Manages historical position data for PnL tracking"""
    
    def __init__(self, db_path="lp_positions.db"):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row  # Enable column access by name
        self.create_tables()
        self._entry_refresh_done = False  # Track if we've done initial refresh
        self.debug_mode = False  # Default debug mode
        
    def create_tables(self):
        """Create database tables for position tracking"""
        
        # Main position tracking table
        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS position_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                wallet_address TEXT NOT NULL,
                dex_name TEXT NOT NULL,
                token_id INTEGER NOT NULL,
                pair_name TEXT NOT NULL,
                token0_address TEXT NOT NULL,
                token1_address TEXT NOT NULL,
                token0_symbol TEXT NOT NULL,
                token1_symbol TEXT NOT NULL,
                
                -- Position data
                tick_lower INTEGER NOT NULL,
                tick_upper INTEGER NOT NULL,
                liquidity TEXT NOT NULL,
                in_range BOOLEAN NOT NULL,
                
                -- Current amounts
                amount0 REAL NOT NULL,
                amount1 REAL NOT NULL,
                
                -- Prices
                current_price REAL NOT NULL,
                token0_price_usd REAL,
                token1_price_usd REAL,
                
                -- Values
                position_value_usd REAL,
                
                -- Fees
                unclaimed_fee0 REAL DEFAULT 0,
                unclaimed_fee1 REAL DEFAULT 0,
                unclaimed_fees_usd REAL DEFAULT 0,
                
                -- Create unique index for position identification
                UNIQUE(wallet_address, dex_name, token_id, timestamp)
            )
        ''')
        
        # Position entry points (when position was first seen or created)
        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS position_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                wallet_address TEXT NOT NULL,
                dex_name TEXT NOT NULL,
                token_id INTEGER NOT NULL,
                
                -- Entry data
                entry_timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                acquired_timestamp REAL,  -- Unix timestamp when position was first acquired
                entry_price REAL NOT NULL,
                entry_amount0 REAL NOT NULL,
                entry_amount1 REAL NOT NULL,
                entry_value_usd REAL,
                
                -- Entry token prices
                entry_token0_price_usd REAL,
                entry_token1_price_usd REAL,
                
                -- Track if position is still active
                is_active BOOLEAN DEFAULT 1,
                exit_timestamp DATETIME,
                
                -- Cumulative fees collected
                total_fees_collected0 REAL DEFAULT 0,
                total_fees_collected1 REAL DEFAULT 0,
                total_fees_collected_usd REAL DEFAULT 0,
                
                UNIQUE(wallet_address, dex_name, token_id)
            )
        ''')
        
        # Fee collection events
        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS fee_collections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                wallet_address TEXT NOT NULL,
                dex_name TEXT NOT NULL,
                token_id INTEGER NOT NULL,
                
                fee_amount0 REAL NOT NULL,
                fee_amount1 REAL NOT NULL,
                fee_value_usd REAL,
                
                token0_price_usd REAL,
                token1_price_usd REAL
            )
        ''')
        
        # Performance metrics table (calculated periodically)
        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS performance_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                wallet_address TEXT NOT NULL,
                dex_name TEXT NOT NULL,
                token_id INTEGER NOT NULL,
                
                -- PnL metrics
                current_value_usd REAL,
                entry_value_usd REAL,
                pnl_usd REAL,
                pnl_percent REAL,
                
                -- IL metrics
                hodl_value_usd REAL,
                il_usd REAL,
                il_percent REAL,
                
                -- Fee metrics
                total_fees_earned_usd REAL,
                fee_apr REAL,
                
                -- Time metrics
                hours_in_position REAL,
                percent_time_in_range REAL
            )
        ''')
        
        # Add acquired_timestamp column if it doesn't exist (migration)
        try:
            self.conn.execute('ALTER TABLE position_entries ADD COLUMN acquired_timestamp REAL')
        except Exception:
            # Column already exists
            pass
        
        # Populate acquired_timestamp for existing entries that don't have it
        # This converts the entry_timestamp (datetime string) to Unix timestamp
        try:
            self.conn.execute('''
                UPDATE position_entries 
                SET acquired_timestamp = strftime('%s', entry_timestamp)
                WHERE acquired_timestamp IS NULL
            ''')
        except Exception:
            pass
        
        self.conn.commit()
    
    def record_position_snapshot(self, position, status, wallet_address, token_prices=None):
        """Record a snapshot of current position state"""
        try:
            # Ensure an entry exists as early as possible so PnL can compute even if
            # later snapshot value calculations fail.
            try:
                self.check_and_record_entry(position, status, wallet_address, token_prices)
            except Exception as _:
                # Non-fatal; continue to snapshot recording
                pass
            # Calculate USD values if prices available
            position_value_usd = None
            token0_price_usd = None
            token1_price_usd = None
            unclaimed_fees_usd = None
            
            if token_prices:
                token0_symbol = status.get('token0_symbol', '')
                token1_symbol = status.get('token1_symbol', '')
                
                if token0_symbol in token_prices:
                    token0_price_usd = token_prices[token0_symbol]
                if token1_symbol in token_prices:
                    token1_price_usd = token_prices[token1_symbol]
                
                # Calculate position value
                if token0_price_usd is not None and token1_price_usd is not None:
                    amt0 = status.get('amount0')
                    amt1 = status.get('amount1')
                    amt0 = 0 if amt0 is None else amt0
                    amt1 = 0 if amt1 is None else amt1
                    position_value_usd = (amt0 * float(token0_price_usd)) + (amt1 * float(token1_price_usd))
                    
                    # Calculate unclaimed fees value
                    if status.get('has_unclaimed_fees'):
                        # Guard against missing token prices and None fee amounts
                        unclaimed_fees_usd = 0
                        fee0 = status.get('fee_amount0')
                        fee1 = status.get('fee_amount1')
                        fee0 = 0 if fee0 is None else fee0
                        fee1 = 0 if fee1 is None else fee1
                        if token0_price_usd is not None:
                            unclaimed_fees_usd += float(fee0) * float(token0_price_usd)
                        if token1_price_usd is not None:
                            unclaimed_fees_usd += float(fee1) * float(token1_price_usd)
            
            # Normalize amounts to avoid None passing into NOT NULL columns
            ins_amount0 = status.get('amount0')
            ins_amount1 = status.get('amount1')
            ins_amount0 = 0 if ins_amount0 is None else ins_amount0
            ins_amount1 = 0 if ins_amount1 is None else ins_amount1

            self.conn.execute('''
                INSERT OR REPLACE INTO position_snapshots (
                    wallet_address, dex_name, token_id, pair_name,
                    token0_address, token1_address, token0_symbol, token1_symbol,
                    tick_lower, tick_upper, liquidity, in_range,
                    amount0, amount1, current_price,
                    token0_price_usd, token1_price_usd, position_value_usd,
                    unclaimed_fee0, unclaimed_fee1, unclaimed_fees_usd
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                wallet_address,
                position['dex_name'],
                position['token_id'],
                position['name'],
                position.get('token0_address', ''),
                position.get('token1_address', ''),
                status.get('token0_symbol', ''),
                status.get('token1_symbol', ''),
                position['tick_lower'],
                position['tick_upper'],
                str(position['liquidity']),
                status.get('in_range', False),
                ins_amount0,
                ins_amount1,
                status.get('current_price', 0),
                token0_price_usd,
                token1_price_usd,
                position_value_usd,
                status.get('fee_amount0', 0),
                status.get('fee_amount1', 0),
                unclaimed_fees_usd
            ))
            
            self.conn.commit()
            
        except Exception as e:
            print(f"Error recording position snapshot: {e}")
    
    def check_and_record_entry(self, position, status, wallet_address, token_prices=None):
        """Check if position is new and record entry point"""
        cursor = self.conn.execute('''
            SELECT * FROM position_entries 
            WHERE wallet_address = ? AND dex_name = ? AND token_id = ?
        ''', (wallet_address, position['dex_name'], position['token_id']))
        existing = cursor.fetchone()
        
        if not existing:
            # This is a new position, record entry point
            entry_value_usd = None
            token0_price_usd = None
            token1_price_usd = None
            # Preferred order: explicit entry amounts -> theoretical center amounts -> current snapshot amounts
            entry_amount0 = status.get('entry_amount0')
            entry_amount1 = status.get('entry_amount1')
            # Track whether amounts came from historical on-chain data
            chain_entry_amounts_provided = (
                (entry_amount0 is not None and entry_amount0 > 0) or
                (entry_amount1 is not None and entry_amount1 > 0)
            )
            
            # If we don't have explicit entry amounts from historical data, 
            # mark this position for later fix-up rather than using incorrect current data
            has_historical_data = (entry_amount0 is not None and entry_amount1 is not None and 
                                 (entry_amount0 > 0 or entry_amount1 > 0))
            
            if not has_historical_data:
                # For new positions without historical data, we have two strategies:
                # 1. If this is a very recent position (last few hours), use current amounts/prices
                # 2. Otherwise, mark for later historical lookup
                
                from datetime import datetime, timedelta
                is_very_recent = False
                
                # Check if position was acquired very recently (last 2 hours)
                acquired_ts = status.get('acquired_timestamp')
                if acquired_ts:
                    try:
                        acquired_dt = datetime.fromtimestamp(float(acquired_ts))
                        hours_since_acquired = (datetime.now() - acquired_dt).total_seconds() / 3600
                        is_very_recent = hours_since_acquired < 2.0
                    except Exception:
                        pass
                
                if is_very_recent:
                    # Use current amounts and prices for very recent positions
                    entry_amount0 = status.get('amount0', 0)
                    entry_amount1 = status.get('amount1', 0)
                    
                    # Calculate entry value using current prices (reasonable for new positions)
                    if token_prices:
                        token0_symbol = status.get('token0_symbol', '')
                        token1_symbol = status.get('token1_symbol', '')
                        if token0_symbol in token_prices and token1_symbol in token_prices:
                            token0_price_usd = token_prices[token0_symbol]
                            token1_price_usd = token_prices[token1_symbol]
                            entry_value_usd = float(entry_amount0) * float(token0_price_usd) + float(entry_amount1) * float(token1_price_usd)
                else:
                    # For older positions without historical data, use current amounts as placeholder
                    # but mark entry_value_usd as None to signal this needs historical lookup
                    entry_amount0 = status.get('amount0', 0)
                    entry_amount1 = status.get('amount1', 0)
                    entry_value_usd = None
                    token0_price_usd = None
                    token1_price_usd = None
                
            # Normalize amounts
            entry_amount0 = 0 if entry_amount0 is None else float(entry_amount0)
            entry_amount1 = 0 if entry_amount1 is None else float(entry_amount1)
            # Prefer precise entry USD inferred from chain when present
            if status.get('entry_value_usd') is not None and status.get('entry_value_usd') > 0:
                # Direct entry value from blockchain historical data
                entry_value_usd = float(status.get('entry_value_usd'))
                token0_price_usd = status.get('entry_token0_price_usd')
                token1_price_usd = status.get('entry_token1_price_usd')
            elif status.get('entry_token0_price_usd') is not None and status.get('entry_token1_price_usd') is not None:
                # Only combine historical entry prices with historical entry AMOUNTS.
                # If we don't have entry amounts from chain, do NOT multiply current amounts by historical prices.
                if chain_entry_amounts_provided:
                    token0_price_usd = status.get('entry_token0_price_usd')
                    token1_price_usd = status.get('entry_token1_price_usd')
                    entry_value_usd = float(entry_amount0) * float(token0_price_usd) + float(entry_amount1) * float(token1_price_usd)
            
            # If historical data was found, use it
            if entry_value_usd is None or entry_value_usd <= 0:
                if status.get('historical_entry_value_usd'):
                    entry_value_usd = status.get('historical_entry_value_usd')
                    token0_price_usd = status.get('historical_token0_price_usd')
                    token1_price_usd = status.get('historical_token1_price_usd')

            # REMOVED: All fallback estimation logic has been removed.
            # The monitor now relies exclusively on the get_initial_position_entry
            # function in blockchain.py to provide the true historical entry data.
            # If historical data cannot be found, PnL will be deferred (remain $0).

            # Store the acquired timestamp from blockchain data if available
            acquired_ts = status.get('acquired_timestamp')
            
            self.conn.execute('''
                INSERT INTO position_entries (
                    wallet_address, dex_name, token_id,
                    entry_price, entry_amount0, entry_amount1,
                    entry_value_usd, entry_token0_price_usd, entry_token1_price_usd,
                    acquired_timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                wallet_address,
                position['dex_name'],
                position['token_id'],
                float(status.get('entry_price_at_entry', status.get('current_price', 0) or 0.0)),
                entry_amount0,
                entry_amount1,
                entry_value_usd,
                token0_price_usd,
                token1_price_usd,
                acquired_ts
            ))
            
            # If this position lacks proper entry data, mark it for automatic fixing
            if entry_value_usd is None:
                if hasattr(self, '_positions_needing_fix'):
                    self._positions_needing_fix.add((wallet_address, position['dex_name'], position['token_id']))
                else:
                    self._positions_needing_fix = {(wallet_address, position['dex_name'], position['token_id'])}
            
            self.conn.commit()
        else:
            # Backfill/Update if we have better on-chain entry data
            # Check if we have precise historical data from blockchain
            precise_entry_value = status.get('entry_value_usd')
            if precise_entry_value is not None and precise_entry_value > 0:
                # We have precise historical data from blockchain
                old_value = existing['entry_value_usd'] or 0
                
                # Always update if old value is missing or significantly different (>10%)
                should_update = (old_value <= 0 or 
                               abs(precise_entry_value - old_value) / max(old_value, 1) > 0.1)
                
                if should_update:
                    entry_amount0 = status.get('entry_amount0', existing['entry_amount0'] or 0)
                    entry_amount1 = status.get('entry_amount1', existing['entry_amount1'] or 0)
                    token0_price = status.get('entry_token0_price_usd')
                    token1_price = status.get('entry_token1_price_usd')
                    entry_price = status.get('entry_price_at_entry', existing['entry_price'] or 0)
                    
                    self.conn.execute('''
                        UPDATE position_entries SET
                            entry_amount0 = ?,
                            entry_amount1 = ?,
                            entry_value_usd = ?,
                            entry_token0_price_usd = ?,
                            entry_token1_price_usd = ?,
                            entry_price = ?
                        WHERE wallet_address = ? AND dex_name = ? AND token_id = ?
                    ''', (
                        entry_amount0,
                        entry_amount1,
                        precise_entry_value,
                        token0_price,
                        token1_price,
                        entry_price,
                        wallet_address,
                        position['dex_name'],
                        position['token_id']
                    ))
                    self.conn.commit()
                    
                    if self.debug_mode:
                        print(f"Updated entry for {position['dex_name']} #{position['token_id']}: ")
                        print(f"  Old value: ${old_value:.2f}, New value: ${precise_entry_value:.2f}")
                    return
            
            # Auto-baseline existing entries that look incorrect for stable pairs
            # This handles cases where the entry was created before proper baseline logic
            if token_prices and existing['entry_value_usd'] is not None:
                try:
                    from price_utils import is_stablecoin
                    t0s = status.get('token0_symbol', '')
                    t1s = status.get('token1_symbol', '')
                    p0_live = token_prices.get(t0s)
                    p1_live = token_prices.get(t1s)
                    
                    if p0_live is not None and p1_live is not None and (is_stablecoin(t0s) or is_stablecoin(t1s)):
                        # Calculate what current amounts would be worth at current USD prices
                        current_amount0 = status.get('amount0', 0) or 0
                        current_amount1 = status.get('amount1', 0) or 0
                        current_usd_value = float(current_amount0) * float(p0_live) + float(current_amount1) * float(p1_live)
                        
                        old_entry_value = float(existing['entry_value_usd'])
                        
                        # If entry value is significantly higher than current value (suggesting wrong baseline),
                        # and the position is relatively recent (< 7 days), auto-correct to current value
                        try:
                            entry_ts = existing.get('entry_timestamp')
                            if entry_ts:
                                from datetime import datetime, timedelta
                                entry_dt = datetime.fromisoformat(entry_ts)
                                age_hours = (datetime.now() - entry_dt).total_seconds() / 3600
                                
                                # For positions < 7 days old where entry is >20% higher than current
                                if (age_hours < 168 and old_entry_value > current_usd_value * 1.2):
                                    # Baseline to current value minus any unclaimed fees
                                    unclaimed_fees_usd = 0
                                    fee0 = status.get('fee_amount0', 0) or 0
                                    fee1 = status.get('fee_amount1', 0) or 0
                                    unclaimed_fees_usd = float(fee0) * float(p0_live) + float(fee1) * float(p1_live)
                                    
                                    new_entry_value = current_usd_value - unclaimed_fees_usd
                                    
                                    self.conn.execute('''
                                        UPDATE position_entries SET
                                            entry_value_usd = ?,
                                            entry_token0_price_usd = ?,
                                            entry_token1_price_usd = ?
                                        WHERE wallet_address = ? AND dex_name = ? AND token_id = ?
                                    ''', (
                                        new_entry_value,
                                        p0_live,
                                        p1_live,
                                        wallet_address,
                                        position['dex_name'],
                                        position['token_id']
                                    ))
                                    self.conn.commit()
                                    
                                    if self.debug_mode:
                                        print(f"Auto-baselined entry for {position['dex_name']} #{position['token_id']}")
                                        print(f"  Old: ${old_entry_value:.2f}, New: ${new_entry_value:.2f}")
                                    return
                        except Exception:
                            pass
                except Exception:
                    pass
            
            # Original backfill logic for other cases
            entry_amount0 = status.get('entry_amount0')
            entry_amount1 = status.get('entry_amount1')
            # If not provided in status, prefer existing, otherwise fall back to current snapshot amounts
            if entry_amount0 is None or entry_amount0 == 0:
                entry_amount0 = existing['entry_amount0'] if existing['entry_amount0'] is not None and existing['entry_amount0'] != 0 else status.get('theoretical_amount0', status.get('amount0'))
            if entry_amount1 is None or entry_amount1 == 0:
                entry_amount1 = existing['entry_amount1'] if existing['entry_amount1'] is not None and existing['entry_amount1'] != 0 else status.get('theoretical_amount1', status.get('amount1'))
            entry_amount0 = 0 if entry_amount0 is None else float(entry_amount0)
            entry_amount1 = 0 if entry_amount1 is None else float(entry_amount1)
            token0_precise = status.get('entry_token0_price_usd')
            token1_precise = status.get('entry_token1_price_usd')
            should_try_update = token0_precise is not None and token1_precise is not None
            if should_try_update:
                new_value = entry_amount0 * float(token0_precise) + entry_amount1 * float(token1_precise)
                old_value = existing['entry_value_usd']
                missing_prices = existing['entry_token0_price_usd'] is None or existing['entry_token1_price_usd'] is None
                large_diff = False
                try:
                    if old_value is None:
                        large_diff = True
                    else:
                        denom = max(abs(float(old_value)), 1e-9)
                        large_diff = abs(new_value - float(old_value)) / denom > 0.02  # >2% difference
                except Exception:
                    large_diff = True

                if missing_prices or large_diff:
                    self.conn.execute('''
                        UPDATE position_entries
                        SET entry_price = ?, entry_amount0 = ?, entry_amount1 = ?,
                            entry_value_usd = ?, entry_token0_price_usd = ?, entry_token1_price_usd = ?
                        WHERE wallet_address = ? AND dex_name = ? AND token_id = ?
                    ''', (
                        status.get('entry_price_at_entry', status.get('current_price', existing['entry_price'])),
                        entry_amount0,
                        entry_amount1,
                        new_value,
                        float(token0_precise),
                        float(token1_precise),
                        wallet_address,
                        position['dex_name'],
                        position['token_id']
                    ))
                    self.conn.commit()

            # If entry still looks empty/zero, backfill using current snapshot amounts/prices
            if (existing['entry_value_usd'] is None or existing['entry_value_usd'] <= 0 or
                ((existing['entry_amount0'] is None or existing['entry_amount0'] == 0) and (existing['entry_amount1'] is None or existing['entry_amount1'] == 0))):
                token0_price_usd = None
                token1_price_usd = None
                if token_prices:
                    t0 = status.get('token0_symbol', '')
                    t1 = status.get('token1_symbol', '')
                    token0_price_usd = token_prices.get(t0)
                    token1_price_usd = token_prices.get(t1)
                if token0_price_usd is not None and token1_price_usd is not None:
                    fallback_value = float(entry_amount0) * float(token0_price_usd) + float(entry_amount1) * float(token1_price_usd)
                    self.conn.execute('''
                        UPDATE position_entries
                        SET entry_price = ?, entry_amount0 = ?, entry_amount1 = ?,
                            entry_value_usd = ?, entry_token0_price_usd = ?, entry_token1_price_usd = ?
                        WHERE wallet_address = ? AND dex_name = ? AND token_id = ?
                    ''', (
                        status.get('entry_price_at_entry', status.get('current_price', existing['entry_price'])),
                        float(entry_amount0),
                        float(entry_amount1),
                        fallback_value,
                        float(token0_price_usd),
                        float(token1_price_usd),
                        wallet_address,
                        position['dex_name'],
                        position['token_id']
                    ))
                    self.conn.commit()
    
    def get_position_entry(self, wallet_address, dex_name, token_id):
        """Get entry point data for a position"""
        cursor = self.conn.execute('''
            SELECT * FROM position_entries
            WHERE wallet_address = ? AND dex_name = ? AND token_id = ?
        ''', (wallet_address, dex_name, token_id))
        
        return cursor.fetchone()
    
    def mark_entries_for_refresh(self, wallet_address=None, positions_with_status=None):
        """Check for active positions with missing entry values (non-blocking)"""
        if hasattr(self, '_entry_refresh_done') and self._entry_refresh_done:
            return
            
        try:
            # Get positions with active liquidity if provided
            active_token_ids = set()
            if positions_with_status:
                for position, status in positions_with_status:
                    liquidity = float(position.get("liquidity", 0))
                    if liquidity > 0:
                        active_token_ids.add(int(position["token_id"]))
            
            # Count all entries that need refresh
            query = "SELECT token_id, COUNT(*) as count FROM position_entries WHERE entry_value_usd IS NULL OR entry_value_usd <= 0"
            params = []
            if wallet_address:
                query += " AND wallet_address = ?"
                params.append(wallet_address)
            query += " GROUP BY token_id"
                
            cursor = self.conn.execute(query, params)
            results = cursor.fetchall()
            
            active_count = 0
            inactive_count = 0
            
            for row in results:
                token_id = row['token_id']
                if positions_with_status and token_id in active_token_ids:
                    active_count += 1
                else:
                    inactive_count += 1
            
            if active_count > 0:
                print(f"📊 {active_count} active positions need entry value refresh (will update automatically)")
            
            if inactive_count > 0:
                print(f"📊 {inactive_count} inactive positions have missing entry data (skipping)")
            
            self._entry_refresh_done = True
        except Exception as e:
            if hasattr(self, 'debug_mode') and self.debug_mode:
                print(f"Error checking entries for refresh: {e}")
    
    def calculate_pnl_metrics(self, position, status, wallet_address, token_prices=None):
        """Calculate PnL and IL metrics for a position"""
        # Mark entries for refresh on first run (non-blocking)
        if not hasattr(self, '_entry_refresh_done'):
            self._entry_refresh_done = False
        if not self._entry_refresh_done:
            # We'll call this from display.py with position data
            pass
            
        entry = self.get_position_entry(wallet_address, position['dex_name'], position['token_id'])
        
        if not entry or not token_prices:
            return None
        
        token0_symbol = status.get('token0_symbol', '')
        token1_symbol = status.get('token1_symbol', '')
        
        # Get current prices (avoid falsy checks; 0.0 is valid for None only when unknown)
        token0_price_usd = token_prices.get(token0_symbol)
        token1_price_usd = token_prices.get(token1_symbol)
        
        if token0_price_usd is None:
            token0_price_usd = entry['entry_token0_price_usd'] if 'entry_token0_price_usd' in entry.keys() else None
        if token1_price_usd is None:
            token1_price_usd = entry['entry_token1_price_usd'] if 'entry_token1_price_usd' in entry.keys() else None
        if token0_price_usd is None:
            token0_price_usd = status.get('entry_token0_price_usd')
        if token1_price_usd is None:
            token1_price_usd = status.get('entry_token1_price_usd')
        
        if token0_price_usd is None or token1_price_usd is None:
            return None
        
        # Calculate current value
        amt0_now = status.get('amount0')
        amt1_now = status.get('amount1')
        amt0_now = 0 if amt0_now is None else amt0_now
        amt1_now = 0 if amt1_now is None else amt1_now
        current_value = (amt0_now * float(token0_price_usd)) + (amt1_now * float(token1_price_usd))
        
        # Entry value - if None, this position needs proper historical entry data
        entry_value = entry['entry_value_usd'] if entry['entry_value_usd'] is not None else 0
        
        # Skip PnL calculation for positions that don't have proper entry data yet
        if entry['entry_value_usd'] is None or entry['entry_value_usd'] <= 0:
            return None
        
        # BUGFIX: Additional safeguard against positions with artificially high entry values
        # If entry value seems unreasonably high compared to current value (>50% higher),
        # it likely used current prices incorrectly. Skip PnL calculation until fixed.
        if current_value > 0 and entry_value > current_value * 1.5:
            return None
        
        # Calculate what we would have if we just held the tokens (HODL)
        ent_amt0 = entry['entry_amount0'] if entry['entry_amount0'] is not None else 0
        ent_amt1 = entry['entry_amount1'] if entry['entry_amount1'] is not None else 0
        hodl_value = (float(ent_amt0) * float(token0_price_usd)) + (float(ent_amt1) * float(token1_price_usd))
        
        # Get total fees earned
        total_fees = self.get_total_fees_collected(wallet_address, position['dex_name'], position['token_id'])
        total_fees_usd = (float(total_fees['total_fees0']) * float(token0_price_usd)) + (float(total_fees['total_fees1']) * float(token1_price_usd))
        
        # Add current unclaimed fees
        fee0 = status.get('fee_amount0')
        fee1 = status.get('fee_amount1')
        fee0 = 0 if fee0 is None else fee0
        fee1 = 0 if fee1 is None else fee1
        unclaimed_fees_usd = (float(fee0) * float(token0_price_usd)) + (float(fee1) * float(token1_price_usd))
        
        total_fees_usd += unclaimed_fees_usd
        
        # PnL calculation (including fees)
        pnl_usd = current_value + total_fees_usd - entry_value
        pnl_percent = (pnl_usd / entry_value * 100) if entry_value > 0 else 0
        
        # Impermanent Loss calculation
        # IL = Current Value + Fees - HODL Value
        il_usd = current_value + total_fees_usd - hodl_value
        il_percent = (il_usd / hodl_value * 100) if hodl_value > 0 else 0
        
        # Calculate time in position (prefer on-chain acquired timestamp, fallback to database entry timestamp)
        acquired_ts = status.get('acquired_timestamp')
        if acquired_ts and acquired_ts > 0:
            entry_time = datetime.fromtimestamp(acquired_ts)
        elif entry['acquired_timestamp'] and entry['acquired_timestamp'] > 0:
            # Use stored acquired timestamp from database as fallback
            entry_time = datetime.fromtimestamp(entry['acquired_timestamp'])
        else:
            # Final fallback: use database entry timestamp
            entry_time = datetime.fromisoformat(entry['entry_timestamp'])
        current_time = datetime.now()
        hours_in_position = (current_time - entry_time).total_seconds() / 3600
        
        # Calculate APR from fees
        if hours_in_position > 0 and entry_value > 0:
            annualized_hours = 8760  # Hours in a year
            fee_apr = (total_fees_usd / entry_value) * (annualized_hours / hours_in_position) * 100
        else:
            fee_apr = 0
        
        return {
            'current_value_usd': current_value,
            'entry_value_usd': entry_value,
            'pnl_usd': pnl_usd,
            'pnl_percent': pnl_percent,
            'hodl_value_usd': hodl_value,
            'il_usd': il_usd,
            'il_percent': il_percent,
            'total_fees_earned_usd': total_fees_usd,
            'fee_apr': fee_apr,
            'hours_in_position': hours_in_position,
            'entry_price': entry['entry_price'],
            'current_price': status.get('current_price', 0),
            'price_change_percent': ((status.get('current_price', 0) - entry['entry_price']) / entry['entry_price'] * 100) if entry['entry_price'] > 0 else 0
        }
    
    def get_total_fees_collected(self, wallet_address, dex_name, token_id):
        """Get total fees collected for a position"""
        cursor = self.conn.execute('''
            SELECT 
                COALESCE(SUM(fee_amount0), 0) as total_fees0,
                COALESCE(SUM(fee_amount1), 0) as total_fees1,
                COALESCE(SUM(fee_value_usd), 0) as total_fees_usd
            FROM fee_collections
            WHERE wallet_address = ? AND dex_name = ? AND token_id = ?
        ''', (wallet_address, dex_name, token_id))
        
        result = cursor.fetchone()
        return {
            'total_fees0': result['total_fees0'] or 0,
            'total_fees1': result['total_fees1'] or 0,
            'total_fees_usd': result['total_fees_usd'] or 0
        }
    
    def record_fee_collection(self, wallet_address, dex_name, token_id, fee0, fee1, token_prices=None):
        """Record a fee collection event"""
        fee_value_usd = None
        token0_price_usd = None
        token1_price_usd = None
        
        if token_prices:
            # You'd need to pass token symbols too for proper lookup
            # This is simplified
            fee_value_usd = 0  # Calculate based on prices
        
        self.conn.execute('''
            INSERT INTO fee_collections (
                wallet_address, dex_name, token_id,
                fee_amount0, fee_amount1, fee_value_usd,
                token0_price_usd, token1_price_usd
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            wallet_address, dex_name, token_id,
            fee0, fee1, fee_value_usd,
            token0_price_usd, token1_price_usd
        ))
        
        self.conn.commit()
    
    def get_portfolio_summary(self, wallet_address):
        """Get overall portfolio performance summary"""
        cursor = self.conn.execute('''
            SELECT 
                COUNT(DISTINCT token_id) as total_positions,
                SUM(current_value_usd) as total_value,
                SUM(pnl_usd) as total_pnl,
                SUM(il_usd) as total_il,
                SUM(total_fees_earned_usd) as total_fees,
                AVG(fee_apr) as avg_apr
            FROM performance_metrics
            WHERE wallet_address = ? 
            AND timestamp = (
                SELECT MAX(timestamp) FROM performance_metrics WHERE wallet_address = ?
            )
        ''', (wallet_address, wallet_address))
        
        return cursor.fetchone()
    
    def cleanup_old_snapshots(self, days_to_keep=30):
        """Clean up old snapshots to prevent database bloat"""
        cutoff_date = datetime.now() - timedelta(days=days_to_keep)
        
        self.conn.execute('''
            DELETE FROM position_snapshots 
            WHERE timestamp < ?
        ''', (cutoff_date,))
        
        self.conn.commit()
    
    def close(self):
        """Close database connection"""
        self.conn.close()