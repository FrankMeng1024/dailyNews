#!/usr/bin/env python3
"""
Start server with Cloudflare Tunnel and QR code for mobile testing
"""
import subprocess
import sys
import time
import re
import os

def print_qr_terminal(url):
    """Print QR code in terminal using ASCII"""
    try:
        import qrcode
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=1,
            border=1,
        )
        qr.add_data(url)
        qr.make(fit=True)

        # Print QR code using ASCII blocks
        matrix = qr.get_matrix()
        print()
        for row in matrix:
            line = "  "
            for cell in row:
                line += "██" if cell else "  "
            print(line)
        print()
    except Exception as e:
        print(f"Could not generate QR code: {e}")
        print(f"URL: {url}")

def get_cloudflare_url(process, timeout=15):
    """Wait for cloudflared to output the tunnel URL"""
    import select
    start_time = time.time()
    output = ""

    while time.time() - start_time < timeout:
        # Read available output
        try:
            line = process.stderr.readline()
            if line:
                line = line.decode('utf-8', errors='ignore')
                output += line
                # Look for the tunnel URL
                match = re.search(r'https://[a-z0-9-]+\.trycloudflare\.com', line)
                if match:
                    return match.group(0)
        except:
            pass
        time.sleep(0.1)

    return None

def main():
    print("=" * 50)
    print("   AI News App - Starting Server")
    print("=" * 50)
    print()

    # Start uvicorn
    print("Starting backend server...")
    server_process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT
    )

    # Wait for server to start
    time.sleep(2)

    # Check if server is running
    if server_process.poll() is not None:
        print("Server failed to start!")
        return

    print("Server started on port 8000")
    print()

    # Start Cloudflare Tunnel
    print("Starting Cloudflare Tunnel...")
    tunnel_process = subprocess.Popen(
        ["cloudflared", "tunnel", "--url", "http://localhost:8000"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )

    # Wait for tunnel URL
    tunnel_url = get_cloudflare_url(tunnel_process)

    if not tunnel_url:
        print("Could not get Cloudflare tunnel URL")
        print("Falling back to local access only")
        tunnel_url = "http://localhost:8000"

    print()
    print("=" * 50)
    print("   Server Started Successfully!")
    print("=" * 50)
    print()
    print(f"  Local:   http://localhost:8000")
    print(f"  Tunnel:  {tunnel_url}")
    print(f"  Docs:    {tunnel_url}/docs")
    print()
    print("-" * 50)
    print("  Scan QR code with WeChat to preview:")
    print("-" * 50)
    print_qr_terminal(tunnel_url)
    print("-" * 50)
    print("  Press Ctrl+C to stop")
    print("-" * 50)
    print()

    try:
        # Keep running
        while True:
            time.sleep(1)
            # Check if processes are still running
            if server_process.poll() is not None:
                print("Server stopped unexpectedly")
                break
            if tunnel_process.poll() is not None:
                print("Tunnel stopped unexpectedly")
                break
    except KeyboardInterrupt:
        print("\n\nShutting down...")
    finally:
        server_process.terminate()
        tunnel_process.terminate()

if __name__ == "__main__":
    main()
