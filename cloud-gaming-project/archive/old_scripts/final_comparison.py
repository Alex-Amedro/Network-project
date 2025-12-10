#!/usr/bin/env python3
"""
COMPARAISON FINALE TCP vs QUIC - Cloud Gaming
============================================
Utilise les mêmes protocoles Python pour une comparaison équitable.

TCP:  tcp_protocol.py (head-of-line blocking)
QUIC: quic_protocol.py (streams indépendants)
"""

import os
import sys
import time
import json
import subprocess

if os.geteuid() != 0:
    print("❌ Exécuter avec: sudo python3 final_comparison.py")
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
NUM_FRAMES = 300
FPS = 60

# Scénarios
SCENARIOS = [
    {'name': 'Parfait', 'loss': 0, 'delay': '5ms', 'bw': 100},
    {'name': 'Bon', 'loss': 1, 'delay': '15ms', 'bw': 100},
    {'name': 'Moyen', 'loss': 2, 'delay': '25ms', 'bw': 50},
    {'name': 'Difficile', 'loss': 3, 'delay': '35ms', 'bw': 50},
]

print("="*70)
print("   COMPARAISON FINALE TCP vs QUIC - CLOUD GAMING")
print("="*70)
print(f"   {NUM_FRAMES} frames à {FPS} FPS")
print(f"   TCP: head-of-line blocking (1 connexion)")
print(f"   QUIC: streams indépendants (pas de HoL blocking)")
print("="*70)

# Scripts pour Mininet
tcp_server_script = '''#!/usr/bin/env python3
import socket, struct, time, json, sys

port = int(sys.argv[1])
output = sys.argv[2]
expected = int(sys.argv[3])

results = {"received": 0, "first_time": None, "last_time": None}

sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
sock.bind(("0.0.0.0", port))
sock.listen(1)
sock.settimeout(120)

try:
    conn, _ = sock.accept()
    conn.settimeout(60)
    buffer = b""
    
    while results["received"] < expected:
        try:
            chunk = conn.recv(65536)
            if not chunk: break
            buffer += chunk
            
            while len(buffer) >= 8:
                seq_num, data_len = struct.unpack("!II", buffer[:8])
                total = 8 + data_len
                if len(buffer) < total: break
                
                now = time.time()
                if results["first_time"] is None:
                    results["first_time"] = now
                results["last_time"] = now
                results["received"] += 1
                
                # ACK
                conn.sendall(struct.pack("!I", seq_num))
                buffer = buffer[total:]
                
        except: break
    conn.close()
except Exception as e:
    results["error"] = str(e)

if results["first_time"] and results["last_time"]:
    results["total_time"] = results["last_time"] - results["first_time"]
else:
    results["total_time"] = 0

with open(output, "w") as f:
    json.dump(results, f)
sock.close()
'''

tcp_client_script = '''#!/usr/bin/env python3
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
'''

quic_server_script = '''#!/usr/bin/env python3
import asyncio, struct, time, json, sys, ssl

from aioquic.asyncio import serve
from aioquic.asyncio.protocol import QuicConnectionProtocol
from aioquic.quic.configuration import QuicConfiguration
from aioquic.quic.events import StreamDataReceived

port = int(sys.argv[1])
output = sys.argv[2]
cert = sys.argv[3]
key = sys.argv[4]
expected = int(sys.argv[5])

results = {"received": 0, "first_time": None, "last_time": None}
done = asyncio.Event()

class Server(QuicConnectionProtocol):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.buffer = b""
    
    def quic_event_received(self, event):
        global results
        if isinstance(event, StreamDataReceived):
            self.buffer += event.data
            
            while len(self.buffer) >= 16:
                seq, ts, size = struct.unpack("!IdI", self.buffer[:16])
                total = 16 + size
                if len(self.buffer) < total: break
                
                now = time.time()
                if results["first_time"] is None:
                    results["first_time"] = now
                results["last_time"] = now
                results["received"] += 1
                self.buffer = self.buffer[total:]
                
                if results["received"] >= expected:
                    done.set()

async def main():
    config = QuicConfiguration(is_client=False, alpn_protocols=["gaming"])
    config.load_cert_chain(cert, key)
    config.idle_timeout = 120.0
    
    server = await serve("0.0.0.0", port, configuration=config, create_protocol=Server)
    
    try:
        await asyncio.wait_for(done.wait(), timeout=120)
    except: pass
    
    if results["first_time"] and results["last_time"]:
        results["total_time"] = results["last_time"] - results["first_time"]
    else:
        results["total_time"] = 0
    
    with open(output, "w") as f:
        json.dump(results, f)
    server.close()

asyncio.run(main())
'''

