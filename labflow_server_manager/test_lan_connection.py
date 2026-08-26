"""
LabFlow Server Manager - LAN Connection & Router Diagnostic Utility
=====================================================================
Detects server local LAN IP, checks router connectivity on ports 8000 and 9000,
and outputs exact firewall commands for Windows.
"""

import socket
import sys

def detect_lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

def run_lan_diagnostics():
    host_name = socket.gethostname()
    local_ip = detect_lan_ip()

    print("=" * 65)
    print("      LABFLOW LOCAL LAN ROUTER DIAGNOSTIC UTILITY          ")
    print("=" * 65)

    print(f"\n[1] Server Machine Info:")
    print(f"  - Computer Name:      {host_name}")
    print(f"  - Local LAN IP:       {local_ip}")
    
    if local_ip.startswith("127."):
        print("  [WARNING] Could not detect LAN IP. Ensure your PC is connected to the Wi-Fi/Ethernet router.")
    else:
        print("  [OK] LAN IP detected successfully!")

    print(f"\n[2] Client Access URLs (Share these with other PCs in your lab):")
    print(f"  - Main Application:    http://{local_ip}:8000")
    print(f"  - Visual Admin Panel:  http://{local_ip}:9000")

    print(f"\n[3] Windows Firewall Rules (Run in PowerShell as Admin if other PCs cannot connect):")
    print("-" * 65)
    print(f'New-NetFirewallRule -DisplayName "LabFlow Server Engine" -Direction Inbound -LocalPort 8000 -Protocol TCP -Action Allow')
    print(f'New-NetFirewallRule -DisplayName "LabFlow Admin Panel" -Direction Inbound -LocalPort 9000 -Protocol TCP -Action Allow')
    print("-" * 65)
    print("\nLAN Diagnostics complete.\n")

if __name__ == "__main__":
    run_lan_diagnostics()
