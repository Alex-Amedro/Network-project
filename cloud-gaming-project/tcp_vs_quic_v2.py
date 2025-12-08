#!/usr/bin/env python3
"""
COMPARAISON FINALE TCP vs QUIC v2 - Cloud Gaming 60 FPS
Version corrigée avec timeout adaptatif pour QUIC
"""

import os
import sys
import time
import json
import struct

if os.geteuid() != 0:
    print("❌ Exécuter avec: sudo venv/bin/python3 tcp_vs_quic_v2.py")
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

# Paramètres Cloud Gaming - Réduits pour permettre les retransmissions
NUM_FRAMES = 120  # 2 secondes à 60 FPS 
FRAME_SIZE = 2000  # 2 KB par frame (plus petit = moins de retransmissions)
FPS = 60

# Scénarios réseau
SCENARIOS = [
    {'name': 'Parfait', 'loss': 0, 'delay': '5ms', 'bw': 100},
    {'name': 'Bon', 'loss': 1, 'delay': '15ms', 'bw': 100},
    {'name': 'Moyen', 'loss': 3, 'delay': '30ms', 'bw': 50},
    {'name': 'Mauvais', 'loss': 5, 'delay': '50ms', 'bw': 30},
]

print("="*70)
print("   COMPARAISON TCP vs QUIC v2 - CLOUD GAMING SIMULATION")
print("="*70)
print(f"   Configuration: {NUM_FRAMES} frames, {FRAME_SIZE} bytes, {FPS} FPS")
print(f"   Durée par test: {NUM_FRAMES/FPS:.1f} secondes")
print("="*70)

# ============ SCRIPTS TCP ============

tcp_server_code = '''#!/usr/bin/env python3
import socket, struct, time, json, sys

port = int(sys.argv[1])
output = sys.argv[2]
expected = int(sys.argv[3])

results = {"frames_received": 0, "bytes": 0, "latencies": [], "status": "starting"}

def save():
    with open(output, "w") as f:
        json.dump(results, f)

sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
sock.bind(("0.0.0.0", port))
sock.listen(1)
sock.settimeout(60)

results["status"] = "listening"
save()

try:
    conn, addr = sock.accept()
    conn.settimeout(30)
    results["status"] = "connected"
    save()
    
    while results["frames_received"] < expected:
        try:
            header = b""
            while len(header) < 12:
                chunk = conn.recv(12 - len(header))
                if not chunk: break
                header += chunk
            
            if len(header) < 12: break
            
            frame_size, send_ts = struct.unpack("!Id", header)
            
            data = b""
            while len(data) < frame_size:
                chunk = conn.recv(min(65536, frame_size - len(data)))
                if not chunk: break
                data += chunk
            
            if len(data) == frame_size:
                recv_time = time.time()
                results["frames_received"] += 1
                results["bytes"] += frame_size
                results["latencies"].append((recv_time - send_ts) * 1000)
                save()
        except socket.timeout:
            break
        except:
            break
    
    conn.close()
except Exception as e:
    results["error"] = str(e)

results["status"] = "done"
save()
sock.close()
'''

tcp_client_code = '''#!/usr/bin/env python3
import socket, struct, time, json, sys

host = sys.argv[1]
port = int(sys.argv[2])
num_frames = int(sys.argv[3])
frame_size = int(sys.argv[4])
fps = int(sys.argv[5])
output = sys.argv[6]

results = {"frames_sent": 0, "status": "starting"}

def save():
    with open(output, "w") as f:
        json.dump(results, f)

time.sleep(0.5)
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.settimeout(60)

try:
    sock.connect((host, port))
    results["status"] = "connected"
    save()
    
    start = time.time()
    
    for i in range(num_frames):
        send_time = time.time()
        data = bytes([i % 256] * frame_size)
        sock.sendall(struct.pack("!Id", len(data), send_time) + data)
        results["frames_sent"] += 1
        
        expected = start + (i + 1) / fps
        sleep = expected - time.time()
        if sleep > 0:
            time.sleep(sleep)
    
    time.sleep(2)
    results["status"] = "done"
except Exception as e:
    results["error"] = str(e)
    results["status"] = "error"

save()
sock.close()
'''

