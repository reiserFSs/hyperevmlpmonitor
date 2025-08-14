#!/usr/bin/env python3
"""
Configuration Management Module for HyperEVM LP Monitor
Handles loading, saving, and setup of LP monitor configuration

UPDATED VERSION: Smart notification setup with per-position cooldowns + Fee tracking + Rich UI

Version: 1.5.0 (Smart Notifications + Fee Tracking + Rich UI)
Developer: 8roku8.hl + Claude
"""

import json
import os
import copy
from constants import DEFAULT_CONFIG, CONFIG_FILE
from utils import validate_dex_configs

def load_config():
    """Load configuration from JSON file, create default if doesn't exist"""
    if not os.path.exists(CONFIG_FILE):
        print("⚙️  Configuration file not found. Creating default config...")
        save_config(DEFAULT_CONFIG)
        print(f"✅ Created {CONFIG_FILE}")
        print("📝 Please edit the configuration file and restart the monitor.")
        return None
    
    try:
        with open(CONFIG_FILE, 'r') as f:
            config = json.load(f)
        
        # Update config with any missing default values
        updated = update_config_with_defaults(config)
        if updated:
            save_config(config)
            print("📝 Updated configuration with new settings")
        
        return config
    except json.JSONDecodeError as e:
        print(f"❌ Error reading config file: {e}")
        return None
    except Exception as e:
        print(f"❌ Error loading config: {e}")
        return None

def save_config(config):
    """Save configuration to JSON file"""
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=4)
    except Exception as e:
        print(f"❌ Error saving config: {e}")

def update_config_with_defaults(config):
    """Update configuration with any missing default values"""
    updated = False
    
    def update_nested_dict(target, source):
        nonlocal updated
        for key, value in source.items():
            if key not in target:
                target[key] = value
                updated = True
            elif isinstance(value, dict) and isinstance(target[key], dict):
                update_nested_dict(target[key], value)
    
    update_nested_dict(config, DEFAULT_CONFIG)
    return updated

def validate_config(config):
    """Validate configuration and return True if valid"""
    if not config.get("wallet_address"):
        print(f"❌ Wallet address not set. Please edit {CONFIG_FILE}")
        return False
    
    if not config.get("dexes") or len(config["dexes"]) == 0:
        print(f"❌ No DEXes configured. Please edit {CONFIG_FILE} or run setup again")
        print(f"💡 Add DEXes to the 'dexes' array with 'name', 'position_manager', and 'type' fields")
        return False
    
    # Validate DEX configurations
    valid_dexes = validate_dex_configs(config["dexes"])
    if len(valid_dexes) == 0:
        print(f"❌ No valid DEXes found. Please check your configuration in {CONFIG_FILE}")
        return False
    
    config["dexes"] = valid_dexes
    return True

def setup_first_run():
    """Interactive setup for first-time users with smart notification system and Rich UI"""
    print("╔══════════════════════════════════════════════════════════════╗")
    print("║              WELCOME TO HYPEREVM LP MONITOR                 ║")
    print("║                    First Time Setup                         ║")
    print("╚══════════════════════════════════════════════════════════════╝")
    print()
    
    # Use deep copy to avoid mutating DEFAULT_CONFIG's nested structures
    config = copy.deepcopy(DEFAULT_CONFIG)
    
    print(f"Let's set up your LP monitor. You can modify these settings later in {CONFIG_FILE}\n")
    
    # Display preferences (Rich UI + color scheme)
    config = setup_display_preferences(config)
    
    # Wallet setup
    config = setup_wallet(config)
    
    # DEX setup
    config = setup_dexes(config)
    
    if not config.get("dexes"):
        print("❌ No DEXes configured. Please run setup again.")
        return None
    
    # Optional settings
    config = setup_optional_settings(config)
    
    # Smart notifications
    config = setup_notifications(config)
    
    save_config(config)
    print(f"\n✅ Configuration saved to {CONFIG_FILE}")
    print(f"📊 Configured {len(config['dexes'])} DEX(es) for monitoring")
    print("🚀 You can now run the monitor again!")
    
    return config

