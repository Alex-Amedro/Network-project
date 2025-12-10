#!/usr/bin/env python3
import socket, struct, time, json, sys

host = sys.argv[1]
port = int(sys.argv[2])
num_frames = int(sys.argv[3])
frame_size = int(sys.argv[4])
fps = int(sys.argv[5])
output = sys.argv[6]

results = {'frames_sent': 0}

time.sleep(0.5)
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.settimeout(60)
sock.connect((host, port))

start = time.time()

for i in range(num_frames):
    send_time = time.time()
    data = bytes([i % 256] * frame_size)
    sock.sendall(struct.pack('!Id', len(data), send_time) + data)
    results['frames_sent'] += 1
    
    expected = start + (i + 1) / fps
    sleep = expected - time.time()
    if sleep > 0: time.sleep(sleep)

time.sleep(1)
sock.close()

with open(output, 'w') as f:
    json.dump(results, f)
