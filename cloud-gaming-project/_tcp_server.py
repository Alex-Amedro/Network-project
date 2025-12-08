#!/usr/bin/env python3
import socket, struct, time, json, sys

port = int(sys.argv[1])
output = sys.argv[2]

results = {'frames_received': 0, 'latencies': []}

sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
sock.bind(('0.0.0.0', port))
sock.listen(1)
sock.settimeout(60)

try:
    conn, addr = sock.accept()
    conn.settimeout(30)
    
    while True:
        try:
            header = b''
            while len(header) < 12:
                chunk = conn.recv(12 - len(header))
                if not chunk: break
                header += chunk
            
            if len(header) < 12: break
            
            frame_size, send_ts = struct.unpack('!Id', header)
            
            data = b''
            while len(data) < frame_size:
                chunk = conn.recv(min(65536, frame_size - len(data)))
                if not chunk: break
                data += chunk
            
            if len(data) == frame_size:
                results['frames_received'] += 1
                results['latencies'].append((time.time() - send_ts) * 1000)
        except: break
    
    conn.close()
except: pass
sock.close()

with open(output, 'w') as f:
    json.dump(results, f)
