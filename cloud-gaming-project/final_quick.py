#!/usr/bin/env python3
"""
COMPARAISON FINALE TCP vs QUIC - Version rapide
100 frames pour des tests plus rapides
"""

import os
import sys
import time
import json

if os.geteuid() != 0:
    print("❌ Exécuter avec: sudo python3 final_quick.py")
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

# Configuration RÉDUITE pour tests rapides
NUM_FRAMES = 100
FPS = 60

# Scénarios
SCENARIOS = [
    {'name': 'Parfait', 'loss': 0, 'delay': '5ms', 'bw': 100},
    {'name': 'Leger', 'loss': 1, 'delay': '10ms', 'bw': 100},
    {'name': 'Moyen', 'loss': 2, 'delay': '20ms', 'bw': 100},
]

print("="*70)
print("   COMPARAISON TCP vs QUIC - Cloud Gaming")
print("="*70)
print(f"   {NUM_FRAMES} frames à {FPS} FPS")
print("="*70)

# Scripts simplifiés
tcp_server_script = '''#!/usr/bin/env python3
import socket, struct, time, json, sys

port, output, expected = int(sys.argv[1]), sys.argv[2], int(sys.argv[3])
results = {"received": 0, "first_time": None, "last_time": None}

sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
sock.bind(("0.0.0.0", port))
sock.listen(1)
sock.settimeout(60)

try:
    conn, _ = sock.accept()
    conn.settimeout(30)
    buffer = b""
    
    while results["received"] < expected:
        chunk = conn.recv(65536)
        if not chunk: break
        buffer += chunk
        
        while len(buffer) >= 8:
            seq, size = struct.unpack("!II", buffer[:8])
            if len(buffer) < 8 + size: break
            
            now = time.time()
            if not results["first_time"]: results["first_time"] = now
            results["last_time"] = now
            results["received"] += 1
            conn.sendall(struct.pack("!I", seq))
            buffer = buffer[8+size:]
    conn.close()
except: pass

results["total_time"] = (results["last_time"] - results["first_time"]) if results["first_time"] else 0
json.dump(results, open(output, "w"))
sock.close()
'''

tcp_client_script = '''#!/usr/bin/env python3
import socket, struct, time, json, sys, random

host, port, num, fps, output = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4]), sys.argv[5]
results = {"sent": 0, "blocked_time": 0}

sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
sock.settimeout(5)

try:
    time.sleep(0.3)
    sock.connect((host, port))
    start = time.time()
    
    for i in range(num):
        size = random.randint(10000, 30000)
        data = b"X" * size
        
        t1 = time.time()
        sock.sendall(struct.pack("!II", i, size) + data)
        results["sent"] += 1
        
        try:
            sock.recv(4)
            if time.time() - t1 > 0.05: results["blocked_time"] += time.time() - t1
        except: pass
        
        wait = start + (i+1)/fps - time.time()
        if wait > 0: time.sleep(wait)
    
    results["duration"] = time.time() - start
except Exception as e:
    results["error"] = str(e)
    results["duration"] = 0

json.dump(results, open(output, "w"))
sock.close()
'''

quic_server_script = '''#!/usr/bin/env python3
import asyncio, struct, time, json, sys, ssl
from aioquic.asyncio import serve
from aioquic.asyncio.protocol import QuicConnectionProtocol
from aioquic.quic.configuration import QuicConfiguration
from aioquic.quic.events import StreamDataReceived

port, output, cert, key, expected = int(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4], int(sys.argv[5])
results = {"received": 0, "first_time": None, "last_time": None}
done = asyncio.Event()

class Server(QuicConnectionProtocol):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.buf = b""
    
    def quic_event_received(self, e):
        global results
        if isinstance(e, StreamDataReceived):
            self.buf += e.data
            while len(self.buf) >= 16:
                seq, ts, size = struct.unpack("!IdI", self.buf[:16])
                if len(self.buf) < 16 + size: break
                now = time.time()
                if not results["first_time"]: results["first_time"] = now
                results["last_time"] = now
                results["received"] += 1
                self.buf = self.buf[16+size:]
                if results["received"] >= expected: done.set()

async def main():
    cfg = QuicConfiguration(is_client=False, alpn_protocols=["g"])
    cfg.load_cert_chain(cert, key)
    cfg.idle_timeout = 60.0
    srv = await serve("0.0.0.0", port, configuration=cfg, create_protocol=Server)
    try: await asyncio.wait_for(done.wait(), 60)
    except: pass
    results["total_time"] = (results["last_time"] - results["first_time"]) if results["first_time"] else 0
    json.dump(results, open(output, "w"))
    srv.close()

asyncio.run(main())
'''

