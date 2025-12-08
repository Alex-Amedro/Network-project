#!/usr/bin/env python3
"""
COMPARAISON ÉQUITABLE TCP vs QUIC
==========================================
Les deux en Python userspace pour une comparaison juste.

L'objectif: Montrer que QUIC gère mieux les pertes grâce à:
- Streams indépendants (pas de Head-of-Line blocking)
- Retransmissions plus efficaces

On mesure le TEMPS TOTAL pour livrer N frames dans différentes conditions.
"""

import os
import sys
import time
import json
import struct
import asyncio
import ssl
import socket
import threading
from concurrent.futures import ThreadPoolExecutor

if os.geteuid() != 0:
    print("❌ Exécuter avec: sudo venv/bin/python3 tcp_vs_quic_fair.py")
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

# Configuration
NUM_FRAMES = 60  # 1 seconde à 60 FPS
FRAME_SIZE = 1000  # 1 KB par frame (petit pour éviter fragmentation)
NUM_STREAMS = 4  # Video, Audio, Input, Chat (pour montrer avantage QUIC)

# Scénarios avec pertes croissantes (modérées pour aioquic)
SCENARIOS = [
    {'name': '0% perte', 'loss': 0, 'delay': '10ms', 'bw': 100},
    {'name': '1% perte', 'loss': 1, 'delay': '15ms', 'bw': 100},
    {'name': '2% perte', 'loss': 2, 'delay': '20ms', 'bw': 100},
    {'name': '3% perte', 'loss': 3, 'delay': '25ms', 'bw': 100},
]

print("="*70)
print("   COMPARAISON ÉQUITABLE TCP vs QUIC")
print("="*70)
print(f"   {NUM_FRAMES} frames x {NUM_STREAMS} streams = {NUM_FRAMES * NUM_STREAMS} total")
print(f"   Taille frame: {FRAME_SIZE} bytes")
print("="*70)
print()
print("   💡 Les deux protocoles sont en Python (même base)")
print("   💡 On mesure le TEMPS TOTAL pour livrer toutes les frames")
print("   💡 QUIC devrait être meilleur avec plus de pertes (pas de HoL blocking)")
print("="*70)

# ============ TCP avec streams simulés (souffre de HoL blocking) ============

tcp_server_code = '''#!/usr/bin/env python3
"""TCP Server - 4 streams sur 1 connexion (HoL blocking)"""
import socket, struct, time, json, sys

port = int(sys.argv[1])
output = sys.argv[2]
expected_total = int(sys.argv[3])

results = {
    "frames_received": 0,
    "streams": {0: 0, 1: 0, 2: 0, 3: 0},
    "first_frame_time": None,
    "last_frame_time": None,
    "latencies": [],
    "status": "starting"
}

def save():
    with open(output, "w") as f:
        json.dump(results, f)

sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
sock.bind(("0.0.0.0", port))
sock.listen(1)
sock.settimeout(120)

results["status"] = "listening"
save()

try:
    conn, addr = sock.accept()
    conn.settimeout(60)
    results["status"] = "connected"
    save()
    
    buffer = b""
    
    while results["frames_received"] < expected_total:
        try:
            chunk = conn.recv(65536)
            if not chunk:
                break
            buffer += chunk
            
            # Header: stream_id (1) + frame_id (4) + timestamp (8) + size (4) = 17 bytes
            while len(buffer) >= 17:
                stream_id = buffer[0]
                frame_id, send_ts, frame_size = struct.unpack("!IdI", buffer[1:17])
                total_needed = 17 + frame_size
                
                if len(buffer) >= total_needed:
                    recv_time = time.time()
                    
                    if results["first_frame_time"] is None:
                        results["first_frame_time"] = recv_time
                    results["last_frame_time"] = recv_time
                    
                    results["frames_received"] += 1
                    results["streams"][stream_id] = results["streams"].get(stream_id, 0) + 1
                    results["latencies"].append((recv_time - send_ts) * 1000)
                    
                    buffer = buffer[total_needed:]
                    save()
                else:
                    break
                    
        except socket.timeout:
            break
        except Exception as e:
            results["error"] = str(e)
            break
    
    conn.close()
except Exception as e:
    results["error"] = str(e)

results["status"] = "done"
if results["first_frame_time"] and results["last_frame_time"]:
    results["total_time"] = results["last_frame_time"] - results["first_frame_time"]
save()
sock.close()
'''