def setup_display_preferences(config):
    """Setup display preferences including Rich UI and color schemes"""
    print("🎨 Display Preferences:")
    
    # Rich UI option
    print("\n📺 Display Options:")
    print("1. Rich UI with beautiful tables (recommended)")
    print("2. Simple colored text")
    print("3. Plain text (no colors)")
    
    choice = input("Choose display mode (1-3, default: 1): ").strip()
    
    if choice == "2":
        config["display_settings"]["use_rich_ui"] = False
        config["display_settings"]["color_scheme"] = "minimal"
        print("📺 Simple colored text display selected")
    elif choice == "3":
        config["display_settings"]["use_rich_ui"] = False
        config["display_settings"]["color_scheme"] = "none"
        print("📺 Plain text display selected")
    else:
        config["display_settings"]["use_rich_ui"] = True
        config["display_settings"]["color_scheme"] = "rich"
        print("📺 Rich UI enabled - enjoy beautiful tables and visualizations!")
        
        # Additional Rich UI options
        compact_input = input("\nUse compact display mode? (y/n, default: n): ").strip().lower()
        if compact_input in ['y', 'yes']:
            config["display_settings"]["compact_mode"] = True
            print("📺 Compact mode enabled - more positions visible at once")
        else:
            config["display_settings"]["compact_mode"] = False
            print("📺 Full display mode - detailed position information")
        
        # Table style for Rich UI
        print("\n📊 Table Style:")
        print("1. Rounded borders (default)")
        print("2. Simple borders")
        print("3. Double borders")
        
        style_choice = input("Choose table style (1-3, default: 1): ").strip()
        if style_choice == "2":
            config["display_settings"]["table_style"] = "simple"
        elif style_choice == "3":
            config["display_settings"]["table_style"] = "double"
        else:
            config["display_settings"]["table_style"] = "rounded"
        
        print(f"📊 Table style: {config['display_settings']['table_style']}")
    
    return config

def get_color_scheme_from_user():
    """Legacy function for backward compatibility"""
    print("📺 Display Options:")
    print("1. Rich UI with beautiful tables (recommended)")
    print("2. Simple colored text")
    print("3. Plain text (no colors)")
    
    choice = input("Choose display mode (1-3, default: 1): ").strip()
    if choice == "2":
        return "minimal"
    elif choice == "3":
        return "none"
    else:
        return "rich"

def setup_wallet(config):
    """Setup wallet address"""
    wallet = input("\nEnter your wallet address: ").strip()
    if wallet:
        config["wallet_address"] = wallet
    return config

def setup_dexes(config):
    """Setup DEX configurations"""
    print("\n📋 Now let's add the DEXes you want to monitor.")
    print("Popular DEXes on HyperEVM: Hybra Finance, HyperSwap, Ramses, Laminar, Kittenswap, Gliquid")
    print("Note: Gliquid uses Algebra Integral - now with enhanced tick parsing!")
    
    dexes = []
    dex_count = 1
    
    while True:
        print(f"\n--- DEX #{dex_count} ---")
        
        dex_name = input("Enter DEX name (or press Enter to finish): ").strip()
        if not dex_name:
            break
            
        position_manager = input(f"Enter NonFungiblePositionManager contract address for {dex_name}: ").strip()
        if not position_manager:
            print(f"⚠️  Skipping {dex_name} - no position manager provided")
            continue
        
        # Ask about DEX type for better compatibility
        dex_type = determine_dex_type(dex_name)
        
        dexes.append({
            "name": dex_name,
            "position_manager": position_manager,
            "type": dex_type
        })
        
        print(f"✅ Added {dex_name} ({dex_type})")
        dex_count += 1
        
        # Ask if they want to add more
        if dex_count > 5:  # Reasonable limit
            more = input("Add another DEX? (y/n): ").strip().lower()
            if more != 'y' and more != 'yes':
                break
    
    config["dexes"] = dexes
    return config

