#!/usr/bin/env python3
"""
Enhanced Position Monitoring Module for HyperEVM LP Monitor
Core LP position monitoring with PnL/IL tracking and Rich UI

Version: 1.6.0 (Complete with PnL/IL + Rich UI + Status Messages)
Developer: 8roku8.hl
"""

import time
from datetime import datetime
from rich.console import Console
from rich.live import Live
from rich.spinner import Spinner
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn
from concurrent.futures import ThreadPoolExecutor, as_completed

from blockchain import BlockchainManager
from notifications import NotificationManager
from constants import VERSION, DEVELOPER
from utils import calculate_dynamic_thresholds, get_risk_level
import sqlite3

# REMOVED: The old entry-fix logic is deprecated.
# The system now relies on the robust historical data fetching
# in blockchain.py (get_initial_position_entry).

# Database utilities for seeding entries if missing
try:
    from position_database import PositionDatabase
    POSITION_DB_AVAILABLE = True
except Exception:
    POSITION_DB_AVAILABLE = False

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
        # Track pending removals to avoid false negatives from rate limits
        self._pending_removed_keys = set()
        
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

        # REMOVED: The call to the deprecated auto-fixer.
        # The new logic in blockchain.py handles this automatically and correctly.

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
        full_rescan_interval_cycles = 300 // max(1, self.config.get("check_interval", 30))  # ~5 minutes default
        cycles_since_full_rescan = 0
        notification_sent_timer = 0  # Track how long to show notification message
        
        # Check if we should use persistent live display instead of screen clearing
        use_live_display = (self.use_rich and 
                           self.config.get("display_settings", {}).get("use_live_display", False))
        
        if use_live_display:
            self._monitor_with_live_display(cycles_since_refresh, refresh_interval, 
                                          full_rescan_interval_cycles, cycles_since_full_rescan, 
                                          notification_sent_timer)
        else:
            self._monitor_with_screen_clearing(cycles_since_refresh, refresh_interval, 
                                             full_rescan_interval_cycles, cycles_since_full_rescan, 
                                             notification_sent_timer)
    
    def _monitor_with_live_display(self, cycles_since_refresh, refresh_interval, 
                                  full_rescan_interval_cycles, cycles_since_full_rescan, 
                                  notification_sent_timer):
        """Monitor with Rich Live persistent display"""
        console.print("[cyan]🔴 Live Display Mode - Press Ctrl+C to stop[/cyan]")
        time.sleep(1)  # Brief pause to let user see the message
        
        # Initial layout creation
        positions_with_status = self.check_all_positions_batch()
        layout = self.display.rich_display.create_dashboard_layout_with_pnl(
            positions_with_status, 
            self.wallet_address,
            refresh_countdown=None,
            notification_sent=False,
            refresh_cycle=(cycles_since_refresh, refresh_interval),
            next_full_rescan_s=max(0, (full_rescan_interval_cycles - cycles_since_full_rescan) * self.config["check_interval"])
        )
        
        with Live(layout, console=console, refresh_per_second=2, screen=True, auto_refresh=False) as live:
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
                    
                    # Update layout for live display
                    updated_layout = self.display.rich_display.create_dashboard_layout_with_pnl(
                        positions_with_status, 
                        self.wallet_address,
                        refresh_countdown=refresh_countdown,
                        notification_sent=(notification_sent_timer > 0),
                        refresh_cycle=(cycles_since_refresh, refresh_interval),
                        next_full_rescan_s=max(0, (full_rescan_interval_cycles - cycles_since_full_rescan) * self.config["check_interval"])
                    )
                    
                    # Update the live display
                    live.update(updated_layout)
                    live.refresh()
                    
                    # Handle position refresh
                    should_refresh = cycles_since_refresh >= refresh_interval
                    if should_refresh:
                        is_refreshing = True
                        # Show refreshing state
                        refreshing_layout = self.display.rich_display.create_dashboard_layout_with_pnl(
                            positions_with_status,
                            self.wallet_address,
                            refresh_countdown=refresh_countdown,
                            notification_sent=(notification_sent_timer > 0),
                            refresh_cycle=(cycles_since_refresh, refresh_interval),
                            is_refreshing=True,
                            next_full_rescan_s=max(0, (full_rescan_interval_cycles - cycles_since_full_rescan) * self.config["check_interval"])
                        )
                        live.update(refreshing_layout)
                        live.refresh()
                        
                        # Perform silent refresh
                        force_full = cycles_since_full_rescan >= full_rescan_interval_cycles
                        changes_detected, had_errors = self.refresh_positions(silent=not force_full, force_full=force_full)
                        if had_errors:
                            time.sleep(2)
                        
                        cycles_since_refresh = 0
                        cycles_since_full_rescan = 0 if force_full else cycles_since_full_rescan
                        is_refreshing = False
                    
                    # Handle zero liquidity detection (immediate refresh)
                    zero_liquidity_detected = False
                    for position, status in positions_with_status:
                        if status:
                            live_liquidity = self.blockchain.get_live_liquidity(position)
                            if live_liquidity == 0:
                                zero_liquidity_detected = True
                                break
                    
                    if zero_liquidity_detected:
                        self.refresh_positions(silent=True)
                        cycles_since_refresh = 0
                        time.sleep(2)
                        continue
                    
                    # Wait before next check
                    time.sleep(self.config["check_interval"])
                    cycles_since_refresh += 1
                    cycles_since_full_rescan += 1
                    
                except KeyboardInterrupt:
                    break
                except Exception as e:
                    if self.debug_mode:
                        import traceback
                        traceback.print_exc()
                    console.print(f"[red]Error in monitoring loop: {e}[/red]")
                    time.sleep(5)
    
    def _monitor_with_screen_clearing(self, cycles_since_refresh, refresh_interval, 
                                    full_rescan_interval_cycles, cycles_since_full_rescan, 
                                    notification_sent_timer):
        """Monitor with traditional screen clearing"""
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
                        refresh_cycle=(cycles_since_refresh, refresh_interval),
                        next_full_rescan_s=max(0, (full_rescan_interval_cycles - cycles_since_full_rescan) * self.config["check_interval"])
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
                            is_refreshing=True,
                            next_full_rescan_s=max(0, (full_rescan_interval_cycles - cycles_since_full_rescan) * self.config["check_interval"])
                        )
                    else:
                        print("\nRefreshing position list...")
                    # Perform silent refresh
                    # Every N cycles force a full rescan by resetting event windows via non-silent pass
                    force_full = cycles_since_full_rescan >= full_rescan_interval_cycles
                    changes_detected, had_errors = self.refresh_positions(silent=not force_full, force_full=force_full)
                    if had_errors:
                        # Keep footer hint but avoid noisy state changes
                        time.sleep(2)
                    
                    cycles_since_refresh = 0
                    cycles_since_full_rescan = 0 if force_full else cycles_since_full_rescan
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
                cycles_since_full_rescan += 1
                
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
                
                def worker(pos):
                    live_liquidity = self.blockchain.get_live_liquidity(pos)
                    if live_liquidity == 0:
                        return None
                    pos["liquidity"] = live_liquidity
                    status = self.blockchain.check_position_status(pos, self.wallet_address)
                    return (pos, status) if status else None

                # Pre-fetch unique pools via multicall to warm the cache
                unique_pools = {(p.get('pool_address'), p.get('dex_type', 'uniswap_v3')) for p in self.positions if p.get('pool_address')}
                try:
                    self.blockchain.prefetch_pool_data(list(unique_pools))
                except Exception:
                    pass

                max_workers = min(16, max(4, len(self.positions)//2))
                with ThreadPoolExecutor(max_workers=max_workers) as executor:
                    futures = [executor.submit(worker, p) for p in self.positions]
                    for fut in as_completed(futures):
                        result = fut.result()
                        if result:
                            positions_with_status.append(result)
                        progress.advance(task)
        else:
            # Simple check without progress bar
            def worker(pos):
                live_liquidity = self.blockchain.get_live_liquidity(pos)
                if live_liquidity == 0:
                    return None
                pos["liquidity"] = live_liquidity
                status = self.blockchain.check_position_status(pos, self.wallet_address)
                return (pos, status) if status else None

            # Pre-fetch unique pools via multicall to warm the cache
            unique_pools = {(p.get('pool_address'), p.get('dex_type', 'uniswap_v3')) for p in self.positions if p.get('pool_address')}
            try:
                self.blockchain.prefetch_pool_data(list(unique_pools))
            except Exception:
                pass

            max_workers = min(8, max(2, len(self.positions)//2))
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                for result in executor.map(worker, self.positions):
                    if result:
                        positions_with_status.append(result)
        
        return positions_with_status

    def refresh_positions(self, silent=False, force_full=False):
        """Refresh position list.
        - Maintenance (force_full=False): merge updates; never remove entries.
        - Full rescan (force_full=True): compute added/removed with safety checks.
        """
        old_positions_list = list(self.positions)
        old_count = len(old_positions_list)
        old_keys = {f"{pos['dex_name']}_{pos['token_id']}" for pos in old_positions_list}

        # Build new list without mutating current until we know scan quality
        new_list = []
        wallet_address = self.config["wallet_address"]
        had_errors_any = False

        for dex_config in self.config["dexes"]:
            positions = self.blockchain.fetch_positions_from_dex(
                wallet_address,
                dex_config,
                suppress_output=True,
                force_full=not silent
            )
            if positions is None and silent:
                # Maintenance refresh with no detected changes or log failure: keep previous positions for this DEX
                prev = [p for p in old_positions_list if p.get('dex_name') == dex_config.get('name')]
                new_list.extend(prev)
                continue
            new_list.extend(positions or [])
            # Check scan status
            status = self.blockchain.get_last_scan_status(dex_config.get('name')) or {}
            if status.get('had_errors'):
                had_errors_any = True

        new_count = len(new_list)
        new_keys = {f"{pos['dex_name']}_{pos['token_id']}" for pos in new_list}

        # Maintenance mode: do nothing to the list (no merge, no removals).
        # We keep metrics fresh each cycle elsewhere; discovery happens only on full rescan.
        if not force_full:
            return False, had_errors_any

        # Commit new list
        self.positions = new_list

        added = new_keys - old_keys
        removed = old_keys - new_keys

        # Cross-check removals against on-chain Transfer events (if available)
        suspected_removed = set()
        for dex_cfg in self.config['dexes']:
            hints = self.blockchain.get_last_event_hints(dex_cfg.get('name'))
            if hints and hints.get('removed_ids'):
                for pos in old_positions_list:
                    if pos.get('dex_name') == dex_cfg.get('name') and pos.get('token_id') in hints['removed_ids']:
                        suspected_removed.add(f"{pos['dex_name']}_{pos['token_id']}")
        # Only remove positions that are either event-confirmed or persistently missing
        event_confirmed_removed = removed & suspected_removed
        removed = event_confirmed_removed

        # Debounce removals across scans to protect against transient rate limits
        if had_errors_any:
            # Mark removed keys as pending, but do not act yet
            self._pending_removed_keys.update(removed)
            removed = set()
        else:
            # Confirm pending removals only if still missing without errors
            confirmed_removed = {k for k in self._pending_removed_keys if k not in new_keys}
            removed |= confirmed_removed
            self._pending_removed_keys -= confirmed_removed

        if (added or removed) and not had_errors_any:
            if self.use_rich:
                console.print("\n[bold]📋 Position Changes Detected:[/bold]")
                if added:
                    console.print(f"[green]➕ Added {len(added)} new position(s)[/green]")
                if removed:
                    console.print(f"[red]➖ Removed {len(removed)} position(s)[/red]")
            else:
                print("\n📋 Position Changes Detected:")
                if added:
                    print(f"➕ Added {len(added)} new position(s)")
                if removed:
                    print(f"➖ Removed {len(removed)} position(s)")

            if self.notifications.enabled:
                self.notifications.send_portfolio_update_notification(
                    len(added),
                    len(removed),
                    len(self.positions),
                    self.config["wallet_address"],
                    self.positions
                )

        return (new_count != old_count), had_errors_any

    # REMOVED: The entire _auto_fix_active_entries_on_startup function is deprecated.
    # All historical entry logic is now correctly handled by the BlockchainManager.


# Export for backward compatibility
LPMonitor = EnhancedLPMonitor