import logging
import os
import sys
import platform
import getpass
from logging.handlers import RotatingFileHandler
from datetime import datetime

def get_app_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

def get_pc_info():
    """Returns basic PC and user information."""
    return {
        "pc_name": platform.node(),
        "user": getpass.getuser(),
        "os": f"{platform.system()} {platform.release()}",
        "architecture": platform.machine()
    }

def get_terminal_name():
    try:
        return f"{platform.node()} ({getpass.getuser()})"
    except Exception:
        return "Lab-Terminal"

# Define log paths
app_dir = get_app_dir()
local_logs_dir = os.path.join(app_dir, "logs")
d_drive_logs_dir = "D:\\LabFlow_System_Logs"
c_drive_logs_dir = "C:\\LabFlow_System_Logs"
d_drive_legacy_path = "D:\\labflowlog" # User requested specific name

pc_info = get_pc_info()
pc_info_str = f"PC: {pc_info['pc_name']} | User: {pc_info['user']} | OS: {pc_info['os']}"

# Ensure directories exist
for path in [local_logs_dir, d_drive_logs_dir, c_drive_logs_dir, d_drive_legacy_path]:
    try:
        if path.startswith("D:") and not os.path.exists("D:\\"):
            continue 
        if not os.path.exists(path):
            os.makedirs(path)
    except Exception:
        pass 

# Configure logging
logger = logging.getLogger("LabFlow")
logger.setLevel(logging.DEBUG)

formatter = logging.Formatter('%(asctime)s - %(levelname)s - [%(name)s] - %(message)s')

# Local File Handler
try:
    local_handler = RotatingFileHandler(
        os.path.join(local_logs_dir, "app_local.log"), 
        maxBytes=10*1024*1024, 
        backupCount=50
    )
    local_handler.setFormatter(formatter)
    logger.addHandler(local_handler)
except Exception as e:
    print(f"Failed to setup local logging: {e}")

# D Drive File Handler (Modern path)
if os.path.exists("D:\\"):
    try:
        d_handler = RotatingFileHandler(
            os.path.join(d_drive_logs_dir, "app_backup.log"),
            maxBytes=20*1024*1024,
            backupCount=50
        )
        d_handler.setFormatter(formatter)
        logger.addHandler(d_handler)
        
        # Also copy to specific legacy path requested by user
        legacy_handler = RotatingFileHandler(
            os.path.join(d_drive_legacy_path, "labflow_dump.log"),
            maxBytes=5*1024*1024,
            backupCount=20
        )
        legacy_handler.setFormatter(formatter)
        logger.addHandler(legacy_handler)
        
    except Exception as e:
        print(f"Failed to setup D drive logging: {e}")

# Console Handler — disabled when frozen (PyInstaller exe) so no CMD window noise
if not getattr(sys, "frozen", False):
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

def save_log(data, category="General", user="System"):
    """
    Saves a log entry. The 'user' parameter allows tracking who performed the action.
    """
    logger.info(f"[USER: {user}] [{category}] [PC_INFO: {pc_info_str}] {data}")

def log_error(error, category="Error", user="System", exc_info=True):
    """
    Logs an error with the active user context.
    """
    logger.error(f"[USER: {user}] [{category}] [PC_INFO: {pc_info_str}] {str(error)}", exc_info=exc_info)

import re

def parse_log_line(line):
    """
    Updated parser to handle USER field.
    Format: timestamp - level - [name] - [USER: user] [category] [PC_INFO: info] message
    """
    pattern = r'^(?P<timestamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}) - (?P<level>\w+) - \[(?P<source>[^\]]+)\] - (?P<content>.*)$'
    match = re.match(pattern, line)
    
    if not match:
        return {"raw": line, "level": "UNKNOWN", "timestamp": "Unknown"}
    
    data = match.groupdict()
    content = data['content']
    
    # Extract User, Category, and PC Info
    user_match = re.search(r'\[USER: (?P<user>[^\]]+)\]', content)
    category_match = re.search(r'\[(?P<category>[^\]]+)\]', content.replace(user_match.group(0) if user_match else "", "", 1))
    pc_info_match = re.search(r'\[PC_INFO: (?P<pc_info>[^\]]+)\]', content)
    
    data['user'] = user_match.group('user') if user_match else "System"
    data['category'] = category_match.group('category') if category_match else "General"
    data['pc_info'] = pc_info_match.group('pc_info') if pc_info_match else "Unknown"
    
    # Extract Message
    clean_msg = content
    if user_match: clean_msg = clean_msg.replace(user_match.group(0), "").strip()
    if category_match: clean_msg = clean_msg.replace(f"[{data['category']}]", "").strip()
    if pc_info_match: clean_msg = clean_msg.replace(f"[PC_INFO: {data['pc_info']}]", "").strip()
    
    data['message'] = clean_msg
    # Add date for filtering
    data['date'] = data['timestamp'].split(" ")[0]
    return data

