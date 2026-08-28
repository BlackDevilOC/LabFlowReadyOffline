"""
LabFlow Headless Linux Server API & Metrics Engine
==================================================
Provides real-time system metrics (CPU %, RAM %, Disk Space %, DB Latency, Active Connections),
automated PostgreSQL .sql backups management, and LAN backup distribution APIs.
"""

import os
import sys
import time
import logging
from datetime import datetime
from typing import Optional, Dict, Any

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

# Ensure root workspace directory is in sys.path
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from local_postgres_engine import get_connection, check_db_health
from server_engine.backup_manager import (
    create_sql_backup,
    list_backups,
    get_latest_backup,
    get_backup_dir
)

try:
    import psutil
except ImportError:
    psutil = None

logger = logging.getLogger("LabFlow.ServerAPI")

app = FastAPI(
    title="LabFlow Headless Server Engine",
    version="2.0.0",
    description="Headless API server providing PostgreSQL health, system hardware metrics, and automated SQL backups."
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def api_root():
    return {
        "status": "online",
        "service": "LabFlow Headless Linux Server Engine",
        "version": "2.0.0",
        "timestamp": datetime.now().isoformat()
    }


@app.get("/api/server/health")
def api_server_health():
    """Returns database health status and latency."""
    return check_db_health()


@app.get("/api/server/metrics")
def api_server_metrics():
    """Returns live hardware metrics (CPU, RAM, Disk) and DB statistics."""
    try:
        # Hardware Metrics
        if psutil:
            cpu_pct = psutil.cpu_percent(interval=0.1)
            mem = psutil.virtual_memory()
            mem_info = {
                "total_mb": round(mem.total / (1024 ** 2), 2),
                "used_mb": round(mem.used / (1024 ** 2), 2),
                "free_mb": round(mem.available / (1024 ** 2), 2),
                "percent": mem.percent
            }
            backup_path = get_backup_dir()
            disk_target = str(backup_path) if backup_path.exists() else "/"
            try:
                disk = psutil.disk_usage(disk_target)
                disk_info = {
                    "total_gb": round(disk.total / (1024 ** 3), 2),
                    "used_gb": round(disk.used / (1024 ** 3), 2),
                    "free_gb": round(disk.free / (1024 ** 3), 2),
                    "percent": disk.percent
                }
            except Exception:
                disk_info = {"total_gb": 0, "used_gb": 0, "free_gb": 0, "percent": 0}
        else:
            cpu_pct = 0.0
            mem_info = {"total_mb": 0, "used_mb": 0, "free_mb": 0, "percent": 0}
            disk_info = {"total_gb": 0, "used_gb": 0, "free_gb": 0, "percent": 0}

        # Database Stats
        db_health = check_db_health()
        latest_b = get_latest_backup()

        return {
            "timestamp": datetime.now().isoformat(),
            "cpu_percent": cpu_pct,
            "memory": mem_info,
            "disk": disk_info,
            "database": db_health,
            "latest_backup": latest_b
        }
    except Exception as e:
        logger.error(f"Error fetching metrics: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/server/backups/create")
def api_create_backup(background_tasks: BackgroundTasks):
    """Triggers an immediate .sql database backup."""
    success, msg, filepath = create_sql_backup("manual_trigger")
    if not success:
        raise HTTPException(status_code=500, detail=msg)
    return {
        "success": True,
        "message": msg,
        "filepath": filepath,
        "timestamp": datetime.now().isoformat()
    }


@app.get("/api/server/backups/list")
def api_list_backups():
    """Returns a list of all available .sql backup files."""
    return {"backups": list_backups()}


@app.get("/api/server/backups/latest")
def api_download_latest_backup():
    """Downloads the most recent .sql database backup file."""
    latest = get_latest_backup()
    if not latest:
        raise HTTPException(status_code=404, detail="No backup files found on server.")
    
    filepath = latest["filepath"]
    filename = latest["filename"]
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail=f"Backup file '{filename}' not found.")
    
    return FileResponse(
        path=filepath,
        filename=filename,
        media_type="application/sql"
    )


@app.get("/api/server/backups/download/{filename}")
def api_download_backup_by_name(filename: str):
    """Downloads a specific .sql database backup file by filename."""
    backup_dir = get_backup_dir()
    filepath = backup_dir / filename
    
    if not filepath.exists() or not filepath.is_file():
        raise HTTPException(status_code=404, detail=f"Backup file '{filename}' not found.")
    
    return FileResponse(
        path=str(filepath),
        filename=filename,
        media_type="application/sql"
    )
