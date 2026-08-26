"""
LabFlow Server Manager - Worker 2: Visual Admin Control Panel UI
==================================================================
Runs on port 9000 (0.0.0.0) providing a visual dashboard to inspect
server status, live LAN traffic, PostgreSQL database tables, and setup config.
"""

import os
import sys
import json
import time
import socket
import logging
import urllib.request
from typing import Dict, Any
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
import psycopg2

# Add workspace root to sys.path
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from local_postgres_engine import check_db_health, get_table_status, init_local_schema

logger = logging.getLogger("LabFlow.Worker2Admin")
app = FastAPI(title="LabFlow Worker 2 Admin Panel", version="2.0")

# Set up templates directory
templates_dir = os.path.join(os.path.dirname(__file__), "templates")
templates = Jinja2Templates(directory=templates_dir)

CONFIG_PATH_ROOT = os.path.join(root_dir, "labflow_config.json")
CONFIG_PATH_LOCAL = os.path.join(os.path.dirname(__file__), "labflow_config.json")


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


def load_config() -> Dict[str, Any]:
    """Loads database & server configuration from labflow_config.json or defaults."""
    if os.path.exists(CONFIG_PATH_ROOT):
        try:
            with open(CONFIG_PATH_ROOT, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "LOCAL_DB_HOST": "127.0.0.1",
        "LOCAL_DB_PORT": 5432,
        "LOCAL_DB_NAME": "labflow_db",
        "LOCAL_DB_USER": "postgres",
        "LOCAL_DB_PASS": "postgres",
        "SERVER_PORT": 8000
    }


def save_config(cfg: Dict[str, Any]):
    """Saves database configuration to labflow_config.json."""
    for path in [CONFIG_PATH_ROOT, CONFIG_PATH_LOCAL]:
        with open(path, "w") as f:
            json.dump(cfg, f, indent=2)


@app.get("/", response_class=HTMLResponse)
def admin_dashboard(request: Request):
    """Renders the main Visual Admin Dashboard."""
    local_ip = get_local_ip()
    config = load_config()
    return templates.TemplateResponse("index.html", {
        "request": request,
        "local_ip": local_ip,
        "config": config
    })


@app.get("/setup", response_class=HTMLResponse)
def admin_setup(request: Request):
    """Renders the Database & Server Setup page."""
    config = load_config()
    return templates.TemplateResponse("setup.html", {
        "request": request,
        "config": config,
        "local_ip": get_local_ip()
    })


@app.get("/api/live-status")
def get_live_status():
    """Returns aggregated status for Worker 1, PostgreSQL DB, LAN network, and database tables."""
    local_ip = get_local_ip()
    db_health = check_db_health()
    tables = get_table_status()

    # Poll Worker 1 background metrics
    worker1_metrics = {}
    worker1_online = False
    try:
        req = urllib.request.Request("http://127.0.0.1:8000/server/metrics", headers={"User-Agent": "Worker2Admin"})
        with urllib.request.urlopen(req, timeout=2) as resp:
            if resp.status == 200:
                worker1_metrics = json.loads(resp.read().decode())
                worker1_online = True
    except Exception:
        pass

    return {
        "timestamp": time.strftime("%H:%M:%S"),
        "local_ip": local_ip,
        "worker1_online": worker1_online,
        "worker1_metrics": worker1_metrics,
        "db_health": db_health,
        "tables": tables
    }


@app.post("/api/save-config")
def save_database_config(
    db_host: str = Form("127.0.0.1"),
    db_port: int = Form(5432),
    db_name: str = Form("labflow_db"),
    db_user: str = Form("postgres"),
    db_pass: str = Form("postgres"),
    server_port: int = Form(8000)
):
    """Tests connection to PostgreSQL with provided parameters and saves labflow_config.json."""
    # Test connection
    try:
        conn = psycopg2.connect(
            host=db_host,
            port=db_port,
            user=db_user,
            password=db_pass,
            dbname="postgres",
            connect_timeout=3
        )
        conn.close()
        test_passed = True
        msg = "Successfully connected to PostgreSQL server!"
    except Exception as e:
        test_passed = False
        msg = f"PostgreSQL connection failed: {e}"

    if test_passed:
        # Update os.environ and save config file
        os.environ["LOCAL_DB_HOST"] = db_host
        os.environ["LOCAL_DB_PORT"] = str(db_port)
        os.environ["LOCAL_DB_NAME"] = db_name
        os.environ["LOCAL_DB_USER"] = db_user
        os.environ["LOCAL_DB_PASS"] = db_pass

        cfg = {
            "LOCAL_DB_HOST": db_host,
            "LOCAL_DB_PORT": db_port,
            "LOCAL_DB_NAME": db_name,
            "LOCAL_DB_USER": db_user,
            "LOCAL_DB_PASS": db_pass,
            "SERVER_PORT": server_port,
            "UPDATED_AT": time.strftime("%Y-%m-%d %H:%M:%S")
        }
        save_config(cfg)
        
        # Trigger schema init
        init_local_schema()

    return {
        "success": test_passed,
        "message": msg
    }


if __name__ == "__main__":
    import uvicorn
    local_ip = get_local_ip()
    print("=========================================================")
    print("      LABFLOW WORKER 2: VISUAL ADMIN PANEL (PORT 9000)    ")
    print("=========================================================")
    print(f" -> Local Dashboard: http://127.0.0.1:9000")
    print(f" -> LAN Admin UI:    http://{local_ip}:9000")
    print("=========================================================\n")
    uvicorn.run(app, host="0.0.0.0", port=9000, reload=False)