# ============ SCRIPTS QUIC AMÉLIORÉS ============

quic_server_code = '''#!/usr/bin/env python3
import asyncio, struct, time, json, sys

from aioquic.asyncio import serve
from aioquic.asyncio.protocol import QuicConnectionProtocol
from aioquic.quic.configuration import QuicConfiguration
from aioquic.quic.events import StreamDataReceived, ConnectionTerminated

port = int(sys.argv[1])
output = sys.argv[2]
cert = sys.argv[3]
key = sys.argv[4]
expected = int(sys.argv[5])
timeout = int(sys.argv[6])

results = {"frames_received": 0, "bytes": 0, "latencies": [], "status": "starting"}

def save():
    with open(output, "w") as f:
        json.dump(results, f)

class Server(QuicConnectionProtocol):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.buffer = b""
    
    def quic_event_received(self, event):
        global results
        if isinstance(event, StreamDataReceived):
            self.buffer += event.data
            
            while len(self.buffer) >= 12:
                frame_size, send_ts = struct.unpack("!Id", self.buffer[:12])
                total = 12 + frame_size
                
                if len(self.buffer) >= total:
                    self.buffer = self.buffer[total:]
                    recv_time = time.time()
                    results["frames_received"] += 1
                    results["bytes"] += frame_size
                    results["latencies"].append((recv_time - send_ts) * 1000)
                    save()  # Sauvegarder après chaque frame
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
    # Augmenter les timeouts internes
    config.idle_timeout = 120.0  # 2 minutes
    config.max_datagram_size = 1200  # Plus petit pour éviter fragmentation
    
    server = await serve("0.0.0.0", port, configuration=config, create_protocol=Server)
    results["status"] = "running"
    save()
    
    # Attendre avec timeout adaptatif
    start = time.time()
    while results["frames_received"] < expected and (time.time() - start) < timeout:
        await asyncio.sleep(0.1)
        save()
    
    results["status"] = "done"
    save()
    server.close()

asyncio.run(main())
'''

