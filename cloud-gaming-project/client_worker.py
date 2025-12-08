#!/usr/bin/env python3
import socket
import struct
import time
import json
import sys

protocol = sys.argv[1]
host = sys.argv[2]
port = int(sys.argv[3])
num_frames = int(sys.argv[4])
fps = int(sys.argv[5])
output_file = sys.argv[6]
frame_size = int(sys.argv[7])

results = {
    'protocol': protocol,
    'frames_sent': 0,
    'retransmissions': 0,
    'acks_received': 0
}

time.sleep(1)  # Attendre le serveur

if protocol == 'tcp':
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(30)
    sock.connect((host, port))
    
    start_time = time.time()
    for i in range(num_frames):
        frame_data = bytes([i % 256] * frame_size)
        sock.sendall(struct.pack('!I', len(frame_data)))
        sock.sendall(frame_data)
        results['frames_sent'] += 1
        
        expected = start_time + (i + 1) / fps
        sleep_time = expected - time.time()
        if sleep_time > 0:
            time.sleep(sleep_time)
    
    sock.close()

elif protocol == 'udp':
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    
    start_time = time.time()
    for i in range(num_frames):
        frame_data = bytes([i % 256] * min(frame_size, 60000))
        sock.sendto(frame_data, (host, port))
        results['frames_sent'] += 1
        
        expected = start_time + (i + 1) / fps
        sleep_time = expected - time.time()
        if sleep_time > 0:
            time.sleep(sleep_time)
    
    sock.close()

elif protocol == 'rquic':
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(0.1)
    
    start_time = time.time()
    for seq in range(num_frames):
        frame_data = struct.pack('!I', seq) + bytes([seq % 256] * min(frame_size - 4, 60000))
        
        acked = False
        for attempt in range(4):  # 1 envoi + 3 retries
            sock.sendto(frame_data, (host, port))
            
            if attempt == 0:
                results['frames_sent'] += 1
            else:
                results['retransmissions'] += 1
            
            try:
                ack_data, _ = sock.recvfrom(1024)
                if len(ack_data) >= 4:
                    ack_seq = struct.unpack('!I', ack_data[:4])[0]
                    if ack_seq == seq:
                        results['acks_received'] += 1
                        acked = True
                        break
            except socket.timeout:
                continue
        
        expected = start_time + (seq + 1) / fps
        sleep_time = expected - time.time()
        if sleep_time > 0:
            time.sleep(sleep_time)
    
    sock.close()
    results['delivery_rate'] = results['acks_received'] / num_frames * 100 if num_frames > 0 else 0

with open(output_file, 'w') as f:
    json.dump(results, f, indent=2)

print(f"Client {protocol}: {results['frames_sent']} frames envoyées", end='')
if protocol == 'rquic':
    print(f", {results['retransmissions']} retrans, {results['acks_received']} ACKs")
else:
    print()
