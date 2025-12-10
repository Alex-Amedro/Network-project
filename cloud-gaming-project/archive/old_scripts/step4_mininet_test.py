#!/usr/bin/env python3
"""
ÉTAPE 4 : Comparaison TCP vs QUIC avec conditions réseau réalistes
Utilise Mininet pour simuler perte et délai
"""

import os
import sys
import time
import json
import subprocess
import struct
import socket

# Vérifier root
if os.geteuid() != 0:
    print("❌ Ce script doit être exécuté avec sudo!")
    print("   sudo venv/bin/python3 step4_mininet_test.py")
    sys.exit(1)

from mininet.net import Mininet
from mininet.node import OVSSwitch
from mininet.link import TCLink
from mininet.log import setLogLevel

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

WORK_DIR = os.path.dirname(os.path.abspath(__file__))

# Paramètres
NUM_FRAMES = 100
FRAME_SIZE = 5000  # 5 KB (plus petit pour éviter fragmentation)
FPS = 30

# Scénarios réseau à tester
SCENARIOS = [
    {'name': 'Parfait', 'loss': 0, 'delay': '1ms', 'bw': 100},
    {'name': 'Bon', 'loss': 1, 'delay': '10ms', 'bw': 100},
    {'name': 'Moyen', 'loss': 3, 'delay': '30ms', 'bw': 50},
    {'name': 'Mauvais', 'loss': 5, 'delay': '50ms', 'bw': 30},
]


def create_tcp_server_script():
    """Crée le script du serveur TCP"""
    code = '''#!/usr/bin/env python3
import socket
import struct
import time
import json
import sys

port = int(sys.argv[1])
output = sys.argv[2]
duration = int(sys.argv[3])

results = {'frames_received': 0, 'bytes': 0, 'latencies': []}

sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
sock.bind(('0.0.0.0', port))
sock.listen(1)
sock.settimeout(duration + 10)

try:
    conn, addr = sock.accept()
    conn.settimeout(5)
    
    while True:
        try:
            header = b''
            while len(header) < 12:
                chunk = conn.recv(12 - len(header))
                if not chunk:
                    break
                header += chunk
            
            if len(header) < 12:
                break
            
            frame_size, send_ts = struct.unpack('!Id', header)
            
            data = b''
            while len(data) < frame_size:
                chunk = conn.recv(min(65536, frame_size - len(data)))
                if not chunk:
                    break
                data += chunk
            
            if len(data) == frame_size:
                recv_time = time.time()
                results['frames_received'] += 1
                results['bytes'] += frame_size
                results['latencies'].append((recv_time - send_ts) * 1000)
        
        except socket.timeout:
            continue
        except:
            break
    
    conn.close()
except:
    pass
finally:
    sock.close()

with open(output, 'w') as f:
    json.dump(results, f)
'''
    path = os.path.join(WORK_DIR, 'tcp_server_mininet.py')
    with open(path, 'w') as f:
        f.write(code)
    return path


def create_tcp_client_script():
    """Crée le script du client TCP"""
    code = '''#!/usr/bin/env python3
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

results = {'frames_sent': 0}

time.sleep(0.5)

sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.settimeout(30)
sock.connect((host, port))

start = time.time()

for i in range(num_frames):
    send_time = time.time()
    data = bytes([i % 256] * frame_size)
    sock.sendall(struct.pack('!Id', len(data), send_time) + data)
    results['frames_sent'] += 1
    
    expected = start + (i + 1) / fps
    sleep = expected - time.time()
    if sleep > 0:
        time.sleep(sleep)

time.sleep(0.5)
sock.close()

with open(output, 'w') as f:
    json.dump(results, f)
'''
    path = os.path.join(WORK_DIR, 'tcp_client_mininet.py')
    with open(path, 'w') as f:
        f.write(code)
    return path


