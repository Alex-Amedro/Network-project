#!/usr/bin/env python3
import socket, struct, time, json, sys, random

host = sys.argv[1]
port = int(sys.argv[2])
num_frames = int(sys.argv[3])
fps = int(sys.argv[4])
output = sys.argv[5]

results = {"sent": 0, "acked": 0, "blocked_time": 0, "retrans": 0}

def gen_frame(n):
    size = random.randint(100000, 150000) if n % 30 == 0 else random.randint(20000, 60000)
    return b"X" * size

sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
sock.settimeout(10)

try:
    time.sleep(0.5)
    sock.connect((host, port))
    start = time.time()
    
    for i in range(num_frames):
        data = gen_frame(i)
        header = struct.pack("!II", i, len(data))
        
        send_time = time.time()
        sock.sendall(header + data)
        results["sent"] += 1
        
        # Attend ACK (BLOQUANT = HoL blocking simulé)
        try:
            ack = sock.recv(4)
            if len(ack) == 4:
                results["acked"] += 1
                blocked = time.time() - send_time
                if blocked > 0.05:
                    results["blocked_time"] += blocked
        except socket.timeout:
            results["retrans"] += 1
        
        # FPS timing
        expected_time = start + (i + 1) / fps
        sleep_time = expected_time - time.time()
        if sleep_time > 0:
            time.sleep(sleep_time)
    
    results["duration"] = time.time() - start
    
except Exception as e:
    results["error"] = str(e)
    results["duration"] = 0

with open(output, "w") as f:
    json.dump(results, f)
sock.close()