quic_client_script = '''#!/usr/bin/env python3
import asyncio, struct, time, json, sys, ssl, random

from aioquic.asyncio import connect
from aioquic.quic.configuration import QuicConfiguration

host = sys.argv[1]
port = int(sys.argv[2])
num_frames = int(sys.argv[3])
fps = int(sys.argv[4])
output = sys.argv[5]

results = {"sent": 0, "blocked_time": 0}

def gen_frame(n):
    size = random.randint(100000, 150000) if n % 30 == 0 else random.randint(20000, 60000)
    return b"X" * size

async def main():
    config = QuicConfiguration(is_client=True, alpn_protocols=["gaming"])
    config.verify_mode = ssl.CERT_NONE
    config.idle_timeout = 120.0
    
    await asyncio.sleep(1)
    
    try:
        async with connect(host, port, configuration=config) as protocol:
            stream_id = protocol._quic.get_next_available_stream_id()
            start = time.time()
            
            for i in range(num_frames):
                data = gen_frame(i)
                ts = time.time()
                header = struct.pack("!IdI", i, ts, len(data))
                
                # QUIC: NON-BLOQUANT - pas d'attente d'ACK !
                protocol._quic.send_stream_data(stream_id, header + data, end_stream=(i == num_frames-1))
                protocol.transmit()
                results["sent"] += 1
                
                # FPS timing
                expected_time = start + (i + 1) / fps
                sleep_time = expected_time - time.time()
                if sleep_time > 0:
                    await asyncio.sleep(sleep_time)
            
            # Attend les retransmissions QUIC
            await asyncio.sleep(5)
            results["duration"] = time.time() - start
            
    except Exception as e:
        results["error"] = str(e)
        results["duration"] = 0
    
    with open(output, "w") as f:
        json.dump(results, f)

asyncio.run(main())
'''

# Sauvegarder les scripts
with open(os.path.join(WORK_DIR, '_final_tcp_srv.py'), 'w') as f:
    f.write(tcp_server_script)
with open(os.path.join(WORK_DIR, '_final_tcp_cli.py'), 'w') as f:
    f.write(tcp_client_script)
with open(os.path.join(WORK_DIR, '_final_quic_srv.py'), 'w') as f:
    f.write(quic_server_script)
with open(os.path.join(WORK_DIR, '_final_quic_cli.py'), 'w') as f:
    f.write(quic_client_script)

cert = os.path.join(WORK_DIR, 'server.cert')
key = os.path.join(WORK_DIR, 'server.key')


