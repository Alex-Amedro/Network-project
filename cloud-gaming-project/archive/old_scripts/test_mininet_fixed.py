#!/usr/bin/env python3
"""
Test COMPLET avec Mininet - TCP vs UDP vs rQUIC
Avec conditions réseau réalistes (perte, délai)
"""

import subprocess
import time
import os
import sys
import json
import socket
import threading
import struct
import signal

# Vérifier qu'on est root
if os.geteuid() != 0:
    print("❌ Ce script doit être exécuté avec sudo!")
    print("   sudo venv/bin/python3 test_mininet_fixed.py")
    sys.exit(1)

from mininet.net import Mininet
from mininet.node import OVSSwitch
from mininet.link import TCLink
from mininet.log import setLogLevel

WORK_DIR = os.path.dirname(os.path.abspath(__file__))

# Paramètres
TEST_DURATION = 10
FPS = 60
FRAME_SIZE = 50000
TOTAL_FRAMES = TEST_DURATION * FPS

# Scénarios réseau
SCENARIOS = {
    'bon': {'loss': 1, 'delay': '10ms', 'bw': 100},
    'moyen': {'loss': 3, 'delay': '25ms', 'bw': 50},
    'mauvais': {'loss': 8, 'delay': '60ms', 'bw': 20},
}


def create_server_script():
    """Crée le script serveur"""
    script = '''#!/usr/bin/env python3
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
'''
    
    path = os.path.join(WORK_DIR, 'server_worker.py')
    with open(path, 'w') as f:
        f.write(script)
    os.chmod(path, 0o755)
    return path


def create_client_script():
    """Crée le script client"""
    script = '''#!/usr/bin/env python3
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
'''
    
    path = os.path.join(WORK_DIR, 'client_worker.py')
    with open(path, 'w') as f:
        f.write(script)
    os.chmod(path, 0o755)
    return path


def run_protocol_test(net, h1, h2, protocol, port, scenario_name):
    """Exécute un test pour un protocole"""
    print(f"\n  🧪 Test {protocol.upper()}...")
    
    server_script = os.path.join(WORK_DIR, 'server_worker.py')
    client_script = os.path.join(WORK_DIR, 'client_worker.py')
    
    server_output = os.path.join(WORK_DIR, f'results_{scenario_name}_{protocol}_server.json')
    client_output = os.path.join(WORK_DIR, f'results_{scenario_name}_{protocol}_client.json')
    
    # Supprimer anciens résultats
    for f in [server_output, client_output]:
        if os.path.exists(f):
            os.remove(f)
    
    # Lancer serveur sur h2
    server_cmd = f'python3 {server_script} {protocol} {port} {server_output} {TEST_DURATION} &'
    h2.cmd(server_cmd)
    time.sleep(0.5)
    
    # Lancer client sur h1
    h2_ip = h2.IP()
    client_cmd = f'python3 {client_script} {protocol} {h2_ip} {port} {TOTAL_FRAMES} {FPS} {client_output} {FRAME_SIZE}'
    h1.cmd(client_cmd)
    
    # Attendre la fin
    time.sleep(3)
    
    # Tuer les processus restants
    h2.cmd('pkill -f server_worker.py')
    
    # Charger les résultats
    client_res = {}
    server_res = {}
    
    if os.path.exists(client_output):
        with open(client_output) as f:
            client_res = json.load(f)
    
    if os.path.exists(server_output):
        with open(server_output) as f:
            server_res = json.load(f)
    
    return client_res, server_res


