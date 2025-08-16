#!/usr/bin/env python3
"""
HyperEVM LP Position Monitor - Main Entry Point
Multi-DEX liquidity position tracking for HyperEVM

Version: 1.5.0 (Modular Architecture + Fee Tracking + Rich UI)
Developer: 8roku8.hl
"""

import sys
import os

# Add current directory to path to import local modules
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from config import load_config, setup_first_run, validate_config
from constants import VERSION, DEVELOPER

# Try to import Rich for enhanced display
try:
    from rich.console import Console
    from rich.panel import Panel
    from rich import box
    RICH_AVAILABLE = True
    console = Console()
except ImportError:
    RICH_AVAILABLE = False
    console = None

def print_startup_banner():
    """Print clean startup banner with Rich if available"""
    if RICH_AVAILABLE:
        from rich.text import Text
        from rich.align import Align
        
        banner_text = Text()
        banner_text.append("💧 HYPEREVM LP MONITOR\n", style="bold cyan")
        banner_text.append("Multi-DEX Position Tracker\n", style="bright_white")
        banner_text.append(f"v{VERSION} by {DEVELOPER}\n", style="italic")
        banner_text.append("(Modular + Fee Tracking + Rich UI)", style="dim")
        
        panel = Panel(
            Align.center(banner_text),
            box=box.DOUBLE_EDGE,
            style="blue",
            padding=(1, 2)
        )
        console.print(panel)
    else:
        print("╔══════════════════════════════════════════════════════════════╗")
        print("║                 💧 HYPEREVM LP MONITOR                       ║")
        print("║                  Multi-DEX Position Tracker                 ║")
        print(f"║                    v{VERSION} by {DEVELOPER}                      ║")
        print("║              (Modular + Fee Tracking)                       ║")
        print("╚══════════════════════════════════════════════════════════════╝")
        print()

