#!/bin/bash
echo "========================================================"
echo "       LabFlow Server Manager Dual Worker Engine (Linux)"
echo "========================================================"
echo ""

# Go to repository root directory
cd "$(dirname "$0")/.."

# Activate virtual environment if present
if [ -d ".venv" ]; then
    source .venv/bin/activate
fi

# Start Worker 1 (Server Engine API on Port 8888) in background
echo "Starting Worker 1 (Server Engine API on Port 8888)..."
python3 server_engine/server_main.py &

# Start Worker 2 (Visual Admin Panel UI on Port 9999) in background
echo "Starting Worker 2 (Visual Admin Panel on Port 9999)..."
python3 labflow_server_manager/worker2_admin_panel.py &

echo ""
echo "Both Linux server workers launched successfully!"
echo " -> Visual Dashboard: http://192.168.1.4:9999"
echo " -> Server API Engine: http://192.168.1.4:8888"
