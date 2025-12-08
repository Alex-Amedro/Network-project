#!/usr/bin/env python3
"""TCP Client - 4 streams multiplexés sur 1 connexion"""
import socket, struct, time, json, sys

host = sys.argv[1]
port = int(sys.argv[2])
num_frames = int(sys.argv[3])
frame_size = int(sys.argv[4])
num_streams = int(sys.argv[5])
output = sys.argv[6]

results = {"frames_sent": 0, "start_time": None, "end_time": None, "status": "starting"}

def save():
    with open(output, "w") as f:
        json.dump(results, f)

time.sleep(0.5)

sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
sock.settimeout(60)

try:
    sock.connect((host, port))
    results["status"] = "connected"
    results["start_time"] = time.time()
    save()
    
    # Envoyer les frames de chaque stream en round-robin
    for frame_id in range(num_frames):
        for stream_id in range(num_streams):
            send_time = time.time()
            data = bytes([frame_id % 256] * frame_size)
            
            # Header: stream_id (1) + frame_id (4) + timestamp (8) + size (4)
            header = bytes([stream_id]) + struct.pack("!IdI", frame_id, send_time, len(data))
            sock.sendall(header + data)
            results["frames_sent"] += 1
        
        # Petit délai pour simuler 60 FPS
        time.sleep(0.001)
    
    results["end_time"] = time.time()
    time.sleep(2)  # Attendre que tout arrive
    results["status"] = "done"
    
except Exception as e:
    results["error"] = str(e)
    results["status"] = "error"

save()
sock.close()
