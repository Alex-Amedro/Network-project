#!/usr/bin/env python3
import socket
import struct
import json
import sys
import time

port = int(sys.argv[1])
output = sys.argv[2]

results = {"frames_received": 0, "first_time": None, "last_time": None}

def save():
    with open(output, "w") as f:
        json.dump(results, f)

sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
sock.bind(("0.0.0.0", port))
sock.listen(1)
sock.settimeout(60)

try:
    conn, _ = sock.accept()
    conn.settimeout(30)
    buffer = b""
    
    while True:
        try:
            chunk = conn.recv(65536)
            if not chunk:
                break
            buffer += chunk
            
            while len(buffer) >= 4:
                frame_size = struct.unpack("!I", buffer[:4])[0]
                total = 4 + frame_size
                
                if len(buffer) >= total:
                    now = time.time()
                    if results["first_time"] is None:
                        results["first_time"] = now
                    results["last_time"] = now
                    results["frames_received"] += 1
                    buffer = buffer[total:]
                    save()
                else:
                    break
        except:
            break
    conn.close()
except:
    pass

if results["first_time"] and results["last_time"]:
    results["total_time"] = results["last_time"] - results["first_time"]
else:
    results["total_time"] = 0
save()
sock.close()