tcp_client_code = '''#!/usr/bin/env python3
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
'''

# ============ QUIC avec vrais streams indépendants ============

quic_server_code = '''#!/usr/bin/env python3
"""QUIC Server - 4 streams VRAIMENT indépendants (pas de HoL blocking)"""
import asyncio, struct, time, json, sys

from aioquic.asyncio import serve
from aioquic.asyncio.protocol import QuicConnectionProtocol
from aioquic.quic.configuration import QuicConfiguration
from aioquic.quic.events import StreamDataReceived, ConnectionTerminated

port = int(sys.argv[1])
output = sys.argv[2]
cert = sys.argv[3]
key = sys.argv[4]
expected_total = int(sys.argv[5])

results = {
    "frames_received": 0,
    "streams": {},
    "first_frame_time": None,
    "last_frame_time": None,
    "latencies": [],
    "status": "starting"
}
stream_buffers = {}

def save():
    with open(output, "w") as f:
        json.dump(results, f)

class Server(QuicConnectionProtocol):
    def quic_event_received(self, event):
        global results, stream_buffers
        
        if isinstance(event, StreamDataReceived):
            stream_id = event.stream_id
            
            if stream_id not in stream_buffers:
                stream_buffers[stream_id] = b""
            stream_buffers[stream_id] += event.data
            
            # Header: frame_id (4) + timestamp (8) + size (4) = 16 bytes
            while len(stream_buffers[stream_id]) >= 16:
                buf = stream_buffers[stream_id]
                frame_id, send_ts, frame_size = struct.unpack("!IdI", buf[:16])
                total_needed = 16 + frame_size
                
                if len(buf) >= total_needed:
                    recv_time = time.time()
                    
                    if results["first_frame_time"] is None:
                        results["first_frame_time"] = recv_time
                    results["last_frame_time"] = recv_time
                    
                    results["frames_received"] += 1
                    results["streams"][str(stream_id)] = results["streams"].get(str(stream_id), 0) + 1
                    results["latencies"].append((recv_time - send_ts) * 1000)
                    
                    stream_buffers[stream_id] = buf[total_needed:]
                    save()
                else:
                    break
        
        elif isinstance(event, ConnectionTerminated):
            results["status"] = "terminated"
            save()

async def main():
    results["status"] = "configuring"
    save()
    
    config = QuicConfiguration(is_client=False, alpn_protocols=["gaming"])
    config.load_cert_chain(cert, key)
    config.idle_timeout = 120.0
    
    server = await serve("0.0.0.0", port, configuration=config, create_protocol=Server)
    results["status"] = "running"
    save()
    
    # Attendre que toutes les frames arrivent
    start = time.time()
    while results["frames_received"] < expected_total and (time.time() - start) < 120:
        await asyncio.sleep(0.1)
        save()
    
    if results["first_frame_time"] and results["last_frame_time"]:
        results["total_time"] = results["last_frame_time"] - results["first_frame_time"]
    
    results["status"] = "done"
    save()
    server.close()

asyncio.run(main())
'''

quic_client_code = '''#!/usr/bin/env python3
"""QUIC Client - 4 streams VRAIMENT indépendants"""
import asyncio, struct, time, json, sys, ssl

from aioquic.asyncio import connect
from aioquic.quic.configuration import QuicConfiguration

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

async def main():
    global results
    
    config = QuicConfiguration(is_client=True, alpn_protocols=["gaming"])
    config.verify_mode = ssl.CERT_NONE
    config.idle_timeout = 120.0
    
    await asyncio.sleep(1)
    
    try:
        async with connect(host, port, configuration=config) as protocol:
            results["status"] = "connected"
            results["start_time"] = time.time()
            save()
            
            # Créer 4 streams QUIC indépendants
            stream_ids = [protocol._quic.get_next_available_stream_id() for _ in range(num_streams)]
            
            # Envoyer les frames sur chaque stream
            for frame_id in range(num_frames):
                for i, stream_id in enumerate(stream_ids):
                    send_time = time.time()
                    data = bytes([frame_id % 256] * frame_size)
                    
                    # Header: frame_id (4) + timestamp (8) + size (4)
                    header = struct.pack("!IdI", frame_id, send_time, len(data))
                    is_last = (frame_id == num_frames - 1) and (i == num_streams - 1)
                    
                    protocol._quic.send_stream_data(stream_id, header + data, end_stream=is_last)
                    results["frames_sent"] += 1
                
                protocol.transmit()
                await asyncio.sleep(0.001)  # Simuler 60 FPS
            
            results["end_time"] = time.time()
            
            # Attendre que les retransmissions soient faites
            await asyncio.sleep(10)
            results["status"] = "done"
            save()
    
    except Exception as e:
        results["error"] = str(e)
        results["status"] = "error"
        save()

asyncio.run(main())
'''