quic_client_code = '''#!/usr/bin/env python3
import asyncio, struct, time, json, sys, ssl

from aioquic.asyncio import connect
from aioquic.quic.configuration import QuicConfiguration

host = sys.argv[1]
port = int(sys.argv[2])
num_frames = int(sys.argv[3])
frame_size = int(sys.argv[4])
fps = int(sys.argv[5])
output = sys.argv[6]
wait_time = int(sys.argv[7]) if len(sys.argv) > 7 else 10

results = {"frames_sent": 0, "status": "starting"}

def save():
    with open(output, "w") as f:
        json.dump(results, f)

async def main():
    global results
    config = QuicConfiguration(is_client=True, alpn_protocols=["gaming"])
    config.verify_mode = ssl.CERT_NONE
    config.idle_timeout = 120.0  # 2 minutes
    config.max_datagram_size = 1200
    
    await asyncio.sleep(1)
    
    try:
        async with connect(host, port, configuration=config) as protocol:
            results["status"] = "connected"
            save()
            
            stream_id = protocol._quic.get_next_available_stream_id()
            start = time.time()
            
            for i in range(num_frames):
                send_time = time.time()
                data = bytes([i % 256] * frame_size)
                msg = struct.pack("!Id", len(data), send_time) + data
                protocol._quic.send_stream_data(stream_id, msg, end_stream=(i == num_frames - 1))
                protocol.transmit()
                results["frames_sent"] += 1
                
                expected = start + (i + 1) / fps
                sleep = expected - time.time()
                if sleep > 0:
                    await asyncio.sleep(sleep)
            
            # Attendre que les retransmissions soient faites
            await asyncio.sleep(wait_time)
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
    '_tcp_srv2.py': tcp_server_code,
    '_tcp_cli2.py': tcp_client_code,
    '_quic_srv2.py': quic_server_code,
    '_quic_cli2.py': quic_client_code,
}

for name, code in scripts.items():
    with open(os.path.join(WORK_DIR, name), 'w') as f:
        f.write(code)

cert = os.path.join(WORK_DIR, 'server.cert')
key = os.path.join(WORK_DIR, 'server.key')


def run_test(net, h1, h2, protocol, scenario_name, port, loss_percent):
    """Exécute un test TCP ou QUIC avec timeout adaptatif"""
    
    srv_out = os.path.join(WORK_DIR, f'_res2_{scenario_name}_{protocol}_srv.json')
    cli_out = os.path.join(WORK_DIR, f'_res2_{scenario_name}_{protocol}_cli.json')
    
    for f in [srv_out, cli_out]:
        if os.path.exists(f):
            os.remove(f)
    
    # Timeout adaptatif: plus de pertes = plus de temps pour retransmissions
    wait_time = 5 + loss_percent * 3  # 5s pour 0%, 20s pour 5%
    server_timeout = wait_time + 10
    
    if protocol == 'tcp':
        h2.cmd(f'python3 {WORK_DIR}/_tcp_srv2.py {port} {srv_out} {NUM_FRAMES} &')
        time.sleep(0.5)
        h1.cmd(f'python3 {WORK_DIR}/_tcp_cli2.py 10.0.0.2 {port} {NUM_FRAMES} {FRAME_SIZE} {FPS} {cli_out}')
    else:
        h2.cmd(f'python3 {WORK_DIR}/_quic_srv2.py {port} {srv_out} {cert} {key} {NUM_FRAMES} {int(server_timeout)} &')
        time.sleep(1)
        h1.cmd(f'python3 {WORK_DIR}/_quic_cli2.py 10.0.0.2 {port} {NUM_FRAMES} {FRAME_SIZE} {FPS} {cli_out} {int(wait_time)}')
    
    # Attendre la fin du test
    time.sleep(wait_time + 3)
    h2.cmd(f'pkill -f _{protocol}_srv2')
    
    # Lire résultats
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
    """Exécute un scénario complet TCP + QUIC"""
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
    
    results = {}
    
    # Test TCP
    print("   🔵 Test TCP...", end=' ', flush=True)
    tcp_cli, tcp_srv = run_test(net, h1, h2, 'tcp', name, 8001, loss)
    tcp_sent = tcp_cli.get('frames_sent', 0)
    tcp_recv = tcp_srv.get('frames_received', 0)
    tcp_rate = (tcp_recv / tcp_sent * 100) if tcp_sent > 0 else 0
    tcp_lat = tcp_srv.get('latencies', [])
    print(f"Envoyées: {tcp_sent}, Reçues: {tcp_recv} ({tcp_rate:.1f}%)")
    
    results['tcp'] = {
        'sent': tcp_sent,
        'received': tcp_recv,
        'rate': tcp_rate,
        'latency_avg': np.mean(tcp_lat) if tcp_lat else 0,
        'latency_std': np.std(tcp_lat) if tcp_lat else 0,
        'latencies': tcp_lat
    }
    
    time.sleep(2)
    
    # Test QUIC
    print("   🟢 Test QUIC...", end=' ', flush=True)
    quic_cli, quic_srv = run_test(net, h1, h2, 'quic', name, 8002, loss)
    quic_sent = quic_cli.get('frames_sent', 0)
    quic_recv = quic_srv.get('frames_received', 0)
    quic_rate = (quic_recv / quic_sent * 100) if quic_sent > 0 else 0
    quic_lat = quic_srv.get('latencies', [])
    print(f"Envoyées: {quic_sent}, Reçues: {quic_recv} ({quic_rate:.1f}%)")
    
    results['quic'] = {
        'sent': quic_sent,
        'received': quic_recv,
        'rate': quic_rate,
        'latency_avg': np.mean(quic_lat) if quic_lat else 0,
        'latency_std': np.std(quic_lat) if quic_lat else 0,
        'latencies': quic_lat
    }
    
    net.stop()
    
    return name, results


# Exécuter tous les scénarios
all_results = {}

for scenario in SCENARIOS:
    name, results = run_scenario(scenario)
    all_results[name] = results

# ============ GRAPHIQUES ============
print("\n" + "="*70)
print("📊 GÉNÉRATION DES GRAPHIQUES")
print("="*70)

fig, axes = plt.subplots(2, 2, figsize=(14, 10))
fig.suptitle('Comparaison TCP vs QUIC - Cloud Gaming 60 FPS\n(Protocoles FIABLES avec retransmissions)', 
             fontsize=14, fontweight='bold')

# 1. Taux de livraison par scénario
ax1 = axes[0, 0]
scenarios_names = list(all_results.keys())
tcp_rates = [all_results[s]['tcp']['rate'] for s in scenarios_names]
quic_rates = [all_results[s]['quic']['rate'] for s in scenarios_names]

x = np.arange(len(scenarios_names))
width = 0.35

bars1 = ax1.bar(x - width/2, tcp_rates, width, label='TCP', color='#2196F3')
bars2 = ax1.bar(x + width/2, quic_rates, width, label='QUIC', color='#4CAF50')

ax1.set_xlabel('Scénario Réseau')
ax1.set_ylabel('Taux de Livraison (%)')
ax1.set_title('Fiabilité: Taux de Livraison des Frames')
ax1.set_xticks(x)
ax1.set_xticklabels(scenarios_names)
ax1.set_ylim(0, 110)
ax1.axhline(y=100, color='gray', linestyle='--', alpha=0.5)
ax1.legend()
ax1.grid(axis='y', alpha=0.3)

for bar in bars1 + bars2:
    height = bar.get_height()
    ax1.annotate(f'{height:.1f}%',
                xy=(bar.get_x() + bar.get_width()/2, height),
                xytext=(0, 3), textcoords="offset points",
                ha='center', va='bottom', fontsize=8)

# 2. Latence moyenne
ax2 = axes[0, 1]
tcp_lats = [all_results[s]['tcp']['latency_avg'] for s in scenarios_names]
quic_lats = [all_results[s]['quic']['latency_avg'] for s in scenarios_names]

bars1 = ax2.bar(x - width/2, tcp_lats, width, label='TCP', color='#2196F3')
bars2 = ax2.bar(x + width/2, quic_lats, width, label='QUIC', color='#4CAF50')

ax2.set_xlabel('Scénario Réseau')
ax2.set_ylabel('Latence Moyenne (ms)')
ax2.set_title('Performance: Latence Moyenne par Frame')
ax2.set_xticks(x)
ax2.set_xticklabels(scenarios_names)
ax2.legend()
ax2.grid(axis='y', alpha=0.3)

# 3. Frames reçues
ax3 = axes[1, 0]
tcp_recv = [all_results[s]['tcp']['received'] for s in scenarios_names]
quic_recv = [all_results[s]['quic']['received'] for s in scenarios_names]

bars1 = ax3.bar(x - width/2, tcp_recv, width, label='TCP', color='#2196F3')
bars2 = ax3.bar(x + width/2, quic_recv, width, label='QUIC', color='#4CAF50')

ax3.set_xlabel('Scénario Réseau')
ax3.set_ylabel('Frames Reçues')
ax3.set_title(f'Comptage: Frames Reçues (sur {NUM_FRAMES} envoyées)')
ax3.set_xticks(x)
ax3.set_xticklabels(scenarios_names)
ax3.axhline(y=NUM_FRAMES, color='red', linestyle='--', alpha=0.5, label='Envoyées')
ax3.legend()
ax3.grid(axis='y', alpha=0.3)

# 4. Tableau récapitulatif
ax4 = axes[1, 1]
ax4.axis('off')

table_data = []
for s in scenarios_names:
    tcp = all_results[s]['tcp']
    quic = all_results[s]['quic']
    table_data.append([
        s,
        f"{tcp['sent']}", f"{tcp['received']}", f"{tcp['rate']:.1f}%", f"{tcp['latency_avg']:.1f}ms",
        f"{quic['sent']}", f"{quic['received']}", f"{quic['rate']:.1f}%", f"{quic['latency_avg']:.1f}ms"
    ])

col_labels = ['Scénario', 
              'TCP\nEnvoyées', 'TCP\nReçues', 'TCP\nTaux', 'TCP\nLatence',
              'QUIC\nEnvoyées', 'QUIC\nReçues', 'QUIC\nTaux', 'QUIC\nLatence']

table = ax4.table(cellText=table_data, colLabels=col_labels,
                  cellLoc='center', loc='center',
                  colColours=['#E3F2FD']*5 + ['#E8F5E9']*4)
table.auto_set_font_size(False)
table.set_fontsize(9)
table.scale(1.2, 1.5)

ax4.set_title('Tableau Récapitulatif', fontsize=12, fontweight='bold', pad=20)

plt.tight_layout()
output_file = os.path.join(WORK_DIR, 'TCP_vs_QUIC_v2.png')
plt.savefig(output_file, dpi=150, bbox_inches='tight')
print(f"✅ Graphique sauvegardé: {output_file}")

# Sauvegarder JSON
json_file = os.path.join(WORK_DIR, 'TCP_vs_QUIC_v2.json')
with open(json_file, 'w') as f:
    json.dump(all_results, f, indent=2, default=float)

# Afficher résultats
print("="*70)
print("📋 RÉSULTATS FINAUX - TCP vs QUIC")
print("="*70)
print()
print(f"{'Scénario':<12} {'Perte':^8} │ {'TCP':<20} │ {'QUIC':<20}")
print(f"{'':12} {'':^8} │ {'Reçues':^10} {'Taux':^10} │ {'Reçues':^10} {'Taux':^10}")
print('─'*70)

for s in scenarios_names:
    tcp = all_results[s]['tcp']
    quic = all_results[s]['quic']
    loss = [sc['loss'] for sc in SCENARIOS if sc['name'] == s][0]
    
    tcp_status = "✅" if tcp['rate'] >= 99 else "❌"
    quic_status = "✅" if quic['rate'] >= 99 else "❌"
    
    print(f"{s:<12} {loss}%{'':<5} │ {tcp['received']:<10} {tcp['rate']:>6.1f}% {tcp_status} │ {quic['received']:<10} {quic['rate']:>6.1f}% {quic_status}")

print('─'*70)

print()
print("="*70)
print("📊 ANALYSE")
print("="*70)
print()
print("Les deux protocoles (TCP et QUIC) sont des protocoles FIABLES:")
print("- Ils garantissent la livraison des données via retransmissions")
print("- Le taux de livraison devrait être ~100% si assez de temps pour retransmissions")
print()
print("Différences observées:")
print("- TCP: Implémenté dans le kernel Linux (très optimisé)")
print("- QUIC (aioquic): Implémenté en Python userspace (moins optimisé)")
print("- QUIC peut nécessiter plus de temps pour les retransmissions sous forte perte")
print()
print("Pour le cloud gaming:")
print("- TCP: Simple mais Head-of-Line blocking (une perte bloque tout)")
print("- QUIC: Streams indépendants, pas de HoL blocking, meilleure latence")
print()
print("="*70)
print()
print(f"📁 Fichiers générés:")
print(f"   📊 {output_file}")
print(f"   📄 {json_file}")
print()
print("="*70)
print("✅ TESTS TERMINÉS!")
print("="*70)
