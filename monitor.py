#!/usr/bin/env python3
"""
CUNI Rehos Dormitory Monitor
Monitors Charles University (Univerzita Karlova) accommodation capacity
and sends alerts / handles commands via Telegram.
"""

import os
import sys
import time
import json
import re
import html
import logging
import argparse
import signal
import threading
import collections
from datetime import datetime
import requests

# Paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
DEFAULT_STATE_PATH = os.path.join(BASE_DIR, "state.json")

# In-memory ring buffer for live log inspection via /logs
class RingBufferLogHandler(logging.Handler):
    def __init__(self, capacity=50):
        super().__init__()
        self.buffer = collections.deque(maxlen=capacity)

    def emit(self, record):
        try:
            msg = self.format(record)
            self.buffer.append(msg)
        except Exception:
            pass

    def get_last(self, n=15):
        return list(self.buffer)[-n:]

log_buffer = RingBufferLogHandler(capacity=60)
log_formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
log_buffer.setFormatter(log_formatter)

logger = logging.getLogger("cuni-dorm-monitor")
logger.setLevel(logging.INFO)
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
logger.addHandler(console_handler)
logger.addHandler(log_buffer)

# Global runtime state
RUNNING = True
MONITORING_PAUSED = False
START_TIME = time.time()
LAST_CHECK_TIME = None
LAST_CHECK_DATA = []
TRIGGER_CHECK_EVENT = threading.Event()


def handle_signal(sig, frame):
    global RUNNING
    sig_name = signal.Signals(sig).name
    logger.info(f"Received signal {sig_name}. Shutting down gracefully...")
    RUNNING = False
    TRIGGER_CHECK_EVENT.set()

signal.signal(signal.SIGINT, handle_signal)
signal.signal(signal.SIGTERM, handle_signal)


def load_config(config_path=DEFAULT_CONFIG_PATH):
    """Load configuration from JSON file."""
    if not os.path.exists(config_path):
        logger.error(f"Configuration file not found: {config_path}")
        sys.exit(1)
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to read configuration: {e}")
        sys.exit(1)


def save_config(config, config_path=DEFAULT_CONFIG_PATH):
    """Save configuration to JSON file."""
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
        f.write("\n")


