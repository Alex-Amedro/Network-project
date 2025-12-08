#!/usr/bin/env python3
import socket, struct, time, json, sys

port, output, expected = int(sys.argv[1]), sys.argv[2], int(sys.argv[3])
results = {"received": 0, "first_time": None, "last_time": None}

sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
sock.bind(("0.0.0.0", port))
sock.listen(1)
sock.settimeout(60)

try:
    conn, _ = sock.accept()
    conn.settimeout(30)
    buffer = b""
    
    while results["received"] < expected:
        chunk = conn.recv(65536)
        if not chunk: break
        buffer += chunk
        
        while len(buffer) >= 8:
            seq, size = struct.unpack("!II", buffer[:8])
            if len(buffer) < 8 + size: break
            
            now = time.time()
            if not results["first_time"]: results["first_time"] = now
            results["last_time"] = now
            results["received"] += 1
            conn.sendall(struct.pack("!I", seq))
            buffer = buffer[8+size:]
    conn.close()
except: pass

results["total_time"] = (results["last_time"] - results["first_time"]) if results["first_time"] else 0
json.dump(results, open(output, "w"))
sock.close()
