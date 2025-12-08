#!/usr/bin/env python3
"""
COMPARAISON TCP vs QUIC - Version qui marche !
Basé sur test_quic_v2.py qui fonctionnait avec 30/30 = 100%
"""

import os
import sys
import time
import json

if os.geteuid() != 0:
    print("❌ Exécuter avec: sudo venv/bin/python3 comparison_fixed.py")
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
NUM_FRAMES = 60
FRAME_SIZE = 2000
FPS = 30

SCENARIOS = [
    {'name': 'Parfait', 'loss': 0, 'delay': '5ms', 'bw': 100},
    {'name': 'Bon', 'loss': 1, 'delay': '10ms', 'bw': 100},
    {'name': 'Moyen', 'loss': 2, 'delay': '20ms', 'bw': 50},
]

print("="*60)
print("COMPARAISON TCP vs QUIC - Cloud Gaming")
print("="*60)
print(f"{NUM_FRAMES} frames, {FRAME_SIZE} bytes, {FPS} FPS")
print("="*60)

# ============ TCP Server (même format simple) ============
tcp_server_code = '''#!/usr/bin/env python3
import socket
import struct
import json
import sys
import time

port = int(sys.argv[1])
output = sys.argv[2]

results = {"frames_received": 0, "first_time": None, "last_time": None}

def save():
    with open(output, "w") as f:
        json.dump(results, f)

sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
sock.bind(("0.0.0.0", port))
sock.listen(1)
sock.settimeout(60)

try:
    conn, _ = sock.accept()
    conn.settimeout(30)
    buffer = b""
    
    while True:
        try:
            chunk = conn.recv(65536)
            if not chunk:
                break
            buffer += chunk
            
            while len(buffer) >= 4:
                frame_size = struct.unpack("!I", buffer[:4])[0]
                total = 4 + frame_size
                
                if len(buffer) >= total:
                    now = time.time()
                    if results["first_time"] is None:
                        results["first_time"] = now
                    results["last_time"] = now
                    results["frames_received"] += 1
                    buffer = buffer[total:]
                    save()
                else:
                    break
        except:
            break
    conn.close()
except:
    pass

if results["first_time"] and results["last_time"]:
    results["total_time"] = results["last_time"] - results["first_time"]
else:
    results["total_time"] = 0
save()
sock.close()
'''

tcp_client_code = '''#!/usr/bin/env python3
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

results = {"frames_sent": 0, "blocked_time": 0}

sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.settimeout(30)

try:
    time.sleep(0.5)
    sock.connect((host, port))
    
    start = time.time()
    frame_interval = 1.0 / fps
    
    for i in range(num_frames):
        frame_start = time.time()
        data = bytes([i % 256] * frame_size)
        msg = struct.pack("!I", len(data)) + data
        sock.sendall(msg)
        results["frames_sent"] += 1
        
        # Calcul temps bloqué
        send_time = time.time() - frame_start
        if send_time > frame_interval:
            results["blocked_time"] += send_time - frame_interval
        
        # Respect du FPS
        next_frame = start + (i + 1) * frame_interval
        sleep_time = next_frame - time.time()
        if sleep_time > 0:
            time.sleep(sleep_time)
    
    time.sleep(1)
    results["duration"] = time.time() - start
except Exception as e:
    results["error"] = str(e)
    results["duration"] = 0

with open(output, "w") as f:
    json.dump(results, f)
sock.close()
'''

# ============ QUIC Server (format simple comme test_quic_v2.py) ============
quic_server_code = '''#!/usr/bin/env python3
import asyncio
import struct
import time
import json
import sys

from aioquic.asyncio import serve
from aioquic.asyncio.protocol import QuicConnectionProtocol
from aioquic.quic.configuration import QuicConfiguration
from aioquic.quic.events import StreamDataReceived, ConnectionTerminated

port = int(sys.argv[1])
output = sys.argv[2]
cert = sys.argv[3]
key = sys.argv[4]
expected = int(sys.argv[5]) if len(sys.argv) > 5 else 60

results = {"frames_received": 0, "first_time": None, "last_time": None, "total_time": 0}

def save():
    # Calcul du temps à chaque sauvegarde
    if results["first_time"] and results["last_time"]:
        results["total_time"] = results["last_time"] - results["first_time"]
    tmp = output + ".tmp"
    with open(tmp, "w") as f:
        json.dump(results, f)
    import os
    os.rename(tmp, output)

class Server(QuicConnectionProtocol):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.buffer = b""
    
    def quic_event_received(self, event):
        global results
        if isinstance(event, StreamDataReceived):
            self.buffer += event.data
            
            while len(self.buffer) >= 4:
                frame_size = struct.unpack("!I", self.buffer[:4])[0]
                total = 4 + frame_size
                
                if len(self.buffer) >= total:
                    now = time.time()
                    if results["first_time"] is None:
                        results["first_time"] = now
                    results["last_time"] = now
                    results["frames_received"] += 1
                    self.buffer = self.buffer[total:]
                    save()
                else:
                    break
        
        elif isinstance(event, ConnectionTerminated):
            save()

async def main():
    config = QuicConfiguration(is_client=False, alpn_protocols=["test"])
    config.load_cert_chain(cert, key)
    config.idle_timeout = 60.0
    
    server = await serve("0.0.0.0", port, configuration=config, create_protocol=Server)
    save()
    
    # Attendre que toutes les frames arrivent
    start = time.time()
    while results["frames_received"] < expected and (time.time() - start) < 30:
        await asyncio.sleep(0.1)
    
    save()
    server.close()

asyncio.run(main())
'''