def determine_dex_type(dex_name):
    """Determine DEX type based on name or user input"""
    dex_type = "uniswap_v3"  # Default
    
    if dex_name.lower() in ["gliquid", "quickswap"]:
        type_input = input(f"Is {dex_name} using Algebra Integral? (y/n, default: y): ").strip().lower()
        if type_input != 'n' and type_input != 'no':
            dex_type = "algebra_integral"
    else:
        type_input = input("DEX type - (1) Uniswap V3 (default), (2) Algebra Integral: ").strip()
        if type_input == "2":
            dex_type = "algebra_integral"
    
    return dex_type

def setup_optional_settings(config):
    """Setup optional monitoring settings"""
    # Monitoring interval
    interval_input = input(f"\nCheck interval in seconds (default: 30): ").strip()
    if interval_input.isdigit():
        config["check_interval"] = int(interval_input)
    
    # Screen clearing
    if config["display_settings"].get("use_rich_ui", True):
        # Rich UI benefits from screen clearing
        clear_screen_input = input(f"\nEnable screen clearing for cleaner display? (y/n, default: y): ").strip().lower()
        if clear_screen_input in ['n', 'no']:
            config["display_settings"]["clear_screen"] = False
            print("📺 Screen clearing disabled - output will scroll")
        else:
            config["display_settings"]["clear_screen"] = True
            print("📺 Screen clearing enabled - cleaner display")
    else:
        # For simple text, scrolling might be preferred
        clear_screen_input = input(f"\nEnable screen clearing? (y/n, default: n): ").strip().lower()
        if clear_screen_input in ['y', 'yes']:
            config["display_settings"]["clear_screen"] = True
            print("📺 Screen clearing enabled")
        else:
            config["display_settings"]["clear_screen"] = False
            print("📺 Screen clearing disabled - output will scroll")
    
    # Fee tracking
    fees_input = input(f"\nEnable unclaimed fee tracking? (y/n, default: y): ").strip().lower()
    if fees_input in ['n', 'no']:
        config["display_settings"]["show_unclaimed_fees"] = False
        print("💰 Fee tracking disabled")
    else:
        config["display_settings"]["show_unclaimed_fees"] = True
        print("💰 Fee tracking enabled - will show unclaimed fees")
    
    # Debug mode
    debug_input = input(f"\nEnable debug mode for troubleshooting? (y/n): ").strip().lower()
    if debug_input in ['y', 'yes']:
        config["display_settings"]["debug_mode"] = True
        print("🔍 Debug mode enabled - will show detailed calculation info")
    
    # Rich UI specific: Show animations
    if config["display_settings"].get("use_rich_ui", True):
        animations_input = input(f"\nShow loading animations and progress bars? (y/n, default: y): ").strip().lower()
        if animations_input in ['n', 'no']:
            config["display_settings"]["refresh_animation"] = False
            print("🎬 Animations disabled")
        else:
            config["display_settings"]["refresh_animation"] = True
            print("🎬 Animations enabled - smoother visual feedback")
    
    return config

