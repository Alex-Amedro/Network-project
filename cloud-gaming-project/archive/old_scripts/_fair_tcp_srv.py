#!/usr/bin/env python3
"""TCP Server - 4 streams sur 1 connexion (HoL blocking)"""
import socket, struct, time, json, sys

port = int(sys.argv[1])
output = sys.argv[2]
expected_total = int(sys.argv[3])

results = {
    "frames_received": 0,
    "streams": {0: 0, 1: 0, 2: 0, 3: 0},
    "first_frame_time": None,
    "last_frame_time": None,
    "latencies": [],
    "status": "starting"
}

def save():
    with open(output, "w") as f:
        json.dump(results, f)

sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
sock.bind(("0.0.0.0", port))
sock.listen(1)
sock.settimeout(120)

results["status"] = "listening"
save()

try:
    conn, addr = sock.accept()
    conn.settimeout(60)
    results["status"] = "connected"
    save()
    
    buffer = b""
    
    while results["frames_received"] < expected_total:
        try:
            chunk = conn.recv(65536)
            if not chunk:
                break
            buffer += chunk
            
            # Header: stream_id (1) + frame_id (4) + timestamp (8) + size (4) = 17 bytes
            while len(buffer) >= 17:
                stream_id = buffer[0]
                frame_id, send_ts, frame_size = struct.unpack("!IdI", buffer[1:17])
                total_needed = 17 + frame_size
                
                if len(buffer) >= total_needed:
                    recv_time = time.time()
                    
                    if results["first_frame_time"] is None:
                        results["first_frame_time"] = recv_time
                    results["last_frame_time"] = recv_time
                    
                    results["frames_received"] += 1
                    results["streams"][stream_id] = results["streams"].get(stream_id, 0) + 1
                    results["latencies"].append((recv_time - send_ts) * 1000)
                    
                    buffer = buffer[total_needed:]
                    save()
                else:
                    break
                    
        except socket.timeout:
            break
        except Exception as e:
            results["error"] = str(e)
            break
    
    conn.close()
except Exception as e:
    results["error"] = str(e)

results["status"] = "done"
if results["first_frame_time"] and results["last_frame_time"]:
    results["total_time"] = results["last_frame_time"] - results["first_frame_time"]
save()
sock.close()
