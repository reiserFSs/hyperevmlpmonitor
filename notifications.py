#!/usr/bin/env python3
"""
Notification Management Module for HyperEVM LP Monitor
Handles all notification methods: Telegram, Discord, Pushover, Email

COMPLETE UPDATED VERSION: Per-position cooldowns + state cleanup + fee information

Version: 1.4.1 (Complete with State Cleanup + Fee Information)
Developer: 8roku8.hl
"""

import requests
import smtplib
import time
import getpass
import json
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from constants import VERSION
from utils import (
    format_price, format_token_amount, format_price_percentage_safe,
    calculate_dynamic_thresholds, get_risk_level, calculate_price_based_percentages,
    is_full_range_position, format_fees_display, has_significant_fees
)

class NotificationManager:
    """Unified notification management with smart per-position cooldowns"""
    
    def __init__(self, config):
        self.config = config
        self.enabled = config.get("notifications", {}).get("enabled", False)
        self.notification_type = config.get("notifications", {}).get("type", "telegram")
        self.last_notification_time = 0
        self.email_password = None
        self.include_fees = config.get("notifications", {}).get("include_fees_in_notifications", True)
        self.include_il = config.get("notifications", {}).get("include_il_in_notifications", True)
        
        # Per-position state tracking for smart cooldowns
        self.position_states_file = "position_notification_states.json"
        self.position_states = self.load_position_states()
        
        # Smart cooldown rules (in seconds) - load from config or use defaults
        default_cooldowns = {
            "status_change": 0,          # Immediate notification for any status change
            "same_out_of_range": 30 * 60,  # 30 min for repeated out-of-range
            "same_danger": 60 * 60,      # 1 hour for repeated danger
            "same_warning": 2 * 60 * 60, # 2 hours for repeated warning  
            "same_safe": 6 * 60 * 60,    # 6 hours for repeated safe
        }
        
        # Use custom cooldowns from config if available
        config_cooldowns = config.get("notifications", {}).get("smart_cooldowns", {})
        self.cooldown_rules = {**default_cooldowns, **config_cooldowns}
        
        if self.enabled:
            self.setup_notifications()
    
    def load_position_states(self):
        """Load position states from file for persistence across restarts"""
        try:
            if os.path.exists(self.position_states_file):
                with open(self.position_states_file, 'r') as f:
                    return json.load(f)
        except Exception as e:
            print(f"⚠️  Could not load position states: {e}")
        return {}
    
    def save_position_states(self):
        """Save position states to file"""
        try:
            with open(self.position_states_file, 'w') as f:
                json.dump(self.position_states, f, indent=2)
        except Exception as e:
            print(f"⚠️  Could not save position states: {e}")

    def cleanup_position_states(self, current_positions, debug_mode=False):
        """Clean up position states for positions that no longer exist"""
        if not self.position_states:
            return
        
        # Generate keys for current active positions
        current_keys = set()
        for position in current_positions:
            position_key = self.get_position_key(position)
            current_keys.add(position_key)
        
        # Find orphaned keys (in states but not in current positions)
        stored_keys = set(self.position_states.keys())
        orphaned_keys = stored_keys - current_keys
        
        if orphaned_keys:
            if debug_mode:
                print(f"🔍 Cleaning up {len(orphaned_keys)} orphaned position states")
            
            # Remove orphaned entries
            for key in orphaned_keys:
                removed_state = self.position_states.pop(key, None)
                if debug_mode and removed_state:
                    print(f"🗑️  Removed state for: {removed_state.get('position_name', key)}")
            
            # Save the cleaned states
            self.save_position_states()
            print(f"🧹 Cleaned up notification states ({len(orphaned_keys)} removed)")

    def setup_notifications(self):
        """Setup notifications based on configured type"""
        try:
            if self.notification_type == "telegram":
                self.setup_telegram()
            elif self.notification_type == "discord":
                self.setup_discord()
            elif self.notification_type == "pushover":
                self.setup_pushover()
            elif self.notification_type == "email":
                self.setup_email()
            else:
                print(f"❌ Unknown notification type: {self.notification_type}")
                self.enabled = False
        except Exception as e:
            print(f"❌ Notification setup error: {e}")
            self.enabled = False

    def setup_telegram(self):
        """Setup Telegram bot notifications"""
        telegram_config = self.config["notifications"]["telegram"]
        
        if not telegram_config.get("bot_token") or not telegram_config.get("chat_id"):
            print("❌ Telegram bot token or chat ID not configured")
            self.enabled = False
            return
        
        print("🔍 Testing Telegram bot connection...")
        if self.test_telegram():
            print("✅ Telegram bot connected successfully!")
        else:
            print("❌ Telegram bot connection failed")
            self.enabled = False

    def setup_discord(self):
        """Setup Discord webhook notifications"""
        discord_config = self.config["notifications"]["discord"]
        
        if not discord_config.get("webhook_url"):
            print("❌ Discord webhook URL not configured")
            self.enabled = False
            return
        
        print("🔍 Testing Discord webhook...")
        if self.test_discord():
            print("✅ Discord webhook connected successfully!")
        else:
            print("❌ Discord webhook connection failed")
            self.enabled = False

    def setup_pushover(self):
        """Setup Pushover notifications"""
        pushover_config = self.config["notifications"]["pushover"]
        
        if not pushover_config.get("user_key") or not pushover_config.get("api_token"):
            print("❌ Pushover user key or API token not configured")
            self.enabled = False
            return
        
        print("🔍 Testing Pushover connection...")
        if self.test_pushover():
            print("✅ Pushover connected successfully!")
        else:
            print("❌ Pushover connection failed")
            self.enabled = False

    def setup_email(self):
        """Setup email credentials securely"""
        try:
            email_config = self.config["notifications"]["email"]
            if not email_config.get("email_address"):
                print("❌ Email address not configured")
                self.enabled = False
                return
            
            print("🔐 Email password required for notifications")
            print(f"Email: {email_config['email_address']}")
            print("⚠️  Note: Many providers have deprecated app passwords")
            
            # Securely prompt for password
            self.email_password = getpass.getpass("Enter email password: ")
            
            if not self.email_password:
                print("⚠️  No password provided, disabling notifications")
                self.enabled = False
                return
            
            # Test email connection
            print("🔍 Testing email connection...")
            if self.test_email_connection():
                print("✅ Email connection successful!")
            else:
                print("❌ Email connection failed, disabling notifications")
                self.enabled = False
                
        except KeyboardInterrupt:
            print("\n⚠️  Email setup cancelled, disabling notifications")
            self.enabled = False
        except Exception as e:
            print(f"❌ Email setup error: {e}")
            self.enabled = False

    def test_telegram(self):
        """Test Telegram bot connection"""
        try:
            telegram_config = self.config["notifications"]["telegram"]
            bot_token = telegram_config["bot_token"]
            chat_id = telegram_config["chat_id"]
            
            url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            data = {
                "chat_id": chat_id,
                "text": "🤖 HyperEVM LP Monitor connected successfully!",
                "parse_mode": "HTML"
            }
            
            response = requests.post(url, data=data, timeout=10)
            return response.status_code == 200
        except Exception as e:
            print(f"Telegram test failed: {e}")
            return False

    def test_discord(self):
        """Test Discord webhook"""
        try:
            discord_config = self.config["notifications"]["discord"]
            webhook_url = discord_config["webhook_url"]
            
            data = {
                "content": "🤖 HyperEVM LP Monitor connected successfully!"
            }
            
            response = requests.post(webhook_url, json=data, timeout=10)
            return response.status_code == 204
        except Exception as e:
            print(f"Discord test failed: {e}")
            return False

    def test_pushover(self):
        """Test Pushover connection"""
        try:
            pushover_config = self.config["notifications"]["pushover"]
            
            data = {
                "token": pushover_config["api_token"],
                "user": pushover_config["user_key"],
                "message": "HyperEVM LP Monitor connected successfully!"
            }
            
            response = requests.post("https://api.pushover.net/1/messages.json", data=data, timeout=10)
            return response.status_code == 200
        except Exception as e:
            print(f"Pushover test failed: {e}")
            return False

    def test_email_connection(self):
        """Test SMTP connection"""
        try:
            email_config = self.config["notifications"]["email"]
            
            server = smtplib.SMTP(email_config["smtp_server"], email_config["smtp_port"])
            server.starttls()
            server.login(email_config["email_address"], self.email_password)
            server.quit()
            return True
        except Exception as e:
            print(f"Email test failed: {e}")
            return False

    def should_send_notification(self):
        """Check if we should send notification based on cooldown"""
        if not self.enabled:
            return False
        
        cooldown = self.config.get("notifications", {}).get("notification_cooldown", 3600)
        current_time = time.time()
        
        if current_time - self.last_notification_time >= cooldown:
            return True
        
        return False

    def get_position_key(self, position):
        """Generate unique key for position tracking"""
        return f"{position['dex_name']}_{position['name']}_{position['token_id']}"

    def should_notify_position(self, position, current_status_type, debug_mode=False):
        """Check if we should notify about this specific position"""
        position_key = self.get_position_key(position)
        current_time = time.time()
        
        # Get stored state for this position
        stored_state = self.position_states.get(position_key, {})
        last_status = stored_state.get("last_status")
        last_notification_time = stored_state.get("last_notification_time", 0)
        
        # Always notify on status changes
        if last_status != current_status_type:
            if debug_mode:
                print(f"🔍 Position {position_key}: Status changed {last_status} → {current_status_type}")
            return True
        
        # For same status, check cooldown
        cooldown_key = f"same_{current_status_type}"
        cooldown_duration = self.cooldown_rules.get(cooldown_key, self.cooldown_rules["same_safe"])
        
        time_since_last = current_time - last_notification_time
        if time_since_last >= cooldown_duration:
            if debug_mode:
                print(f"🔍 Position {position_key}: Cooldown expired ({time_since_last:.0f}s >= {cooldown_duration}s)")
            return True
        
        if debug_mode:
            remaining_cooldown = cooldown_duration - time_since_last
            print(f"🔍 Position {position_key}: In cooldown ({remaining_cooldown:.0f}s remaining)")
        
        return False

    def update_position_state(self, position, status_type):
        """Update stored state for a position"""
        position_key = self.get_position_key(position)
        current_time = time.time()
        
        self.position_states[position_key] = {
            "last_status": status_type,
            "last_notification_time": current_time,
            "position_name": position["name"],
            "dex_name": position["dex_name"]
        }
        
        # Save to file for persistence
        self.save_position_states()

    def send_notification(self, message, title="LP Position Alert"):
        """Send notification via configured method"""
        if not self.enabled:
            return False
        
        try:
            if self.notification_type == "telegram":
                return self.send_telegram(message, title)
            elif self.notification_type == "discord":
                return self.send_discord(message, title)
            elif self.notification_type == "pushover":
                return self.send_pushover(message, title)
            elif self.notification_type == "email":
                return self.send_email_notification(title, message)
            return False
        except Exception as e:
            print(f"❌ Failed to send notification: {e}")
            return False

    def send_telegram(self, message, title):
        """Send Telegram message"""
        try:
            telegram_config = self.config["notifications"]["telegram"]
            bot_token = telegram_config["bot_token"]
            chat_id = telegram_config["chat_id"]
            
            # Format message with emojis and HTML
            formatted_message = f"<b>🚨 {title}</b>\n\n{message}"
            
            url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            data = {
                "chat_id": chat_id,
                "text": formatted_message,
                "parse_mode": "HTML"
            }
            
            response = requests.post(url, data=data, timeout=10)
            return response.status_code == 200
        except Exception as e:
            print(f"Telegram send failed: {e}")
            return False

    def send_discord(self, message, title):
        """Send Discord message"""
        try:
            discord_config = self.config["notifications"]["discord"]
            webhook_url = discord_config["webhook_url"]
            
            # Format as Discord embed
            embed = {
                "title": f"🚨 {title}",
                "description": message,
                "color": 0xff0000,  # Red color
                "timestamp": datetime.now().isoformat()
            }
            
            data = {
                "embeds": [embed]
            }
            
            response = requests.post(webhook_url, json=data, timeout=10)
            return response.status_code == 204
        except Exception as e:
            print(f"Discord send failed: {e}")
            return False

    def send_pushover(self, message, title):
        """Send Pushover notification"""
        try:
            pushover_config = self.config["notifications"]["pushover"]
            
            data = {
                "token": pushover_config["api_token"],
                "user": pushover_config["user_key"],
                "title": title,
                "message": message,
                "priority": 1  # High priority
            }
            
            response = requests.post("https://api.pushover.net/1/messages.json", data=data, timeout=10)
            return response.status_code == 200
        except Exception as e:
            print(f"Pushover send failed: {e}")
            return False

    def send_email_notification(self, subject, body):
        """Send email notification"""
        if not self.enabled or self.notification_type != "email":
            return False
        
        try:
            email_config = self.config["notifications"]["email"]
            
            # Create message
            msg = MIMEMultipart()
            msg['From'] = email_config["email_address"]
            msg['To'] = email_config["recipient_email"]
            msg['Subject'] = subject
            
            # Add body
            msg.attach(MIMEText(body, 'plain'))
            
            # Send email
            server = smtplib.SMTP(email_config["smtp_server"], email_config["smtp_port"])
            server.starttls()
            server.login(email_config["email_address"], self.email_password)
            
            text = msg.as_string()
            server.sendmail(email_config["email_address"], email_config["recipient_email"], text)
            server.quit()
            
            return True
            
        except Exception as e:
            print(f"❌ Failed to send email: {e}")
            return False

    def analyze_positions(self, position_statuses):
        """Analyze positions and determine what should be notified"""
        current_time = time.time()
        positions_to_notify = []
        
        safe_count = warning_count = danger_count = out_of_range_count = 0
        
        for position, status in position_statuses:
            if not status:
                continue
            
            # Calculate risk level
            range_size = position['tick_upper'] - position['tick_lower']
            closer_distance_pct = min(status["distance_to_lower"], status["distance_to_upper"]) / range_size * 100
            danger_threshold, warning_threshold = calculate_dynamic_thresholds(position, self.config)
            
            # Determine status type
            if not status["in_range"]:
                status_type = "out_of_range"
                status_emoji = "❌"
                out_of_range_count += 1
            elif closer_distance_pct < danger_threshold:
                status_type = "danger"
                status_emoji = "🚨"
                danger_count += 1
            elif closer_distance_pct < warning_threshold:
                status_type = "warning"
                status_emoji = "⚠️"
                warning_count += 1
            else:
                status_type = "safe"
                status_emoji = "✅"
                safe_count += 1
            
            # Check if we should notify about this position
            if self.should_notify_position(position, status_type):
                positions_to_notify.append({
                    "position": position,
                    "status": status,
                    "status_type": status_type,
                    "emoji": status_emoji,
                    "is_issue": status_type in ["out_of_range", "danger", "warning"]
                })
                
                # Update position state
                self.update_position_state(position, status_type)
        
        return positions_to_notify, safe_count, warning_count, danger_count, out_of_range_count

    def format_position_details(self, pos_data):
        """Shared formatting logic for position details with fee information"""
        position = pos_data["position"]
        status = pos_data["status"]
        
        # Calculate price movements
        price_lower_pct, price_upper_pct = calculate_price_based_percentages(
            status["current_price"], status["lower_price"], status["upper_price"]
        )
        
        # Check if full range
        is_full_range = is_full_range_position(position['tick_lower'], position['tick_upper'])
        
        # Format position amount
        position_amount = f"{format_token_amount(status['amount0'], status['token0_symbol'])} + {format_token_amount(status['amount1'], status['token1_symbol'])}"
        
        details = {
            "header": f"{pos_data['emoji']} {position['name']} on {position['dex_name']}",
            "position_amount": position_amount,
            "price": format_price(status["current_price"]),
            "is_full_range": is_full_range
        }
        
        # Add fee information if enabled and available
        if self.include_fees and status.get("has_unclaimed_fees") is not None:
            fee_amount0 = status.get("fee_amount0", 0)
            fee_amount1 = status.get("fee_amount1", 0)
            token0_symbol = status.get("token0_symbol", "TOKEN0")
            token1_symbol = status.get("token1_symbol", "TOKEN1")
            
            if has_significant_fees(fee_amount0, fee_amount1, 0.000001):
                details["fees"] = format_fees_display(fee_amount0, fee_amount1, token0_symbol, token1_symbol)
            else:
                details["fees"] = "No significant fees"
        
        # Add IL information if enabled and available
        if self.include_il and "il_data" in status:
            il_data = status["il_data"]
            rebalance_rec = status.get("rebalance_recommendation", {})
            
            if not il_data.get("is_full_range", False):
                il_pct = il_data.get("il_percentage", 0)
                efficiency = rebalance_rec.get("efficiency_score", 0)
                urgency = rebalance_rec.get("urgency", "none")
                
                details["il_analysis"] = f"{il_pct:.1f}% vs HODL"
                details["efficiency"] = f"{efficiency:.0f}/100"
                
                if rebalance_rec.get("should_rebalance", False):
                    details["rebalance_needed"] = f"{urgency.upper()} priority"
                else:
                    details["rebalance_needed"] = "Not needed"
        
        if is_full_range:
            details["range_info"] = "Full Range (No limits)"
            details["buffer_info"] = "Always earning fees"
        else:
            details["range_info"] = f"{format_price(status['lower_price'])} - {format_price(status['upper_price'])}"
            
            if status["in_range"]:
                if price_lower_pct != float('inf') and price_upper_pct != float('inf'):
                    lower_buffer = format_price_percentage_safe(abs(price_lower_pct))
                    upper_buffer = format_price_percentage_safe(price_upper_pct)
                    details["buffer_info"] = f"{lower_buffer} to lower / {upper_buffer} to upper"
                else:
                    details["buffer_info"] = None
            else:
                # Out of range
                if status["current_price"] < status["lower_price"]:
                    price_move_needed = (status["lower_price"] - status["current_price"]) / status["current_price"] * 100
                    details["buffer_info"] = f"BELOW range - needs +{price_move_needed:.1f}% to re-enter"
                else:
                    price_move_needed = (status["current_price"] - status["upper_price"]) / status["upper_price"] * 100
                    details["buffer_info"] = f"ABOVE range - needs -{price_move_needed:.1f}% to re-enter"
        
        return details

    def send_status_notification(self, position_statuses, wallet_address, debug_mode=False):
        """Send notification with smart per-position cooldowns and truncation"""
        if not self.should_send_notification():
            return
        
        if debug_mode:
            print("🔍 ANALYZING POSITIONS for smart notifications...")
        
        # Analyze which positions need notification
        positions_to_notify, safe_count, warning_count, danger_count, out_of_range_count = self.analyze_positions(position_statuses)
        
        if not positions_to_notify:
            if debug_mode:
                print("🔍 No positions need notification (all in cooldown)")
            return
        
        # Check if we should send based on issues-only setting
        notify_on_issues_only = self.config.get("notifications", {}).get("notify_on_issues_only", True)
        has_issues = any(pos["is_issue"] for pos in positions_to_notify)
        
        if notify_on_issues_only and not has_issues:
            if debug_mode:
                print("🔍 No issues found and notify_on_issues_only is enabled, skipping notification")
            return
        
        # Debug cooldown status
        if debug_mode:
            print(f"🔍 Total positions: {len(position_statuses)}")
            print(f"🔍 Positions to notify: {len(positions_to_notify)}")
            for position, status in position_statuses:
                if status:
                    position_key = self.get_position_key(position)
                    stored_state = self.position_states.get(position_key, {})
                    print(f"🔍 {position['name']}: last_status={stored_state.get('last_status', 'none')}, cooldown_check=...")
        
        # Smart truncation for many positions
        total_positions = len(position_statuses)
        issue_positions = [pos for pos in positions_to_notify if pos["is_issue"]]
        safe_positions = [pos for pos in positions_to_notify if not pos["is_issue"]]
        
        # Create notification title
        if has_issues:
            title = f"LP Position Alert ({len(issue_positions)} need attention)"
        else:
            title = f"LP Portfolio Status ({len(positions_to_notify)} updates)"
        
        # Create notification message
        if self.notification_type == "telegram":
            message = self.format_telegram_message(
                positions_to_notify, issue_positions, safe_positions,
                total_positions, safe_count, warning_count, danger_count, out_of_range_count,
                wallet_address
            )
        else:
            message = self.format_standard_message(
                positions_to_notify, issue_positions, safe_positions,
                total_positions, safe_count, warning_count, danger_count, out_of_range_count,
                wallet_address
            )
        
        if self.send_notification(message, title):
            self.last_notification_time = time.time()
            notification_icon = "📧" if self.notification_type == "email" else "🔔"
            print(f"✅ {notification_icon} Smart notification sent ({len(positions_to_notify)} positions, {self.notification_type})")
        else:
            print(f"❌ Failed to send {self.notification_type} notification")

    def format_telegram_message(self, positions_to_notify, issue_positions, safe_positions, 
                              total_positions, safe_count, warning_count, danger_count, out_of_range_count, wallet_address):
        """Format Telegram message with smart truncation and fee information"""
        message_parts = []
        
        # Summary
        message_parts.append(f"<b>📊 Portfolio Summary ({total_positions} total positions)</b>")
        message_parts.append("")
        
        if out_of_range_count > 0:
            message_parts.append(f"❌ <b>{out_of_range_count}</b> OUT OF RANGE")
        if danger_count > 0:
            message_parts.append(f"🚨 <b>{danger_count}</b> DANGER ZONE")
        if warning_count > 0:
            message_parts.append(f"⚠️ <b>{warning_count}</b> WARNING ZONE")
        if safe_count > 0:
            message_parts.append(f"✅ <b>{safe_count}</b> SAFE")
        
        # Show cooldown info if some positions are not displayed
        total_notifiable = len(positions_to_notify)
        if total_notifiable < total_positions:
            cooldown_count = total_positions - total_notifiable
            message_parts.append(f"⏰ <i>{cooldown_count} position(s) in notification cooldown</i>")
        
        message_parts.append("")
        
        # Smart truncation: Show up to 6 issue positions in detail
        if issue_positions:
            message_parts.append(f"<b>🚨 Positions Needing Attention (Updated):</b>")
            
            positions_to_show = issue_positions[:6]  # Smart limit
            for pos_data in positions_to_show:
                details = self.format_position_details(pos_data)
                message_parts.append(f"<b>{details['header']}</b>")
                message_parts.append(f"    💼 Position: {details['position_amount']}")
                message_parts.append(f"    💰 Price: {details['price']}")
                message_parts.append(f"    📊 Range: {details['range_info']}")
                if details["buffer_info"]:
                    message_parts.append(f"    🎯 Buffer: {details['buffer_info']}")
                # Add fee information if available
                if self.include_fees and "fees" in details:
                    message_parts.append(f"    💸 Fees: {details['fees']}")
                # Add IL information if available
                if self.include_il and "il_analysis" in details:
                    message_parts.append(f"    📊 IL: {details['il_analysis']}")
                    message_parts.append(f"    🎯 Efficiency: {details['efficiency']}")
                    message_parts.append(f"    🔄 Rebalance: {details['rebalance_needed']}")
                message_parts.append("")
            
            # Show summary for remaining positions
            if len(issue_positions) > 6:
                remaining = len(issue_positions) - 6
                message_parts.append(f"<i>... and {remaining} more positions needing attention</i>")
                message_parts.append("")
        
        # Safe positions - show up to 3 in detail, then summarize
        if safe_positions:
            if len(safe_positions) <= 3:
                message_parts.append(f"<b>✅ Safe Positions (Updated):</b>")
                for pos_data in safe_positions:
                    details = self.format_position_details(pos_data)
                    message_parts.append(f"<b>{details['header']}</b>")
                    message_parts.append(f"    💼 Position: {details['position_amount']}")
                    message_parts.append(f"    💰 Price: {details['price']}")
                    message_parts.append(f"    📊 Range: {details['range_info']}")
                    if details["buffer_info"]:
                        message_parts.append(f"    🎯 Buffer: {details['buffer_info']}")
                    # Add fee information if available
                    if self.include_fees and "fees" in details:
                        message_parts.append(f"    💸 Fees: {details['fees']}")
                    # Add IL information if available
                    if self.include_il and "il_analysis" in details:
                        message_parts.append(f"    📊 IL: {details['il_analysis']}")
                        message_parts.append(f"    🎯 Efficiency: {details['efficiency']}")
                    message_parts.append("")
            else:
                message_parts.append(f"<b>✅ {len(safe_positions)} safe positions updated</b>")
                message_parts.append("")
        
        # Footer
        message_parts.append(f"<b>Wallet:</b> <code>{wallet_address}</code>")
        message_parts.append(f"<i>HyperEVM LP Monitor v{VERSION}</i>")
        message_parts.append(f"<i>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</i>")
        
        return "\n".join(message_parts)

    def format_standard_message(self, positions_to_notify, issue_positions, safe_positions,
                              total_positions, safe_count, warning_count, danger_count, out_of_range_count, wallet_address):
        """Format standard message for Discord/Pushover/Email with smart truncation and fee information"""
        message_parts = []
        
        # Summary
        message_parts.append(f"📊 Portfolio Summary ({total_positions} total positions)")
        message_parts.append("")
        
        if out_of_range_count > 0:
            message_parts.append(f"❌ {out_of_range_count} OUT OF RANGE")
        if danger_count > 0:
            message_parts.append(f"🚨 {danger_count} DANGER ZONE")
        if warning_count > 0:
            message_parts.append(f"⚠️ {warning_count} WARNING ZONE")
        if safe_count > 0:
            message_parts.append(f"✅ {safe_count} SAFE")
        
        # Show cooldown info if some positions are not displayed
        total_notifiable = len(positions_to_notify)
        if total_notifiable < total_positions:
            cooldown_count = total_positions - total_notifiable
            message_parts.append(f"⏰ {cooldown_count} position(s) in notification cooldown")
        
        message_parts.append("")
        
        # Smart truncation: Show up to 6 issue positions in detail
        if issue_positions:
            message_parts.append("🚨 Positions Needing Attention (Updated):")
            
            positions_to_show = issue_positions[:6]  # Smart limit
            for pos_data in positions_to_show:
                details = self.format_position_details(pos_data)
                message_parts.append(details['header'])
                message_parts.append(f"    Position: {details['position_amount']}")
                message_parts.append(f"    Price: {details['price']}")
                message_parts.append(f"    Range: {details['range_info']}")
                if details["buffer_info"]:
                    message_parts.append(f"    Buffer: {details['buffer_info']}")
                # Add fee information if available
                if self.include_fees and "fees" in details:
                    message_parts.append(f"    Fees: {details['fees']}")
                # Add IL information if available
                if self.include_il and "il_analysis" in details:
                    message_parts.append(f"    IL: {details['il_analysis']}")
                    message_parts.append(f"    Efficiency: {details['efficiency']}")
                    message_parts.append(f"    Rebalance: {details['rebalance_needed']}")
                message_parts.append("")
            
            # Show summary for remaining positions
            if len(issue_positions) > 6:
                remaining = len(issue_positions) - 6
                message_parts.append(f"... and {remaining} more positions needing attention")
                message_parts.append("")
        
        # Safe positions - show up to 3 in detail, then summarize
        if safe_positions:
            if len(safe_positions) <= 3:
                message_parts.append("✅ Safe Positions (Updated):")
                for pos_data in safe_positions:
                    details = self.format_position_details(pos_data)
                    message_parts.append(details['header'])
                    message_parts.append(f"    Position: {details['position_amount']}")
                    message_parts.append(f"    Price: {details['price']}")
                    message_parts.append(f"    Range: {details['range_info']}")
                    if details["buffer_info"]:
                        message_parts.append(f"    Buffer: {details['buffer_info']}")
                    # Add fee information if available
                    if self.include_fees and "fees" in details:
                        message_parts.append(f"    Fees: {details['fees']}")
                    # Add IL information if available
                    if self.include_il and "il_analysis" in details:
                        message_parts.append(f"    IL: {details['il_analysis']}")
                        message_parts.append(f"    Efficiency: {details['efficiency']}")
                    message_parts.append("")
            else:
                message_parts.append(f"✅ {len(safe_positions)} safe positions updated")
                message_parts.append("")
        
        # Footer
        message_parts.append(f"Wallet: {wallet_address}")
        message_parts.append(f"HyperEVM LP Monitor v{VERSION}")
        message_parts.append(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        return "\n".join(message_parts)

    def send_portfolio_update_notification(self, added_count, removed_count, total_positions, wallet_address, current_positions=None):
        """Send notification about portfolio changes and cleanup states"""
        # Clean up position states if positions were removed and we have current positions
        if removed_count > 0 and current_positions is not None:
            self.cleanup_position_states(current_positions, debug_mode=True)
        
        if added_count == 0 and removed_count == 0:
            return
        
        title = "LP Portfolio Update"
        
        changes = []
        if added_count > 0:
            changes.append(f"➕ {added_count} new position(s) added")
        if removed_count > 0:
            changes.append(f"➖ {removed_count} position(s) removed (no liquidity)")
        
        message_parts = [
            f"Portfolio changes detected:",
            "",
            *changes,
            "",
            f"Total active positions: {total_positions}",
            f"Wallet: {wallet_address}",
            "",
            f"HyperEVM LP Monitor v{VERSION}",
            f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        ]
        
        message = "\n".join(message_parts)
        
        if self.send_notification(message, title):
            print("🔔 Portfolio update notification sent")