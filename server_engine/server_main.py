"""
LabFlow Standalone Local Server Engine Launcher
================================================
Boots the standalone local FastAPI server engine on host 0.0.0.0:8000,
verifying local PostgreSQL database health on boot up.
"""

import os
import sys
import uvicorn
import logging

# Add parent directory to path so root modules can be loaded
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from local_postgres_engine import init_local_schema, check_db_health
from server_engine.local_db_config import load_config

logger = logging.getLogger("LabFlow.ServerEngine")

def boot_server():
    print("=" * 65)
    print("       LABFLOW OFFLINE LOCAL SERVER ENGINE STARTUP          ")
    print("=" * 65)

    config = load_config()

    # 1. Probe & auto-initialize local PostgreSQL schema
    print("\n[Step 1/2] Probing Local PostgreSQL Database Engine...")
    health = check_db_health()
    
    if health["status"] != "healthy":
        print(f" -> Database status: {health['status'].upper()}")
        print(f" -> {health.get('message')}")
        print(" -> Attempting automated schema initialization...")
        ok, msg = init_local_schema()
        print(f" -> Schema Init: {msg}")
    else:
        print(f" -> Database connected: {health['database_name']} ({health['latency_ms']} ms)")
        print(f" -> Active connections: {health['active_connections']}, Tables: {health['total_tables']}")

    # 2. Start Uvicorn Server Engine
    host = config["HOST"]
    port = config["PORT"]

    print(f"\n[Step 2/2] Launching Local FastAPI Server Engine...")
    print(f" -> Server bound to: http://{host}:{port}")
    print(f" -> Local LAN Access: http://<SERVER_IP>:{port}")
    print("=" * 65)
    print("Server engine is running. Press Ctrl+C to stop.\n")

    # Import standalone headless server_api app
    from server_engine.server_api import app
    uvicorn.run(app, host=host, port=port, reload=False)

if __name__ == "__main__":
    boot_server()
