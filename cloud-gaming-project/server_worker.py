#!/usr/bin/env python3
import socket
import struct
import time
import json
import sys

protocol = sys.argv[1]  # tcp, udp, rquic
port = int(sys.argv[2])
output_file = sys.argv[3]
duration = int(sys.argv[4])

results = {
    'protocol': protocol,
    'frames_received': 0,
    'bytes_received': 0,
    'frame_times': []
}

start_time = None
end_time = None

if protocol == 'tcp':
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(('0.0.0.0', port))
    sock.listen(1)
    sock.settimeout(duration + 10)
    
    try:
        conn, addr = sock.accept()
        conn.settimeout(5)
        start_time = time.time()
        
        while time.time() - start_time < duration + 5:
            try:
                # Lire taille (4 bytes)
                size_data = b''
                while len(size_data) < 4:
                    chunk = conn.recv(4 - len(size_data))
                    if not chunk:
                        break
                    size_data += chunk
                
                if len(size_data) < 4:
                    break
                
                frame_size = struct.unpack('!I', size_data)[0]
                
                # Lire frame
                frame_data = b''
                while len(frame_data) < frame_size:
                    chunk = conn.recv(min(65536, frame_size - len(frame_data)))
                    if not chunk:
                        break
                    frame_data += chunk
                
                if len(frame_data) == frame_size:
                    results['frames_received'] += 1
                    results['bytes_received'] += frame_size
                    results['frame_times'].append(time.time())
                    
            except socket.timeout:
                continue
            except:
                break
        
        conn.close()
    except:
        pass
    finally:
        sock.close()

elif protocol == 'udp':
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(('0.0.0.0', port))
    sock.settimeout(2)
    
    while True:
        try:
            data, addr = sock.recvfrom(65536)
            if start_time is None:
                start_time = time.time()
            
            results['frames_received'] += 1
            results['bytes_received'] += len(data)
            results['frame_times'].append(time.time())
            
        except socket.timeout:
            if start_time and time.time() - start_time > duration + 5:
                break

    sock.close()

elif protocol == 'rquic':
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(('0.0.0.0', port))
    sock.settimeout(2)
    
    received_seqs = set()
    
    while True:
        try:
            data, addr = sock.recvfrom(65536)
            if start_time is None:
                start_time = time.time()
            
            if len(data) >= 4:
                seq_num = struct.unpack('!I', data[:4])[0]
                
                # Envoyer ACK
                ack = struct.pack('!I', seq_num)
                sock.sendto(ack, addr)
                
                if seq_num not in received_seqs:
                    received_seqs.add(seq_num)
                    results['frames_received'] += 1
                    results['bytes_received'] += len(data)
                    results['frame_times'].append(time.time())
                    
        except socket.timeout:
            if start_time and time.time() - start_time > duration + 5:
                break

    sock.close()

end_time = time.time()

# Calculer métriques
if start_time and results['frame_times']:
    results['duration'] = end_time - start_time
    results['fps'] = results['frames_received'] / results['duration'] if results['duration'] > 0 else 0
    
    # Latence inter-frame
    if len(results['frame_times']) > 1:
        delays = [results['frame_times'][i] - results['frame_times'][i-1] 
                  for i in range(1, len(results['frame_times']))]
        results['avg_delay_ms'] = sum(delays) / len(delays) * 1000
    
    # Supprimer les timestamps pour économiser de l'espace
    results['frame_times'] = len(results['frame_times'])

with open(output_file, 'w') as f:
    json.dump(results, f, indent=2)

print(f"Serveur {protocol}: {results['frames_received']} frames reçues")
