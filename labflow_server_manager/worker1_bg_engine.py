"""
LabFlow Server Manager - Worker 1: Headless Background Engine
==============================================================
Runs the background API & database traffic engine on port 8000 (0.0.0.0),
handling DB requests and recording live network traffic metrics for Worker 2.
"""

import os
import sys
import time
import socket
import logging
from typing import Dict, List, Any
from datetime import datetime
from collections import deque
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

# Add workspace root to sys.path
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from local_postgres_engine import check_db_health, get_table_status, init_local_schema

logger = logging.getLogger("LabFlow.Worker1Engine")
app = FastAPI(title="LabFlow Worker 1 Engine", version="2.0")

# Live Traffic & Client Metrics Store
metrics_store = {
    "start_time": time.time(),
    "total_requests": 0,
    "client_ips": {},  # ip -> {"count": int, "last_seen": str}
    "recent_logs": deque(maxlen=50),  # last 50 traffic logs
    "requests_last_minute": deque(maxlen=60)
}


def get_local_ip() -> str:
    """Detects primary local LAN IP address of this host machine."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


@app.middleware("http")
async def track_network_traffic(request: Request, call_next):
    """Middleware to record incoming LAN client traffic and response latencies."""
    start_ts = time.time()
    client_ip = request.client.host if request.client else "unknown"
    path = request.url.path
    method = request.method

    response = await call_next(request)

    duration_ms = round((time.time() - start_ts) * 1000, 2)
    status_code = response.status_code

    # Exclude internal metrics polling from spamming logs
    if not path.startswith("/server/"):
        metrics_store["total_requests"] += 1
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Update client IP info
        if client_ip not in metrics_store["client_ips"]:
            metrics_store["client_ips"][client_ip] = {"count": 0, "first_seen": now_str, "last_seen": now_str}

        metrics_store["client_ips"][client_ip]["count"] += 1
        metrics_store["client_ips"][client_ip]["last_seen"] = now_str

        # Append to recent traffic log
        metrics_store["recent_logs"].appendleft({
            "timestamp": now_str,
            "ip": client_ip,
            "method": method,
            "path": path,
            "status": status_code,
            "duration_ms": duration_ms
        })

    return response


@app.get("/")
def engine_root():
    return {
        "engine": "LabFlow Worker 1 Background DB Engine",
        "status": "online",
        "local_lan_ip": get_local_ip(),
        "port": 8000,
        "timestamp": datetime.now().isoformat()
    }


@app.get("/server/metrics")
def get_server_metrics():
    """Internal endpoint polled by Worker 2 Admin Panel."""
    uptime_sec = int(time.time() - metrics_store["start_time"])
    health = check_db_health()

    return {
        "uptime_seconds": uptime_sec,
        "total_requests": metrics_store["total_requests"],
        "active_client_count": len(metrics_store["client_ips"]),
        "client_ips": metrics_store["client_ips"],
        "recent_logs": list(metrics_store["recent_logs"]),
        "database_health": health,
        "host_ip": get_local_ip()
    }


@app.get("/server/tables")
def get_database_tables():
    """Returns row counts for all 11 lab database tables."""
    return {
        "tables": get_table_status(),
        "timestamp": datetime.now().isoformat()
    }


@app.post("/server/init-db")
def trigger_db_init():
    """Triggers database schema initialization."""
    ok, msg = init_local_schema()
    return {"success": ok, "message": msg}


if __name__ == "__main__":
    import uvicorn
    local_ip = get_local_ip()
    print("=========================================================")
    print("      LABFLOW WORKER 1: BACKGROUND ENGINE (PORT 8000)     ")
    print("=========================================================")
    print(f" -> Local Host IP: http://127.0.0.1:8000")
    print(f" -> LAN Router IP: http://{local_ip}:8000")
    print("=========================================================\n")
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=False)
