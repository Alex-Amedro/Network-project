#!/usr/bin/env python3
import socket, struct, time, json, sys

port = int(sys.argv[1])
output = sys.argv[2]
expected = int(sys.argv[3])

results = {"received": 0, "first_time": None, "last_time": None}

sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
sock.bind(("0.0.0.0", port))
sock.listen(1)
sock.settimeout(120)

try:
    conn, _ = sock.accept()
    conn.settimeout(60)
    buffer = b""
    
    while results["received"] < expected:
        try:
            chunk = conn.recv(65536)
            if not chunk: break
            buffer += chunk
            
            while len(buffer) >= 8:
                seq_num, data_len = struct.unpack("!II", buffer[:8])
                total = 8 + data_len
                if len(buffer) < total: break
                
                now = time.time()
                if results["first_time"] is None:
                    results["first_time"] = now
                results["last_time"] = now
                results["received"] += 1
                
                # ACK
                conn.sendall(struct.pack("!I", seq_num))
                buffer = buffer[total:]
                
        except: break
    conn.close()
except Exception as e:
    results["error"] = str(e)

if results["first_time"] and results["last_time"]:
    results["total_time"] = results["last_time"] - results["first_time"]
else:
    results["total_time"] = 0

with open(output, "w") as f:
    json.dump(results, f)
sock.close()