def create_quic_server_script():
    """Crée le script serveur QUIC"""
    code = '''#!/usr/bin/env python3
import asyncio
import struct
import time
import json
import sys
import ssl
import os

# Ajouter le venv au path
venv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'venv', 'lib', 'python3.12', 'site-packages')
sys.path.insert(0, venv_path)

from aioquic.asyncio import serve
from aioquic.asyncio.protocol import QuicConnectionProtocol
from aioquic.quic.configuration import QuicConfiguration
from aioquic.quic.events import StreamDataReceived

port = int(sys.argv[1])
output = sys.argv[2]
duration = int(sys.argv[3])
cert = sys.argv[4]
key = sys.argv[5]

results = {'frames_received': 0, 'bytes': 0, 'latencies': []}

class Server(QuicConnectionProtocol):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.buf = b''
    
    def quic_event_received(self, event):
        if isinstance(event, StreamDataReceived):
            self.buf += event.data
            while len(self.buf) >= 12:
                frame_size, send_ts = struct.unpack('!Id', self.buf[:12])
                total = 12 + frame_size
                if len(self.buf) >= total:
                    self.buf = self.buf[total:]
                    recv_time = time.time()
                    results['frames_received'] += 1
                    results['bytes'] += frame_size
                    results['latencies'].append((recv_time - send_ts) * 1000)
                else:
                    break

async def main():
    config = QuicConfiguration(is_client=False, alpn_protocols=["test"])
    config.load_cert_chain(cert, key)
    
    server = await serve('0.0.0.0', port, configuration=config, create_protocol=Server)
    
    await asyncio.sleep(duration + 5)
    server.close()
    
    with open(output, 'w') as f:
        json.dump(results, f)

asyncio.run(main())
'''
    path = os.path.join(WORK_DIR, 'quic_server_mininet.py')
    with open(path, 'w') as f:
        f.write(code)
    return path


def create_quic_client_script():
    """Crée le script client QUIC"""
    code = '''#!/usr/bin/env python3
import asyncio
import struct
import time
import json
import sys
import ssl
import os

venv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'venv', 'lib', 'python3.12', 'site-packages')
sys.path.insert(0, venv_path)

from aioquic.asyncio import connect
from aioquic.quic.configuration import QuicConfiguration

host = sys.argv[1]
port = int(sys.argv[2])
num_frames = int(sys.argv[3])
frame_size = int(sys.argv[4])
fps = int(sys.argv[5])
output = sys.argv[6]

results = {'frames_sent': 0}

async def main():
    config = QuicConfiguration(is_client=True, alpn_protocols=["test"])
    config.verify_mode = ssl.CERT_NONE
    
    await asyncio.sleep(1)
    
    async with connect(host, port, configuration=config) as protocol:
        stream_id = protocol._quic.get_next_available_stream_id()
        
        start = time.time()
        
        for i in range(num_frames):
            send_time = time.time()
            data = bytes([i % 256] * frame_size)
            msg = struct.pack('!Id', len(data), send_time) + data
            protocol._quic.send_stream_data(stream_id, msg, end_stream=(i == num_frames - 1))
            protocol.transmit()
            results['frames_sent'] += 1
            
            expected = start + (i + 1) / fps
            sleep = expected - time.time()
            if sleep > 0:
                await asyncio.sleep(sleep)
        
        await asyncio.sleep(2)
    
    with open(output, 'w') as f:
        json.dump(results, f)

asyncio.run(main())
'''
    path = os.path.join(WORK_DIR, 'quic_client_mininet.py')
    with open(path, 'w') as f:
        f.write(code)
    return path


