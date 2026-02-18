#!/bin/bash
# =============================================================
# MYSTES Mobile Setup Script
# Sets up Capacitor for iOS and Android builds
# =============================================================

set -e

echo "=========================================="
echo "  MYSTES Mobile Build Setup"
echo "=========================================="

# Check prerequisites
command -v node >/dev/null 2>&1 || {
    echo "ERROR: Node.js is required. Install it first:"
    echo "  macOS:   brew install node"
    echo "  Ubuntu:  sudo apt install nodejs npm"
    echo "  Or:      https://nodejs.org/en/download/"
    exit 1
}

echo "Node.js: $(node --version)"
echo "npm:     $(npm --version)"

# Install dependencies
echo ""
echo "Installing Capacitor dependencies..."
npm install

# Initialize Capacitor (if not already done)
if [ ! -d "ios" ]; then
    echo ""
    echo "Adding iOS platform..."
    npx cap add ios
fi

if [ ! -d "android" ]; then
    echo ""
    echo "Adding Android platform..."
    npx cap add android
fi

# Copy icons to native projects
echo ""
echo "Syncing web assets to native projects..."
npx cap sync

echo ""
echo "=========================================="
echo "  Setup Complete!"
echo "=========================================="
echo ""
echo "To build for iOS:"
echo "  npx cap open ios"
echo "  (Opens Xcode — select a team and build)"
echo ""
echo "To build for Android:"
echo "  npx cap open android"
echo "  (Opens Android Studio — build from there)"
echo ""
echo "For development, the app connects to:"
echo "  http://localhost:5001"
echo ""
echo "For production, update capacitor.config.ts:"
echo "  server.url → your deployed server URL"
echo "=========================================="
