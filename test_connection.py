#!/usr/bin/env python3
"""
Simple test script to verify PORT AUTHORITY daemon connection
"""

import requests
import json

def test_connection():
    """Test connection to PORT AUTHORITY daemon"""
    daemon_url = "http://127.0.0.1:9999"
    
    try:
        # Test health endpoint
        print(f"🔍 Testing connection to {daemon_url}...")
        response = requests.get(f"{daemon_url}/health", timeout=10)
        
        if response.ok:
            data = response.json()
            print("✅ PORT AUTHORITY is CONNECTED and running!")
            print(f"   Status: {data['status']}")
            print(f"   Version: {data['version']}")
            print(f"   Uptime: {data['uptime']:.0f} seconds")
            print(f"   Active leases: {data['active_leases']}")
            print(f"   Blocked ports: {data['blocked_ports']}")
            print(f"   Guarded ports: {data['guarded_ports']}")
            return True
        else:
            print(f"❌ HTTP Error: {response.status_code}")
            print(f"   Response: {response.text}")
            return False
            
    except requests.exceptions.ConnectionError:
        print("❌ PORT AUTHORITY daemon is NOT running")
        print("   Start it with: python pad.py")
        return False
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

if __name__ == "__main__":
    test_connection()
