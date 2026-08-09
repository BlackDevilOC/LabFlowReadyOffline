"""
LabFlow Manual Database Switcher & Live Health Probe Engine
Enables full user control over active database target (Primary Supabase, Secondary Supabase, or Offline Local SQLite).
"""

import os
import sys
import time
import socket
import logging
from typing import Dict, Any, Optional
from datetime import datetime, timezone
from urllib.parse import urlparse
from dotenv import load_dotenv

logger = logging.getLogger("LabFlowDBSwitcher")
MASTER_PASSWORD = "youcannotenter"

def get_base_path() -> str:
    if getattr(sys, "frozen", False):
        return sys._MEIPASS  # type: ignore
    return os.path.dirname(os.path.abspath(__file__))


def load_env_fresh():
    """Forces reloading of .env with override to ensure latest values."""
    env_file = os.path.join(get_base_path(), ".env")
    if os.path.exists(env_file):
        load_dotenv(env_file, override=True)
    else:
        load_dotenv(override=True)


def get_current_db_status() -> Dict[str, Any]:
    """Returns current active database target and connection configuration."""
    load_env_fresh()

    active_url = os.getenv("SUPABASE_URL", "").strip()
    primary_url = os.getenv("PRIMARY_BACKUP_URL", os.getenv("SUPABASE_URL", "")).strip()
    secondary_url = os.getenv("SECONDARY_SUPABASE_URL", "").strip()
    
    # Determine which target is currently active
    if active_url and secondary_url and active_url.rstrip("/") == secondary_url.rstrip("/"):
        active_target = "secondary"
    elif active_url and primary_url and active_url.rstrip("/") == primary_url.rstrip("/"):
        active_target = "primary"
    else:
        active_target = os.getenv("ACTIVE_DB_TARGET", "primary")

    # Local replica info
    local_db_path = os.path.join(get_base_path(), "replica_backups", "primary", "database", "labflow_replica.db")
    local_exists = os.path.exists(local_db_path)
    local_size_kb = round(os.path.getsize(local_db_path) / 1024, 1) if local_exists else 0

    return {
        "active_target": active_target,
        "active_url": active_url,
        "primary_url": primary_url,
        "secondary_url": secondary_url,
        "local_db_exists": local_exists,
        "local_db_size_kb": local_size_kb,
        "local_db_path": local_db_path
    }


def switch_database_target(target: str, password: str) -> Dict[str, Any]:
    """
    Manually switches active database to 'primary', 'secondary', or 'offline'.
    Persists changes to .env file, updates os.environ, and resets database client cache.
    """
    if password != MASTER_PASSWORD:
        return {
            "status": "error",
            "message": "Invalid master password. Access denied."
        }

    load_env_fresh()
    target = target.lower().strip()

    primary_url = os.getenv("PRIMARY_BACKUP_URL", os.getenv("SUPABASE_URL", "")).strip()
    primary_key = os.getenv("PRIMARY_BACKUP_KEY", os.getenv("SUPABASE_KEY", "")).strip()
    secondary_url = os.getenv("SECONDARY_SUPABASE_URL", "").strip()
    secondary_key = os.getenv("SECONDARY_SUPABASE_KEY", "").strip()

    if target == "secondary":
        if not secondary_url or not secondary_key:
            return {
                "status": "error",
                "message": "Secondary Supabase credentials are not configured in .env"
            }
        new_active_url = secondary_url
        new_active_key = secondary_key
        target_name = "Secondary Supabase (Failover)"
    elif target == "primary":
        if not primary_url or not primary_key:
            return {
                "status": "error",
                "message": "Primary Supabase credentials are not configured in .env"
            }
        new_active_url = primary_url
        new_active_key = primary_key
        target_name = "Primary Supabase (Default)"
    elif target == "offline":
        new_active_url = primary_url
        new_active_key = primary_key
        target_name = "Local Offline SQLite Mode"
    else:
        return {
            "status": "error",
            "message": f"Unknown target '{target}'. Use 'primary', 'secondary', or 'offline'."
        }

    # Update in-memory environment variables
    os.environ["SUPABASE_URL"] = new_active_url
    os.environ["SUPABASE_KEY"] = new_active_key
    os.environ["ACTIVE_DB_TARGET"] = target

    # Write / Persist changes to .env file
    env_file = os.path.join(get_base_path(), ".env")
    try:
        env_lines = [
            f"SUPABASE_URL={new_active_url}\n",
            f"SUPABASE_KEY={new_active_key}\n",
            f"PRIMARY_BACKUP_URL={primary_url}\n",
            f"PRIMARY_BACKUP_KEY={primary_key}\n",
            f"SECONDARY_SUPABASE_URL={secondary_url}\n",
            f"SECONDARY_SUPABASE_KEY={secondary_key}\n",
            f"ACTIVE_DB_TARGET={target}\n",
            f"LAST_SWITCHED_AT={datetime.now(timezone.utc).isoformat()}\n"
        ]
        with open(env_file, "w", encoding="utf-8") as f:
            f.writelines(env_lines)
        logger.info(f"Database switched successfully to {target_name}. Persisted to {env_file}")
    except Exception as env_err:
        logger.warning(f"Could not write to .env file: {env_err}")

    # Reset global Supabase client in dbActions if imported
    try:
        import dbActions
        if hasattr(dbActions, "supabase_client_cache"):
            dbActions.supabase_client_cache = None
    except Exception:
        pass

    return {
        "status": "success",
        "active_target": target,
        "active_url": new_active_url,
        "target_name": target_name,
        "message": f"Active database successfully switched to {target_name}!"
    }


