#!/usr/bin/env bash
# ===========================================================================
# MYSTES Node Service Installer (Build #91)
#
# Installs node_service.py as a persistent background service.
# Supports macOS (LaunchAgent) and Linux (systemd user service).
#
# Usage:
#   ./install-node-service.sh --token YOUR_TOKEN --server https://mystes.example.com
#   ./install-node-service.sh --token YOUR_TOKEN                # defaults to http://localhost:5000
#   ./install-node-service.sh --uninstall                       # remove the service
#   ./install-node-service.sh --status                          # check service status
# ===========================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
NODE_SERVICE_PATH="$PROJECT_DIR/node_service.py"
TEMPLATES_DIR="$SCRIPT_DIR/service-templates"

DEFAULT_SERVER="http://localhost:5000"
HELPER_TOKEN=""
SERVER_URL="$DEFAULT_SERVER"
ACTION="install"

# ---------------------------------------------------------------------------
# Parse arguments
# ---------------------------------------------------------------------------

while [[ $# -gt 0 ]]; do
    case "$1" in
        --token)
            HELPER_TOKEN="$2"
            shift 2
            ;;
        --server)
            SERVER_URL="$2"
            shift 2
            ;;
        --uninstall)
            ACTION="uninstall"
            shift
            ;;
        --status)
            ACTION="status"
            shift
            ;;
        --help|-h)
            echo "Mystes Node Service Installer"
            echo ""
            echo "Usage:"
            echo "  $0 --token TOKEN [--server URL]   Install the service"
            echo "  $0 --uninstall                     Remove the service"
            echo "  $0 --status                        Check service status"
            echo ""
            echo "Options:"
            echo "  --token TOKEN    Helper token for node authentication (required for install)"
            echo "  --server URL     Mystes backend URL (default: $DEFAULT_SERVER)"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# ---------------------------------------------------------------------------
# OS detection
# ---------------------------------------------------------------------------

detect_os() {
    case "$(uname -s)" in
        Darwin*)  echo "macos" ;;
        Linux*)   echo "linux" ;;
        *)        echo "unknown" ;;
    esac
}

OS="$(detect_os)"

# ---------------------------------------------------------------------------
# Python detection
# ---------------------------------------------------------------------------

find_python() {
    for cmd in python3 python; do
        if command -v "$cmd" &>/dev/null; then
            local version
            version="$("$cmd" --version 2>&1 | grep -oE '[0-9]+\.[0-9]+')"
            local major="${version%%.*}"
            if [[ "$major" -ge 3 ]]; then
                echo "$(command -v "$cmd")"
                return 0
            fi
        fi
    done
    return 1
}

# ---------------------------------------------------------------------------
# macOS LaunchAgent
# ---------------------------------------------------------------------------

PLIST_NAME="com.mystes.node-service"
PLIST_PATH="$HOME/Library/LaunchAgents/$PLIST_NAME.plist"
LOG_DIR_MACOS="$HOME/Library/Logs"

install_macos() {
    local python_path
    python_path="$(find_python)" || { echo "ERROR: Python 3 not found"; exit 1; }

    echo "Installing Mystes Node Service (macOS LaunchAgent)..."
    echo "  Python: $python_path"
    echo "  Service: $NODE_SERVICE_PATH"
    echo "  Server: $SERVER_URL"
    echo "  Log: $LOG_DIR_MACOS/mystes-node-service.log"

    # Check aiohttp
    "$python_path" -c "import aiohttp" 2>/dev/null || {
        echo ""
        echo "ERROR: aiohttp is required. Install with:"
        echo "  $python_path -m pip install aiohttp"
        exit 1
    }

    # Create plist from template
    mkdir -p "$HOME/Library/LaunchAgents"

    sed -e "s|__PYTHON_PATH__|$python_path|g" \
        -e "s|__NODE_SERVICE_PATH__|$NODE_SERVICE_PATH|g" \
        -e "s|__HELPER_TOKEN__|$HELPER_TOKEN|g" \
        -e "s|__SERVER_URL__|$SERVER_URL|g" \
        -e "s|__LOG_DIR__|$LOG_DIR_MACOS|g" \
        "$TEMPLATES_DIR/com.mystes.node-service.plist" > "$PLIST_PATH"

    # Load the service
    launchctl unload "$PLIST_PATH" 2>/dev/null || true
    launchctl load "$PLIST_PATH"

    echo ""
    echo "Mystes Node Service installed and started."
    echo "  To check status:  launchctl list | grep mystes"
    echo "  To view logs:     tail -f $LOG_DIR_MACOS/mystes-node-service.log"
    echo "  To uninstall:     $0 --uninstall"
}