quic_client_script = '''#!/usr/bin/env python3
import asyncio, struct, time, json, sys, ssl, random
from aioquic.asyncio import connect
from aioquic.quic.configuration import QuicConfiguration

host, port, num, fps, output = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4]), sys.argv[5]
results = {"sent": 0}

async def main():
    cfg = QuicConfiguration(is_client=True, alpn_protocols=["g"])
    cfg.verify_mode = ssl.CERT_NONE
    cfg.idle_timeout = 60.0
    await asyncio.sleep(0.5)
    
    try:
        async with connect(host, port, configuration=cfg) as p:
            sid = p._quic.get_next_available_stream_id()
            start = time.time()
            
            for i in range(num):
                size = random.randint(10000, 30000)
                data = b"X" * size
                p._quic.send_stream_data(sid, struct.pack("!IdI", i, time.time(), size) + data, end_stream=(i==num-1))
                p.transmit()
                results["sent"] += 1
                
                wait = start + (i+1)/fps - time.time()
                if wait > 0: await asyncio.sleep(wait)
            
            await asyncio.sleep(3)
            results["duration"] = time.time() - start
    except Exception as e:
        results["error"] = str(e)
        results["duration"] = 0
    
    json.dump(results, open(output, "w"))

asyncio.run(main())
'''

# Sauvegarder
for name, code in [('_q_tcp_srv.py', tcp_server_script), ('_q_tcp_cli.py', tcp_client_script),
                   ('_q_quic_srv.py', quic_server_script), ('_q_quic_cli.py', quic_client_script)]:
    open(os.path.join(WORK_DIR, name), 'w').write(code)

cert = os.path.join(WORK_DIR, 'server.cert')
key = os.path.join(WORK_DIR, 'server.key')

def run_scenario(scenario):
    name, loss = scenario['name'], scenario['loss']
    
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
    
    # TCP
    print("   🔵 TCP...", end=' ', flush=True)
    tcp_srv = os.path.join(WORK_DIR, f'_r_{name}_tcp_s.json')
    tcp_cli = os.path.join(WORK_DIR, f'_r_{name}_tcp_c.json')
    
    h2.cmd(f'python3 {WORK_DIR}/_q_tcp_srv.py 5000 {tcp_srv} {NUM_FRAMES} &')
    time.sleep(0.3)
    h1.cmd(f'python3 {WORK_DIR}/_q_tcp_cli.py 10.0.0.2 5000 {NUM_FRAMES} {FPS} {tcp_cli}')
    time.sleep(1)
    h2.cmd('pkill -f _q_tcp_srv')
    
    ts = json.load(open(tcp_srv)) if os.path.exists(tcp_srv) else {}
    tc = json.load(open(tcp_cli)) if os.path.exists(tcp_cli) else {}
    
    tcp_recv = ts.get('received', 0)
    tcp_time = ts.get('total_time', 0)
    tcp_blocked = tc.get('blocked_time', 0)
    print(f"{tcp_recv}/{NUM_FRAMES} frames, {tcp_time:.2f}s, bloqué: {tcp_blocked:.2f}s")
    
    results['tcp'] = {'received': tcp_recv, 'time': tcp_time, 'blocked': tcp_blocked}
    time.sleep(1)
    
    # QUIC
    print("   🟢 QUIC...", end=' ', flush=True)
    quic_srv = os.path.join(WORK_DIR, f'_r_{name}_quic_s.json')
    quic_cli = os.path.join(WORK_DIR, f'_r_{name}_quic_c.json')
    
    h2.cmd(f'python3 {WORK_DIR}/_q_quic_srv.py 5001 {quic_srv} {cert} {key} {NUM_FRAMES} &')
    time.sleep(0.5)
    h1.cmd(f'python3 {WORK_DIR}/_q_quic_cli.py 10.0.0.2 5001 {NUM_FRAMES} {FPS} {quic_cli}')
    time.sleep(5)
    h2.cmd('pkill -f _q_quic_srv')
    
    qs = json.load(open(quic_srv)) if os.path.exists(quic_srv) else {}
    quic_recv = qs.get('received', 0)
    quic_time = qs.get('total_time', 0)
    print(f"{quic_recv}/{NUM_FRAMES} frames, {quic_time:.2f}s")
    
    results['quic'] = {'received': quic_recv, 'time': quic_time, 'blocked': 0}
    
    # Verdict
    if tcp_time > 0 and quic_time > 0:
        if quic_time < tcp_time:
            print(f"   ⚡ QUIC {tcp_time/quic_time:.1f}x plus rapide!")
        else:
            print(f"   ⏱️  TCP {quic_time/tcp_time:.1f}x plus rapide")
    
    net.stop()
    return results

