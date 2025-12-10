#!/usr/bin/env python3
import socket
import struct
import time
import json
import sys

host = sys.argv[1]
port = int(sys.argv[2])
num_frames = int(sys.argv[3])
frame_size = int(sys.argv[4])
fps = int(sys.argv[5])
output = sys.argv[6]

results = {"frames_sent": 0, "blocked_time": 0}

sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.settimeout(30)

try:
    time.sleep(0.5)
    sock.connect((host, port))
    
    start = time.time()
    frame_interval = 1.0 / fps
    
    for i in range(num_frames):
        frame_start = time.time()
        data = bytes([i % 256] * frame_size)
        msg = struct.pack("!I", len(data)) + data
        sock.sendall(msg)
        results["frames_sent"] += 1
        
        # Calcul temps bloqué
        send_time = time.time() - frame_start
        if send_time > frame_interval:
            results["blocked_time"] += send_time - frame_interval
        
        # Respect du FPS
        next_frame = start + (i + 1) * frame_interval
        sleep_time = next_frame - time.time()
        if sleep_time > 0:
            time.sleep(sleep_time)
    
    time.sleep(1)
    results["duration"] = time.time() - start
except Exception as e:
    results["error"] = str(e)
    results["duration"] = 0

with open(output, "w") as f:
    json.dump(results, f)
sock.close()