def run_scenario(scenario):
    """Exécute un scénario de test"""
    name = scenario['name']
    loss = scenario['loss']
    delay = scenario['delay']
    bw = scenario['bw']
    
    print(f"\n{'='*60}")
    print(f"📡 Scénario: {name}")
    print(f"   Perte: {loss}%, Délai: {delay}, Bande passante: {bw} Mbps")
    print('='*60)
    
    setLogLevel('warning')
    
    # Créer réseau
    net = Mininet(link=TCLink, switch=OVSSwitch)
    
    h1 = net.addHost('h1', ip='10.0.0.1')
    h2 = net.addHost('h2', ip='10.0.0.2')
    s1 = net.addSwitch('s1', failMode='standalone')
    
    net.addLink(h1, s1, loss=loss, delay=delay, bw=bw)
    net.addLink(h2, s1, loss=loss, delay=delay, bw=bw)
    
    net.start()
    s1.cmd('ovs-ofctl add-flow s1 action=normal')
    time.sleep(1)
    
    results = {'tcp': {}, 'quic': {}}
    
    # ===== TEST TCP =====
    print("\n  🔵 Test TCP...")
    
    tcp_server_out = os.path.join(WORK_DIR, f'tmp_tcp_server_{name}.json')
    tcp_client_out = os.path.join(WORK_DIR, f'tmp_tcp_client_{name}.json')
    
    # Lancer serveur TCP
    h2.cmd(f'python3 {WORK_DIR}/tcp_server_mininet.py 8001 {tcp_server_out} {NUM_FRAMES//FPS + 10} &')
    time.sleep(0.5)
    
    # Lancer client TCP
    h1.cmd(f'python3 {WORK_DIR}/tcp_client_mininet.py 10.0.0.2 8001 {NUM_FRAMES} {FRAME_SIZE} {FPS} {tcp_client_out}')
    time.sleep(2)
    
    h2.cmd('pkill -f tcp_server_mininet')
    
    # Lire résultats TCP
    if os.path.exists(tcp_client_out):
        with open(tcp_client_out) as f:
            results['tcp']['client'] = json.load(f)
    if os.path.exists(tcp_server_out):
        with open(tcp_server_out) as f:
            results['tcp']['server'] = json.load(f)
    
    time.sleep(1)
    
    # ===== TEST QUIC =====
    print("  🟢 Test QUIC...")
    
    quic_server_out = os.path.join(WORK_DIR, f'tmp_quic_server_{name}.json')
    quic_client_out = os.path.join(WORK_DIR, f'tmp_quic_client_{name}.json')
    
    cert = os.path.join(WORK_DIR, 'server.cert')
    key = os.path.join(WORK_DIR, 'server.key')
    
    # Lancer serveur QUIC
    h2.cmd(f'python3 {WORK_DIR}/quic_server_mininet.py 8002 {quic_server_out} {NUM_FRAMES//FPS + 10} {cert} {key} &')
    time.sleep(1)
    
    # Lancer client QUIC
    h1.cmd(f'python3 {WORK_DIR}/quic_client_mininet.py 10.0.0.2 8002 {NUM_FRAMES} {FRAME_SIZE} {FPS} {quic_client_out}')
    time.sleep(3)
    
    h2.cmd('pkill -f quic_server_mininet')
    
    # Lire résultats QUIC
    if os.path.exists(quic_client_out):
        with open(quic_client_out) as f:
            results['quic']['client'] = json.load(f)
    if os.path.exists(quic_server_out):
        with open(quic_server_out) as f:
            results['quic']['server'] = json.load(f)
    
    net.stop()
    
    # Afficher résultats
    tcp_sent = results['tcp'].get('client', {}).get('frames_sent', 0)
    tcp_recv = results['tcp'].get('server', {}).get('frames_received', 0)
    tcp_rate = (tcp_recv / tcp_sent * 100) if tcp_sent > 0 else 0
    
    quic_sent = results['quic'].get('client', {}).get('frames_sent', 0)
    quic_recv = results['quic'].get('server', {}).get('frames_received', 0)
    quic_rate = (quic_recv / quic_sent * 100) if quic_sent > 0 else 0
    
    tcp_lat = results['tcp'].get('server', {}).get('latencies', [])
    quic_lat = results['quic'].get('server', {}).get('latencies', [])
    
    print(f"\n  TCP:  {tcp_sent} envoyées → {tcp_recv} reçues ({tcp_rate:.1f}%)")
    if tcp_lat:
        print(f"        Latence: {np.mean(tcp_lat):.1f} ms (±{np.std(tcp_lat):.1f})")
    
    print(f"  QUIC: {quic_sent} envoyées → {quic_recv} reçues ({quic_rate:.1f}%)")
    if quic_lat:
        print(f"        Latence: {np.mean(quic_lat):.1f} ms (±{np.std(quic_lat):.1f})")
    
    return {
        'scenario': scenario,
        'tcp': {
            'sent': tcp_sent,
            'received': tcp_recv,
            'rate': tcp_rate,
            'latency_avg': np.mean(tcp_lat) if tcp_lat else 0,
            'latency_std': np.std(tcp_lat) if tcp_lat else 0
        },
        'quic': {
            'sent': quic_sent,
            'received': quic_recv,
            'rate': quic_rate,
            'latency_avg': np.mean(quic_lat) if quic_lat else 0,
            'latency_std': np.std(quic_lat) if quic_lat else 0
        }
    }


