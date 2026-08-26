"""
LabFlow Offline Local Server Engine - Configuration
====================================================
Configuration settings for local PostgreSQL database and server host parameters.
"""

import os
import sys
from dotenv import load_dotenv

def get_base_dir() -> str:
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

def load_config():
    # Load .env from root or server_engine directory
    root_env = os.path.join(os.path.dirname(get_base_dir()), ".env")
    local_env = os.path.join(get_base_dir(), ".env")
    
    if os.path.exists(root_env):
        load_dotenv(root_env, override=True)
    if os.path.exists(local_env):
        load_dotenv(local_env, override=True)

    return {
        "HOST": os.getenv("SERVER_HOST", "0.0.0.0"),
        "PORT": int(os.getenv("SERVER_PORT", "8000")),
        "DB_HOST": os.getenv("LOCAL_DB_HOST", "127.0.0.1"),
        "DB_PORT": int(os.getenv("LOCAL_DB_PORT", "5432")),
        "DB_NAME": os.getenv("LOCAL_DB_NAME", "labflow_db"),
        "DB_USER": os.getenv("LOCAL_DB_USER", "postgres"),
        "DB_PASS": os.getenv("LOCAL_DB_PASS", "postgres"),
    }

if __name__ == "__main__":
    cfg = load_config()
    print("Local Server Configuration:")
    for k, v in cfg.items():
        if "PASS" in k:
            print(f"  {k}: ********")
        else:
            print(f"  {k}: {v}")