def load_state(state_path=DEFAULT_STATE_PATH):
    """Load monitor state from file."""
    if os.path.exists(state_path):
        try:
            with open(state_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Could not load state file: {e}")
    return {}


def save_state(state, state_path=DEFAULT_STATE_PATH):
    """Save monitor state to file."""
    try:
        with open(state_path, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
            f.write("\n")
    except Exception as e:
        logger.warning(f"Could not save state file: {e}")


def send_telegram_message(token, chat_id, text, parse_mode="HTML"):
    """Send a message via Telegram Bot API."""
    if not token or not chat_id:
        return False, "Missing credentials"
    
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": False
    }
    try:
        resp = requests.post(url, json=payload, timeout=10)
        data = resp.json()
        if resp.status_code == 200 and data.get("ok"):
            return True, None
        else:
            error_desc = data.get("description", resp.text)
            logger.error(f"Telegram API error: {error_desc}")
            return False, error_desc
    except Exception as e:
        logger.error(f"Network error sending Telegram message: {e}")
        return False, str(e)


def register_telegram_commands(token):
    """Register menu commands in Telegram UI."""
    if not token:
        return
    url = f"https://api.telegram.org/bot{token}/setMyCommands"
    commands = [
        {"command": "check", "description": "Immediate check across all dormitories"},
        {"command": "status", "description": "Monitor status and active categories"},
        {"command": "men", "description": "Enable / disable monitoring for men"},
        {"command": "women", "description": "Enable / disable monitoring for women"},
        {"command": "logs", "description": "Recent log entries"},
        {"command": "stop", "description": "Pause monitoring"},
        {"command": "start", "description": "Resume monitoring"},
        {"command": "restart", "description": "Restart service"},
        {"command": "help", "description": "Display help message"}
    ]
    try:
        requests.post(url, json={"commands": commands}, timeout=5)
    except Exception as e:
        logger.warning(f"Could not register Telegram commands: {e}")


def parse_college_page(session, url, fallback_name="Kolej", monitor_men=True, monitor_women=False, monitor_unspecified=True):
    """
    Fetch and parse a college detail page.
    Returns:
        (title, all_rooms, available_rooms)
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "cs,en-US;q=0.9,en;q=0.8"
    }
    
    resp = session.get(url, headers=headers, timeout=15)
    resp.raise_for_status()
    page_html = resp.text

    title_m = re.search(r"<h1>(.*?)</h1>", page_html, re.DOTALL)
    title = title_m.group(1).strip() if title_m else fallback_name

    tables = re.findall(r"<table[^>]*>(.*?)</table>", page_html, re.DOTALL)
    capacity_table = None
    for t in tables:
        if "Muži" in t or "Muzi" in t:
            capacity_table = t
            break
            
    if not capacity_table:
        return title, [], []

    thead_m = re.search(r"<thead>(.*?)</thead>", capacity_table, re.DOTALL)
    col_map = {"desc": 0, "price": 1, "men": 2, "women": 3, "unspecified": 4}
    if thead_m:
        raw_headers = [re.sub(r"<[^>]+>", "", h).strip() for h in re.findall(r"<th[^>]*>(.*?)(?=</?th|$)", thead_m.group(1), re.DOTALL)]
        valid_headers = [h for h in raw_headers if h]
        for idx, h in enumerate(valid_headers):
            h_lower = h.lower()
            if "popis" in h_lower:
                col_map["desc"] = idx
            elif "kč" in h_lower or "cena" in h_lower:
                col_map["price"] = idx
            elif "muž" in h_lower or "muz" in h_lower:
                col_map["men"] = idx
            elif "žen" in h_lower or "zen" in h_lower:
                col_map["women"] = idx
            elif "neurč" in h_lower or "neurc" in h_lower:
                col_map["unspecified"] = idx

    tbody_m = re.search(r"<tbody>(.*?)</tbody>", capacity_table, re.DOTALL)
    tbody = tbody_m.group(1) if tbody_m else capacity_table

    all_rooms = []
    available_rooms = []

    for tr in re.findall(r"<tr>(.*?)</tr>", tbody, re.DOTALL):
        cells = [re.sub(r"<[^>]+>", "", c).strip() for c in re.findall(r"<td[^>]*>(.*?)(?=</?td|$)", tr, re.DOTALL)]
        meaningful = [c for c in cells if c != ""]
        
        if len(meaningful) >= 5:
            desc_idx = col_map.get("desc", 0)
            price_idx = col_map.get("price", 1)
            men_idx = col_map.get("men", 2)
            women_idx = col_map.get("women", 3)
            unspec_idx = col_map.get("unspecified", 4)

            desc = meaningful[desc_idx] if desc_idx < len(meaningful) else "Neznámý pokoj"
            price = meaningful[price_idx] if price_idx < len(meaningful) else "0"
            
            try:
                raw_men = meaningful[men_idx] if men_idx < len(meaningful) else "0"
                men = int(re.sub(r"[^\d]", "", raw_men) or "0")
            except ValueError:
                men = 0

            try:
                raw_women = meaningful[women_idx] if women_idx < len(meaningful) else "0"
                women = int(re.sub(r"[^\d]", "", raw_women) or "0")
            except ValueError:
                women = 0

            try:
                raw_unspec = meaningful[unspec_idx] if unspec_idx < len(meaningful) else "0"
                unspecified = int(re.sub(r"[^\d]", "", raw_unspec) or "0")
            except ValueError:
                unspecified = 0

            room_data = {
                "room": desc,
                "price": price,
                "men": men,
                "women": women,
                "unspecified": unspecified,
                "url": url,
                "college": title
            }
            all_rooms.append(room_data)

            is_avail = (
                (monitor_men and men > 0) or
                (monitor_unspecified and unspecified > 0) or
                (monitor_women and women > 0)
            )
            if is_avail:
                available_rooms.append(room_data)

    return title, all_rooms, available_rooms


def format_alert_message(room_data, is_reminder=False):
    """Format Telegram HTML message for an available room."""
    header = "<b>DORM CAPACITY STILL AVAILABLE! (Reminder)</b>" if is_reminder else "<b>DORM CAPACITY AVAILABLE!</b>"
    
    return (
        f"{header}\n\n"
        f"Dormitory: <b>{room_data['college']}</b>\n"
        f"Room: <b>{room_data['room']}</b>\n\n"
        f"• <b>Men:</b> {room_data['men']}\n"
        f"• <b>Unspecified:</b> {room_data['unspecified']}\n"
        f"• <b>Women:</b> {room_data['women']}\n"
        f"• <b>Price:</b> {room_data['price']} CZK/night\n\n"
        f"<a href=\"{room_data['url']}\"><b>Open reservation on CUNI portal</b></a>\n"
        f"<i>Detected at {datetime.now().strftime('%H:%M:%S')}</i>"
    )


def run_monitor_cycle(config, session, state, state_path=DEFAULT_STATE_PATH):
    """Run one monitoring check across all configured colleges."""
    global LAST_CHECK_TIME, LAST_CHECK_DATA
    colleges = config.get("colleges", [])
    token = config.get("telegram_bot_token", "").strip()
    chat_id = config.get("telegram_chat_id", "")
    reminder_minutes = config.get("reminder_interval_minutes", 60)
    monitor_men = config.get("monitor_men", True)
    monitor_women = config.get("monitor_women", False)
    monitor_unspecified = config.get("monitor_unspecified", True)
    
    current_active_keys = set()
    newly_found_count = 0
    cycle_data = []

    for item in colleges:
        url = item.get("url")
        fallback_name = item.get("name", "Kolej")
        if not url:
            continue
            
        try:
            title, all_rooms, available_rooms = parse_college_page(
                session, url, fallback_name,
                monitor_men=monitor_men,
                monitor_women=monitor_women,
                monitor_unspecified=monitor_unspecified
            )
            cycle_data.append({
                "title": title,
                "url": url,
                "all_rooms": all_rooms,
                "available": available_rooms
            })
            
            for rm in available_rooms:
                room_key = f"{title}::{rm['room']}"
                current_active_keys.add(room_key)
                
                existing_entry = state.get(room_key)
                now_ts = time.time()
                
                should_notify = False
                is_reminder = False
                
                if not existing_entry:
                    should_notify = True
                    is_reminder = False
                elif (existing_entry.get("men") != rm["men"] or 
                      existing_entry.get("unspecified") != rm["unspecified"] or
                      existing_entry.get("women") != rm["women"]):
                    should_notify = True
                    is_reminder = False
                elif reminder_minutes > 0 and (now_ts - existing_entry.get("last_notified", 0)) >= (reminder_minutes * 60):
                    should_notify = True
                    is_reminder = True
                
                if should_notify:
                    newly_found_count += 1
                    logger.info(f"FOUND CAPACITY: {title} - {rm['room']} (Men: {rm['men']}, Unspec: {rm['unspecified']}, Women: {rm['women']})")
                    msg = format_alert_message(rm, is_reminder=is_reminder)
                    success, err = send_telegram_message(token, chat_id, msg)
                    if success:
                        state[room_key] = {
                            "college": title,
                            "room": rm["room"],
                            "men": rm["men"],
                            "unspecified": rm["unspecified"],
                            "women": rm["women"],
                            "price": rm["price"],
                            "last_notified": now_ts
                        }
                    else:
                        logger.warning(f"Failed to deliver Telegram alert: {err}")
                else:
                    existing_entry["men"] = rm["men"]
                    existing_entry["unspecified"] = rm["unspecified"]
                    existing_entry["women"] = rm["women"]
                    
        except requests.RequestException as e:
            logger.warning(f"Error fetching {fallback_name} ({url}): {e}")
        except Exception as e:
            logger.error(f"Unexpected error processing {fallback_name}: {e}", exc_info=True)

        # Gentle pause between colleges to mimic human pacing and prevent burst traffic
        time.sleep(1.0)

    LAST_CHECK_TIME = time.time()
    LAST_CHECK_DATA = cycle_data

    # Clean up state for rooms that are no longer available
    removed_keys = []
    for k in list(state.keys()):
        if k not in current_active_keys:
            logger.info(f"Capacity no longer available: {k}")
            removed_keys.append(k)
            del state[k]

    if newly_found_count > 0 or removed_keys:
        save_state(state, state_path)


def handle_telegram_command(cmd_text, token, chat_id, config, session, state):
    """Process incoming command from authorized Telegram user."""
    global MONITORING_PAUSED, TRIGGER_CHECK_EVENT
    cmd = cmd_text.strip().split()[0].lower()
    # Strip @botname if sent in group or full format
    if "@" in cmd:
        cmd = cmd.split("@")[0]

    logger.info(f"Processing Telegram command: {cmd}")

    if cmd in ("/start", "/resume"):
        if MONITORING_PAUSED:
            MONITORING_PAUSED = False
            send_telegram_message(
                token, chat_id,
                "<b>Monitoring resumed!</b>\n\n"
                f"The service is actively checking dormitories every {config.get('check_interval_seconds', 60)}s."
            )
            TRIGGER_CHECK_EVENT.set()
        else:
            send_telegram_message(
                token, chat_id,
                "<b>CUNI Dorm Monitor is active.</b>\n\n"
                "Send /status to check status or /check for an immediate scan.\n"
                "Send /help to view all available commands."
            )

    elif cmd in ("/stop", "/pause"):
        MONITORING_PAUSED = True
        logger.info("Monitoring paused via Telegram /stop")
        send_telegram_message(
            token, chat_id,
            "<b>Monitoring paused.</b>\n\n"
            "Automated checks are stopped. Send /start or /resume to restart."
        )

    elif cmd == "/status":
        uptime_sec = int(time.time() - START_TIME)
        hours, rem = divmod(uptime_sec, 3600)
        minutes, seconds = divmod(rem, 60)
        uptime_str = f"{hours}h {minutes}m {seconds}s"
        
        last_check_str = "Not performed yet"
        if LAST_CHECK_TIME:
            elapsed = int(time.time() - LAST_CHECK_TIME)
            last_check_str = f"{elapsed}s ago ({datetime.fromtimestamp(LAST_CHECK_TIME).strftime('%H:%M:%S')})"

        status_icon = "Paused" if MONITORING_PAUSED else "Active (running)"
        colleges_count = len(config.get("colleges", []))
        avail_count = len(state)

        monitored_list = []
        if config.get("monitor_men", True):
            monitored_list.append("Men")
        if config.get("monitor_unspecified", True):
            monitored_list.append("Unspecified")
        if config.get("monitor_women", False):
            monitored_list.append("Women")
        monitored_str = ", ".join(monitored_list) if monitored_list else "None"

        text = (
            "<b>CUNI Dorm Monitor Status</b>\n\n"
            f"• <b>Status:</b> {status_icon}\n"
            f"• <b>Uptime:</b> {uptime_str}\n"
            f"• <b>Last check:</b> {last_check_str}\n"
            f"• <b>Interval:</b> {config.get('check_interval_seconds', 60)}s\n"
            f"• <b>Monitored categories:</b> {monitored_str}\n"
            f"• <b>Monitored dormitories:</b> {colleges_count}\n"
            f"• <b>Currently available room types:</b> {avail_count}\n"
        )
        send_telegram_message(token, chat_id, text)

    elif cmd == "/men":
        parts = cmd_text.strip().split()
        if len(parts) > 1:
            subcmd = parts[1].lower()
            if subcmd in ("on", "1", "true", "yes", "ano"):
                config["monitor_men"] = True
                save_config(config)
                send_telegram_message(token, chat_id, "Monitoring category Men: <b>ENABLED</b>.")
                TRIGGER_CHECK_EVENT.set()
            elif subcmd in ("off", "0", "false", "no", "ne"):
                config["monitor_men"] = False
                save_config(config)
                send_telegram_message(token, chat_id, "Monitoring category Men: <b>DISABLED</b>.")
            else:
                send_telegram_message(token, chat_id, "Usage: /men on or /men off")
        else:
            status_curr = "ENABLED" if config.get("monitor_men", True) else "DISABLED"
            send_telegram_message(
                token, chat_id,
                f"Monitoring category Men is currently: <b>{status_curr}</b>.\n"
                "To toggle, use: /men on or /men off"
            )

    elif cmd == "/women":
        parts = cmd_text.strip().split()
        if len(parts) > 1:
            subcmd = parts[1].lower()
            if subcmd in ("on", "1", "true", "ano", "yes"):
                config["monitor_women"] = True
                save_config(config)
                send_telegram_message(token, chat_id, "Monitoring category Women: <b>ENABLED</b>.")
                TRIGGER_CHECK_EVENT.set()
            elif subcmd in ("off", "0", "false", "ne", "no"):
                config["monitor_women"] = False
                save_config(config)
                send_telegram_message(token, chat_id, "Monitoring category Women: <b>DISABLED</b>.")
            else:
                send_telegram_message(token, chat_id, "Usage: /women on or /women off")
        else:
            status_curr = "ENABLED" if config.get("monitor_women", False) else "DISABLED"
            send_telegram_message(
                token, chat_id,
                f"Monitoring category Women is currently: <b>{status_curr}</b>.\n"
                "To toggle, use: /women on or /women off"
            )

    elif cmd == "/check":
        send_telegram_message(token, chat_id, "<i>Performing immediate check across all dormitories...</i>")
        run_monitor_cycle(config, session, state)
        
        # Build nice summary
        lines = ["<b>Current check results:</b>\n\n"]
        total_avail = 0
        
        for c in LAST_CHECK_DATA:
            avail_rooms = c.get("available", [])
            title = c.get("title", "Dormitory")
            url = c.get("url", "")
            
            if avail_rooms:
                total_avail += len(avail_rooms)
                for rm in avail_rooms:
                    lines.append(
                        f"[AVAILABLE] <b><a href=\"{url}\">{title}</a></b>: {rm['room']}\n"
                        f"   Men: {rm['men']} | Unspecified: {rm['unspecified']} | Women: {rm['women']} ({rm['price']} CZK)\n"
                    )
            else:
                lines.append(f"[Occupied] <b>{title}</b>\n")
                
        if total_avail == 0:
            lines.append("\n<i>All dormitories currently have 0 available spots.</i>")
        else:
            lines.append(f"\n<b>Total available offers found: {total_avail}!</b>")
            
        send_telegram_message(token, chat_id, "".join(lines))

    elif cmd == "/logs":
        lines = log_buffer.get_last(15)
        if not lines:
            raw_text = "No log entries recorded yet."
        else:
            raw_text = "\n".join(lines)
            
        safe_logs = html.escape(raw_text)
        if len(safe_logs) > 3800:
            safe_logs = safe_logs[-3800:]
            
        msg = f"<b>Recent log entries:</b>\n\n<pre>{safe_logs}</pre>"
        send_telegram_message(token, chat_id, msg)

    elif cmd == "/restart":
        send_telegram_message(token, chat_id, "<b>Restarting service on server...</b>")
        logger.info("Restart requested via Telegram /restart")
        def _restart_worker():
            time.sleep(1.5)
            os.system("systemctl --user restart cuni-dorm-monitor.service")
        threading.Thread(target=_restart_worker, daemon=True).start()

    elif cmd == "/help":
        help_text = (
            "<b>Available commands:</b>\n\n"
            "• /check - Immediate check across all dormitories\n"
            "• /status - Service status, uptime, and active categories\n"
            "• /men [on|off] - Enable / disable monitoring for men\n"
            "• /women [on|off] - Enable / disable monitoring for women\n"
            "• /logs - Last 15 lines from runtime log\n"
            "• /stop - Pause automated monitoring\n"
            "• /start - Resume monitoring\n"
            "• /restart - Restart service on ThinkPad\n"
            "• /help - Display this help message"
        )
        send_telegram_message(token, chat_id, help_text)

    else:
        send_telegram_message(
            token, chat_id,
            "Unknown command. Send /help to see available options."
        )


def telegram_listener_thread(config, session, state):
    """Long-polling thread for Telegram commands."""
    token = config.get("telegram_bot_token", "").strip()
    authorized_chat_id = str(config.get("telegram_chat_id", "")).strip()

    if not token or not authorized_chat_id:
        logger.warning("Telegram listener thread not started: missing token or chat_id.")
        return

    logger.info("Telegram command listener started.")
    last_update_id = 0

    while RUNNING:
        try:
            url = f"https://api.telegram.org/bot{token}/getUpdates"
            params = {"offset": last_update_id + 1, "timeout": 5}
            resp = requests.get(url, params=params, timeout=10)
            
            if resp.status_code == 200:
                data = resp.json()
                if data.get("ok"):
                    for update in data.get("result", []):
                        last_update_id = update["update_id"]
                        msg = update.get("message") or update.get("edited_message")
                        if not msg:
                            continue
                            
                        sender_id = str(msg.get("from", {}).get("id") or msg.get("chat", {}).get("id") or "")
                        # Security verification
                        if sender_id != authorized_chat_id:
                            logger.warning(f"Ignored unauthorized message from ID {sender_id}")
                            continue

                        text = msg.get("text", "")
                        if text.startswith("/"):
                            handle_telegram_command(text, token, authorized_chat_id, config, session, state)
                            
        except requests.RequestException:
            # Network hiccup or timeout, continue gracefully
            time.sleep(2)
        except Exception as e:
            logger.error(f"Error in telegram_listener_thread: {e}", exc_info=True)
            time.sleep(2)


def test_telegram_cmd(config):
    """Test Telegram notification."""
    token = config.get("telegram_bot_token", "").strip()
    chat_id = config.get("telegram_chat_id", "")
    
    if not token or not chat_id:
        print("ERROR: telegram_bot_token or telegram_chat_id is empty in config.json.")
        print("Please configure them first.")
        sys.exit(1)
        
    print(f"Sending test notification to chat {chat_id}...")
    test_msg = (
        "<b>CUNI Dorm Monitor - Test successful!</b>\n\n"
        "This bot is successfully sending messages. As soon as capacity opens in your "
        "monitored categories on Charles University dormitories, you will receive an "
        "immediate alert with a direct reservation link."
    )
    success, err = send_telegram_message(token, chat_id, test_msg)
    if success:
        print("SUCCESS! Test message sent to your Telegram. Check your Telegram app!")
    else:
        print(f"FAILED: {err}")
        sys.exit(1)


def check_once_cmd(config):
    """Run one-off check and print detailed table to console."""
    colleges = config.get("colleges", [])
    monitor_men = config.get("monitor_men", True)
    monitor_women = config.get("monitor_women", False)
    monitor_unspecified = config.get("monitor_unspecified", True)
    session = requests.Session()
    print(f"\n{'='*70}")
    print(f"CUNI DORM CAPACITY CHECK - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*70}\n")
    
    total_available = 0
    
    for item in colleges:
        url = item.get("url")
        fallback_name = item.get("name", "Dormitory")
        try:
            title, all_rooms, available_rooms = parse_college_page(
                session, url, fallback_name,
                monitor_men=monitor_men,
                monitor_women=monitor_women,
                monitor_unspecified=monitor_unspecified
            )
            print(f"Dormitory: {title} ({url})")
            if not all_rooms:
                print("    (No rooms found or table error)")
            for rm in all_rooms:
                is_avail = (
                    (monitor_men and rm["men"] > 0) or
                    (monitor_unspecified and rm["unspecified"] > 0) or
                    (monitor_women and rm["women"] > 0)
                )
                status_icon = "AVAILABLE!" if is_avail else "Occupied"
                print(
                    f"    [{status_icon:<10}] {rm['room']:<36} | "
                    f"Men: {rm['men']:<2} | Unspecified: {rm['unspecified']:<2} | Women: {rm['women']:<2} | "
                    f"{rm['price']} CZK"
                )
                if is_avail:
                    total_available += 1
            print("-" * 70)
        except Exception as e:
            print(f"    Error fetching {fallback_name}: {e}")
            print("-" * 70)
            
    print(f"\nTotal available room types found: {total_available}\n")


def main():
    parser = argparse.ArgumentParser(description="CUNI Dormitory Capacity Monitor")
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH, help="Path to config.json")
    parser.add_argument("--check-once", action="store_true", help="Perform a single check and print to stdout")
    parser.add_argument("--test-telegram", action="store_true", help="Send a test message to Telegram and exit")
    args = parser.parse_args()

    config = load_config(args.config)

    if args.test_telegram:
        test_telegram_cmd(config)
        return

    if args.check_once:
        check_once_cmd(config)
        return

    # Normal daemon monitoring mode
    token = config.get("telegram_bot_token", "").strip()
    chat_id = config.get("telegram_chat_id", "")
    interval = int(config.get("check_interval_seconds", 60))
    send_startup = config.get("send_startup_message", True)
    
    if not token or not chat_id:
        logger.warning("WARNING: telegram_bot_token or telegram_chat_id is NOT set!")

    logger.info(f"Starting CUNI Dorm Monitor daemon (interval: {interval}s)...")
    logger.info(f"Monitoring {len(config.get('colleges', []))} dormitories.")
    
    register_telegram_commands(token)

    if send_startup and token and chat_id:
        startup_text = (
            "<b>CUNI Dorm Monitor started!</b>\n\n"
            f"Monitoring {len(config.get('colleges', []))} dormitories every {interval} seconds.\n"
            "Commands: /status, /check, /men, /women, /logs, /stop, /restart."
        )
        send_telegram_message(token, chat_id, startup_text)

    session = requests.Session()
    state = load_state()

    # Start Telegram listener thread for commands
    listener = threading.Thread(
        target=telegram_listener_thread,
        args=(config, session, state),
        daemon=True,
        name="TelegramListener"
    )
    listener.start()

    while RUNNING:
        if not MONITORING_PAUSED:
            try:
                run_monitor_cycle(config, session, state)
            except Exception as e:
                logger.error(f"Error during monitor cycle: {e}", exc_info=True)
        else:
            logger.debug("Monitoring is currently paused.")

        # Wait for interval or until an immediate /check is requested
        TRIGGER_CHECK_EVENT.wait(timeout=interval)
        TRIGGER_CHECK_EVENT.clear()

    logger.info("Monitor daemon stopped cleanly.")

if __name__ == "__main__":
    main()