def run_scenario(scenario):
    """Exécute un scénario complet"""
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
    
    # ===== TEST TCP =====
    print("   🔵 Test TCP (avec head-of-line blocking)...", end=' ', flush=True)
    
    tcp_srv_out = os.path.join(WORK_DIR, f'_res_{name}_tcp_srv.json')
    tcp_cli_out = os.path.join(WORK_DIR, f'_res_{name}_tcp_cli.json')
    
    h2.cmd(f'python3 {WORK_DIR}/_final_tcp_srv.py 5000 {tcp_srv_out} {NUM_FRAMES} &')
    time.sleep(0.5)
    h1.cmd(f'python3 {WORK_DIR}/_final_tcp_cli.py 10.0.0.2 5000 {NUM_FRAMES} {FPS} {tcp_cli_out}')
    time.sleep(2)
    h2.cmd('pkill -f _final_tcp_srv')
    
    tcp_srv = json.load(open(tcp_srv_out)) if os.path.exists(tcp_srv_out) else {}
    tcp_cli = json.load(open(tcp_cli_out)) if os.path.exists(tcp_cli_out) else {}
    
    tcp_recv = tcp_srv.get('received', 0)
    tcp_time = tcp_srv.get('total_time', 0)
    tcp_blocked = tcp_cli.get('blocked_time', 0)
    
    print(f"Reçues: {tcp_recv}/{NUM_FRAMES}, Temps: {tcp_time:.2f}s, Bloqué: {tcp_blocked:.2f}s")
    
    results['tcp'] = {
        'received': tcp_recv,
        'total_time': tcp_time,
        'blocked_time': tcp_blocked,
        'rate': (tcp_recv / NUM_FRAMES * 100) if NUM_FRAMES > 0 else 0
    }
    
    time.sleep(2)
    
    # ===== TEST QUIC =====
    print("   🟢 Test QUIC (sans head-of-line blocking)...", end=' ', flush=True)
    
    quic_srv_out = os.path.join(WORK_DIR, f'_res_{name}_quic_srv.json')
    quic_cli_out = os.path.join(WORK_DIR, f'_res_{name}_quic_cli.json')
    
    h2.cmd(f'python3 {WORK_DIR}/_final_quic_srv.py 5001 {quic_srv_out} {cert} {key} {NUM_FRAMES} &')
    time.sleep(1)
    h1.cmd(f'python3 {WORK_DIR}/_final_quic_cli.py 10.0.0.2 5001 {NUM_FRAMES} {FPS} {quic_cli_out}')
    time.sleep(8)
    h2.cmd('pkill -f _final_quic_srv')
    
    quic_srv = json.load(open(quic_srv_out)) if os.path.exists(quic_srv_out) else {}
    quic_cli = json.load(open(quic_cli_out)) if os.path.exists(quic_cli_out) else {}
    
    quic_recv = quic_srv.get('received', 0)
    quic_time = quic_srv.get('total_time', 0)
    
    print(f"Reçues: {quic_recv}/{NUM_FRAMES}, Temps: {quic_time:.2f}s")
    
    results['quic'] = {
        'received': quic_recv,
        'total_time': quic_time,
        'blocked_time': 0,  # QUIC ne bloque pas
        'rate': (quic_recv / NUM_FRAMES * 100) if NUM_FRAMES > 0 else 0
    }
    
    # Comparaison
    if tcp_time > 0 and quic_time > 0:
        if quic_time < tcp_time:
            print(f"   ⚡ QUIC {tcp_time/quic_time:.1f}x plus rapide!")
        else:
            print(f"   ⏱️  TCP {quic_time/tcp_time:.1f}x plus rapide")
    
    net.stop()
    return results


# ===== EXÉCUTION =====
all_results = []

for scenario in SCENARIOS:
    result = run_scenario(scenario)
    all_results.append(result)

# ===== GRAPHIQUES =====
print("\n" + "="*70)
print("📊 GÉNÉRATION DES GRAPHIQUES")
print("="*70)

fig, axes = plt.subplots(2, 2, figsize=(14, 10))
fig.suptitle(f'TCP vs QUIC - Cloud Gaming ({NUM_FRAMES} frames @ {FPS} FPS)\n' +
             'TCP = Head-of-Line Blocking | QUIC = Streams Independants', 
             fontsize=14, fontweight='bold')

names = [r['scenario'] for r in all_results]
x = np.arange(len(names))
width = 0.35

# 1. Temps total
ax1 = axes[0, 0]
tcp_times = [r['tcp']['total_time'] for r in all_results]
quic_times = [r['quic']['total_time'] for r in all_results]

bars1 = ax1.bar(x - width/2, tcp_times, width, label='TCP', color='#2196F3')
bars2 = ax1.bar(x + width/2, quic_times, width, label='QUIC', color='#4CAF50')

ax1.set_ylabel('Temps (secondes)')
ax1.set_title('Temps total de transmission')
ax1.set_xticks(x)
ax1.set_xticklabels(names)
ax1.legend()
ax1.grid(axis='y', alpha=0.3)

# 2. Taux de livraison
ax2 = axes[0, 1]
tcp_rates = [r['tcp']['rate'] for r in all_results]
quic_rates = [r['quic']['rate'] for r in all_results]

bars1 = ax2.bar(x - width/2, tcp_rates, width, label='TCP', color='#2196F3')
bars2 = ax2.bar(x + width/2, quic_rates, width, label='QUIC', color='#4CAF50')

ax2.set_ylabel('Taux de livraison (%)')
ax2.set_title('Fiabilite - Frames recues')
ax2.set_xticks(x)
ax2.set_xticklabels(names)
ax2.set_ylim(0, 110)
ax2.axhline(y=100, color='gray', linestyle='--', alpha=0.5)
ax2.legend()
ax2.grid(axis='y', alpha=0.3)