def get_all_logs(level_filter=None, category_filter=None, date_filter=None):
    """Reads logs and returns structured data with optional date filtering."""
    log_file_path = os.path.join(local_logs_dir, "app_local.log")
    if not os.path.exists(log_file_path):
        return []
    
    structured_logs = []
    try:
        with open(log_file_path, "r") as f:
            lines = f.readlines()
            for line in lines[-2000:]: # History depth
                if not line.strip(): continue
                parsed = parse_log_line(line.strip())
                
                # Apply filters
                if level_filter and parsed.get('level') != level_filter: continue
                if category_filter and parsed.get('category') != category_filter: continue
                if date_filter and parsed.get('date') != date_filter: continue
                
                structured_logs.append(parsed)
    except Exception as e:
        logger.error(f"Error structured reading log file: {e}")
    
    return structured_logs[::-1]


def get_system_stats():
    """Returns aggregated stats from logs."""
    logs = get_all_logs()
    stats = {
        "total": len(logs),
        "errors": len([l for l in logs if l.get('level') == 'ERROR']),
        "warnings": len([l for l in logs if l.get('level') == 'WARNING']),
        "info": len([l for l in logs if l.get('level') == 'INFO']),
        "unique_pcs": len(set([l.get('pc_info') for l in logs if l.get('pc_info') != 'Unknown'])),
        "categories": {}
    }
    for l in logs:
        cat = l.get('category', 'General')
        stats['categories'][cat] = stats['categories'].get(cat, 0) + 1
    return stats


def insert_audit_log(mr_no=None, action="GENERAL", user="System", details="", ip_address=None):
    """
    Saves an audit trail entry.
    """
    try:
        msg = f"MR: {mr_no} | Action: {action} | Details: {details}" if mr_no else f"Action: {action} | Details: {details}"
        save_log(msg, category="AUDIT", user=user)
        return 1
    except Exception as e:
        logger.error(f"Error inserting audit log: {e}")
        return 0


def list_audit_trail(mr_no=None, search=None, user_name=None, action=None, date_from=None, date_to=None, limit=200, **kwargs):
    """
    Retrieves audit trail entries filtered by MR, search, user_name, or action.
    """
    try:
        logs = get_all_logs(category_filter="AUDIT")
        filtered = []
        for l in logs:
            msg = l.get("message", "")
            usr = l.get("user", "")
            dt = l.get("date", "")
            
            if mr_no and str(mr_no) not in msg:
                continue
            if user_name and str(user_name).lower() not in usr.lower():
                continue
            if search and str(search).lower() not in msg.lower() and str(search).lower() not in usr.lower():
                continue
            if action and action.lower() not in msg.lower():
                continue
            if date_from and dt and dt < str(date_from):
                continue
            if date_to and dt and dt > str(date_to):
                continue

            display_name = usr
            if usr in ["admin@admin.com", "admin@labflow.local", "System"] or not usr:
                display_name = "Rehan Ahmed"

            filtered.append({
                "timestamp": l.get("timestamp"),
                "date": dt,
                "user": usr,
                "user_name": display_name,
                "actor": display_name,
                "action": l.get("category"),
                "pc_info": l.get("pc_info"),
                "details": msg,
                "message": msg
            })
            if len(filtered) >= limit:
                break
        return filtered
    except Exception as e:
        logger.error(f"Error listing audit trail: {e}")
        return []

