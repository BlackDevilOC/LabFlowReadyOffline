"""
LabFlow - Supabase Continuous Replica Background Worker (CLI)
=============================================================
Runs the replication engine in standalone daemon mode or as a one-shot task.

Usage:
  python replica_worker.py                    # Run continuous background worker (default 20s interval)
  python replica_worker.py --interval 15      # Custom 15-second polling interval
  python replica_worker.py --once             # Perform a single sync and exit
  python replica_worker.py --full             # Perform a full snapshot sync and exit
  python replica_worker.py --status           # Show current status and disk locations
"""

import sys
import time
import signal
import argparse
from datetime import datetime
from replica_engine import SupabaseReplicaEngine, get_replica_engine, logger


def format_size(bytes_val: int) -> str:
    for unit in ['B', 'KB', 'MB', 'GB']:
        if bytes_val < 1024.0:
            return f"{bytes_val:.1f} {unit}"
        bytes_val /= 1024.0
    return f"{bytes_val:.1f} TB"


def print_status(engine: SupabaseReplicaEngine):
    status = engine.get_status()
    print("\n=======================================================")
    print("      LABFLOW SUPABASE REPLICA & DR STATUS             ")
    print("=======================================================")
    print(f"Worker Running:       {'YES' if status['is_running'] else 'NO'}")
    print(f"Last Sync Time:       {status['last_sync_time'] or 'Never'}")
    print(f"Last Sync Type:       {status['last_sync_type'].upper()}")
    print(f"Last Duration:        {status['last_sync_duration_ms']} ms")
    print(f"Total Sync Cycles:    {status['total_sync_cycles']}")
    print(f"Consecutive Errors:   {status['consecutive_errors']}")
    if status['last_error']:
        print(f"Last Error:           {status['last_error']}")
    print("\n--- REPLICA STORAGE LOCATIONS ---")
    locs = status["locations"]
    for name, info in locs.items():
        loc_label = "Location 1 (Primary)" if name == "location_1" else "Location 2 (Secondary)"
        exists_str = "ACTIVE" if info["exists"] else "NOT FOUND / UNREACHABLE"
        free_str = f"{info['free_mb']} MB free" if info['free_mb'] is not None else "Unknown"
        db_size_str = format_size(info['db_size_bytes'])
        print(f"• {loc_label}:")
        print(f"    Path:    {info['path']}")
        print(f"    Status:  {exists_str} ({free_str})")
        print(f"    DB Size: {db_size_str}")

    print("\n--- REPLICATED TABLES ---")
    print(f"{'Table Name':<22} | {'Rows':<8} | {'Last Delta / Updated':<25} | {'Status':<10}")
    print("-" * 72)
    for tbl, info in status["tables"].items():
        rows = info.get("row_count", 0)
        last_up = info.get("last_updated_at") or info.get("last_created_at") or "Initial"
        tbl_status = info.get("status", "unknown")
        print(f"{tbl:<22} | {rows:<8} | {str(last_up):<25} | {tbl_status:<10}")
    print("=======================================================\n")


def main():
    parser = argparse.ArgumentParser(description="LabFlow Supabase Continuous Replica Background Worker")
    parser.add_argument("--interval", type=int, default=20, help="Polling interval in seconds (default: 20)")
    parser.add_argument("--reconcile", type=int, default=900, help="Full reconciliation interval in seconds (default: 900)")
    parser.add_argument("--once", action="store_true", help="Run once and exit")
    parser.add_argument("--full", action="store_true", help="Force a full snapshot sync")
    parser.add_argument("--status", action="store_true", help="Show current status and exit")
    parser.add_argument("--loc1", type=str, default=None, help="Custom Location 1 directory path")
    parser.add_argument("--loc2", type=str, default=None, help="Custom Location 2 directory path")

    args = parser.parse_args()

    engine = SupabaseReplicaEngine(
        location_1=args.loc1,
        location_2=args.loc2,
        poll_interval=args.interval,
        full_reconcile_interval=args.reconcile
    )

    if args.status:
        print_status(engine)
        return

    if args.once or args.full:
        print(f"Starting single {'FULL' if args.full else 'DELTA'} replication cycle...")
        result = engine.perform_sync(force_full=args.full)
        print_status(engine)
        if result.get("status") == "success":
            print(f"[OK] Replication completed successfully in {result.get('duration_ms')}ms.")
            sys.exit(0)
        else:
            print(f"[FAILED] Replication failed: {result.get('error')}")
            sys.exit(1)

    # Continuous Daemon Mode
    print("\n=======================================================")
    print("  LABFLOW CONTINUOUS SUPABASE REPLICA WORKER STARTED   ")
    print("=======================================================")
    print(f"Polling Interval:        Every {args.interval} seconds")
    print(f"Full Reconcile Interval: Every {args.reconcile} seconds")
    print(f"Location 1:              {engine.location_1}")
    print(f"Location 2:              {engine.location_2}")
    print("Press Ctrl+C to stop.\n")

    def handle_sigint(sig, frame):
        print("\nStopping background replica worker...")
        engine.stop_background_worker()
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_sigint)
    signal.signal(signal.SIGTERM, handle_sigint)

    engine.start_background_worker()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        handle_sigint(None, None)


if __name__ == "__main__":
    main()