def setup_notifications(config):
    """Setup notification system with smart per-position tracking"""
    print(f"\n🔔 SMART NOTIFICATION SETUP")
    print("Get intelligent notifications about your LP positions!")
    print("Smart notifications track each position individually and avoid spam:")
    print("  ✅ Immediate alerts when positions change status")
    print("  ⏰ Smart cooldowns prevent repeated notifications")
    print("  📊 Escalation alerts when situations get worse")
    print("  🎯 Resolution alerts when danger passes")
    
    enable_notifications = input("\nEnable smart notifications? (y/n): ").strip().lower()
    if enable_notifications not in ['y', 'yes']:
        print("🔔 Notifications disabled")
        return config
    
    config["notifications"]["enabled"] = True
    
    # Choose notification method
    print(f"\n📋 Choose your notification method:")
    print("1. 🤖 Telegram Bot (Recommended - Free, secure, instant)")
    print("2. 💬 Discord Webhook (Free, simple setup)")
    print("3. 📱 Pushover (Push notifications, $5 one-time)")
    print("4. 📧 Email (Traditional, may have setup issues)")
    
    choice = input("Enter choice (1-4): ").strip()
    
    if choice == "1":
        config = setup_telegram_notifications(config)
    elif choice == "2":
        config = setup_discord_notifications(config)
    elif choice == "3":
        config = setup_pushover_notifications(config)
    elif choice == "4":
        config = setup_email_notifications(config)
    
    # Smart notification preferences
    config = setup_smart_notification_preferences(config)
    
    print("✅ Smart notifications configured!")
    return config

def setup_smart_notification_preferences(config):
    """Setup smart notification preferences with per-position cooldowns"""
    print(f"\n⚙️  Smart Notification Settings:")
    
    # Explain the smart system
    print("Smart notifications use different cooldown periods:")
    print("  🚨 Status changes: Immediate (no cooldown)")
    print("  ❌ Out-of-range: 30 min cooldown")  
    print("  🚨 Danger zone: 60 min cooldown")
    print("  ⚠️  Warning zone: 2 hour cooldown")
    print("  ✅ Safe positions: 6 hour cooldown")
    
    # Ask if they want to customize cooldowns
    customize = input("\nCustomize cooldown periods? (y/n, default: n): ").strip().lower()
    if customize in ['y', 'yes']:
        config = setup_custom_cooldowns(config)
    else:
        print("✅ Using default smart cooldown periods")
    
    # Global notification limit (replaces old interval)
    print(f"\n📊 Global notification limit:")
    print("Prevents notification overload during market volatility.")
    
    global_cooldown_input = input("Minimum time between any notifications (minutes, default: 15): ").strip()
    if global_cooldown_input.isdigit():
        global_cooldown_seconds = int(global_cooldown_input) * 60
        config["notifications"]["notification_cooldown"] = global_cooldown_seconds
        print(f"✅ Set global cooldown to {global_cooldown_input} minutes")
    else:
        config["notifications"]["notification_cooldown"] = 900  # 15 minutes default
        print("✅ Using default 15-minute global cooldown")
    
    # Include fees in notifications
    if config.get("display_settings", {}).get("show_unclaimed_fees", True):
        include_fees = input("\nInclude fee information in notifications? (y/n, default: y): ").strip().lower()
        if include_fees in ['n', 'no']:
            config["notifications"]["include_fees_in_notifications"] = False
            print("💰 Fee information will not be included in notifications")
        else:
            config["notifications"]["include_fees_in_notifications"] = True
            print("💰 Fee information will be included in notifications")
    
    # Issues-only mode (still useful for very conservative users)
    issues_only = input("\nOnly notify about problems (skip all safe position updates)? (y/n, default: n): ").strip().lower()
    if issues_only in ['y', 'yes']:
        config["notifications"]["notify_on_issues_only"] = True
        print("✅ Will only notify about out-of-range, danger, and warning positions")
    else:
        config["notifications"]["notify_on_issues_only"] = False
        print("✅ Will send smart updates for all position changes")
    
    return config