def generate_final_graphs(all_results):
    """Génère les graphiques finaux"""
    print("\n" + "="*60)
    print("📊 GÉNÉRATION DES GRAPHIQUES FINAUX")
    print("="*60)
    
    scenarios = [r['scenario']['name'] for r in all_results]
    tcp_rates = [r['tcp']['rate'] for r in all_results]
    quic_rates = [r['quic']['rate'] for r in all_results]
    tcp_lat = [r['tcp']['latency_avg'] for r in all_results]
    quic_lat = [r['quic']['latency_avg'] for r in all_results]
    
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    fig.suptitle('Comparaison TCP vs QUIC sous différentes conditions réseau', fontsize=14, fontweight='bold')
    
    x = np.arange(len(scenarios))
    width = 0.35
    
    # 1. Taux de livraison
    ax1 = axes[0, 0]
    bars1 = ax1.bar(x - width/2, tcp_rates, width, label='TCP', color='#2196F3')
    bars2 = ax1.bar(x + width/2, quic_rates, width, label='QUIC', color='#4CAF50')
    ax1.set_ylabel('Taux de livraison (%)')
    ax1.set_title('Taux de Livraison par Scénario')
    ax1.set_xticks(x)
    ax1.set_xticklabels(scenarios)
    ax1.legend()
    ax1.set_ylim(0, 110)
    ax1.axhline(y=100, color='red', linestyle='--', alpha=0.3)
    
    # 2. Latence moyenne
    ax2 = axes[0, 1]
    ax2.bar(x - width/2, tcp_lat, width, label='TCP', color='#2196F3')
    ax2.bar(x + width/2, quic_lat, width, label='QUIC', color='#4CAF50')
    ax2.set_ylabel('Latence moyenne (ms)')
    ax2.set_title('Latence Moyenne par Scénario')
    ax2.set_xticks(x)
    ax2.set_xticklabels(scenarios)
    ax2.legend()
    
    # 3. Frames reçues
    ax3 = axes[1, 0]
    tcp_recv = [r['tcp']['received'] for r in all_results]
    quic_recv = [r['quic']['received'] for r in all_results]
    ax3.bar(x - width/2, tcp_recv, width, label='TCP', color='#2196F3')
    ax3.bar(x + width/2, quic_recv, width, label='QUIC', color='#4CAF50')
    ax3.axhline(y=NUM_FRAMES, color='red', linestyle='--', alpha=0.5, label=f'Cible ({NUM_FRAMES})')
    ax3.set_ylabel('Frames reçues')
    ax3.set_title('Nombre de Frames Reçues')
    ax3.set_xticks(x)
    ax3.set_xticklabels(scenarios)
    ax3.legend()
    
    # 4. Tableau récapitulatif
    ax4 = axes[1, 1]
    ax4.axis('off')
    
    table_data = [
        ['Scénario', 'TCP\nEnvoyées', 'TCP\nReçues', 'TCP\nTaux', 'QUIC\nEnvoyées', 'QUIC\nReçues', 'QUIC\nTaux']
    ]
    for r in all_results:
        table_data.append([
            r['scenario']['name'],
            str(r['tcp']['sent']),
            str(r['tcp']['received']),
            f"{r['tcp']['rate']:.1f}%",
            str(r['quic']['sent']),
            str(r['quic']['received']),
            f"{r['quic']['rate']:.1f}%"
        ])
    
    table = ax4.table(cellText=table_data, loc='center', cellLoc='center')
    table.auto_set_font_size(False)
    table.set_fontsize(10)
    table.scale(1.2, 1.5)
    
    # Colorer l'en-tête
    for i in range(len(table_data[0])):
        table[(0, i)].set_facecolor('#E0E0E0')
        table[(0, i)].set_text_props(fontweight='bold')
    
    ax4.set_title('Tableau Récapitulatif', fontweight='bold', pad=20)
    
    plt.tight_layout()
    
    output_file = os.path.join(WORK_DIR, 'tcp_vs_quic_mininet_results.png')
    plt.savefig(output_file, dpi=150, bbox_inches='tight')
    print(f"✅ Graphique sauvegardé: {output_file}")
    plt.close()


def main():
    print("="*70)
    print("ÉTAPE 4 : TEST MININET - TCP vs QUIC")
    print("="*70)
    print(f"Configuration: {NUM_FRAMES} frames, {FRAME_SIZE} bytes, {FPS} FPS")
    print("="*70)
    
    # Créer les scripts
    create_tcp_server_script()
    create_tcp_client_script()
    create_quic_server_script()
    create_quic_client_script()
    
    all_results = []
    
    for scenario in SCENARIOS:
        result = run_scenario(scenario)
        all_results.append(result)
        time.sleep(2)
    
    # Générer graphiques
    generate_final_graphs(all_results)
    
    # Sauvegarder JSON
    with open(os.path.join(WORK_DIR, 'step4_mininet_results.json'), 'w') as f:
        json.dump(all_results, f, indent=2)
    
    # Résumé final
    print("\n" + "="*70)
    print("📋 RÉSUMÉ FINAL")
    print("="*70)
    
    print(f"\n{'Scénario':<12} {'TCP Taux':<12} {'QUIC Taux':<12} {'TCP Lat':<12} {'QUIC Lat':<12}")
    print("-"*60)
    
    for r in all_results:
        print(f"{r['scenario']['name']:<12} {r['tcp']['rate']:.1f}%{'':<7} {r['quic']['rate']:.1f}%{'':<7} {r['tcp']['latency_avg']:.1f} ms{'':<5} {r['quic']['latency_avg']:.1f} ms")
    
    print("\n" + "="*70)
    print("✅ Tests terminés!")
    print("   📊 Graphique: tcp_vs_quic_mininet_results.png")
    print("   📁 Données: step4_mininet_results.json")
    print("="*70)


if __name__ == '__main__':
    main()