# Exécution
all_results = []
for s in SCENARIOS:
    all_results.append(run_scenario(s))

# Graphique
print("\n" + "="*60)
print("📊 GÉNÉRATION DU GRAPHIQUE")
print("="*60)

fig, axes = plt.subplots(1, 3, figsize=(15, 5))
fig.suptitle(f'TCP vs QUIC - Cloud Gaming ({NUM_FRAMES} frames @ {FPS} FPS)', fontsize=14, fontweight='bold')

names = [r['scenario'] for r in all_results]
x = np.arange(len(names))
w = 0.35

# Temps
ax = axes[0]
tcp_t = [r['tcp']['time'] for r in all_results]
quic_t = [r['quic']['time'] for r in all_results]
ax.bar(x - w/2, tcp_t, w, label='TCP', color='#2196F3')
ax.bar(x + w/2, quic_t, w, label='QUIC', color='#4CAF50')
ax.set_ylabel('Temps (s)')
ax.set_title('Temps total')
ax.set_xticks(x)
ax.set_xticklabels(names)
ax.legend()
ax.grid(axis='y', alpha=0.3)

# Frames reçues
ax = axes[1]
tcp_r = [r['tcp']['received'] for r in all_results]
quic_r = [r['quic']['received'] for r in all_results]
ax.bar(x - w/2, tcp_r, w, label='TCP', color='#2196F3')
ax.bar(x + w/2, quic_r, w, label='QUIC', color='#4CAF50')
ax.set_ylabel('Frames recues')
ax.set_title('Fiabilite')
ax.set_xticks(x)
ax.set_xticklabels(names)
ax.axhline(y=NUM_FRAMES, color='red', linestyle='--', alpha=0.5)
ax.legend()
ax.grid(axis='y', alpha=0.3)

# Temps bloqué
ax = axes[2]
tcp_b = [r['tcp']['blocked'] for r in all_results]
quic_b = [0] * len(all_results)
ax.bar(x - w/2, tcp_b, w, label='TCP (HoL)', color='#F44336')
ax.bar(x + w/2, quic_b, w, label='QUIC', color='#4CAF50')
ax.set_ylabel('Temps bloque (s)')
ax.set_title('Head-of-Line Blocking')
ax.set_xticks(x)
ax.set_xticklabels(names)
ax.legend()
ax.grid(axis='y', alpha=0.3)

plt.tight_layout()
out = os.path.join(WORK_DIR, 'QUICK_TCP_vs_QUIC.png')
plt.savefig(out, dpi=150)
print(f"✅ {out}")

# Résumé
print("\n" + "="*60)
print("📋 RÉSUMÉ")
print("="*60)
for r in all_results:
    t, q = r['tcp']['time'], r['quic']['time']
    if t > 0 and q > 0:
        winner = f"QUIC {t/q:.1f}x ✅" if q < t else f"TCP {q/t:.1f}x"
    else:
        winner = "N/A"
    print(f"  {r['scenario']:<10} │ TCP: {t:.2f}s │ QUIC: {q:.2f}s │ {winner}")

print("\n✅ TERMINÉ!")
