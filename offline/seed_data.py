import os
import sys
import json
from dotenv import load_dotenv
from supabase import create_client

# Add parent directory to path so we can import things if needed
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import init_db, get_db_conn

# Load .env from parent directory
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
dotenv_path = os.path.join(parent_dir, ".env")
if os.path.exists(dotenv_path):
    load_dotenv(dotenv_path)
else:
    load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("Error: Supabase credentials not found in environment!")
    sys.exit(1)

def seed_supabase_data():
    print("Connecting to Supabase...")
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    
    # Tables to fetch and seed
    tables_to_seed = [
        "tests",
        "test_groups",
        "shift",
        "users",
        "remarks",
        "invoice_settings",
        "print_settings"
    ]
    
    # Make sure SQLite db is initialized
    init_db()
    
    with get_db_conn() as conn:
        cursor = conn.cursor()
        
        for table in tables_to_seed:
            print(f"Fetching data for '{table}' from Supabase...")
            try:
                # Query all data from Supabase
                res = supabase.table(table).select("*").execute()
                records = res.data or []
                print(f"Fetched {len(records)} records for '{table}'. Seeding into SQLite...")
                
                if not records:
                    continue
                
                # Delete existing records in local table to avoid conflicts on re-run
                cursor.execute(f"DELETE FROM {table}")
                
                # Get columns of the SQLite table to make sure we match them
                cursor.execute(f"PRAGMA table_info({table})")
                sqlite_cols = [col[1] for col in cursor.fetchall()]
                
                for record in records:
                    # Clean record to only include columns present in SQLite table
                    filtered_record = {}
                    for col in sqlite_cols:
                        if col in record:
                            val = record[col]
                            # Serialize list or dict columns to JSON strings for SQLite
                            if isinstance(val, (list, dict)):
                                val = json.dumps(val)
                            # Convert boolean to integer for SQLite
                            elif isinstance(val, bool):
                                val = 1 if val else 0
                            filtered_record[col] = val
                    
                    columns_str = ", ".join(filtered_record.keys())
                    placeholders = ", ".join(["?"] * len(filtered_record))
                    values = list(filtered_record.values())
                    
                    cursor.execute(
                        f"INSERT OR REPLACE INTO {table} ({columns_str}) VALUES ({placeholders})",
                        values
                    )
                print(f"Successfully seeded '{table}' table.")
                
            except Exception as e:
                print(f"Error seeding table '{table}': {e}")
                
    print("\nAll seeding operations completed.")

if __name__ == "__main__":
    seed_supabase_data()