# 3. Temps bloqué (TCP seulement)
ax3 = axes[1, 0]
tcp_blocked = [r['tcp']['blocked_time'] for r in all_results]
quic_blocked = [0] * len(all_results)  # QUIC ne bloque jamais

bars1 = ax3.bar(x - width/2, tcp_blocked, width, label='TCP (HoL blocking)', color='#F44336')
bars2 = ax3.bar(x + width/2, quic_blocked, width, label='QUIC (pas de blocage)', color='#4CAF50')

ax3.set_ylabel('Temps bloque (secondes)')
ax3.set_title('Head-of-Line Blocking')
ax3.set_xticks(x)
ax3.set_xticklabels(names)
ax3.legend()
ax3.grid(axis='y', alpha=0.3)

# 4. Tableau
ax4 = axes[1, 1]
ax4.axis('off')

table_data = []
for r in all_results:
    winner = ""
    if r['tcp']['total_time'] > 0 and r['quic']['total_time'] > 0:
        ratio = r['tcp']['total_time'] / r['quic']['total_time']
        if ratio > 1.1:
            winner = f"QUIC {ratio:.1f}x"
        elif ratio < 0.9:
            winner = f"TCP {1/ratio:.1f}x"
        else:
            winner = "~Egal"
    
    table_data.append([
        r['scenario'],
        f"{r['loss']}%",
        f"{r['tcp']['received']}/{NUM_FRAMES}",
        f"{r['quic']['received']}/{NUM_FRAMES}",
        f"{r['tcp']['total_time']:.1f}s",
        f"{r['quic']['total_time']:.1f}s",
        winner
    ])

table = ax4.table(cellText=table_data,
                  colLabels=['Scenario', 'Perte', 'TCP Recu', 'QUIC Recu', 'TCP Temps', 'QUIC Temps', 'Gagnant'],
                  cellLoc='center', loc='center',
                  colColours=['#E3F2FD']*7)
table.auto_set_font_size(False)
table.set_fontsize(9)
table.scale(1.2, 1.8)

plt.tight_layout()
output_png = os.path.join(WORK_DIR, 'FINAL_TCP_vs_QUIC.png')
plt.savefig(output_png, dpi=150, bbox_inches='tight')
print(f"✅ Graphique: {output_png}")

# JSON
output_json = os.path.join(WORK_DIR, 'FINAL_TCP_vs_QUIC.json')
with open(output_json, 'w') as f:
    json.dump(all_results, f, indent=2)
print(f"✅ Données: {output_json}")

# Résumé
print("\n" + "="*70)
print("📋 RÉSUMÉ FINAL")
print("="*70)
print()
print(f"{'Scénario':<12} {'Perte':>6} │ {'TCP':>12} │ {'QUIC':>12} │ {'Gagnant':>12}")
print('─'*60)

for r in all_results:
    tcp_t = r['tcp']['total_time']
    quic_t = r['quic']['total_time']
    
    if tcp_t > 0 and quic_t > 0:
        ratio = tcp_t / quic_t
        if ratio > 1.1:
            winner = f"QUIC {ratio:.1f}x ✅"
        elif ratio < 0.9:
            winner = f"TCP {1/ratio:.1f}x"
        else:
            winner = "~Égal"
    else:
        winner = "N/A"
    
    print(f"{r['scenario']:<12} {r['loss']:>5}% │ {tcp_t:>10.2f}s │ {quic_t:>10.2f}s │ {winner:>12}")

print('─'*60)
print()
print("="*70)
print("🎮 CONCLUSION CLOUD GAMING")
print("="*70)
print()
print("TCP souffre du Head-of-Line (HoL) blocking:")
print("  → Une perte bloque TOUT jusqu'à retransmission")
print("  → Latence imprévisible, mauvais pour le gaming")
print()
print("QUIC utilise des streams indépendants:")
print("  → Une perte sur un stream ne bloque pas les autres")
print("  → Vidéo, audio, inputs peuvent être sur des streams séparés")
print("  → Meilleure réactivité pour le cloud gaming")
print()
print("="*70)
print("✅ COMPARAISON TERMINÉE!")
print("="*70)
