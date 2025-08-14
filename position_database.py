#!/usr/bin/env python3
"""
Position Database Module for HyperEVM LP Monitor
Tracks historical position data for PnL and IL calculations

Version: 1.6.0
Developer: 8roku8.hl + Claude
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
        
        self.conn.commit()
    
    def record_position_snapshot(self, position, status, wallet_address, token_prices=None):
        """Record a snapshot of current position state"""
        try:
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
                if token0_price_usd and token1_price_usd:
                    position_value_usd = (
                        status['amount0'] * token0_price_usd +
                        status['amount1'] * token1_price_usd
                    )
                    
                    # Calculate unclaimed fees value
                    if status.get('has_unclaimed_fees'):
                        unclaimed_fees_usd = (
                            status.get('fee_amount0', 0) * token0_price_usd +
                            status.get('fee_amount1', 0) * token1_price_usd
                        )
            
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
                status.get('amount0', 0),
                status.get('amount1', 0),
                status.get('current_price', 0),
                token0_price_usd,
                token1_price_usd,
                position_value_usd,
                status.get('fee_amount0', 0),
                status.get('fee_amount1', 0),
                unclaimed_fees_usd
            ))
            
            self.conn.commit()
            
            # Check if this is a new position (entry point)
            self.check_and_record_entry(position, status, wallet_address, token_prices)
            
        except Exception as e:
            print(f"Error recording position snapshot: {e}")
    
    def check_and_record_entry(self, position, status, wallet_address, token_prices=None):
        """Check if position is new and record entry point"""
        cursor = self.conn.execute('''
            SELECT id FROM position_entries 
            WHERE wallet_address = ? AND dex_name = ? AND token_id = ?
        ''', (wallet_address, position['dex_name'], position['token_id']))
        
        if not cursor.fetchone():
            # This is a new position, record entry point
            entry_value_usd = None
            token0_price_usd = None
            token1_price_usd = None
            
            if token_prices:
                token0_symbol = status.get('token0_symbol', '')
                token1_symbol = status.get('token1_symbol', '')
                
                if token0_symbol in token_prices:
                    token0_price_usd = token_prices[token0_symbol]
                if token1_symbol in token_prices:
                    token1_price_usd = token_prices[token1_symbol]
                
                if token0_price_usd and token1_price_usd:
                    entry_value_usd = (
                        status['amount0'] * token0_price_usd +
                        status['amount1'] * token1_price_usd
                    )
            
            self.conn.execute('''
                INSERT INTO position_entries (
                    wallet_address, dex_name, token_id,
                    entry_price, entry_amount0, entry_amount1,
                    entry_value_usd, entry_token0_price_usd, entry_token1_price_usd
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                wallet_address,
                position['dex_name'],
                position['token_id'],
                status.get('current_price', 0),
                status.get('amount0', 0),
                status.get('amount1', 0),
                entry_value_usd,
                token0_price_usd,
                token1_price_usd
            ))
            
            self.conn.commit()
    
    def get_position_entry(self, wallet_address, dex_name, token_id):
        """Get entry point data for a position"""
        cursor = self.conn.execute('''
            SELECT * FROM position_entries
            WHERE wallet_address = ? AND dex_name = ? AND token_id = ?
        ''', (wallet_address, dex_name, token_id))
        
        return cursor.fetchone()
    
    def calculate_pnl_metrics(self, position, status, wallet_address, token_prices=None):
        """Calculate PnL and IL metrics for a position"""
        entry = self.get_position_entry(wallet_address, position['dex_name'], position['token_id'])
        
        if not entry or not token_prices:
            return None
        
        token0_symbol = status.get('token0_symbol', '')
        token1_symbol = status.get('token1_symbol', '')
        
        # Get current prices
        token0_price_usd = token_prices.get(token0_symbol, 0)
        token1_price_usd = token_prices.get(token1_symbol, 0)
        
        if not token0_price_usd or not token1_price_usd:
            return None
        
        # Calculate current value
        current_value = (
            status['amount0'] * token0_price_usd +
            status['amount1'] * token1_price_usd
        )
        
        # Entry value
        entry_value = entry['entry_value_usd'] or 0
        
        # Calculate what we would have if we just held the tokens (HODL)
        hodl_value = (
            entry['entry_amount0'] * token0_price_usd +
            entry['entry_amount1'] * token1_price_usd
        )
        
        # Get total fees earned
        total_fees = self.get_total_fees_collected(wallet_address, position['dex_name'], position['token_id'])
        total_fees_usd = (
            total_fees['total_fees0'] * token0_price_usd +
            total_fees['total_fees1'] * token1_price_usd
        )
        
        # Add current unclaimed fees
        unclaimed_fees_usd = (
            status.get('fee_amount0', 0) * token0_price_usd +
            status.get('fee_amount1', 0) * token1_price_usd
        )
        
        total_fees_usd += unclaimed_fees_usd
        
        # PnL calculation (including fees)
        pnl_usd = current_value + total_fees_usd - entry_value
        pnl_percent = (pnl_usd / entry_value * 100) if entry_value > 0 else 0
        
        # Impermanent Loss calculation
        # IL = Current Value + Fees - HODL Value
        il_usd = current_value + total_fees_usd - hodl_value
        il_percent = (il_usd / hodl_value * 100) if hodl_value > 0 else 0
        
        # Calculate time in position
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