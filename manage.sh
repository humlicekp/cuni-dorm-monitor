#!/bin/bash
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

SERVICE_NAME="cuni-dorm-monitor.service"

case "$1" in
    start)
        echo "Starting $SERVICE_NAME..."
        systemctl --user enable --now "$SERVICE_NAME"
        systemctl --user status "$SERVICE_NAME" --no-pager
        ;;
    stop)
        echo "Stopping $SERVICE_NAME..."
        systemctl --user stop "$SERVICE_NAME"
        ;;
    restart)
        echo "Restarting $SERVICE_NAME..."
        systemctl --user restart "$SERVICE_NAME"
        systemctl --user status "$SERVICE_NAME" --no-pager
        ;;
    status)
        systemctl --user status "$SERVICE_NAME" --no-pager
        ;;
    logs)
        journalctl --user -u "$SERVICE_NAME" -f -n 50
        ;;
    check)
        python3 "$DIR/monitor.py" --check-once
        ;;
    test)
        python3 "$DIR/monitor.py" --test-telegram
        ;;
    setup)
        python3 "$DIR/monitor.py" --setup
        ;;
    *)
        echo "Usage: $0 {start|stop|restart|status|logs|check|test|setup}"
        echo ""
        echo "Commands:"
        echo "  start   - Enable and start the background 24/7 systemd service"
        echo "  stop    - Stop the background service"
        echo "  restart - Restart the background service"
        echo "  status  - Show current status of the background service"
        echo "  logs    - Stream live logs from the service (journalctl)"
        echo "  check   - Perform an instant manual check and show in terminal"
        echo "  test    - Send a test alert to your Telegram chat"
        echo "  setup   - Run interactive Telegram bot configuration wizard"
        exit 1
        ;;
esac
