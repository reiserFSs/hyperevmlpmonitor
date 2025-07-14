#!/usr/bin/env python3
"""
Display Management Module for HyperEVM LP Monitor
Handles colors, formatting, and UI display functions

UPDATED VERSION: Added unclaimed fee display

Version: 1.4.1 (With Fee Display)
Developer: 8roku8.hl
"""

import os
from datetime import datetime
from constants import VERSION, DEVELOPER
from utils import (
    format_price, format_token_amount, format_price_percentage_safe,
    format_fees_display, has_significant_fees
)

class Colors:
    """Simplified color management with scheme support"""
    # Essential colors only
    RED = '\033[91m'      # Danger/Error
    GREEN = '\033[92m'    # Success/Safe
    YELLOW = '\033[93m'   # Warning
    WHITE = '\033[97m'    # Important text
    BOLD = '\033[1m'      # Headers
    END = '\033[0m'       # Reset
    
    @classmethod
    def get_minimal_scheme(cls):
        """Return minimal color scheme with just red/green for status"""
        return {
            'danger': cls.RED,
            'safe': cls.GREEN,
            'warning': cls.YELLOW,
            'text': cls.WHITE,
            'bold': cls.BOLD,
            'end': cls.END
        }
    
    @classmethod
    def get_no_color_scheme(cls):
        """Return scheme with no colors at all"""
        return {
            'danger': '',
            'safe': '',
            'warning': '',
            'text': '',
            'bold': '',
            'end': ''
        }
    
    @classmethod
    def get_full_color_scheme(cls):
        """Return full color scheme with all colors"""
        return {
            'danger': cls.RED,
            'safe': cls.GREEN,
            'warning': cls.YELLOW,
            'text': cls.WHITE,
            'bold': cls.BOLD,
            'end': cls.END,
            # Additional colors for full scheme
            'blue': '\033[94m',
            'purple': '\033[95m',
            'cyan': '\033[96m',
            'bg_red': '\033[101m',
            'bg_green': '\033[102m',
            'bg_yellow': '\033[103m',
            'underline': '\033[4m'
        }