def setup_custom_cooldowns(config):
    """Allow users to customize cooldown periods"""
    print(f"\n⚙️  Customize Cooldown Periods:")
    
    # Initialize smart_cooldowns section if not exists
    if "smart_cooldowns" not in config["notifications"]:
        config["notifications"]["smart_cooldowns"] = {}
    
    cooldowns = config["notifications"]["smart_cooldowns"]
    
    # Out of range cooldown
    out_of_range_input = input("Out-of-range position cooldown (minutes, default: 30): ").strip()
    if out_of_range_input.isdigit():
        cooldowns["same_out_of_range"] = int(out_of_range_input) * 60
    else:
        cooldowns["same_out_of_range"] = 30 * 60
    
    # Danger cooldown  
    danger_input = input("Danger zone cooldown (minutes, default: 60): ").strip()
    if danger_input.isdigit():
        cooldowns["same_danger"] = int(danger_input) * 60
    else:
        cooldowns["same_danger"] = 60 * 60
    
    # Warning cooldown
    warning_input = input("Warning zone cooldown (hours, default: 2): ").strip()
    if warning_input.isdigit():
        cooldowns["same_warning"] = int(warning_input) * 60 * 60
    else:
        cooldowns["same_warning"] = 2 * 60 * 60
    
    # Safe cooldown
    safe_input = input("Safe position cooldown (hours, default: 6): ").strip()
    if safe_input.isdigit():
        cooldowns["same_safe"] = int(safe_input) * 60 * 60
    else:
        cooldowns["same_safe"] = 6 * 60 * 60
    
    print("✅ Custom cooldown periods configured!")
    return config

def setup_telegram_notifications(config):
    """Setup Telegram bot notifications"""
    config["notifications"]["type"] = "telegram"
    print(f"\n🤖 TELEGRAM BOT SETUP")
    print("Step 1: Create a bot")
    print("  - Message @BotFather on Telegram")
    print("  - Send: /newbot")
    print("  - Follow instructions to get your bot token")
    print(f"\nStep 2: Get your chat ID")
    print("  - Start a chat with your new bot")
    print("  - Send any message to the bot")
    print("  - Visit: https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates")
    print("  - Look for 'chat':{'id'} in the response")
    
    bot_token = input(f"\nEnter your bot token: ").strip()
    if bot_token:
        config["notifications"]["telegram"]["bot_token"] = bot_token
    
    chat_id = input("Enter your chat ID: ").strip()
    if chat_id:
        config["notifications"]["telegram"]["chat_id"] = chat_id
    
    return config

def setup_discord_notifications(config):
    """Setup Discord webhook notifications"""
    config["notifications"]["type"] = "discord"
    print(f"\n💬 DISCORD WEBHOOK SETUP")
    print("Step 1: Go to your Discord server")
    print("Step 2: Go to channel settings → Integrations → Webhooks")
    print("Step 3: Create New Webhook")
    print("Step 4: Copy the webhook URL")
    
    webhook_url = input(f"\nEnter Discord webhook URL: ").strip()
    if webhook_url:
        config["notifications"]["discord"]["webhook_url"] = webhook_url
    
    return config

def setup_pushover_notifications(config):
    """Setup Pushover notifications"""
    config["notifications"]["type"] = "pushover"
    print(f"\n📱 PUSHOVER SETUP")
    print("Step 1: Sign up at https://pushover.net ($5 one-time)")
    print("Step 2: Create an application")
    print("Step 3: Get your User Key and API Token")
    
    user_key = input(f"\nEnter your Pushover User Key: ").strip()
    if user_key:
        config["notifications"]["pushover"]["user_key"] = user_key
        
    api_token = input("Enter your Pushover API Token: ").strip()
    if api_token:
        config["notifications"]["pushover"]["api_token"] = api_token
    
    return config

def setup_email_notifications(config):
    """Setup email notifications"""
    config["notifications"]["type"] = "email"
    print(f"\n📧 EMAIL SETUP")
    print("⚠️  Note: Gmail App Passwords are deprecated. Consider using a different provider.")
    
    email_address = input("Your email address: ").strip()
    if email_address:
        config["notifications"]["email"]["email_address"] = email_address
    
    recipient_email = input("Recipient email (can be same): ").strip()
    if recipient_email:
        config["notifications"]["email"]["recipient_email"] = recipient_email
    else:
        config["notifications"]["email"]["recipient_email"] = email_address
    
    return config