#!/usr/bin/env python3
"""
Enhanced Display Management Module for HyperEVM LP Monitor
Now with PnL and Impermanent Loss tracking

Version: 1.5.0 (PnL/IL Enhancement)
Developer: 8roku8.hl
"""

import os
import time
from datetime import datetime, timedelta
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.layout import Layout
from rich.live import Live
from rich.progress import Progress, BarColumn, TextColumn
from rich.text import Text
from rich.align import Align
from rich.columns import Columns
from rich import box

from constants import VERSION, DEVELOPER
from utils import (
    format_price, format_token_amount, format_price_percentage_safe,
    format_fees_display, has_significant_fees, is_full_range_position,
    calculate_price_based_percentages
)

# Try to import price utilities
try:
    from price_utils import (
        is_stablecoin, extract_token_prices_from_positions,
        calculate_fees_usd_value, format_fee_with_usd,
        calculate_position_value_usd, format_usd_value
    )
    PRICE_UTILS_AVAILABLE = True
except ImportError:
    PRICE_UTILS_AVAILABLE = False

# Try to import database for PnL tracking
try:
    from position_database import PositionDatabase
    DATABASE_AVAILABLE = True
except ImportError:
    DATABASE_AVAILABLE = False

# Initialize Rich console
console = Console()

class RichDisplayManager:
    """Enhanced display manager using Rich for beautiful terminal UI with PnL tracking"""
    
    def __init__(self, config):
        self.config = config
        self.console = Console()
        self.last_update_time = None
        
        # Initialize database if available
        self.db = None
        if DATABASE_AVAILABLE:
            try:
                self.db = PositionDatabase()
            except Exception as e:
                console.print(f"[yellow]⚠️ Could not initialize database: {e}[/yellow]")
    
    def create_header_panel(self):
        """Create a stylized header panel"""
        header_text = Text()
        header_text.append("HYPEREVM LP MONITOR\n", style="bold cyan")
        header_text.append(f"Multi-DEX Position Tracker v{VERSION}\n", style="bright_white")
        header_text.append(f"by {DEVELOPER}", style="italic dim")
        
        return Panel(
            Align.center(header_text),
            box=box.DOUBLE_EDGE,
            style="blue",
            padding=(1, 2)
        )
    
    def create_position_table_with_pnl(self, positions_with_status, wallet_address):
        """Create enhanced position table with PnL/IL metrics"""
        # Check for entry refresh needs (active positions only)
        if hasattr(self, 'db') and self.db:
            self.db.mark_entries_for_refresh(wallet_address, positions_with_status)
        
        # Extract token prices
        token_prices = {}
        show_value_column = False
        if PRICE_UTILS_AVAILABLE:
            token_prices = extract_token_prices_from_positions(positions_with_status)
            show_value_column = bool(token_prices)
        
        table = Table(
            title="LP Positions & Performance",
            box=box.ROUNDED,
            show_header=True,
            header_style="bold magenta",
            title_style="bold cyan",
            border_style="blue"
        )
        
        # Add columns - optimized widths for better fit
        table.add_column("DEX", style="cyan", width=11)
        table.add_column("Pair", style="yellow", width=16)
        table.add_column("Status", justify="center", width=12)
        table.add_column("Range", justify="center", width=18)
        
        if show_value_column:
            table.add_column("Value", justify="right", style="white")
            table.add_column("PnL", justify="right")
            table.add_column("IL", justify="right")
            table.add_column("APR", justify="right", style="cyan")
        
        table.add_column("Risk", justify="center", width=8)
        table.add_column("Fees", justify="right", style="green")
        
        # Track totals
        total_value = 0
        total_pnl = 0
        total_il = 0
        total_fees_earned = 0
        
        for position, status in positions_with_status:
            if not status:
                continue
            
            # Get PnL metrics if database available
            pnl_metrics = None
            if self.db and token_prices:
                try:
                    # Record snapshot/entry first so PnL has data immediately
                    self.db.record_position_snapshot(
                        position, status, wallet_address, token_prices
                    )
                    pnl_metrics = self.db.calculate_pnl_metrics(
                        position, status, wallet_address, token_prices
                    )
                except Exception as e:
                    if self.config.get("display_settings", {}).get("debug_mode", False):
                        console.print(f"[yellow]⚠️ PnL calculation error: {e}[/yellow]")
            
            # Format basic info
            pair_name = f"{status.get('token0_symbol', '?')}/{status.get('token1_symbol', '?')}"
            
            # Status - use full text
            if status['in_range']:
                status_text = Text("✅ IN RANGE", style="green")
            else:
                status_text = Text("❌ OUT", style="red")
            
            # Simplified range bar
            range_bar = self.create_compact_range_bar(
                position['tick_lower'],
                position['tick_upper'],
                status['current_tick'],
                status['in_range']
            )
            
            # Build row
            row = [
                position['dex_name'],
                pair_name,
                status_text,
                range_bar
            ]
            
            if show_value_column:
                # Position value
                position_value = calculate_position_value_usd(position, status, token_prices)
                if position_value:
                    total_value += position_value
                    value_text = format_usd_value(position_value)
                else:
                    value_text = "-"
                row.append(value_text)
                
                # PnL metrics
                if pnl_metrics:
                    # PnL
                    pnl_usd = pnl_metrics['pnl_usd']
                    pnl_pct = pnl_metrics['pnl_percent']
                    total_pnl += pnl_usd
                    
                    if pnl_usd >= 0:
                        pnl_text = Text(f"+{format_usd_value(pnl_usd)}", style="green")
                        pnl_text.append(f"\n{pnl_pct:+.1f}%", style="dim green")
                    else:
                        pnl_text = Text(f"{format_usd_value(pnl_usd)}", style="red")
                        pnl_text.append(f"\n{pnl_pct:.1f}%", style="dim red")
                    row.append(pnl_text)
                    
                    # Impermanent Loss
                    il_usd = pnl_metrics['il_usd']
                    il_pct = pnl_metrics['il_percent']
                    total_il += il_usd
                    
                    if il_usd >= 0:
                        il_text = Text(f"+{format_usd_value(il_usd)}", style="green")
                        il_text.append(f"\n{il_pct:+.1f}%", style="dim green")
                    else:
                        il_text = Text(f"{format_usd_value(il_usd)}", style="yellow")
                        il_text.append(f"\n{il_pct:.1f}%", style="dim yellow")
                    row.append(il_text)
                    
                    # APR from fees
                    apr = pnl_metrics['fee_apr']
                    if apr > 0:
                        apr_text = Text(f"{apr:.1f}%", style="cyan")
                        # Add time in position: prefer on-chain acquired timestamp when present
                        hours = pnl_metrics['hours_in_position']
                        if status.get('acquired_timestamp'):
                            from datetime import datetime
                            try:
                                onchain_hours = max(0.0, (datetime.now().timestamp() - float(status['acquired_timestamp'])) / 3600)
                                hours = max(hours, onchain_hours)
                            except Exception:
                                pass
                        if hours < 24:
                            apr_text.append(f"\n{hours:.1f}h", style="dim")
                        else:
                            days = hours / 24
                            apr_text.append(f"\n{days:.1f}d", style="dim")
                    else:
                        apr_text = Text("-", style="dim")
                    row.append(apr_text)
                    
                    total_fees_earned += pnl_metrics['total_fees_earned_usd']
                else:
                    # No PnL data yet
                    row.extend([
                        Text("New", style="dim"),
                        Text("New", style="dim"),
                        Text("-", style="dim")
                    ])
            
            # Risk level
            risk_text = self.get_compact_risk_badge(position, status)
            row.append(risk_text)
            
            # Fees
            if status.get('has_unclaimed_fees') and token_prices:
                fee0 = status.get('fee_amount0', 0)
                fee1 = status.get('fee_amount1', 0)
                token0 = status.get('token0_symbol', '')
                token1 = status.get('token1_symbol', '')
                
                fee_usd = 0
                if token0 in token_prices:
                    fee_usd += fee0 * token_prices[token0]
                if token1 in token_prices:
                    fee_usd += fee1 * token_prices[token1]
                
                if fee_usd > 0.01:
                    fee_text = f"{format_usd_value(fee_usd)}"
                else:
                    fee_text = "-"
            else:
                fee_text = "-"
            row.append(fee_text)
            
            table.add_row(*row)
        
        # Add summary footer if we have values
        if show_value_column and total_value > 0:
            table.add_row(
                Text("TOTAL", style="bold"),
                "",
                "",
                "",
                Text(format_usd_value(total_value), style="bold green"),
                Text(f"{format_usd_value(total_pnl)}\n{(total_pnl/total_value*100):+.1f}%" if total_value > 0 else "-", 
                     style="bold green" if total_pnl >= 0 else "bold red"),
                Text(f"{format_usd_value(total_il)}\n{(total_il/total_value*100):+.1f}%" if total_value > 0 else "-",
                     style="bold green" if total_il >= 0 else "bold yellow"),
                Text(f"{(total_fees_earned/total_value*100*365/30):,.1f}%" if total_value > 0 else "-", style="bold cyan"),  # Monthly to annual APR
                "",
                Text(format_usd_value(total_fees_earned), style="bold green")
            )
        
        return table
    
    def create_compact_range_bar(self, lower_tick, upper_tick, current_tick, in_range):
        """Create a compact visual range bar centered at mid-range.

        The pointer starts in the center and moves left (toward lower bound) or
        right (toward upper bound). Shows a signed percentage offset from center.
        """
        if is_full_range_position(lower_tick, upper_tick):
            return Text("[FULL]", style="bold cyan")

        bar_length = 11  # odd length so there is a true center cell
        center_index = bar_length // 2
        range_size = upper_tick - lower_tick

        # Out of range indicators remain explicit
        if not in_range:
            if current_tick < lower_tick:
                return Text("<[     ]", style="red")
            else:
                return Text("[     ]>", style="red")

        # Compute normalized offset relative to the midpoint (-1.0 .. 1.0)
        mid_tick = (lower_tick + upper_tick) / 2
        half_span = max(1, range_size / 2)
        normalized = (current_tick - mid_tick) / half_span
        if normalized < -1:
            normalized = -1
        elif normalized > 1:
            normalized = 1

        # Map normalized offset to a pointer index on the bar
        pointer_index = int(round(center_index + normalized * center_index))
        pointer_index = max(0, min(bar_length - 1, pointer_index))

        bar_text = Text()
        bar_text.append("[")

        for i in range(bar_length):
            # Center marker, unless the pointer sits exactly on it
            if i == center_index and i != pointer_index:
                bar_text.append("│", style="dim white")
                continue

            if i == pointer_index:
                bar_text.append("▓", style="yellow")
            elif (pointer_index > center_index and center_index < i < pointer_index) or \
                 (pointer_index < center_index and pointer_index < i < center_index):
                bar_text.append("█", style="green")
            else:
                bar_text.append("░", style="dim white")

        # Append signed percentage offset from center with fixed width to keep centering consistent
        offset_pct = normalized * 100
        bar_text.append("]", style="dim")
        bar_text.append(f" {offset_pct:+4.0f}%", style="dim")
        return bar_text
    
    def get_compact_risk_badge(self, position, status):
        """Get compact risk badge"""
        if not status['in_range']:
            return Text("OUT", style="bold red")
        
        if is_full_range_position(position['tick_lower'], position['tick_upper']):
            return Text("FULL", style="bold cyan")
        
        range_size = position['tick_upper'] - position['tick_lower']
        min_distance_pct = min(status['distance_to_lower'], status['distance_to_upper']) / range_size * 100
        
        if min_distance_pct < 5:
            return Text("HIGH", style="bold red")
        elif min_distance_pct < 15:
            return Text("MED", style="bold yellow")
        else:
            return Text("LOW", style="bold green")
    
    def create_performance_summary_panel(self, positions_with_status, wallet_address):
        """Create a panel showing overall portfolio performance"""
        summary_text = Text()
        summary_text.append("📈 Portfolio Performance\n\n", style="bold yellow")
        
        if not self.db or not PRICE_UTILS_AVAILABLE:
            summary_text.append("Install database module for performance tracking", style="dim")
            return Panel(summary_text, title="Performance", border_style="yellow", box=box.ROUNDED)
        
        # Get token prices
        token_prices = extract_token_prices_from_positions(positions_with_status)
        if not token_prices:
            summary_text.append("Need stablecoin pairs for USD metrics", style="dim")
            return Panel(summary_text, title="Performance", border_style="yellow", box=box.ROUNDED)
        
        # Calculate aggregate metrics
        total_value = 0
        total_pnl = 0
        total_il = 0
        total_fees = 0
        positions_with_data = 0
        
        for position, status in positions_with_status:
            if not status:
                continue
            
            try:
                pnl_metrics = self.db.calculate_pnl_metrics(
                    position, status, wallet_address, token_prices
                )
                
                if pnl_metrics:
                    positions_with_data += 1
                    total_value += pnl_metrics['current_value_usd']
                    total_pnl += pnl_metrics['pnl_usd']
                    total_il += pnl_metrics['il_usd']
                    total_fees += pnl_metrics['total_fees_earned_usd']
            except Exception as e:
                # Debug: print the actual error instead of silently continuing
                if hasattr(self, 'debug_mode') and self.debug_mode:
                    print(f"Error calculating PnL for position {position.get('token_id', 'unknown')}: {e}")
                continue
        
        if positions_with_data == 0:
            summary_text.append("No historical data yet - positions are new", style="dim")
            return Panel(summary_text, title="Performance", border_style="yellow", box=box.ROUNDED)
        
        # Display metrics
        summary_text.append(f"💼 Total Value: ", style="white")
        summary_text.append(f"{format_usd_value(total_value)}\n", style="bold green")
        
        # PnL
        summary_text.append(f"💰 Total PnL: ", style="white")
        pnl_color = "green" if total_pnl >= 0 else "red"
        pnl_pct = (total_pnl / total_value * 100) if total_value > 0 else 0
        summary_text.append(f"{format_usd_value(total_pnl)} ({pnl_pct:+.1f}%)\n", style=f"bold {pnl_color}")
        
        # IL
        summary_text.append(f"📊 Impermanent Loss: ", style="white")
        il_color = "green" if total_il >= 0 else "yellow"
        il_pct = (total_il / total_value * 100) if total_value > 0 else 0
        summary_text.append(f"{format_usd_value(total_il)} ({il_pct:+.1f}%)\n", style=f"bold {il_color}")
        
        # Fees earned
        summary_text.append(f"💎 Total Fees Earned: ", style="white")
        summary_text.append(f"{format_usd_value(total_fees)}\n", style="bold cyan")
        
        # Performance vs HODL
        summary_text.append(f"\n📈 LP vs HODL: ", style="white")
        if total_il >= 0:
            summary_text.append(f"Outperforming by {format_usd_value(total_il)}", style="bold green")
        else:
            summary_text.append(f"Underperforming by {format_usd_value(abs(total_il))}", style="bold yellow")
        
        return Panel(summary_text, title="Performance", border_style="green", box=box.ROUNDED)
    
    def create_dashboard_layout_with_pnl(self, positions_with_status, wallet_address, 
                                         refresh_countdown=None, notification_sent=False, refresh_cycle=None, is_refreshing=False, next_full_rescan_s=None):
        """Create dashboard layout with PnL metrics and status messages"""
        layout = Layout()
        
        # Create header
        layout.split_column(
            Layout(self.create_header_panel(), size=5, name="header"),
            Layout(name="body"),
            Layout(name="footer", size=3)
        )
        
        # Main body with PnL table
        layout["body"].split_row(
            Layout(self.create_position_table_with_pnl(positions_with_status, wallet_address), name="main", ratio=3),
            Layout(name="sidebar", ratio=1)
        )
        
        # Sidebar with stats and performance
        layout["sidebar"].split_column(
            Layout(self.create_stats_panel(positions_with_status, wallet_address)),
            Layout(self.create_performance_summary_panel(positions_with_status, wallet_address))
        )
        
        # Enhanced footer with all status messages
        footer_text = Text()
        footer_text.append(f"Last Update: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", style="dim")
        
        # Replace legacy cycle counter with next full rescan ETA if available
        if isinstance(next_full_rescan_s, (int, float)) and next_full_rescan_s is not None and next_full_rescan_s > 0:
            minutes = int(next_full_rescan_s // 60)
            seconds = int(next_full_rescan_s % 60)
            eta_str = f"{minutes}m {seconds:02d}s" if minutes > 0 else f"{seconds}s"
            footer_text.append(f" | Next full rescan in {eta_str}", style="cyan")
        
        # Maintenance hint removed (no longer applicable)
        
        # Background refresh hint
        if is_refreshing:
            footer_text.append(" | Scanning for new/removed positions...", style="cyan")
        
        # Add notification status if sent
        if notification_sent:
            footer_text.append(" | 🔔 Notification sent", style="green")
        
        # Add feature status
        footer_text.append(" | PnL/IL tracking enabled", style="green")
        
        # Add exit instruction
        footer_text.append(" | Press Ctrl+C to stop", style="yellow")
        
        layout["footer"].update(Panel(Align.center(footer_text), box=box.SIMPLE))
        
        return layout
    
    def create_stats_panel(self, positions_with_status, wallet_address):
        """Create portfolio statistics panel (simplified for space)"""
        stats_text = Text()
        
        total_positions = len(positions_with_status)
        in_range = sum(1 for _, status in positions_with_status if status and status.get('in_range', False))
        out_of_range = total_positions - in_range
        
        stats_text.append("📊 Positions\n\n", style="bold yellow")
        stats_text.append(f"Total: {total_positions}\n", style="white")
        
        if in_range > 0:
            stats_text.append(f"✅ In Range: {in_range}\n", style="green")
        if out_of_range > 0:
            stats_text.append(f"❌ Out: {out_of_range}\n", style="red")
        
        # DEX breakdown
        dex_counts = {}
        for position, _ in positions_with_status:
            dex_name = position.get("dex_name", "Unknown")
            dex_counts[dex_name] = dex_counts.get(dex_name, 0) + 1
        
        stats_text.append(f"\n🏪 DEXes:\n", style="bold")
        for dex, count in dex_counts.items():
            stats_text.append(f"  {dex}: {count}\n", style="cyan")
        
        return Panel(stats_text, title="Stats", border_style="green", box=box.ROUNDED)
    
    def print_live_dashboard(self, positions_with_status, wallet_address, 
                           refresh_countdown=None, notification_sent=False, refresh_cycle=None, is_refreshing=False, next_full_rescan_s=None):
        """Print the live updating dashboard with PnL and status messages"""
        layout = self.create_dashboard_layout_with_pnl(
            positions_with_status, 
            wallet_address,
            refresh_countdown=refresh_countdown,
            notification_sent=notification_sent,
            refresh_cycle=refresh_cycle,
            is_refreshing=is_refreshing,
            next_full_rescan_s=next_full_rescan_s
        )
        self.console.print(layout)


class EnhancedDisplayManager:
    """Enhanced display manager with PnL/IL tracking"""
    
    def __init__(self, config):
        self.config = config
        self.rich_display = RichDisplayManager(config)
        self.use_rich = config.get("display_settings", {}).get("use_rich_ui", True)
        self.setup_color_scheme()
    
    def setup_color_scheme(self):
        """Setup color scheme for fallback mode"""
        self.colors = {
            'danger': '\033[91m',
            'safe': '\033[92m',
            'warning': '\033[93m',
            'text': '\033[97m',
            'bold': '\033[1m',
            'end': '\033[0m'
        }
    
    def c(self, color_name):
        """Get color code for fallback mode"""
        return self.colors.get(color_name, '')
    
    def print_header(self):
        """Print header - use Rich if available"""
        if self.use_rich:
            console.print(self.rich_display.create_header_panel())
        else:
            print(f"{self.c('bold')}")
            print("╔══════════════════════════════════════════════════════════════╗")
            print("║                 💧 HYPEREVM LP MONITOR                       ║")
            print(f"║                    v{VERSION} by {DEVELOPER}                      ║")
            print("╚══════════════════════════════════════════════════════════════╝")
            print(f"{self.c('end')}")
    
    def display_positions(self, positions_with_status, wallet_address, 
                        refresh_countdown=None, notification_sent=False, refresh_cycle=None, is_refreshing=False, next_full_rescan_s=None):
        """Display all positions with PnL metrics and status messages"""
        if self.use_rich:
            self.rich_display.print_live_dashboard(
                positions_with_status, 
                wallet_address,
                refresh_countdown=refresh_countdown,
                notification_sent=notification_sent,
                refresh_cycle=refresh_cycle,
                is_refreshing=is_refreshing,
                next_full_rescan_s=next_full_rescan_s
            )
        else:
            self.display_positions_simple(positions_with_status)
            # Show status messages in simple mode too
            if refresh_cycle and isinstance(refresh_cycle, tuple) and len(refresh_cycle) == 2:
                try:
                    current_cycle_int = int(refresh_cycle[0])
                    total_cycles_int = int(refresh_cycle[1])
                    # Legacy: suppress noisy ratio prints
                    pass
                except Exception:
                    pass
            if refresh_countdown is not None and refresh_countdown > 0:
                print(f"Maintenance refresh soon")
            if notification_sent:
                print("🔔 Notification sent")
    
    def display_positions_simple(self, positions_with_status):
        """Simple fallback display without Rich"""
        for position, status in positions_with_status:
            if not status:
                continue
            
            name = position["name"]
            in_range = "✅ IN RANGE" if status['in_range'] else "❌ OUT OF RANGE"
            
            print(f"\n📍 {name}")
            print(f"   Status: {in_range}")
            print(f"   Price: {format_price(status['current_price'])}")
            
            # Try to show PnL if database available
            if DATABASE_AVAILABLE and hasattr(self, 'db'):
                try:
                    pnl_metrics = self.rich_display.db.calculate_pnl_metrics(
                        position, status, "wallet", {}
                    )
                    if pnl_metrics:
                        print(f"   PnL: {format_usd_value(pnl_metrics['pnl_usd'])} ({pnl_metrics['pnl_percent']:+.1f}%)")
                        print(f"   IL: {format_usd_value(pnl_metrics['il_usd'])} ({pnl_metrics['il_percent']:+.1f}%)")
                except:
                    pass
    
    def print_goodbye(self):
        """Print goodbye message"""
        if self.use_rich:
            goodbye_text = Text()
            goodbye_text.append("👋 MONITORING STOPPED\n", style="bold yellow")
            goodbye_text.append(f"Thanks for using LP Monitor v{VERSION}!", style="white")
            
            console.print(Panel(
                Align.center(goodbye_text),
                box=box.DOUBLE_EDGE,
                style="yellow",
                padding=(1, 2)
            ))
        else:
            print("👋 Monitoring stopped")


# For backward compatibility
DisplayManager = EnhancedDisplayManager

def clear_screen():
    """Clear the terminal screen"""
    try:
        if os.name == 'nt':
            os.system('cls')
        else:
            os.system('clear')
    except:
        print('\n' * 50)

def get_color_scheme_from_user():
    """Interactive color scheme selection for setup"""
    print("📺 Display Options:")
    print("1. Rich UI with PnL tracking (recommended)")
    print("2. Simple colored text")
    print("3. No colors (plain text)")
    
    choice = input("Choose display mode (1-3, default: 1): ").strip()
    if choice == "2":
        return "simple"
    elif choice == "3":
        return "none"
    else:
        return "rich"