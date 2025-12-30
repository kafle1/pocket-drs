#!/usr/bin/env python3
"""Detect the host machine's reachable IP address for mobile devices.

This script attempts to find an IP address that a mobile device on the same
network can use to reach this machine. It outputs the IP to stdout.
"""

import socket
import sys


def get_local_ip() -> str:
    """Get the local IP address that's likely reachable from other devices."""
    
    # Method 1: Connect to external address (doesn't actually send packets)
    # This finds the interface that would be used to reach the internet
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0)
        # Doesn't matter if this IP is reachable - we just need to find
        # which interface would be used to reach it
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        if ip and not ip.startswith('127.'):
            return ip
    except Exception:
        pass
    
    # Method 2: Get hostname and resolve it
    try:
        hostname = socket.gethostname()
        ip = socket.gethostbyname(hostname)
        if ip and not ip.startswith('127.'):
            return ip
    except Exception:
        pass
    
    # Method 3: Scan network interfaces
    try:
        import subprocess
        result = subprocess.run(
            ['ifconfig'],
            capture_output=True,
            text=True,
            timeout=5
        )
        for line in result.stdout.split('\n'):
            if 'inet ' in line and '127.0.0.1' not in line:
                parts = line.strip().split()
                for i, part in enumerate(parts):
                    if part == 'inet' and i + 1 < len(parts):
                        ip = parts[i + 1]
                        # Prefer 192.168.x.x addresses (typical home/office network)
                        if ip.startswith('192.168.'):
                            return ip
    except Exception:
        pass
    
    # Fallback: localhost (won't work for physical devices)
    return 'localhost'


if __name__ == '__main__':
    ip = get_local_ip()
    print(ip)
    sys.exit(0)
