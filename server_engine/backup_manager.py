"""
LabFlow Automated PostgreSQL Backup Manager
===========================================
Handles generation of standard PostgreSQL .sql backups using pg_dump,
retention policy management, custom destination directory support,
and automated backup listing / download / restore capabilities.
"""

import os
import sys
import time
import glob
import logging
import subprocess
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Tuple

logger = logging.getLogger("LabFlow.BackupManager")

# Default backup storage directory
DEFAULT_BACKUP_DIR = Path.home() / "labflow_backups"

def get_backup_dir() -> Path:
    """Returns the backup storage directory, creating it if needed."""
    env_dir = os.getenv("LABFLOW_BACKUP_DIR")
    target_dir = Path(env_dir) if env_dir else DEFAULT_BACKUP_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    return target_dir


def create_sql_backup(comment: str = "scheduled") -> Tuple[bool, str, Optional[str]]:
    """
    Executes pg_dump to produce a timestamped standard .sql backup file.
    Returns: (success, message_or_filename, backup_filepath)
    """
    backup_dir = get_backup_dir()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"labflow_backup_{timestamp}.sql"
    filepath = backup_dir / filename

    db_host = os.getenv("LOCAL_DB_HOST", "127.0.0.1")
    db_port = os.getenv("LOCAL_DB_PORT", "5432")
    db_name = os.getenv("LOCAL_DB_NAME", "labflow_db")
    db_user = os.getenv("LOCAL_DB_USER", "postgres")
    db_pass = os.getenv("LOCAL_DB_PASS", "opd_pass")

    env = os.environ.copy()
    env["PGPASSWORD"] = db_pass

    # Command: pg_dump -h <host> -p <port> -U <user> -d <dbname> --clean --if-exists -f <filepath>
    cmd = [
        "pg_dump",
        "-h", db_host,
        "-p", str(db_port),
        "-U", db_user,
        "-d", db_name,
        "--clean",
        "--if-exists",
        "-f", str(filepath)
    ]

    try:
        logger.info(f"Starting pg_dump backup to {filepath}...")
        res = subprocess.run(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if res.returncode == 0 and filepath.is_file() and filepath.stat().st_size > 0:
            size_mb = round(filepath.stat().st_size / (1024 * 1024), 2)
            msg = f"Backup created successfully: {filename} ({size_mb} MB)"
            logger.info(msg)
            cleanup_old_backups(max_keep=30)
            return True, msg, str(filepath)
        else:
            err_msg = res.stderr or "pg_dump produced empty file or non-zero exit code"
            logger.error(f"Backup failed: {err_msg}")
            return False, f"Backup failed: {err_msg}", None
    except FileNotFoundError:
        # If pg_dump binary is not in PATH, fallback to Python-based SQL export
        logger.warning("pg_dump binary not found in PATH. Using fallback Python export.")
        return _fallback_python_sql_export(filepath)
    except Exception as e:
        logger.error(f"Unexpected backup error: {e}")
        return False, str(e), None


def _fallback_python_sql_export(filepath: Path) -> Tuple[bool, str, Optional[str]]:
    """Fallback exporter if pg_dump CLI is not installed on PATH."""
    try:
        from local_postgres_engine import get_connection
        conn = get_connection()
        cursor = conn.cursor()

        tables = ["shift", "users", "tests", "test_groups", "remarks", "invoice_settings", "print_settings", "app_settings", "patients", "test_results_all", "analytics_snapshots"]
        
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(f"-- LabFlow Fallback SQL Backup Dump\n")
            f.write(f"-- Generated: {datetime.now().isoformat()}\n\n")
            
            for tbl in tables:
                cursor.execute(f'SELECT * FROM public."{tbl}";')
                rows = cursor.fetchall()
                col_names = [desc[0] for desc in cursor.description] if cursor.description else []
                
                f.write(f"-- Table: {tbl} ({len(rows)} rows)\n")
                for r in rows:
                    vals = []
                    for v in r:
                        if v is None:
                            vals.append("NULL")
                        elif isinstance(v, (int, float)):
                            vals.append(str(v))
                        elif isinstance(v, bool):
                            vals.append("TRUE" if v else "FALSE")
                        elif isinstance(v, (dict, list)):
                            import json
                            vals.append("'" + json.dumps(v).replace("'", "''") + "'")
                        else:
                            vals.append("'" + str(v).replace("'", "''") + "'")
                    col_str = '", "'.join(col_names)
                    val_str = ", ".join(vals)
                    f.write(f'INSERT INTO public."{tbl}" ("{col_str}") VALUES ({val_str}) ON CONFLICT DO NOTHING;\n')
                f.write("\n")
        
        conn.close()
        size_mb = round(filepath.stat().st_size / (1024 * 1024), 2)
        msg = f"Fallback backup created: {filepath.name} ({size_mb} MB)"
        return True, msg, str(filepath)
    except Exception as e:
        return False, f"Fallback export error: {e}", None


def list_backups() -> List[Dict]:
    """Returns a list of all backup files sorted newest to oldest."""
    backup_dir = get_backup_dir()
    files = sorted(backup_dir.glob("*.sql"), key=lambda f: f.stat().st_mtime, reverse=True)
    
    result = []
    for f in files:
        stat = f.stat()
        result.append({
            "filename": f.name,
            "filepath": str(f),
            "size_bytes": stat.st_size,
            "size_mb": round(stat.st_size / (1024 * 1024), 2),
            "created_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            "created_at_formatted": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        })
    return result


def get_latest_backup() -> Optional[Dict]:
    """Returns details of the latest backup file or None if no backups exist."""
    backups = list_backups()
    return backups[0] if backups else None


def cleanup_old_backups(max_keep: int = 30):
    """Deletes old backups beyond max_keep limit."""
    backups = list_backups()
    if len(backups) > max_keep:
        for b in backups[max_keep:]:
            try:
                os.remove(b["filepath"])
                logger.info(f"Cleaned up old backup: {b['filename']}")
            except Exception as e:
                logger.warning(f"Could not remove old backup {b['filename']}: {e}")
