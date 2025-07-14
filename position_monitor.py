#!/usr/bin/env python3
"""
Position Monitoring Module for HyperEVM LP Monitor
Core LP position monitoring and analysis logic

COMPLETE UPDATED VERSION: Immediate refresh on zero liquidity + state cleanup + Fee Tracking

Version: 1.4.1 (Fixed Zero Liquidity Bug + State Cleanup + Fee Tracking)
Developer: 8roku8.hl
"""

import time
from datetime import datetime
from display import DisplayManager, clear_screen
from blockchain import BlockchainManager
from notifications import NotificationManager
from constants import VERSION, DEVELOPER
from utils import calculate_dynamic_thresholds, get_risk_level

class LPMonitor:
    """Main LP position monitoring class"""
    
    def __init__(self, config):
        self.config = config
        self.positions = []
        self.wallet_address = config["wallet_address"]
        
        # Initialize display manager
        self.display = DisplayManager(config)
        
        # Clear screen and show header
        if config.get("display_settings", {}).get("clear_screen", True):
            clear_screen()
        self.display.print_header()
        
        # Initialize blockchain manager
        debug_mode = config.get("display_settings", {}).get("debug_mode", False)
        try:
            self.blockchain = BlockchainManager(config["rpc_url"], debug_mode)
        except Exception as e:
            print(f"❌ Failed to initialize blockchain manager: {e}")
            raise
        
        # Initialize notification manager
        self.notifications = NotificationManager(config)
        
        # Setup debug mode
        self.debug_mode = debug_mode
        self.show_raw_data = config.get("display_settings", {}).get("show_raw_data", False)
        self.show_fees = config.get("display_settings", {}).get("show_unclaimed_fees", True)
        
        # Display configuration info
        self.print_initial_info()
        
        # Fetch positions from all DEXes
        self.fetch_all_positions()
        
        print(f"{self.display.c('safe')}📊 Found {len(self.positions)} LP positions total{self.display.c('end')}")
        self.display.print_separator()

    def print_initial_info(self):
        """Print initial configuration information"""
        wallet = self.config["wallet_address"]
        dexes = self.config["dexes"]
        
        print(f"{self.display.c('text')}👛 Monitoring wallet: {self.display.c('bold')}{wallet}{self.display.c('end')}")
        
        # Show configured DEXes
        dex_info_list = [f"{dex['name']} ({dex.get('type', 'uniswap_v3')})" for dex in dexes]
        dex_info_str = ', '.join(dex_info_list)
        print(f"🏪 Configured DEXes: {self.display.c('bold')}{dex_info_str}{self.display.c('end')}")
        
        # Show notification status
        if self.notifications.enabled:
            notify_issues_only = self.config.get("notifications", {}).get("notify_on_issues_only", True)
            cooldown_hours = self.config.get("notifications", {}).get("notification_cooldown", 3600) / 3600
            if notify_issues_only:
                print(f"🔔 Notifications enabled ({self.notifications.notification_type}) - Issues only, every {cooldown_hours:.1f}h")
            else:
                print(f"🔔 Notifications enabled ({self.notifications.notification_type}) - All updates, every {cooldown_hours:.1f}h")
        
        # Show fee tracking status
        if self.show_fees:
            print(f"💰 Fee tracking enabled - will show unclaimed fees")
        
        if self.debug_mode:
            print(f"{self.display.c('warning')}🔍 Debug mode enabled{self.display.c('end')}")
        
        # Show dynamic thresholds
        dynamic_config = self.config.get('dynamic_thresholds', {})
        print(f"🎯 Dynamic thresholds: {dynamic_config.get('danger_threshold_pct', 5.0)}% danger, {dynamic_config.get('warning_threshold_pct', 15.0)}% warning")
        
        print("🔍 Fetching LP positions from all DEXes...")

    def fetch_all_positions(self):
        """Fetch positions from all configured DEXes"""
        total_positions = 0
        
        wallet_address = self.config["wallet_address"]
        
        for dex_config in self.config["dexes"]:
            positions = self.blockchain.fetch_positions_from_dex(wallet_address, dex_config)
            self.positions.extend(positions)
            total_positions += len(positions)
        
        if total_positions == 0:
            print(f"\n{self.display.c('warning')}🤔 No LP positions found across any configured DEX{self.display.c('end')}")

    def refresh_positions(self):
        """Re-scan for positions to catch new ones and remove old ones"""
        print(f"\n🔄 Refreshing position list...")
        old_count = len(self.positions)
        old_positions = {f"{pos['dex_name']}_{pos['token_id']}" for pos in self.positions}
        
        # Clear and re-fetch positions
        self.positions = []
        self.fetch_all_positions()
        
        new_count = len(self.positions)
        new_positions = {f"{pos['dex_name']}_{pos['token_id']}" for pos in self.positions}
        
        # Analyze changes
        added_positions = new_positions - old_positions
        removed_positions = old_positions - new_positions
        
        if added_positions or removed_positions:
            print(f"\n📋 Position Changes Detected:")
            if added_positions:
                print(f"{self.display.c('safe')}➕ Added {len(added_positions)} new position(s){self.display.c('end')}")
            if removed_positions:
                print(f"{self.display.c('danger')}➖ Removed {len(removed_positions)} position(s) (no liquidity){self.display.c('end')}")
            
            # Send notification about portfolio changes and cleanup states
            if self.notifications.enabled and (added_positions or removed_positions):
                self.notifications.send_portfolio_update_notification(
                    len(added_positions), 
                    len(removed_positions), 
                    len(self.positions),
                    self.config["wallet_address"],
                    self.positions  # Pass current positions for cleanup
                )
        else:
            print("✅ No position changes detected")
        
        return new_count != old_count

    def monitor_positions(self):
        """Main monitoring loop - UPDATED (handle immediate refresh on zero liquidity + fee tracking)"""
        print(f"{self.display.c('bold')}{self.display.c('safe')}🔄 Starting position monitoring...{self.display.c('end')}")
        print(f"⏰ Checking every {self.config['check_interval']} seconds")
        
        # Show supported DEX types
        dex_types = set(dex.get("type", "uniswap_v3") for dex in self.config["dexes"])
        print(f"🔧 Supported DEX types: {', '.join(dex_types)}")
        
        # Show notification settings
        if self.notifications.enabled:
            cooldown_hours = self.config.get("notifications", {}).get("notification_cooldown", 3600) / 3600
            issues_only = self.config.get("notifications", {}).get("notify_on_issues_only", True)
            if issues_only:
                print(f"🔔 Notifications: Issues only, every {cooldown_hours:.1f}h")
            else:
                print(f"🔔 Notifications: All status updates, every {cooldown_hours:.1f}h")
        
        # Show thresholds and settings
        dynamic_config = self.config.get('dynamic_thresholds', {})
        print(f"📋 Alert thresholds: {dynamic_config.get('danger_threshold_pct', 5.0)}% (danger), {dynamic_config.get('warning_threshold_pct', 15.0)}% (warning)")
        print(f"🔄 Dynamic position tracking: Enabled (auto-detects new/removed positions)")
        
        # Show fee tracking status
        if self.show_fees:
            print(f"💰 Fee tracking: Enabled (shows unclaimed fees)")
        
        # Show display settings
        if self.config.get("display_settings", {}).get("clear_screen", True):
            print("📺 Screen clearing: Enabled (clean display)")
        else:
            print("📺 Screen clearing: Disabled (scrolling display)")
        
        # Show color scheme
        color_scheme = self.config.get("display_settings", {}).get("color_scheme", "minimal")
        print(f"🎨 Color scheme: {color_scheme}")
        
        self.display.print_separator()
        
        cycles_since_refresh = 0
        refresh_interval = 20  # Refresh every 20 cycles (20 * 30 seconds = 10 minutes by default)
        
        while True:
            try:
                # Clear screen for clean updates if enabled
                if self.config.get("display_settings", {}).get("clear_screen", True):
                    clear_screen()
                    self.display.print_header()
                    self.print_monitoring_header()
                else:
                    # Just print a small header for scrolling mode
                    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    print(f"\n{self.display.c('bold')}🕐 Check at {timestamp}{self.display.c('end')}")
                    self.display.print_separator()
                
                # Show refresh countdown
                cycles_until_refresh = refresh_interval - cycles_since_refresh
                if cycles_until_refresh <= 5:
                    print(f"{self.display.c('warning')}🔄 Next position refresh in {cycles_until_refresh} cycle(s){self.display.c('end')}")
                
                if self.debug_mode:
                    print(f"🔍 STARTING POSITION CHECKS - Found {len(self.positions)} positions")
                
                # Check all positions - may trigger immediate refresh
                immediate_refresh_performed = self.check_all_positions()
                
                # Handle regular refresh logic (skip if immediate refresh was performed)
                if not immediate_refresh_performed:
                    should_refresh = False
                    if cycles_since_refresh >= refresh_interval:
                        print(f"\n🔄 Periodic position refresh (every {refresh_interval} cycles)...")
                        should_refresh = True
                    
                    if should_refresh:
                        changes_detected = self.refresh_positions()
                        cycles_since_refresh = 0  # Reset counter
                        if changes_detected:
                            print(f"{self.display.c('safe')}🎯 Position list updated! Continuing monitoring...{self.display.c('end')}")
                        time.sleep(2)  # Brief pause to show refresh message
                        continue  # Skip to next cycle with updated positions
                else:
                    # Immediate refresh was performed, reset cycle counter
                    cycles_since_refresh = 0
                    time.sleep(2)  # Brief pause to show refresh message
                    continue  # Skip to next cycle with updated positions
                
                # Wait before next check
                time.sleep(self.config["check_interval"])
                cycles_since_refresh += 1
                
            except KeyboardInterrupt:
                clear_screen()
                self.display.print_goodbye()
                break
            except Exception as e:
                print(f"{self.display.c('danger')}❌ Error during monitoring: {e}{self.display.c('end')}")
                print(f"{self.display.c('warning')}⏳ Retrying in 5 seconds...{self.display.c('end')}")
                if self.debug_mode:
                    import traceback
                    traceback.print_exc()
                time.sleep(5)  # Wait a bit before retrying

    def print_monitoring_header(self):
        """Print monitoring header with current status"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        wallet = self.config["wallet_address"]
        
        print(f"{self.display.c('bold')}🕐 Last Update: {timestamp}{self.display.c('end')}")
        print(f"👛 Wallet: {wallet[:6]}...{wallet[-4:]}")
        print(f"📊 Monitoring {len(self.positions)} LP positions")
        
        # Show DEX breakdown
        dex_counts = {}
        for position in self.positions:
            dex_name = position["dex_name"]
            dex_counts[dex_name] = dex_counts.get(dex_name, 0) + 1
        
        dex_summary = ", ".join([f"{count} on {dex}" for dex, count in dex_counts.items()])
        print(f"🏪 DEX Distribution: {dex_summary}")
        
        # Show next check time
        next_check = datetime.fromtimestamp(time.time() + self.config['check_interval'])
        print(f"⏰ Next check: {next_check.strftime('%H:%M:%S')}")
        
        # Show notification status
        if self.notifications.enabled:
            time_since_last = time.time() - self.notifications.last_notification_time
            cooldown = self.config.get("notifications", {}).get("notification_cooldown", 3600)
            time_until_next = max(0, cooldown - time_since_last)
            if time_until_next > 0:
                next_notification = datetime.fromtimestamp(time.time() + time_until_next)
                print(f"🔔 Next notification: {next_notification.strftime('%H:%M:%S')}")
            else:
                print("🔔 Notification ready")
        
        self.display.print_separator()

    def check_all_positions(self):
        """Check status of all positions - UPDATED (immediate refresh on zero liquidity + fee tracking)"""
        all_in_range = True
        danger_positions = 0
        warning_positions = 0
        zero_liquidity_detected = False
        position_statuses = []  # For notifications
        
        # Check each position
        positions_to_check = self.positions.copy()  # Create copy to avoid modification during iteration
        
        for i, position in enumerate(positions_to_check):
            if self.debug_mode:
                print(f"🔍 CHECKING POSITION {i+1}: {position['name']}")
            
            # First check if liquidity still exists (live check)
            live_liquidity = self.blockchain.get_live_liquidity(position)
            if self.debug_mode:
                print(f"🔍 Live liquidity: {live_liquidity}")
            
            if live_liquidity == 0:
                zero_liquidity_detected = True
                print(f"{self.display.c('warning')}👻 {position['name']} on {position['dex_name']} now has zero liquidity!{self.display.c('end')}")
                continue
            
            # Update cached liquidity if it changed
            if live_liquidity != position["liquidity"]:
                position["liquidity"] = live_liquidity
            
            if self.debug_mode:
                print("🔍 Getting position status...")
            
            # Pass wallet address for fee tracking
            status = self.blockchain.check_position_status(position, self.wallet_address)
            
            if status:
                position_statuses.append((position, status))  # Store for notifications
                
                if self.debug_mode:
                    print("🔍 Status received, calculating percentages...")
                
                # Calculate thresholds for this position
                danger_threshold, warning_threshold = calculate_dynamic_thresholds(position, self.config)
                
                # Calculate risk level
                range_size = position['tick_upper'] - position['tick_lower']
                closer_distance_pct = min(status["distance_to_lower"], status["distance_to_upper"]) / range_size * 100
                risk_level, _ = get_risk_level(position, closer_distance_pct, self.config)
                
                # Track status for summary
                if not status["in_range"]:
                    all_in_range = False
                elif risk_level == "danger":
                    danger_positions += 1
                elif risk_level == "warning":
                    warning_positions += 1
                
                self.display.print_position_status(position, status, danger_threshold, warning_threshold, risk_level, closer_distance_pct)
            else:
                print(f"{self.display.c('danger')}❌ Failed to check {position['name']} on {position['dex_name']}{self.display.c('end')}")
        
        # Send notification if enabled
        if self.notifications.enabled and position_statuses:
            self.notifications.send_status_notification(position_statuses, self.config["wallet_address"], self.debug_mode)
        
        # Handle zero liquidity detection - IMMEDIATE REFRESH
        if zero_liquidity_detected:
            print(f"\n{self.display.c('warning')}🔄 Zero liquidity detected - refreshing position list immediately!{self.display.c('end')}")
            changes_detected = self.refresh_positions()
            if changes_detected:
                print(f"{self.display.c('safe')}✅ Position list updated! Continuing monitoring...{self.display.c('end')}")
            return True  # Signal that we refreshed
        
        # Summary with color coding and DEX breakdown
        self.display.print_portfolio_summary(self.positions, all_in_range, danger_positions, warning_positions, self.config["check_interval"])
        return False  # No refresh performed