def main():
    setLogLevel('warning')
    
    print("="*70)
    print("TEST MININET CORRIGÉ - TCP vs UDP vs rQUIC")
    print("="*70)
    
    # Créer les scripts
    create_server_script()
    create_client_script()
    
    all_results = {}
    
    for scenario_name, params in SCENARIOS.items():
        print(f"\n{'='*70}")
        print(f"📡 SCÉNARIO: {scenario_name.upper()}")
        print(f"   Perte: {params['loss']}%, Délai: {params['delay']}, Bande passante: {params['bw']} Mbps")
        print("="*70)
        
        # Créer le réseau
        net = Mininet(link=TCLink, switch=OVSSwitch)
        
        h1 = net.addHost('h1', ip='10.0.0.1')
        h2 = net.addHost('h2', ip='10.0.0.2')
        s1 = net.addSwitch('s1', failMode='standalone')
        
        net.addLink(h1, s1, 
                    loss=params['loss'], 
                    delay=params['delay'], 
                    bw=params['bw'])
        net.addLink(h2, s1,
                    loss=params['loss'],
                    delay=params['delay'],
                    bw=params['bw'])
        
        net.start()
        s1.cmd('ovs-ofctl add-flow s1 action=normal')
        time.sleep(1)
        
        scenario_results = {}
        
        # Test TCP
        tcp_client, tcp_server = run_protocol_test(net, h1, h2, 'tcp', 5001, scenario_name)
        scenario_results['tcp'] = {'client': tcp_client, 'server': tcp_server}
        time.sleep(1)
        
        # Test UDP
        udp_client, udp_server = run_protocol_test(net, h1, h2, 'udp', 5002, scenario_name)
        scenario_results['udp'] = {'client': udp_client, 'server': udp_server}
        time.sleep(1)
        
        # Test rQUIC
        rquic_client, rquic_server = run_protocol_test(net, h1, h2, 'rquic', 5003, scenario_name)
        scenario_results['rquic'] = {'client': rquic_client, 'server': rquic_server}
        
        all_results[scenario_name] = scenario_results
        
        net.stop()
        time.sleep(2)
    
    # Afficher les résultats
    print("\n" + "="*70)
    print("📊 RÉSULTATS FINAUX")
    print("="*70)
    
    for scenario_name, scenario_results in all_results.items():
        params = SCENARIOS[scenario_name]
        print(f"\n{'─'*70}")
        print(f"📡 {scenario_name.upper()} (perte: {params['loss']}%, délai: {params['delay']})")
        print(f"{'─'*70}")
        
        print(f"\n{'Métrique':<25} {'TCP':<15} {'UDP':<15} {'rQUIC':<15}")
        print("-"*70)
        
        tcp = scenario_results.get('tcp', {})
        udp = scenario_results.get('udp', {})
        rquic = scenario_results.get('rquic', {})
        
        # Frames envoyées
        tcp_sent = tcp.get('client', {}).get('frames_sent', 0)
        udp_sent = udp.get('client', {}).get('frames_sent', 0)
        rquic_sent = rquic.get('client', {}).get('frames_sent', 0)
        print(f"{'Frames envoyées':<25} {tcp_sent:<15} {udp_sent:<15} {rquic_sent:<15}")
        
        # Frames reçues
        tcp_recv = tcp.get('server', {}).get('frames_received', 0)
        udp_recv = udp.get('server', {}).get('frames_received', 0)
        rquic_recv = rquic.get('server', {}).get('frames_received', 0)
        print(f"{'Frames reçues':<25} {tcp_recv:<15} {udp_recv:<15} {rquic_recv:<15}")
        
        # Taux de livraison
        tcp_del = (tcp_recv / tcp_sent * 100) if tcp_sent > 0 else 0
        udp_del = (udp_recv / udp_sent * 100) if udp_sent > 0 else 0
        rquic_del = rquic.get('client', {}).get('delivery_rate', 0)
        print(f"{'Taux de livraison':<25} {tcp_del:.1f}%{'':<10} {udp_del:.1f}%{'':<10} {rquic_del:.1f}%")
        
        # FPS
        tcp_fps = tcp.get('server', {}).get('fps', 0)
        udp_fps = udp.get('server', {}).get('fps', 0)
        rquic_fps = rquic.get('server', {}).get('fps', 0)
        print(f"{'FPS serveur':<25} {tcp_fps:.1f}{'':<12} {udp_fps:.1f}{'':<12} {rquic_fps:.1f}")
        
        # Retransmissions
        rquic_retrans = rquic.get('client', {}).get('retransmissions', 0)
        print(f"{'Retransmissions':<25} {'N/A':<15} {'N/A':<15} {rquic_retrans}")
    
    # Sauvegarder
    with open(os.path.join(WORK_DIR, 'all_results.json'), 'w') as f:
        json.dump(all_results, f, indent=2)
    
    print("\n" + "="*70)
    print("✅ Tous les tests terminés!")
    print(f"   Résultats sauvegardés dans all_results.json")
    print("="*70)


if __name__ == '__main__':
    main()