class DisplayManager:
    """Manages all display and UI functionality"""
    
    def __init__(self, config):
        self.config = config
        self.setup_color_scheme()
        
    def setup_color_scheme(self):
        """Setup color scheme based on config"""
        color_scheme = self.config.get("display_settings", {}).get("color_scheme", "minimal")
        
        if color_scheme == "none":
            self.colors = Colors.get_no_color_scheme()
        elif color_scheme == "full":
            self.colors = Colors.get_full_color_scheme()
        else:  # minimal (default)
            self.colors = Colors.get_minimal_scheme()
    
    def c(self, color_name):
        """Get color code for specified color name"""
        return self.colors.get(color_name, '')
    
    def print_header(self):
        """Print stylized header with simplified styling"""
        print(f"{self.c('bold')}")
        print("╔══════════════════════════════════════════════════════════════╗")
        print("║                 💧 HYPEREVM LP MONITOR                       ║")
        print("║                  Multi-DEX Position Tracker                 ║")
        print(f"║                    v{VERSION} by {DEVELOPER}                      ║")
        print("╚══════════════════════════════════════════════════════════════╝")
        print(f"{self.c('end')}")
    
    def print_separator(self):
        """Print a visual separator"""
        print("=" * 70)
    
    def print_monitoring_header(self, wallet, positions, dexes, check_interval, notifications_enabled, notification_type, notification_settings):
        """Print monitoring header with current status"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"{self.c('bold')}🕐 Last Update: {timestamp}{self.c('end')}")
        print(f"👛 Wallet: {wallet[:6]}...{wallet[-4:]}")
        print(f"📊 Monitoring {len(positions)} LP positions")
        
        # Show DEX breakdown
        dex_counts = {}
        for position in positions:
            dex_name = position["dex_name"]
            dex_counts[dex_name] = dex_counts.get(dex_name, 0) + 1
        
        dex_summary = ", ".join([f"{count} on {dex}" for dex, count in dex_counts.items()])
        print(f"🏪 DEX Distribution: {dex_summary}")
        
        # Show next check time
        next_check = datetime.fromtimestamp(time.time() + check_interval)
        print(f"⏰ Next check: {next_check.strftime('%H:%M:%S')}")
        
        # Show notification status
        if notifications_enabled:
            time_since_last = time.time() - notification_settings.get("last_notification_time", 0)
            cooldown = notification_settings.get("cooldown", 3600)
            time_until_next = max(0, cooldown - time_since_last)
            if time_until_next > 0:
                next_notification = datetime.fromtimestamp(time.time() + time_until_next)
                print(f"🔔 Next notification: {next_notification.strftime('%H:%M:%S')}")
            else:
                print("🔔 Notification ready")
        
        self.print_separator()
    
    def print_position_status(self, position, status, danger_threshold, warning_threshold, risk_level, closer_distance_pct):
        """Enhanced position status display with fee information"""
        name = position["name"]
        dex_name = status["dex_name"]
        dex_type = status.get("dex_type", "uniswap_v3")
        method = status.get("method", "unknown")
        
        # Calculate distances as percentages for display
        range_size = position['tick_upper'] - position['tick_lower']
        lower_distance_pct = status["distance_to_lower"] / range_size * 100
        upper_distance_pct = status["distance_to_upper"] / range_size * 100
        
        # Calculate price-based percentages
        from utils import calculate_price_based_percentages, is_full_range_position, format_price_percentage_safe
        price_lower_pct, price_upper_pct = calculate_price_based_percentages(
            status["current_price"], status["lower_price"], status["upper_price"]
        )
        
        # Check if this is a full-range position
        is_full_range = is_full_range_position(position['tick_lower'], position['tick_upper'])
        
        closer_to_lower = status["distance_to_lower"] < status["distance_to_upper"]
        
        # === HEADER SECTION ===
        print(f"\n{self.c('bold')}📍 {name} (Token ID: {status['token_id']}){self.c('end')}")
        print(f"🏪 DEX: {self.c('bold')}{dex_name}{self.c('end')} ({dex_type})")
        if method != "unknown":
            print(f"📡 Method: {method}")
        print(f"Pool Address: {position['pool_address'][:10]}...{position['pool_address'][-6:]}")
        
        # Show raw data if enabled
        if self.config.get("display_settings", {}).get("show_raw_data") and status.get("raw_data"):
            print(f"🔍 Raw Data: {status['raw_data']}")
        
        print()  # Spacing after header
        
        # === POSITION COMPOSITION SECTION ===
        show_theoretical = self.config.get("display_settings", {}).get("show_theoretical_amounts", True)
        
        if status["in_range"]:
            # Show current amounts when in range
            print(f"{self.c('bold')}💼 Position:{self.c('end')} {format_token_amount(status['amount0'], status['token0_symbol'])} + {format_token_amount(status['amount1'], status['token1_symbol'])}")
        else:
            # Show actual amounts (which will be 0 for one token when out of range)
            print(f"{self.c('bold')}💼 Current Position:{self.c('end')} {format_token_amount(status['amount0'], status['token0_symbol'])} + {format_token_amount(status['amount1'], status['token1_symbol'])}")
            
            # Show what the position would look like if in range (theoretical amounts)
            if show_theoretical:
                print(f"🔮 If In Range (center): {format_token_amount(status['theoretical_amount0'], status['token0_symbol'])} + {format_token_amount(status['theoretical_amount1'], status['token1_symbol'])}")
        
        # === UNCLAIMED FEES SECTION ===
        show_fees = self.config.get("display_settings", {}).get("show_unclaimed_fees", True)
        if show_fees:
            self.print_fee_info(status)
        
        print()  # Spacing after position composition
        
        # === PRICE INFORMATION SECTION ===
        print(f"{self.c('bold')}💹 Current Price:{self.c('end')} {format_price(status['current_price'])}")
        
        if is_full_range:
            print(f"{self.c('bold')}📊 Range:{self.c('end')} Full Range (Unlimited)")
            print(f"{self.c('bold')}🎯 Current Tick:{self.c('end')} {status['current_tick']} (Full Range: {position['tick_lower']} to {position['tick_upper']})")
        else:
            print(f"{self.c('bold')}📊 Range:{self.c('end')} {format_price(status['lower_price'])} - {format_price(status['upper_price'])}")
            print(f"{self.c('bold')}🎯 Current Tick:{self.c('end')} {status['current_tick']} (Range: {position['tick_lower']} to {position['tick_upper']})")
        
        print()  # Spacing after price information
        
        # === RISK ANALYSIS SECTION ===
        print(f"{self.c('bold')}📏 Range Position:{self.c('end')} {lower_distance_pct:.1f}% from lower / {upper_distance_pct:.1f}% from upper")
        
        if is_full_range:
            print(f"{self.c('bold')}📈 Price Movements:{self.c('end')} Full Range Position - No Exit Risk")
        else:
            print(f"{self.c('bold')}📈 Price Movements:{self.c('end')} {format_price_percentage_safe(price_lower_pct)} to lower / {format_price_percentage_safe(price_upper_pct)} to upper")
        
        # Show dynamic thresholds for this position
        if is_full_range:
            print(f"{self.c('bold')}🎯 Position Type:{self.c('end')} Full Range - Maximum Liquidity Coverage")
        else:
            print(f"{self.c('bold')}🎯 Dynamic Thresholds:{self.c('end')} {danger_threshold:.1f}% danger / {warning_threshold:.1f}% warning (based on {range_size} tick range)")
        
        print()  # Spacing before status section
        
        # === STATUS SECTION ===
        if status["in_range"]:
            if is_full_range:
                status_icon = f"{self.c('safe')}✅ FULL RANGE{self.c('end')}"
                print(f"{status_icon} {self.c('safe')}Full range position - Always earning fees!{self.c('end')}")
                print(f"   {self.c('safe')}Covers entire price spectrum - no exit risk{self.c('end')}")
                print(f"   {self.c('safe')}Maximum capital efficiency for volatile markets{self.c('end')}")
            elif risk_level == "danger":
                status_icon = f"{self.c('danger')}🚨 DANGER{self.c('end')}"
                edge_name = "LOWER" if closer_to_lower else "UPPER"
                price_edge_pct = abs(price_lower_pct) if closer_to_lower else price_upper_pct
                print(f"{status_icon} {self.c('danger')}Getting very close to {edge_name} bound!{self.c('end')}")
                print(f"   {self.c('danger')}Range position: {closer_distance_pct:.1f}% from edge (< {danger_threshold:.1f}% threshold){self.c('end')}")
                if price_edge_pct != float('inf'):
                    print(f"   {self.c('danger')}Price movement: {format_price_percentage_safe(price_edge_pct)} to exit range{self.c('end')}")
            elif risk_level == "warning":
                status_icon = f"{self.c('warning')}⚠️  WARNING{self.c('end')}"
                edge_name = "LOWER" if closer_to_lower else "UPPER"
                price_edge_pct = abs(price_lower_pct) if closer_to_lower else price_upper_pct
                print(f"{status_icon} {self.c('warning')}Getting close to {edge_name} bound{self.c('end')}")
                print(f"   {self.c('warning')}Range position: {closer_distance_pct:.1f}% from edge (< {warning_threshold:.1f}% threshold){self.c('end')}")
                if price_edge_pct != float('inf'):
                    print(f"   {self.c('warning')}Price movement: {format_price_percentage_safe(price_edge_pct)} to exit range{self.c('end')}")
            else:
                status_icon = f"{self.c('safe')}✅ SAFE{self.c('end')}"
                print(f"{status_icon} {self.c('safe')}Position is safely in range - Earning fees!{self.c('end')}")
                print(f"   {self.c('safe')}Range position: {lower_distance_pct:.1f}% from lower / {upper_distance_pct:.1f}% from upper{self.c('end')}")
                if price_lower_pct != float('inf') and price_upper_pct != float('inf'):
                    print(f"   {self.c('safe')}Price buffer: {format_price_percentage_safe(price_lower_pct)} to lower / {format_price_percentage_safe(price_upper_pct)} to upper{self.c('end')}")
        else:
            print(f"{self.c('danger')}❌ OUT OF RANGE - Not earning fees!{self.c('end')}")
            
            if status["current_tick"] < position["tick_lower"]:
                ticks_away = position["tick_lower"] - status["current_tick"]
                if status['lower_price'] > 0:
                    price_needed = (status['lower_price'] - status['current_price']) / status['current_price'] * 100
                    print(f"{self.c('danger')}📉 Price is BELOW range by {ticks_away} ticks{self.c('end')}")
                    if abs(price_needed) < 1e10:
                        print(f"💡 Price needs to rise {format_price_percentage_safe(price_needed)} to {format_price(status['lower_price'])} to re-enter")
                else:
                    print(f"{self.c('danger')}📉 Price is far below range{self.c('end')}")
            else:
                ticks_away = status["current_tick"] - position["tick_upper"]
                if status['upper_price'] != float('inf'):
                    price_needed = (status['upper_price'] - status['current_price']) / status['current_price'] * 100
                    print(f"{self.c('danger')}📈 Price is ABOVE range by {ticks_away} ticks{self.c('end')}")
                    if abs(price_needed) < 1e10:
                        print(f"💡 Price needs to drop {format_price_percentage_safe(price_needed)} to {format_price(status['upper_price'])} to re-enter")
                else:
                    print(f"{self.c('danger')}📈 Price is far above range{self.c('end')}")
        
        print("─" * 60)

    def print_fee_info(self, status):
        """Print unclaimed fee information"""
        fee_amount0 = status.get("fee_amount0", 0)
        fee_amount1 = status.get("fee_amount1", 0)
        token0_symbol = status.get("token0_symbol", "TOKEN0")
        token1_symbol = status.get("token1_symbol", "TOKEN1")
        has_fees = status.get("has_unclaimed_fees", False)
        fee_error = status.get("fee_error")
        
        if fee_error:
            print(f"💰 Unclaimed Fees: {self.c('warning')}Error checking fees ({fee_error}){self.c('end')}")
            return
        
        if not has_fees:
            # Only show "No fees" if fees are significant enough
            if has_significant_fees(fee_amount0, fee_amount1, 0.000001):
                fees_display = format_fees_display(fee_amount0, fee_amount1, token0_symbol, token1_symbol)
                print(f"💰 Unclaimed Fees: {self.c('text')}{fees_display}{self.c('end')}")
            else:
                print(f"💰 Unclaimed Fees: {self.c('text')}No significant fees{self.c('end')}")
        else:
            fees_display = format_fees_display(fee_amount0, fee_amount1, token0_symbol, token1_symbol)
            if has_significant_fees(fee_amount0, fee_amount1, 0.01):  # Higher threshold for highlighting
                print(f"💰 Unclaimed Fees: {self.c('safe')}{fees_display} ✨{self.c('end')}")
            else:
                print(f"💰 Unclaimed Fees: {self.c('text')}{fees_display}{self.c('end')}")
    
    def print_portfolio_summary(self, positions, all_in_range, danger_positions, warning_positions, check_interval):
        """Print portfolio summary with clean formatting"""
        print(f"\n{self.c('bold')}📊 PORTFOLIO SUMMARY{self.c('end')}")
        
        if not all_in_range:
            print(f"{self.c('danger')}🚨 ALERT: Some positions are OUT OF RANGE!{self.c('end')}")
        elif danger_positions > 0:
            print(f"{self.c('danger')}🚨 {danger_positions} position(s) in DANGER zone!{self.c('end')}")
        elif warning_positions > 0:
            print(f"{self.c('warning')}⚠️  {warning_positions} position(s) in WARNING zone{self.c('end')}")
        else:
            print(f"{self.c('safe')}✅ All positions are SAFE and earning fees!{self.c('end')}")
        
        # Show DEX breakdown
        dex_counts = {}
        for position in positions:
            dex_name = position["dex_name"]
            dex_counts[dex_name] = dex_counts.get(dex_name, 0) + 1
        
        dex_summary = ", ".join([f"{count} on {dex}" for dex, count in dex_counts.items()])
        print(f"📋 Active positions: {dex_summary}")
        
        # Show refresh info
        print(f"Next check in {check_interval} seconds... (Ctrl+C to stop)")
        self.print_separator()
    
    def print_goodbye(self):
        """Print goodbye message when monitoring stops"""
        print(f"{self.c('bold')}")
        print("╔══════════════════════════════════════════════════════════════╗")
        print("║                    👋 MONITORING STOPPED                    ║")
        print("║                   Thanks for using LP Monitor!              ║")
        print(f"║                      v{VERSION} by {DEVELOPER}                      ║")
        print("╚══════════════════════════════════════════════════════════════╝")
        print(f"{self.c('end')}")

def clear_screen():
    """Clear the terminal screen using appropriate command for OS"""
    try:
        # For Windows
        if os.name == 'nt':
            os.system('cls')
        # For Unix/Linux/macOS
        else:
            os.system('clear')
    except:
        # Fallback: print multiple newlines
        print('\n' * 50)

def get_color_scheme_from_user():
    """Interactive color scheme selection for setup"""
    print("📺 Display Options:")
    print("1. Minimal colors (recommended - red/green for status only)")
    print("2. No colors (plain text)")
    print("3. Full colors (original colorful interface)")
    
    choice = input("Choose color scheme (1-3, default: 1): ").strip()
    if choice == "2":
        return "none"
    elif choice == "3":
        return "full"
    else:
        return "minimal"