# Sauvegarder les scripts
scripts = {
    '_fair_tcp_srv.py': tcp_server_code,
    '_fair_tcp_cli.py': tcp_client_code,
    '_fair_quic_srv.py': quic_server_code,
    '_fair_quic_cli.py': quic_client_code,
}

for name, code in scripts.items():
    with open(os.path.join(WORK_DIR, name), 'w') as f:
        f.write(code)

cert = os.path.join(WORK_DIR, 'server.cert')
key = os.path.join(WORK_DIR, 'server.key')


def run_test(net, h1, h2, protocol, scenario_name, port, loss_percent):
    """Exécute un test et retourne le temps total"""
    
    srv_out = os.path.join(WORK_DIR, f'_fair_{scenario_name}_{protocol}_srv.json')
    cli_out = os.path.join(WORK_DIR, f'_fair_{scenario_name}_{protocol}_cli.json')
    
    for f in [srv_out, cli_out]:
        if os.path.exists(f):
            os.remove(f)
    
    expected_total = NUM_FRAMES * NUM_STREAMS
    wait_time = 15 + loss_percent * 2
    
    if protocol == 'tcp':
        h2.cmd(f'python3 {WORK_DIR}/_fair_tcp_srv.py {port} {srv_out} {expected_total} &')
        time.sleep(0.5)
        h1.cmd(f'python3 {WORK_DIR}/_fair_tcp_cli.py 10.0.0.2 {port} {NUM_FRAMES} {FRAME_SIZE} {NUM_STREAMS} {cli_out}')
    else:
        h2.cmd(f'python3 {WORK_DIR}/_fair_quic_srv.py {port} {srv_out} {cert} {key} {expected_total} &')
        time.sleep(1)
        h1.cmd(f'python3 {WORK_DIR}/_fair_quic_cli.py 10.0.0.2 {port} {NUM_FRAMES} {FRAME_SIZE} {NUM_STREAMS} {cli_out}')
    
    time.sleep(wait_time)
    h2.cmd(f'pkill -f _fair_{protocol}')
    
    cli_res = {}
    srv_res = {}
    
    if os.path.exists(cli_out):
        with open(cli_out) as f:
            cli_res = json.load(f)
    if os.path.exists(srv_out):
        with open(srv_out) as f:
            srv_res = json.load(f)
    
    return cli_res, srv_res


