#!/usr/bin/env python3
import socket, struct, time, json, sys

port = int(sys.argv[1])
output = sys.argv[2]
expected = int(sys.argv[3])

results = {"frames_received": 0, "bytes": 0, "latencies": [], "status": "starting"}

def save():
    with open(output, "w") as f:
        json.dump(results, f)

sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
sock.bind(("0.0.0.0", port))
sock.listen(1)
sock.settimeout(60)

results["status"] = "listening"
save()

try:
    conn, addr = sock.accept()
    conn.settimeout(30)
    results["status"] = "connected"
    save()
    
    while results["frames_received"] < expected:
        try:
            header = b""
            while len(header) < 12:
                chunk = conn.recv(12 - len(header))
                if not chunk: break
                header += chunk
            
            if len(header) < 12: break
            
            frame_size, send_ts = struct.unpack("!Id", header)
            
            data = b""
            while len(data) < frame_size:
                chunk = conn.recv(min(65536, frame_size - len(data)))
                if not chunk: break
                data += chunk
            
            if len(data) == frame_size:
                recv_time = time.time()
                results["frames_received"] += 1
                results["bytes"] += frame_size
                results["latencies"].append((recv_time - send_ts) * 1000)
                save()
        except socket.timeout:
            break
        except:
            break
    
    conn.close()
except Exception as e:
    results["error"] = str(e)

results["status"] = "done"
save()
sock.close()