def main():
    """Clean main function with proper error handling and Rich UI support"""
    try:
        # Print startup banner
        print_startup_banner()
        
        # Check if Rich is available and inform user
        if RICH_AVAILABLE:
            console.print("[green]✅ Rich UI library detected - enhanced display enabled![/green]")
        else:
            print("📝 Rich UI not installed. Run 'pip3 install rich' for enhanced display")
            print("   Continuing with simple text display...")
        
        # Load or create configuration
        if RICH_AVAILABLE:
            console.print("[cyan]🔧 Loading configuration...[/cyan]")
        else:
            print("🔧 Loading configuration...")
        
        config = load_config()
        
        if config is None:
            if RICH_AVAILABLE:
                console.print("[yellow]🚀 Starting first-time setup...[/yellow]")
            else:
                print("🚀 Starting first-time setup...")
            
            config = setup_first_run()
            if config is None:
                if RICH_AVAILABLE:
                    console.print("[red]❌ Setup cancelled or failed[/red]")
                else:
                    print("❌ Setup cancelled or failed")
                return 1
        
        # Auto-enable Rich UI if available and not explicitly disabled
        if RICH_AVAILABLE and "use_rich_ui" not in config.get("display_settings", {}):
            config["display_settings"]["use_rich_ui"] = True
            if console:
                console.print("[green]🎨 Auto-enabled Rich UI for better experience[/green]")
        
        # Validate configuration
        if RICH_AVAILABLE:
            console.print("[cyan]✅ Validating configuration...[/cyan]")
        else:
            print("✅ Validating configuration...")
        
        if not validate_config(config):
            if RICH_AVAILABLE:
                console.print("[red]❌ Configuration validation failed[/red]")
            else:
                print("❌ Configuration validation failed")
            return 1
        
        if RICH_AVAILABLE:
            console.print("[green]🎯 Configuration validated successfully![/green]")
        else:
            print("🎯 Configuration validated successfully!")
        
        # Show features status
        show_features_status(config)
        
        # Initialize LP Monitor - use enhanced version if Rich is available
        if RICH_AVAILABLE:
            console.print("[cyan]🔄 Initializing LP Monitor...[/cyan]")
        else:
            print("🔄 Initializing LP Monitor...")
        
        try:
            # Import the appropriate monitor based on Rich availability
            if RICH_AVAILABLE and config.get("display_settings", {}).get("use_rich_ui", True):
                from position_monitor import EnhancedLPMonitor
                monitor = EnhancedLPMonitor(config)
            else:
                from position_monitor import LPMonitor
                monitor = LPMonitor(config)
        except ImportError:
            # Fallback to original monitor if enhanced not available
            from position_monitor import LPMonitor
            monitor = LPMonitor(config)
        except Exception as e:
            if RICH_AVAILABLE:
                console.print(f"[red]❌ Failed to initialize monitor: {e}[/red]")
            else:
                print(f"❌ Failed to initialize monitor: {e}")
            return 1
        
        # Check if positions were found
        if len(monitor.positions) == 0:
            error_msg = """
🤔 No LP positions found across any configured DEX.
This could mean:
  1. Wrong wallet address
  2. Wrong position manager contract addresses
  3. No LP positions in this wallet
  4. Position managers don't implement standard interface

💡 Check your configuration in lp_monitor_config.json
"""
            if RICH_AVAILABLE:
                console.print(Panel(error_msg, title="No Positions Found", border_style="yellow"))
            else:
                print(error_msg)
            
            # Show configured DEXes for debugging
            dex_names = [dex['name'] for dex in config['dexes']]
            if RICH_AVAILABLE:
                console.print(f"[dim]📋 Configured DEXes: {', '.join(dex_names)}[/dim]")
            else:
                print(f"📋 Configured DEXes: {', '.join(dex_names)}")
            return 1
        
        if RICH_AVAILABLE:
            console.print(f"[green]✅ Found {len(monitor.positions)} LP positions[/green]")
            console.print("[bold green]🚀 Starting monitoring loop...[/bold green]\n")
        else:
            print(f"✅ Found {len(monitor.positions)} LP positions")
            print("🚀 Starting monitoring loop...\n")
        
        # Start monitoring (this runs indefinitely until Ctrl+C)
        monitor.monitor_positions()
        
        return 0
        
    except KeyboardInterrupt:
        if RICH_AVAILABLE:
            console.print("\n[yellow]👋 Monitoring stopped by user[/yellow]")
        else:
            print("\n👋 Monitoring stopped by user")
        return 0
    except Exception as e:
        if RICH_AVAILABLE:
            console.print(f"\n[red]❌ Unexpected error: {e}[/red]")
        else:
            print(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return 1

def show_features_status(config):
    """Show status of key features with Rich formatting if available"""
    features = []
    
    # Rich UI status
    use_rich = config.get("display_settings", {}).get("use_rich_ui", True)
    use_live = config.get("display_settings", {}).get("use_live_display", False)
    
    if RICH_AVAILABLE and use_rich:
        if use_live:
            features.append(("🎨 Display", "Rich UI (Live Mode)", "green"))
        else:
            features.append(("🎨 Display", "Rich UI (Clear Mode)", "green"))
    elif RICH_AVAILABLE and not use_rich:
        features.append(("🎨 Display", "Simple Text (Rich available)", "yellow"))
    else:
        features.append(("🎨 Display", "Simple Text", "white"))
    
    # Fee tracking
    fee_tracking = config.get("display_settings", {}).get("show_unclaimed_fees", True)
    if fee_tracking:
        features.append(("💰 Fee tracking", "Enabled", "green"))
    else:
        features.append(("💰 Fee tracking", "Disabled", "dim"))
    
    # Notifications
    notifications_enabled = config.get("notifications", {}).get("enabled", False)
    if notifications_enabled:
        notification_type = config.get("notifications", {}).get("type", "telegram")
        include_fees = config.get("notifications", {}).get("include_fees_in_notifications", True)
        fee_status = "with fees" if include_fees and fee_tracking else "without fees"
        features.append(("🔔 Notifications", f"{notification_type} ({fee_status})", "green"))
    else:
        features.append(("🔔 Notifications", "Disabled", "dim"))
    
    # Debug mode
    debug_mode = config.get("display_settings", {}).get("debug_mode", False)
    if debug_mode:
        features.append(("🔍 Debug mode", "Enabled", "yellow"))
    
    # Color scheme
    color_scheme = config.get("display_settings", {}).get("color_scheme", "minimal")
    if color_scheme == "rich":
        features.append(("🎯 Color scheme", "Rich", "cyan"))
    else:
        features.append(("🎯 Color scheme", color_scheme, "white"))
    
    if RICH_AVAILABLE:
        from rich.table import Table
        
        table = Table(title="Feature Status", box=box.SIMPLE, show_header=False)
        table.add_column("Feature", style="cyan")
        table.add_column("Status", style="white")
        
        for feature, status, color in features:
            table.add_row(feature, f"[{color}]{status}[/{color}]")
        
        console.print(table)
        console.print()
    else:
        print("📋 Feature Status:")
        for feature, status, _ in features:
            print(f"   {feature}: {status}")
        print()

if __name__ == "__main__":
    """Entry point with proper exit code"""
    exit_code = main()
    sys.exit(exit_code)