def run_scenario(scenario):
    """Exécute TCP et QUIC pour un scénario"""
    name = scenario['name']
    loss = scenario['loss']
    
    print(f"\n{'─'*70}")
    print(f"📡 Scénario: {name}")
    print(f"   Perte: {loss}%, Délai: {scenario['delay']}, BW: {scenario['bw']} Mbps")
    print('─'*70)
    
    setLogLevel('warning')
    
    net = Mininet(link=TCLink, switch=OVSSwitch)
    h1 = net.addHost('h1', ip='10.0.0.1')
    h2 = net.addHost('h2', ip='10.0.0.2')
    s1 = net.addSwitch('s1', failMode='standalone')
    
    net.addLink(h1, s1, loss=loss, delay=scenario['delay'], bw=scenario['bw'])
    net.addLink(h2, s1, loss=loss, delay=scenario['delay'], bw=scenario['bw'])
    
    net.start()
    s1.cmd('ovs-ofctl add-flow s1 action=normal')
    time.sleep(1)
    
    results = {'scenario': name, 'loss': loss}
    expected = NUM_FRAMES * NUM_STREAMS
    
    # Test TCP
    print("   🔵 Test TCP (1 connexion, 4 streams simulés)...", end=' ', flush=True)
    tcp_cli, tcp_srv = run_test(net, h1, h2, 'tcp', name.replace(' ', '_').replace('%', ''), 8001, loss)
    tcp_recv = tcp_srv.get('frames_received', 0)
    tcp_time = tcp_srv.get('total_time', 0)
    tcp_lat = tcp_srv.get('latencies', [])
    print(f"Reçues: {tcp_recv}/{expected}, Temps: {tcp_time:.2f}s")
    
    results['tcp'] = {
        'received': tcp_recv,
        'expected': expected,
        'rate': (tcp_recv / expected * 100) if expected > 0 else 0,
        'total_time': tcp_time,
        'avg_latency': np.mean(tcp_lat) if tcp_lat else 0,
    }
    
    time.sleep(2)
    
    # Test QUIC
    print("   🟢 Test QUIC (4 streams indépendants)...", end=' ', flush=True)
    quic_cli, quic_srv = run_test(net, h1, h2, 'quic', name.replace(' ', '_').replace('%', ''), 8002, loss)
    quic_recv = quic_srv.get('frames_received', 0)
    quic_time = quic_srv.get('total_time', 0)
    quic_lat = quic_srv.get('latencies', [])
    print(f"Reçues: {quic_recv}/{expected}, Temps: {quic_time:.2f}s")
    
    results['quic'] = {
        'received': quic_recv,
        'expected': expected,
        'rate': (quic_recv / expected * 100) if expected > 0 else 0,
        'total_time': quic_time,
        'avg_latency': np.mean(quic_lat) if quic_lat else 0,
    }
    
    # Comparaison
    if tcp_time > 0 and quic_time > 0:
        if quic_time < tcp_time:
            speedup = tcp_time / quic_time
            print(f"   ⚡ QUIC {speedup:.1f}x plus rapide que TCP!")
        else:
            slowdown = quic_time / tcp_time
            print(f"   ⏱️ TCP {slowdown:.1f}x plus rapide que QUIC")
    
    net.stop()
    return results


# ============ EXÉCUTION ============

all_results = []

for scenario in SCENARIOS:
    result = run_scenario(scenario)
    all_results.append(result)

# ============ GRAPHIQUES ============

print("\n" + "="*70)
print("📊 GÉNÉRATION DES GRAPHIQUES")
print("="*70)

fig, axes = plt.subplots(2, 2, figsize=(14, 10))
fig.suptitle('TCP vs QUIC - Comparaison Équitable (Python userspace)\n' + 
             f'{NUM_FRAMES} frames × {NUM_STREAMS} streams = {NUM_FRAMES * NUM_STREAMS} total', 
             fontsize=14, fontweight='bold')

scenarios_names = [r['scenario'] for r in all_results]
losses = [r['loss'] for r in all_results]

# 1. Temps total de transmission
ax1 = axes[0, 0]
tcp_times = [r['tcp']['total_time'] for r in all_results]
quic_times = [r['quic']['total_time'] for r in all_results]

x = np.arange(len(scenarios_names))
width = 0.35

bars1 = ax1.bar(x - width/2, tcp_times, width, label='TCP', color='#2196F3')
bars2 = ax1.bar(x + width/2, quic_times, width, label='QUIC', color='#4CAF50')

ax1.set_xlabel('Taux de perte réseau')
ax1.set_ylabel('Temps total (secondes)')
ax1.set_title('⏱️ Temps pour livrer toutes les frames')
ax1.set_xticks(x)
ax1.set_xticklabels(scenarios_names)
ax1.legend()
ax1.grid(axis='y', alpha=0.3)

# Annotations
for i, (t, q) in enumerate(zip(tcp_times, quic_times)):
    if t > 0 and q > 0:
        if q < t:
            ax1.annotate(f'QUIC\n{t/q:.1f}x\nplus rapide', 
                        xy=(i, max(t, q)), xytext=(i, max(t, q) * 1.1),
                        ha='center', fontsize=8, color='green')

# 2. Latence moyenne
ax2 = axes[0, 1]
tcp_lats = [r['tcp']['avg_latency'] for r in all_results]
quic_lats = [r['quic']['avg_latency'] for r in all_results]

bars1 = ax2.bar(x - width/2, tcp_lats, width, label='TCP', color='#2196F3')
bars2 = ax2.bar(x + width/2, quic_lats, width, label='QUIC', color='#4CAF50')

ax2.set_xlabel('Taux de perte réseau')
ax2.set_ylabel('Latence moyenne (ms)')
ax2.set_title('📊 Latence moyenne par frame')
ax2.set_xticks(x)
ax2.set_xticklabels(scenarios_names)
ax2.legend()
ax2.grid(axis='y', alpha=0.3)

