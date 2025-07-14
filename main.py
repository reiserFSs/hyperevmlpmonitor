#!/usr/bin/env python3
"""
HyperEVM LP Position Monitor - Main Entry Point
Multi-DEX liquidity position tracking for HyperEVM

Features:
- Dynamic position tracking (auto-detects new/removed positions)
- Multi-notification support (Telegram, Discord, Pushover, Email)
- Real-time price monitoring with DYNAMIC thresholds
- Multi-DEX support (Uniswap V3, Algebra Integral)
- Unclaimed fee tracking using static collect() calls
- Simplified color scheme options
- Modular architecture for maintainability

Version: 1.4.1 (Modular Architecture + Fee Tracking)
Developer: 8roku8.hl
"""

import sys
import os

# Add current directory to path to import local modules
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from config import load_config, setup_first_run, validate_config
from position_monitor import LPMonitor
from constants import VERSION, DEVELOPER

def print_startup_banner():
    """Print clean startup banner"""
    print("╔══════════════════════════════════════════════════════════════╗")
    print("║                 💧 HYPEREVM LP MONITOR                       ║")
    print("║                  Multi-DEX Position Tracker                 ║")
    print(f"║                    v{VERSION} by {DEVELOPER}                      ║")
    print("║              (Modular + Fee Tracking)                       ║")
    print("╚══════════════════════════════════════════════════════════════╝")
    print()

def main():
    """Clean main function with proper error handling"""
    try:
        # Print startup banner
        print_startup_banner()
        
        # Load or create configuration
        print("🔧 Loading configuration...")
        config = load_config()
        
        if config is None:
            print("🚀 Starting first-time setup...")
            config = setup_first_run()
            if config is None:
                print("❌ Setup cancelled or failed")
                return 1
        
        # Validate configuration
        print("✅ Validating configuration...")
        if not validate_config(config):
            print("❌ Configuration validation failed")
            return 1
        
        print("🎯 Configuration validated successfully!")
        
        # Show features status
        show_features_status(config)
        
        # Initialize LP Monitor
        print("🔄 Initializing LP Monitor...")
        try:
            monitor = LPMonitor(config)
        except Exception as e:
            print(f"❌ Failed to initialize monitor: {e}")
            return 1
        
        # Check if positions were found
        if len(monitor.positions) == 0:
            print("\n🤔 No LP positions found across any configured DEX.")
            print("This could mean:")
            print("  1. Wrong wallet address")
            print("  2. Wrong position manager contract addresses")
            print("  3. No LP positions in this wallet")
            print("  4. Position managers don't implement standard interface")
            print(f"\n💡 Check your configuration in lp_monitor_config.json")
            
            # Show configured DEXes for debugging
            dex_names = [dex['name'] for dex in config['dexes']]
            print(f"📋 Configured DEXes: {', '.join(dex_names)}")
            return 1
        
        print(f"✅ Found {len(monitor.positions)} LP positions")
        print("🚀 Starting monitoring loop...\n")
        
        # Start monitoring (this runs indefinitely until Ctrl+C)
        monitor.monitor_positions()
        
        return 0
        
    except KeyboardInterrupt:
        print("\n👋 Monitoring stopped by user")
        return 0
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return 1

def show_features_status(config):
    """Show status of key features"""
    print("📋 Feature Status:")
    
    # Fee tracking
    fee_tracking = config.get("display_settings", {}).get("show_unclaimed_fees", True)
    if fee_tracking:
        print("   💰 Fee tracking: ✅ Enabled")
    else:
        print("   💰 Fee tracking: ❌ Disabled")
    
    # Notifications
    notifications_enabled = config.get("notifications", {}).get("enabled", False)
    if notifications_enabled:
        notification_type = config.get("notifications", {}).get("type", "telegram")
        include_fees = config.get("notifications", {}).get("include_fees_in_notifications", True)
        fee_status = "with fees" if include_fees and fee_tracking else "without fees"
        print(f"   🔔 Notifications: ✅ Enabled ({notification_type}, {fee_status})")
    else:
        print("   🔔 Notifications: ❌ Disabled")
    
    # Debug mode
    debug_mode = config.get("display_settings", {}).get("debug_mode", False)
    if debug_mode:
        print("   🔍 Debug mode: ✅ Enabled")
    
    # Color scheme
    color_scheme = config.get("display_settings", {}).get("color_scheme", "minimal")
    print(f"   🎨 Color scheme: {color_scheme}")
    
    print()

if __name__ == "__main__":
    """Entry point with proper exit code"""
    exit_code = main()
    sys.exit(exit_code)