uninstall_macos() {
    echo "Uninstalling Mystes Node Service (macOS)..."
    if [[ -f "$PLIST_PATH" ]]; then
        launchctl unload "$PLIST_PATH" 2>/dev/null || true
        rm -f "$PLIST_PATH"
        echo "Service removed."
    else
        echo "Service not found at $PLIST_PATH"
    fi
}

status_macos() {
    if launchctl list 2>/dev/null | grep -q "$PLIST_NAME"; then
        echo "Mystes Node Service: RUNNING"
        launchctl list "$PLIST_NAME" 2>/dev/null || true
    else
        echo "Mystes Node Service: NOT RUNNING"
    fi
}

# ---------------------------------------------------------------------------
# Linux systemd user service
# ---------------------------------------------------------------------------

SERVICE_NAME="mystes-node"
SERVICE_DIR="$HOME/.config/systemd/user"
SERVICE_PATH="$SERVICE_DIR/$SERVICE_NAME.service"
LOG_DIR_LINUX="$HOME/.local/share/mystes"

install_linux() {
    local python_path
    python_path="$(find_python)" || { echo "ERROR: Python 3 not found"; exit 1; }

    echo "Installing Mystes Node Service (Linux systemd user service)..."
    echo "  Python: $python_path"
    echo "  Service: $NODE_SERVICE_PATH"
    echo "  Server: $SERVER_URL"

    # Check aiohttp
    "$python_path" -c "import aiohttp" 2>/dev/null || {
        echo ""
        echo "ERROR: aiohttp is required. Install with:"
        echo "  $python_path -m pip install aiohttp"
        exit 1
    }

    # Create directories
    mkdir -p "$SERVICE_DIR"
    mkdir -p "$LOG_DIR_LINUX"

    # Create service unit from template
    sed -e "s|__PYTHON_PATH__|$python_path|g" \
        -e "s|__NODE_SERVICE_PATH__|$NODE_SERVICE_PATH|g" \
        -e "s|__HELPER_TOKEN__|$HELPER_TOKEN|g" \
        -e "s|__SERVER_URL__|$SERVER_URL|g" \
        -e "s|__LOG_DIR__|$LOG_DIR_LINUX|g" \
        "$TEMPLATES_DIR/mystes-node.service" > "$SERVICE_PATH"

    # Enable and start
    systemctl --user daemon-reload
    systemctl --user enable "$SERVICE_NAME"
    systemctl --user start "$SERVICE_NAME"

    echo ""
    echo "Mystes Node Service installed and started."
    echo "  To check status:  systemctl --user status $SERVICE_NAME"
    echo "  To view logs:     journalctl --user -u $SERVICE_NAME -f"
    echo "  To uninstall:     $0 --uninstall"
}

uninstall_linux() {
    echo "Uninstalling Mystes Node Service (Linux)..."
    if [[ -f "$SERVICE_PATH" ]]; then
        systemctl --user stop "$SERVICE_NAME" 2>/dev/null || true
        systemctl --user disable "$SERVICE_NAME" 2>/dev/null || true
        rm -f "$SERVICE_PATH"
        systemctl --user daemon-reload
        echo "Service removed."
    else
        echo "Service not found at $SERVICE_PATH"
    fi
}

status_linux() {
    if systemctl --user is-active "$SERVICE_NAME" &>/dev/null; then
        echo "Mystes Node Service: RUNNING"
        systemctl --user status "$SERVICE_NAME" --no-pager
    else
        echo "Mystes Node Service: NOT RUNNING"
    fi
}

# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

case "$ACTION" in
    install)
        if [[ -z "$HELPER_TOKEN" ]]; then
            echo "ERROR: --token is required for installation"
            echo "  Get your token from: https://your-mystes-server/helper/dashboard"
            exit 1
        fi

        if [[ ! -f "$NODE_SERVICE_PATH" ]]; then
            echo "ERROR: node_service.py not found at $NODE_SERVICE_PATH"
            exit 1
        fi

        case "$OS" in
            macos)  install_macos ;;
            linux)  install_linux ;;
            *)      echo "ERROR: Unsupported OS. Use install-node-service.ps1 for Windows."; exit 1 ;;
        esac
        ;;

    uninstall)
        case "$OS" in
            macos)  uninstall_macos ;;
            linux)  uninstall_linux ;;
            *)      echo "ERROR: Unsupported OS."; exit 1 ;;
        esac
        ;;

    status)
        case "$OS" in
            macos)  status_macos ;;
            linux)  status_linux ;;
            *)      echo "ERROR: Unsupported OS."; exit 1 ;;
        esac
        ;;
esac
