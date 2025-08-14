#!/usr/bin/env python3
"""
Enhanced Position Monitoring Module for HyperEVM LP Monitor
Core LP position monitoring with PnL/IL tracking and Rich UI

Version: 1.6.0 (Complete with PnL/IL + Rich UI + Status Messages)
Developer: 8roku8.hl + Claude
"""

import time
from datetime import datetime
from rich.console import Console
from rich.live import Live
from rich.spinner import Spinner
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn

from blockchain import BlockchainManager
from notifications import NotificationManager
from constants import VERSION, DEVELOPER
from utils import calculate_dynamic_thresholds, get_risk_level

# Try to import enhanced display
try:
    from display import EnhancedDisplayManager, clear_screen
    ENHANCED_DISPLAY = True
except ImportError:
    from display import DisplayManager, clear_screen
    ENHANCED_DISPLAY = False

console = Console()

class EnhancedLPMonitor:
    """Enhanced LP position monitoring with Rich UI and PnL tracking"""
    
    def __init__(self, config):
        self.config = config
        self.positions = []
        self.wallet_address = config["wallet_address"]
        
        # Initialize enhanced display manager
        if ENHANCED_DISPLAY:
            self.display = EnhancedDisplayManager(config)
        else:
            self.display = DisplayManager(config)
            
        self.use_rich = config.get("display_settings", {}).get("use_rich_ui", True)
        
        # Clear screen and show header
        if config.get("display_settings", {}).get("clear_screen", True):
            clear_screen()
        self.display.print_header()
        
        # Initialize blockchain manager with progress indicator
        debug_mode = config.get("display_settings", {}).get("debug_mode", False)
        
        if self.use_rich:
            with console.status("[bold green]Initializing blockchain connection...", spinner="dots"):
                try:
                    self.blockchain = BlockchainManager(config["rpc_url"], debug_mode)
                except Exception as e:
                    console.print(f"[red]❌ Failed to initialize blockchain manager: {e}[/red]")
                    raise
        else:
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
        # PnL/IL toggles from config
        self.pnl_enabled = config.get("pnl_settings", {}).get("enabled", True)
        self.include_il_metrics = config.get("pnl_settings", {}).get("include_il_metrics", True)
        
        # Display configuration info
        self.print_initial_info()
        
        # Fetch positions from all DEXes with progress bar
        self.fetch_all_positions_with_progress()
        
        if self.use_rich:
            console.print(f"[green]Found {len(self.positions)} LP positions total[/green]")
            console.rule(style="blue")
        else:
            print(f"Found {len(self.positions)} LP positions total")
            print("=" * 70)

    def print_initial_info(self):
        """Print initial configuration information with Rich formatting"""
        wallet = self.config["wallet_address"]
        dexes = self.config["dexes"]
        
        if self.use_rich:
            console.print(f"[white]Monitoring wallet:[/white] [bold cyan]{wallet}[/bold cyan]")
            
            # Show configured DEXes
            dex_info_list = [f"{dex['name']} ({dex.get('type', 'uniswap_v3')})" for dex in dexes]
            dex_info_str = ', '.join(dex_info_list)
            console.print(f"[white]Configured DEXes:[/white] [bold]{dex_info_str}[/bold]")
            
            # Show notification status
            if self.notifications.enabled:
                notify_issues_only = self.config.get("notifications", {}).get("notify_on_issues_only", True)
                cooldown_hours = self.config.get("notifications", {}).get("notification_cooldown", 3600) / 3600
                status = "Issues only" if notify_issues_only else "All updates"
                console.print(f"[white]Notifications:[/white] [green]{self.notifications.notification_type}[/green] - {status}, every {cooldown_hours:.1f}h")
            
            # Show fee tracking status
            if self.show_fees:
                console.print(f"[white]Fee tracking:[/white] [green]Enabled[/green]")
            
            # Show PnL tracking status
            console.print(f"[white]PnL/IL tracking:[/white] [green]Enabled[/green]")
            
            if self.debug_mode:
                console.print(f"[yellow]Debug mode enabled[/yellow]")
            
            # Show dynamic thresholds
            dynamic_config = self.config.get('dynamic_thresholds', {})
            console.print(f"[white]Dynamic thresholds:[/white] [red]{dynamic_config.get('danger_threshold_pct', 5.0)}%[/red] danger, [yellow]{dynamic_config.get('warning_threshold_pct', 15.0)}%[/yellow] warning")
        else:
            # Fallback to simple printing
            print(f"Monitoring wallet: {wallet}")
            dex_info_list = [f"{dex['name']} ({dex.get('type', 'uniswap_v3')})" for dex in dexes]
            print(f"Configured DEXes: {', '.join(dex_info_list)}")

    def fetch_all_positions_with_progress(self):
        """Fetch positions from all DEXes with progress indicator"""
        total_positions = 0
        wallet_address = self.config["wallet_address"]
        
        if self.use_rich:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
                TimeElapsedColumn(),
                console=console
            ) as progress:
                
                task = progress.add_task(
                    "[cyan]Fetching LP positions...", 
                    total=len(self.config["dexes"])
                )
                
                for dex_config in self.config["dexes"]:
                    progress.update(task, description=f"[cyan]Checking {dex_config['name']}...")
                    positions = self.blockchain.fetch_positions_from_dex(wallet_address, dex_config)
                    self.positions.extend(positions)
                    total_positions += len(positions)
                    progress.advance(task)
        else:
            print("Fetching LP positions from all DEXes...")
            for dex_config in self.config["dexes"]:
                positions = self.blockchain.fetch_positions_from_dex(wallet_address, dex_config)
                self.positions.extend(positions)
                total_positions += len(positions)
        
        if total_positions == 0:
            msg = "🤔 No LP positions found across any configured DEX"
            if self.use_rich:
                console.print(f"[yellow]{msg}[/yellow]")
            else:
                print(msg)

    def monitor_positions(self):
        """Main monitoring loop with Rich Live display and integrated status messages"""
        if self.use_rich:
            console.print("[bold green]Starting position monitoring...[/bold green]")
            console.print(f"[white]Checking every {self.config['check_interval']} seconds[/white]")
        else:
            print("Starting position monitoring...")
            print(f"Checking every {self.config['check_interval']} seconds")
        
        cycles_since_refresh = 0
        refresh_interval = 20  # Refresh every 20 cycles
        notification_sent_timer = 0  # Track how long to show notification message
        
        while True:
            try:
                # Check all positions
                positions_with_status = self.check_all_positions_batch()
                
                # Calculate refresh countdown
                cycles_until_refresh = refresh_interval - cycles_since_refresh
                refresh_countdown = cycles_until_refresh if cycles_until_refresh <= 5 else None
                
                # Check if notification was sent this cycle
                notification_sent_this_cycle = False
                
                # Send notifications if enabled
                if self.notifications.enabled and positions_with_status:
                    # Check if notification was actually sent (respects cooldowns)
                    if self.notifications.should_send_notification():
                        self.notifications.send_status_notification(
                            positions_with_status, 
                            self.config["wallet_address"], 
                            self.debug_mode
                        )
                        notification_sent_timer = 3  # Show for 3 cycles
                        notification_sent_this_cycle = True
                
                # Track notification display timer
                if notification_sent_timer > 0 and not notification_sent_this_cycle:
                    notification_sent_timer -= 1
                
                # Display with integrated status messages
                if self.use_rich:
                    if self.config.get("display_settings", {}).get("clear_screen", True):
                        clear_screen()
                    
                    # Display using Rich UI with status messages
                    self.display.display_positions(
                        positions_with_status, 
                        self.wallet_address,
                        refresh_countdown=refresh_countdown,
                        notification_sent=(notification_sent_timer > 0),
                        refresh_cycle=(cycles_since_refresh, refresh_interval)
                    )
                else:
                    # Fallback to simple display
                    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    status_line = f"{timestamp}"
                    
                    if refresh_countdown:
                        status_line += f" | Refresh in {refresh_countdown} cycles"
                    
                    if notification_sent_timer > 0:
                        status_line += " | Notification sent"
                    
                    print(f"\n{status_line}")
                    print("=" * 70)
                    
                    self.display.display_positions(
                        positions_with_status, 
                        self.wallet_address,
                        refresh_countdown=refresh_countdown,
                        notification_sent=(notification_sent_timer > 0),
                        refresh_cycle=(cycles_since_refresh, refresh_interval)
                    )
                
                # Handle position refresh
                should_refresh = cycles_since_refresh >= refresh_interval
                if should_refresh:
                    is_refreshing = True
                    if self.use_rich:
                        # Render a cycle with the refreshing flag on
                        if self.config.get("display_settings", {}).get("clear_screen", True):
                            clear_screen()
                        self.display.display_positions(
                            positions_with_status,
                            self.wallet_address,
                            refresh_countdown=refresh_countdown,
                            notification_sent=(notification_sent_timer > 0),
                            refresh_cycle=(cycles_since_refresh, refresh_interval),
                            is_refreshing=True
                        )
                    else:
                        print("\nRefreshing position list...")
                    # Perform silent refresh
                    changes_detected = self.refresh_positions(silent=True)
                    
                    cycles_since_refresh = 0
                    if changes_detected:
                        # Changes will be reflected in next display update
                        # No need for extra message
                        pass
                    is_refreshing = False
                
                # Handle zero liquidity detection (immediate refresh)
                zero_liquidity_detected = False
                for position, status in positions_with_status:
                    if status:
                        live_liquidity = self.blockchain.get_live_liquidity(position)
                        if live_liquidity == 0:
                            zero_liquidity_detected = True
                            if self.use_rich:
                                console.print(f"[yellow]{position['name']} on {position['dex_name']} now has zero liquidity[/yellow]")
                            else:
                                print(f"{position['name']} on {position['dex_name']} now has zero liquidity")
                            break
                
                if zero_liquidity_detected:
                    if self.use_rich:
                        console.print("[yellow]Zero liquidity detected - refreshing immediately[/yellow]")
                    else:
                        print("Zero liquidity detected - refreshing immediately")
                    self.refresh_positions(silent=True)
                    cycles_since_refresh = 0
                    time.sleep(2)
                    continue
                
                # Wait before next check
                time.sleep(self.config["check_interval"])
                cycles_since_refresh += 1
                
            except KeyboardInterrupt:
                clear_screen()
                self.display.print_goodbye()
                break
            except Exception as e:
                error_msg = f"❌ Error during monitoring: {e}"
                if self.use_rich:
                    console.print(f"[red]{error_msg}[/red]")
                    console.print("[yellow]⏳ Retrying in 5 seconds...[/yellow]")
                else:
                    print(error_msg)
                    print("⏳ Retrying in 5 seconds...")
                
                if self.debug_mode:
                    import traceback
                    traceback.print_exc()
                time.sleep(5)

    def check_all_positions_batch(self):
        """Check all positions and return status data"""
        positions_with_status = []
        
        if self.use_rich and len(self.positions) > 5:
            # Show progress for many positions
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TextColumn("{task.completed}/{task.total}"),
                console=console,
                transient=True
            ) as progress:
                
                task = progress.add_task(
                    "[cyan]Checking positions...", 
                    total=len(self.positions)
                )
                
                for position in self.positions:
                    # Check liquidity
                    live_liquidity = self.blockchain.get_live_liquidity(position)
                    if live_liquidity == 0:
                        progress.advance(task)
                        continue
                    
                    position["liquidity"] = live_liquidity
                    
                    # Get status with fee tracking
                    status = self.blockchain.check_position_status(position, self.wallet_address)
                    if status:
                        positions_with_status.append((position, status))
                    
                    progress.advance(task)
        else:
            # Simple check without progress bar
            for position in self.positions:
                live_liquidity = self.blockchain.get_live_liquidity(position)
                if live_liquidity == 0:
                    continue
                
                position["liquidity"] = live_liquidity
                status = self.blockchain.check_position_status(position, self.wallet_address)
                if status:
                    positions_with_status.append((position, status))
        
        return positions_with_status

    def refresh_positions(self, silent=False):
        """Re-scan for positions to catch new ones and remove old ones"""
        old_count = len(self.positions)
        old_positions = {f"{pos['dex_name']}_{pos['token_id']}" for pos in self.positions}
        
        # Clear and re-fetch positions
        self.positions = []
        wallet_address = self.config["wallet_address"]
        
        for dex_config in self.config["dexes"]:
            positions = self.blockchain.fetch_positions_from_dex(wallet_address, dex_config, silent=silent)
            self.positions.extend(positions)
        
        new_count = len(self.positions)
        new_positions = {f"{pos['dex_name']}_{pos['token_id']}" for pos in self.positions}
        
        # Analyze changes
        added_positions = new_positions - old_positions
        removed_positions = old_positions - new_positions
        
        if added_positions or removed_positions:
            if self.use_rich:
                console.print("\n[bold]📋 Position Changes Detected:[/bold]")
                if added_positions:
                    console.print(f"[green]➕ Added {len(added_positions)} new position(s)[/green]")
                if removed_positions:
                    console.print(f"[red]➖ Removed {len(removed_positions)} position(s)[/red]")
            else:
                print("\n📋 Position Changes Detected:")
                if added_positions:
                    print(f"➕ Added {len(added_positions)} new position(s)")
                if removed_positions:
                    print(f"➖ Removed {len(removed_positions)} position(s)")
            
            # Send notification about changes
            if self.notifications.enabled and (added_positions or removed_positions):
                self.notifications.send_portfolio_update_notification(
                    len(added_positions), 
                    len(removed_positions), 
                    len(self.positions),
                    self.config["wallet_address"],
                    self.positions
                )
        
        return new_count != old_count


# Export for backward compatibility
LPMonitor = EnhancedLPMonitor