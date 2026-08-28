#!/bin/bash
echo "========================================================"
echo "       LabFlow Standalone Local Server Engine (Linux)"
echo "========================================================"
echo ""
cd "$(dirname "$0")/.."
python3 server_engine/server_main.py