quic_client_code = '''#!/usr/bin/env python3
import asyncio
import struct
import time
import json
import sys
import ssl

from aioquic.asyncio import connect
from aioquic.quic.configuration import QuicConfiguration

host = sys.argv[1]
port = int(sys.argv[2])
num_frames = int(sys.argv[3])
frame_size = int(sys.argv[4])
fps = int(sys.argv[5])
output = sys.argv[6]

results = {"frames_sent": 0}

async def main():
    config = QuicConfiguration(is_client=True, alpn_protocols=["test"])
    config.verify_mode = ssl.CERT_NONE
    config.idle_timeout = 60.0
    
    await asyncio.sleep(1)  # Attendre que le serveur soit prêt
    
    try:
        async with connect(host, port, configuration=config) as protocol:
            stream_id = protocol._quic.get_next_available_stream_id()
            
            start = time.time()
            frame_interval = 1.0 / fps
            
            for i in range(num_frames):
                data = bytes([i % 256] * frame_size)
                msg = struct.pack("!I", len(data)) + data
                
                is_last = (i == num_frames - 1)
                protocol._quic.send_stream_data(stream_id, msg, end_stream=is_last)
                protocol.transmit()
                results["frames_sent"] += 1
                
                # Respect du FPS
                next_frame = start + (i + 1) * frame_interval
                sleep_time = next_frame - time.time()
                if sleep_time > 0:
                    await asyncio.sleep(sleep_time)
            
            # Attendre que les retransmissions finissent
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
scripts = {
    '_fix_tcp_srv.py': tcp_server_code,
    '_fix_tcp_cli.py': tcp_client_code,
    '_fix_quic_srv.py': quic_server_code,
    '_fix_quic_cli.py': quic_client_code,
}

for name, code in scripts.items():
    with open(os.path.join(WORK_DIR, name), 'w') as f:
        f.write(code)

cert = os.path.join(WORK_DIR, 'server.cert')
key = os.path.join(WORK_DIR, 'server.key')


def run_scenario(scenario):
    name = scenario['name']
    loss = scenario['loss']
    
    print(f"\n{'─'*60}")
    print(f"📡 {name} (perte: {loss}%, délai: {scenario['delay']})")
    print('─'*60)
    
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
    
    # ===== TCP =====
    print("   🔵 TCP...", end=' ', flush=True)
    tcp_srv = os.path.join(WORK_DIR, f'_fix_{name}_tcp_s.json')
    tcp_cli = os.path.join(WORK_DIR, f'_fix_{name}_tcp_c.json')
    
    for f in [tcp_srv, tcp_cli]:
        if os.path.exists(f):
            os.remove(f)
    
    h2.cmd(f'python3 {WORK_DIR}/_fix_tcp_srv.py 5000 {tcp_srv} &')
    time.sleep(0.5)
    h1.cmd(f'python3 {WORK_DIR}/_fix_tcp_cli.py 10.0.0.2 5000 {NUM_FRAMES} {FRAME_SIZE} {FPS} {tcp_cli}')
    time.sleep(2)
    h2.cmd('pkill -f _fix_tcp_srv')
    
    ts = json.load(open(tcp_srv)) if os.path.exists(tcp_srv) else {}
    tc = json.load(open(tcp_cli)) if os.path.exists(tcp_cli) else {}
    
    tcp_recv = ts.get('frames_received', 0)
    tcp_time = ts.get('total_time', 0)
    tcp_blocked = tc.get('blocked_time', 0)
    print(f"{tcp_recv}/{NUM_FRAMES}, temps: {tcp_time:.2f}s, bloqué: {tcp_blocked:.2f}s")
    
    results['tcp'] = {
        'received': tcp_recv,
        'time': tcp_time,
        'blocked': tcp_blocked,
        'rate': (tcp_recv / NUM_FRAMES * 100) if NUM_FRAMES > 0 else 0
    }
    
    time.sleep(2)
    
    # ===== QUIC =====
    print("   🟢 QUIC...", end=' ', flush=True)
    quic_srv = os.path.join(WORK_DIR, f'_fix_{name}_quic_s.json')
    quic_cli = os.path.join(WORK_DIR, f'_fix_{name}_quic_c.json')
    
    for f in [quic_srv, quic_cli]:
        if os.path.exists(f):
            os.remove(f)
    
    h2.cmd(f'python3 {WORK_DIR}/_fix_quic_srv.py 5001 {quic_srv} {cert} {key} {NUM_FRAMES} &')
    time.sleep(1)
    h1.cmd(f'python3 {WORK_DIR}/_fix_quic_cli.py 10.0.0.2 5001 {NUM_FRAMES} {FRAME_SIZE} {FPS} {quic_cli}')
    
    # Attendre que le serveur finisse (il s'arrêtera tout seul quand il aura reçu toutes les frames)
    time.sleep(8)
    h2.cmd('pkill -9 -f _fix_quic_srv 2>/dev/null')
    time.sleep(0.5)
    
    qs = json.load(open(quic_srv)) if os.path.exists(quic_srv) else {}
    qc = json.load(open(quic_cli)) if os.path.exists(quic_cli) else {}
    
    quic_recv = qs.get('frames_received', 0)
    quic_time = qs.get('total_time', 0)
    print(f"{quic_recv}/{NUM_FRAMES}, temps: {quic_time:.2f}s")
    
    results['quic'] = {
        'received': quic_recv,
        'time': quic_time,
        'blocked': 0,
        'rate': (quic_recv / NUM_FRAMES * 100) if NUM_FRAMES > 0 else 0
    }
    
    # Verdict
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

# ===== GRAPHIQUE =====
print("\n" + "="*60)
print("📊 GÉNÉRATION DU GRAPHIQUE")
print("="*60)

fig, axes = plt.subplots(1, 3, figsize=(15, 5))
fig.suptitle(f'TCP vs QUIC - Cloud Gaming ({NUM_FRAMES} frames @ {FPS} FPS)', fontsize=14, fontweight='bold')

names = [r['scenario'] for r in all_results]
x = np.arange(len(names))
w = 0.35

# 1. Temps
ax = axes[0]
tcp_t = [r['tcp']['time'] for r in all_results]
quic_t = [r['quic']['time'] for r in all_results]
ax.bar(x - w/2, tcp_t, w, label='TCP', color='#2196F3')
ax.bar(x + w/2, quic_t, w, label='QUIC', color='#4CAF50')
ax.set_ylabel('Temps (secondes)')
ax.set_title('Temps de transmission')
ax.set_xticks(x)
ax.set_xticklabels(names)
ax.legend()
ax.grid(axis='y', alpha=0.3)

# 2. Frames reçues
ax = axes[1]
tcp_r = [r['tcp']['received'] for r in all_results]
quic_r = [r['quic']['received'] for r in all_results]
ax.bar(x - w/2, tcp_r, w, label='TCP', color='#2196F3')
ax.bar(x + w/2, quic_r, w, label='QUIC', color='#4CAF50')
ax.set_ylabel('Frames recues')
ax.set_title('Fiabilite')
ax.set_xticks(x)
ax.set_xticklabels(names)
ax.axhline(y=NUM_FRAMES, color='red', linestyle='--', alpha=0.5, label=f'Cible ({NUM_FRAMES})')
ax.legend()
ax.grid(axis='y', alpha=0.3)

# 3. Taux de livraison
ax = axes[2]
tcp_rate = [r['tcp']['rate'] for r in all_results]
quic_rate = [r['quic']['rate'] for r in all_results]
ax.bar(x - w/2, tcp_rate, w, label='TCP', color='#2196F3')
ax.bar(x + w/2, quic_rate, w, label='QUIC', color='#4CAF50')
ax.set_ylabel('Taux (%)')
ax.set_title('Taux de livraison')
ax.set_xticks(x)
ax.set_xticklabels(names)
ax.set_ylim(0, 110)
ax.axhline(y=100, color='gray', linestyle='--', alpha=0.5)
ax.legend()
ax.grid(axis='y', alpha=0.3)

plt.tight_layout()
output_file = os.path.join(WORK_DIR, 'TCP_vs_QUIC_FIXED.png')
plt.savefig(output_file, dpi=150, bbox_inches='tight')
print(f"✅ Graphique: {output_file}")

# JSON
json_file = os.path.join(WORK_DIR, 'TCP_vs_QUIC_FIXED.json')
with open(json_file, 'w') as f:
    json.dump(all_results, f, indent=2)
print(f"✅ JSON: {json_file}")

# Résumé
print("\n" + "="*60)
print("📋 RÉSUMÉ")
print("="*60)
print(f"{'Scénario':<10} │ {'TCP':^20} │ {'QUIC':^20} │ Gagnant")
print(f"{'':10} │ {'Reçu':^8} {'Temps':^10} │ {'Reçu':^8} {'Temps':^10} │")
print('─'*70)

for r in all_results:
    tcp_recv = r['tcp']['received']
    tcp_time = r['tcp']['time']
    quic_recv = r['quic']['received']
    quic_time = r['quic']['time']
    
    if tcp_time > 0 and quic_time > 0:
        if quic_time < tcp_time:
            winner = f"QUIC {tcp_time/quic_time:.1f}x ✅"
        else:
            winner = f"TCP {quic_time/tcp_time:.1f}x"
    elif quic_recv > tcp_recv:
        winner = "QUIC (+ fiable)"
    elif tcp_recv > quic_recv:
        winner = "TCP (+ fiable)"
    else:
        winner = "Égal"
    
    print(f"{r['scenario']:<10} │ {tcp_recv:^8} {tcp_time:^10.2f} │ {quic_recv:^8} {quic_time:^10.2f} │ {winner}")

print('─'*70)
print("\n✅ TERMINÉ!")
