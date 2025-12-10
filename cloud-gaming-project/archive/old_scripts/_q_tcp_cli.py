#!/usr/bin/env python3
import socket, struct, time, json, sys, random

host, port, num, fps, output = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4]), sys.argv[5]
results = {"sent": 0, "blocked_time": 0}

sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
sock.settimeout(5)

try:
    time.sleep(0.3)
    sock.connect((host, port))
    start = time.time()
    
    for i in range(num):
        size = random.randint(10000, 30000)
        data = b"X" * size
        
        t1 = time.time()
        sock.sendall(struct.pack("!II", i, size) + data)
        results["sent"] += 1
        
        try:
            sock.recv(4)
            if time.time() - t1 > 0.05: results["blocked_time"] += time.time() - t1
        except: pass
        
        wait = start + (i+1)/fps - time.time()
        if wait > 0: time.sleep(wait)
    
    results["duration"] = time.time() - start
except Exception as e:
    results["error"] = str(e)
    results["duration"] = 0

json.dump(results, open(output, "w"))
sock.close()
