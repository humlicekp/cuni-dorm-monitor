# CUNI Dormitory Capacity Monitor

An automated, lightweight capacity monitor for Charles University (Univerzita Karlova) dormitories via the central reservation portal (rehos.cuni.cz).
It runs 24/7 in the background as a systemd user service and immediately sends Telegram alerts with direct booking links when available rooms are detected.

---

## Features

- Real-Time Monitoring: Automatically monitors specified dormitories and detects vacancies.
- Configurable Gender Categories: Monitor capacity for Men, Women, and Unspecified rooms independently.
- Telegram Remote Control: Check status, trigger manual scans, toggle female room monitoring, and inspect logs directly from Telegram.
- Anti-Spam State Tracking: Alerts on new capacity and changes without flooding your chat.
- Lightweight & Polite: Minimal bandwidth (~2 KB/s) and gentle pacing to avoid rate-limiting or server load.
- Resilient: Automatically restarts on failures and survives reboots via systemd and user linger.

---

## Monitored Dormitories

1. Kolej Hvezda - https://rehos.cuni.cz/crpp/eshop/collegeDetail/380944
2. Kolej Budec - https://rehos.cuni.cz/crpp/eshop/collegeDetail/380942
3. Kolej Jednota - https://rehos.cuni.cz/crpp/eshop/collegeDetail/380939
4. Kolej Na Vetrniku - https://rehos.cuni.cz/crpp/eshop/collegeDetail/380945
5. Kolej Svehlova - https://rehos.cuni.cz/crpp/eshop/collegeDetail/380943
6. Kolej 17. listopadu - https://rehos.cuni.cz/crpp/eshop/collegeDetail/380948

---

## Telegram Bot Commands

You can control the monitor directly from your Telegram conversation:

- /check - Perform an immediate scan across all dormitories and return current availability.
- /status - Display service uptime, last check timestamp, interval, and active monitored categories.
- /men on - Enable monitoring for Men (Muzi) category.
- /men off - Disable monitoring for Men (Muzi) category.
- /men - Check current status of Men category monitoring.
- /women on - Enable monitoring for Women (Zeny) category.
- /women off - Disable monitoring for Women (Zeny) category.
- /women - Check current status of Women category monitoring.
- /logs - Display the last 15 lines of runtime log output.
- /stop - Temporarily pause automated monitoring checks.
- /start - Resume automated monitoring checks.
- /restart - Remotely restart the background systemd service.
- /help - Display the list of available commands.

Note: For security, the bot only processes commands sent from your authorized Telegram chat ID.

---

## Setup & Configuration

### 1. Requirements
- Python 3.8+
- Python requests library: `pip install -r requirements.txt`

### 2. Configuration (`config.json`)
Copy `config.example.json` to `config.json` and enter your credentials:

```json
{
  "telegram_bot_token": "YOUR_TELEGRAM_BOT_TOKEN",
  "telegram_chat_id": "YOUR_TELEGRAM_CHAT_ID",
  "check_interval_seconds": 60,
  "reminder_interval_minutes": 60,
  "send_startup_message": true,
  "monitor_men": true,
  "monitor_women": false,
  "monitor_unspecified": true,
  "colleges": [
    {
      "name": "Kolej Hvezda",
      "url": "https://rehos.cuni.cz/crpp/eshop/collegeDetail/380944"
    }
  ]
}
```

Configuration parameters:
- `telegram_bot_token`: HTTP API token from @BotFather.
- `telegram_chat_id`: Your Telegram User ID.
- `check_interval_seconds`: Polling frequency in seconds (default: 60).
- `reminder_interval_minutes`: Periodic reminder interval while capacity remains open (default: 60, 0 to disable).
- `send_startup_message`: Send a confirmation notification when the service starts.
- `monitor_men`: Monitor capacity in the Men (Muzi) column (true/false).
- `monitor_women`: Monitor capacity in the Women (Zeny) column (true/false).
- `monitor_unspecified`: Monitor capacity in the Unspecified (Neurceno) column (true/false).
- `colleges`: Array of dormitory names and URLs to monitor.

---

## Service Management (`manage.sh`)

Use the included helper script to control the daemon:

- `./manage.sh start` - Enable and start the background 24/7 systemd service.
- `./manage.sh stop` - Stop the background service.
- `./manage.sh restart` - Restart the background service.
- `./manage.sh status` - Check the systemd service status.
- `./manage.sh logs` - View live journalctl logs.
- `./manage.sh check` - Run an immediate one-off check and display results in terminal.
- `./manage.sh test` - Send a test notification to verify Telegram setup.
- `./manage.sh setup` - Run the interactive configuration wizard.

---

## Running 24/7 with systemd

The monitor is configured as a systemd user service. To ensure it runs continuously after logout and survives system reboots, enable linger for your user:

```bash
loginctl enable-linger $USER
```

Start the service:

```bash
systemctl --user enable --now cuni-dorm-monitor.service
```

View live logs at any time:

```bash
journalctl --user -u cuni-dorm-monitor.service -f
```