# 3. Taux de livraison
ax3 = axes[1, 0]
tcp_rates = [r['tcp']['rate'] for r in all_results]
quic_rates = [r['quic']['rate'] for r in all_results]

bars1 = ax3.bar(x - width/2, tcp_rates, width, label='TCP', color='#2196F3')
bars2 = ax3.bar(x + width/2, quic_rates, width, label='QUIC', color='#4CAF50')

ax3.set_xlabel('Taux de perte réseau')
ax3.set_ylabel('Taux de livraison (%)')
ax3.set_title('✅ Fiabilité (frames reçues / envoyées)')
ax3.set_xticks(x)
ax3.set_xticklabels(scenarios_names)
ax3.set_ylim(0, 110)
ax3.axhline(y=100, color='gray', linestyle='--', alpha=0.5)
ax3.legend()
ax3.grid(axis='y', alpha=0.3)

# 4. Tableau récapitulatif
ax4 = axes[1, 1]
ax4.axis('off')

table_data = []
for r in all_results:
    speedup = ""
    if r['tcp']['total_time'] > 0 and r['quic']['total_time'] > 0:
        ratio = r['tcp']['total_time'] / r['quic']['total_time']
        if ratio > 1:
            speedup = f"QUIC {ratio:.1f}x ✅"
        else:
            speedup = f"TCP {1/ratio:.1f}x"
    
    table_data.append([
        r['scenario'],
        f"{r['tcp']['total_time']:.2f}s",
        f"{r['quic']['total_time']:.2f}s",
        f"{r['tcp']['avg_latency']:.0f}ms",
        f"{r['quic']['avg_latency']:.0f}ms",
        speedup
    ])

col_labels = ['Scénario', 'TCP\nTemps', 'QUIC\nTemps', 'TCP\nLatence', 'QUIC\nLatence', 'Gagnant']

table = ax4.table(cellText=table_data, colLabels=col_labels,
                  cellLoc='center', loc='center',
                  colColours=['#E3F2FD', '#BBDEFB', '#C8E6C9', '#BBDEFB', '#C8E6C9', '#FFF9C4'])
table.auto_set_font_size(False)
table.set_fontsize(10)
table.scale(1.2, 1.8)
ax4.set_title('📋 Résumé Comparatif', fontsize=12, fontweight='bold', pad=20)

plt.tight_layout()
output_file = os.path.join(WORK_DIR, 'TCP_vs_QUIC_FAIR.png')
plt.savefig(output_file, dpi=150, bbox_inches='tight')
print(f"✅ Graphique: {output_file}")

# JSON
json_file = os.path.join(WORK_DIR, 'TCP_vs_QUIC_FAIR.json')
with open(json_file, 'w') as f:
    json.dump(all_results, f, indent=2, default=float)
print(f"✅ Données: {json_file}")

# Résumé
print("\n" + "="*70)
print("📋 RÉSULTATS")
print("="*70)
print()
print(f"{'Scénario':<12} │ {'TCP Temps':>10} │ {'QUIC Temps':>10} │ {'Gagnant':>15}")
print('─'*60)

for r in all_results:
    tcp_t = r['tcp']['total_time']
    quic_t = r['quic']['total_time']
    
    if tcp_t > 0 and quic_t > 0:
        if quic_t < tcp_t:
            winner = f"QUIC {tcp_t/quic_t:.1f}x ✅"
        else:
            winner = f"TCP {quic_t/tcp_t:.1f}x"
    else:
        winner = "N/A"
    
    print(f"{r['scenario']:<12} │ {tcp_t:>9.2f}s │ {quic_t:>9.2f}s │ {winner:>15}")

print('─'*60)

print()
print("="*70)
print("📊 CONCLUSION")
print("="*70)
print()
print("Les deux protocoles sont en Python (même base de comparaison).")
print()
print("QUIC devrait être plus rapide quand il y a des pertes car:")
print("  • 4 streams INDÉPENDANTS (pas de Head-of-Line blocking)")
print("  • Une perte sur le stream video ne bloque PAS l'audio")
print()
print("TCP est pénalisé car:")
print("  • 1 seule connexion pour 4 streams")
print("  • Une perte BLOQUE tous les streams (HoL blocking)")
print()
print("="*70)
print("✅ TEST TERMINÉ!")
print("="*70)