def run_full_diagnostics() -> Dict[str, Any]:
    """
    Executes live network pings, DNS queries, and Supabase table probes
    across Primary Supabase, Secondary Supabase, and Local SQLite replica.
    """
    load_env_fresh()

    primary_url = os.getenv("PRIMARY_BACKUP_URL", os.getenv("SUPABASE_URL", "")).strip()
    primary_key = os.getenv("PRIMARY_BACKUP_KEY", os.getenv("SUPABASE_KEY", "")).strip()
    secondary_url = os.getenv("SECONDARY_SUPABASE_URL", "").strip()
    secondary_key = os.getenv("SECONDARY_SUPABASE_KEY", "").strip()

    status_data = get_current_db_status()
    root_causes = []

    # 1. Probe Primary Supabase
    primary_probe = _probe_supabase_endpoint(primary_url, primary_key, "Primary")
    if primary_probe["status"] != "ONLINE_HEALTHY":
        root_causes.append(f"Primary Supabase Alert: {primary_probe.get('error', 'Unreachable')}")

    # 2. Probe Secondary Supabase
    secondary_probe = _probe_supabase_endpoint(secondary_url, secondary_key, "Secondary")
    if secondary_probe["status"] not in ("ONLINE_HEALTHY", "ONLINE_READY", "ONLINE_NEEDS_SCHEMA"):
        root_causes.append(f"Secondary Supabase Alert: {secondary_probe.get('error', 'Unreachable')}")

    # 3. Probe Local SQLite Replica
    local_probe = _probe_local_replica()

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "active_target": status_data["active_target"],
        "active_url": status_data["active_url"],
        "primary": primary_probe,
        "secondary": secondary_probe,
        "local_replica": local_probe,
        "root_cause_analysis": root_causes
    }


def _probe_supabase_endpoint(url: str, key: str, label: str) -> Dict[str, Any]:
    """Helper to test DNS, Ping, and API health of a Supabase instance."""
    if not url or not key:
        return {
            "status": "UNCONFIGURED",
            "url": url,
            "latency_ms": 0,
            "dns_ip": "None",
            "error": "Credentials missing"
        }

    parsed = urlparse(url)
    hostname = parsed.hostname or ""
    dns_ip = "Unknown"
    dns_resolved = False

    # DNS Resolution
    t0 = time.time()
    try:
        dns_ip = socket.gethostbyname(hostname)
        dns_resolved = True
    except Exception as dns_err:
        return {
            "status": "DNS_FAILED",
            "url": url,
            "hostname": hostname,
            "dns_ip": "Failed",
            "latency_ms": 0,
            "error": f"DNS resolution failed for {hostname}: {dns_err}"
        }

    # API Health Check with Supabase client or HTTPS query
    latency_ms = 0
    try:
        from supabase import create_client
        client = create_client(url, key)
        t_req = time.time()
        # Query lightweight table or auth
        res = client.table("patients").select("mr_no").limit(1).execute()
        latency_ms = int((time.time() - t_req) * 1000)
        return {
            "status": "ONLINE_HEALTHY" if label == "Primary" else "ONLINE_READY",
            "url": url,
            "hostname": hostname,
            "dns_ip": dns_ip,
            "latency_ms": latency_ms,
            "tables_found": True,
            "error": None
        }
    except Exception as req_err:
        latency_ms = int((time.time() - t0) * 1000)
        err_str = str(req_err)
        
        # Check if table schema doesn't exist yet
        if "PGRST205" in err_str or "schema cache" in err_str or "does not exist" in err_str:
            return {
                "status": "ONLINE_NEEDS_SCHEMA",
                "url": url,
                "hostname": hostname,
                "dns_ip": dns_ip,
                "latency_ms": latency_ms,
                "tables_found": False,
                "error": "Supabase project is online, but database tables are not yet created."
            }
        
        return {
            "status": "CONNECTION_FAILED",
            "url": url,
            "hostname": hostname,
            "dns_ip": dns_ip,
            "latency_ms": latency_ms,
            "error": err_str
        }


def _probe_local_replica() -> Dict[str, Any]:
    """Helper to check local SQLite replica health."""
    db_path = os.path.join(get_base_path(), "replica_backups", "primary", "database", "labflow_replica.db")
    if not os.path.exists(db_path):
        return {
            "status": "NOT_FOUND",
            "db_path": db_path,
            "db_size_bytes": 0,
            "patients_count": 0,
            "tests_count": 0,
            "last_sync_time": None
        }

    try:
        import sqlite3
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        
        cur.execute("SELECT COUNT(*) FROM patients")
        p_count = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM test_results_all")
        r_count = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM tests")
        t_count = cur.fetchone()[0]
        conn.close()

        # Read last sync time from sync_state.json if available
        sync_state_file = os.path.join(get_base_path(), "replica_backups", "primary", "sync_state.json")
        last_sync = None
        if os.path.exists(sync_state_file):
            import json
            with open(sync_state_file, "r", encoding="utf-8") as sf:
                state_data = json.load(sf)
                last_sync = state_data.get("last_sync_completed_at")

        return {
            "status": "ONLINE_HEALTHY",
            "db_path": db_path,
            "db_size_bytes": os.path.getsize(db_path),
            "patients_count": p_count,
            "results_count": r_count,
            "tests_count": t_count,
            "last_sync_time": last_sync
        }
    except Exception as e:
        return {
            "status": "READ_ERROR",
            "db_path": db_path,
            "db_size_bytes": os.path.getsize(db_path) if os.path.exists(db_path) else 0,
            "error": str(e)
        }
