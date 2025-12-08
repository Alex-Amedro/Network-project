#!/usr/bin/env python3
"""
COMPARAISON FINALE TCP vs QUIC - Cloud Gaming 60 FPS
Avec graphiques matplotlib
"""

import os
import sys
import time
import json
import struct

if os.geteuid() != 0:
    print("❌ Exécuter avec: sudo venv/bin/python3 tcp_vs_quic_final.py")
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

# Paramètres Cloud Gaming
NUM_FRAMES = 300  # 5 secondes à 60 FPS
FRAME_SIZE = 5000  # 5 KB par frame
FPS = 60

# Scénarios réseau
SCENARIOS = [
    {'name': 'Parfait', 'loss': 0, 'delay': '5ms', 'bw': 100},
    {'name': 'Bon', 'loss': 1, 'delay': '15ms', 'bw': 100},
    {'name': 'Moyen', 'loss': 3, 'delay': '30ms', 'bw': 50},
    {'name': 'Mauvais', 'loss': 5, 'delay': '50ms', 'bw': 30},
]

print("="*70)
print("   COMPARAISON TCP vs QUIC - CLOUD GAMING SIMULATION")
print("="*70)
print(f"   Configuration: {NUM_FRAMES} frames, {FRAME_SIZE} bytes, {FPS} FPS")
print(f"   Durée par test: {NUM_FRAMES/FPS:.1f} secondes")
print("="*70)

# ============ SCRIPTS TCP ============

tcp_server_code = '''#!/usr/bin/env python3
import socket, struct, time, json, sys

port = int(sys.argv[1])
output = sys.argv[2]

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
    
    while True:
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
                if results["frames_received"] % 60 == 0:
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
    
    time.sleep(1)
    results["status"] = "done"
except Exception as e:
    results["error"] = str(e)
    results["status"] = "error"

save()
sock.close()
'''

# ============ SCRIPTS QUIC ============

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
                    if results["frames_received"] % 60 == 0:
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
    
    server = await serve("0.0.0.0", port, configuration=config, create_protocol=Server)
    results["status"] = "running"
    save()
    
    await asyncio.sleep(30)
    
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

results = {"frames_sent": 0, "status": "starting"}

def save():
    with open(output, "w") as f:
        json.dump(results, f)

async def main():
    global results
    config = QuicConfiguration(is_client=True, alpn_protocols=["gaming"])
    config.verify_mode = ssl.CERT_NONE
    
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
            
            await asyncio.sleep(2)
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
    '_tcp_srv.py': tcp_server_code,
    '_tcp_cli.py': tcp_client_code,
    '_quic_srv.py': quic_server_code,
    '_quic_cli.py': quic_client_code,
}

for name, code in scripts.items():
    with open(os.path.join(WORK_DIR, name), 'w') as f:
        f.write(code)

cert = os.path.join(WORK_DIR, 'server.cert')
key = os.path.join(WORK_DIR, 'server.key')


def run_test(net, h1, h2, protocol, scenario_name, port):
    """Exécute un test TCP ou QUIC"""
    
    srv_out = os.path.join(WORK_DIR, f'_res_{scenario_name}_{protocol}_srv.json')
    cli_out = os.path.join(WORK_DIR, f'_res_{scenario_name}_{protocol}_cli.json')
    
    for f in [srv_out, cli_out]:
        if os.path.exists(f):
            os.remove(f)
    
    if protocol == 'tcp':
        h2.cmd(f'python3 {WORK_DIR}/_tcp_srv.py {port} {srv_out} &')
        time.sleep(0.5)
        h1.cmd(f'python3 {WORK_DIR}/_tcp_cli.py 10.0.0.2 {port} {NUM_FRAMES} {FRAME_SIZE} {FPS} {cli_out}')
    else:
        h2.cmd(f'python3 {WORK_DIR}/_quic_srv.py {port} {srv_out} {cert} {key} &')
        time.sleep(1)
        h1.cmd(f'python3 {WORK_DIR}/_quic_cli.py 10.0.0.2 {port} {NUM_FRAMES} {FRAME_SIZE} {FPS} {cli_out}')
    
    time.sleep(2)
    h2.cmd(f'pkill -f _{protocol}_srv')
    
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
    
    print(f"\n{'─'*70}")
    print(f"📡 Scénario: {name}")
    print(f"   Perte: {scenario['loss']}%, Délai: {scenario['delay']}, BW: {scenario['bw']} Mbps")
    print('─'*70)
    
    setLogLevel('warning')
    
    net = Mininet(link=TCLink, switch=OVSSwitch)
    h1 = net.addHost('h1', ip='10.0.0.1')
    h2 = net.addHost('h2', ip='10.0.0.2')
    s1 = net.addSwitch('s1', failMode='standalone')
    
    net.addLink(h1, s1, loss=scenario['loss'], delay=scenario['delay'], bw=scenario['bw'])
    net.addLink(h2, s1, loss=scenario['loss'], delay=scenario['delay'], bw=scenario['bw'])
    
    net.start()
    s1.cmd('ovs-ofctl add-flow s1 action=normal')
    time.sleep(1)
    
    results = {}
    
    # Test TCP
    print("   🔵 Test TCP...", end=' ', flush=True)
    tcp_cli, tcp_srv = run_test(net, h1, h2, 'tcp', name, 8001)
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
    
    time.sleep(1)
    
    # Test QUIC
    print("   🟢 Test QUIC...", end=' ', flush=True)
    quic_cli, quic_srv = run_test(net, h1, h2, 'quic', name, 8002)
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
    
    return {'scenario': scenario, 'results': results}


def generate_graphs(all_results):
    """Génère les graphiques matplotlib"""
    print("\n" + "="*70)
    print("📊 GÉNÉRATION DES GRAPHIQUES")
    print("="*70)
    
    scenarios = [r['scenario']['name'] for r in all_results]
    x = np.arange(len(scenarios))
    width = 0.35
    
    tcp_rates = [r['results']['tcp']['rate'] for r in all_results]
    quic_rates = [r['results']['quic']['rate'] for r in all_results]
    tcp_lat = [r['results']['tcp']['latency_avg'] for r in all_results]
    quic_lat = [r['results']['quic']['latency_avg'] for r in all_results]
    tcp_recv = [r['results']['tcp']['received'] for r in all_results]
    quic_recv = [r['results']['quic']['received'] for r in all_results]
    
    fig = plt.figure(figsize=(16, 12))
    fig.suptitle(f'Comparaison TCP vs QUIC - Cloud Gaming ({FPS} FPS, {NUM_FRAMES} frames)', 
                 fontsize=16, fontweight='bold')
    
    # 1. Taux de livraison
    ax1 = fig.add_subplot(2, 2, 1)
    bars1 = ax1.bar(x - width/2, tcp_rates, width, label='TCP', color='#2196F3', edgecolor='black')
    bars2 = ax1.bar(x + width/2, quic_rates, width, label='QUIC', color='#4CAF50', edgecolor='black')
    ax1.set_ylabel('Taux de livraison (%)', fontsize=12)
    ax1.set_title('Taux de Livraison', fontsize=14, fontweight='bold')
    ax1.set_xticks(x)
    ax1.set_xticklabels(scenarios)
    ax1.legend(loc='lower left')
    ax1.set_ylim(0, 110)
    ax1.axhline(y=100, color='red', linestyle='--', alpha=0.5)
    for bar, val in zip(bars1, tcp_rates):
        ax1.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 1, f'{val:.0f}%', 
                ha='center', fontsize=9, fontweight='bold')
    for bar, val in zip(bars2, quic_rates):
        ax1.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 1, f'{val:.0f}%', 
                ha='center', fontsize=9, fontweight='bold')
    
    # 2. Latence moyenne
    ax2 = fig.add_subplot(2, 2, 2)
    bars1 = ax2.bar(x - width/2, tcp_lat, width, label='TCP', color='#2196F3', edgecolor='black')
    bars2 = ax2.bar(x + width/2, quic_lat, width, label='QUIC', color='#4CAF50', edgecolor='black')
    ax2.set_ylabel('Latence moyenne (ms)', fontsize=12)
    ax2.set_title('Latence Moyenne', fontsize=14, fontweight='bold')
    ax2.set_xticks(x)
    ax2.set_xticklabels(scenarios)
    ax2.legend()
    
    # 3. Frames reçues
    ax3 = fig.add_subplot(2, 2, 3)
    bars1 = ax3.bar(x - width/2, tcp_recv, width, label='TCP', color='#2196F3', edgecolor='black')
    bars2 = ax3.bar(x + width/2, quic_recv, width, label='QUIC', color='#4CAF50', edgecolor='black')
    ax3.axhline(y=NUM_FRAMES, color='red', linestyle='--', alpha=0.7, label=f'Cible ({NUM_FRAMES})')
    ax3.set_ylabel('Frames reçues', fontsize=12)
    ax3.set_title('Nombre de Frames Reçues', fontsize=14, fontweight='bold')
    ax3.set_xticks(x)
    ax3.set_xticklabels(scenarios)
    ax3.legend()
    
    # 4. Tableau récapitulatif
    ax4 = fig.add_subplot(2, 2, 4)
    ax4.axis('off')
    
    table_data = [
        ['Scénario', 'Perte', 'Délai', 'TCP\nReçues', 'TCP\nTaux', 'QUIC\nReçues', 'QUIC\nTaux']
    ]
    
    for r in all_results:
        s = r['scenario']
        t = r['results']['tcp']
        q = r['results']['quic']
        table_data.append([
            s['name'],
            f"{s['loss']}%",
            s['delay'],
            str(t['received']),
            f"{t['rate']:.1f}%",
            str(q['received']),
            f"{q['rate']:.1f}%"
        ])
    
    table = ax4.table(cellText=table_data, loc='center', cellLoc='center')
    table.auto_set_font_size(False)
    table.set_fontsize(11)
    table.scale(1.2, 2)
    
    # Style header
    for i in range(len(table_data[0])):
        table[(0, i)].set_facecolor('#404040')
        table[(0, i)].set_text_props(color='white', fontweight='bold')
    
    # Colorer les cellules selon le taux
    for row in range(1, len(table_data)):
        tcp_rate = float(table_data[row][4].replace('%', ''))
        quic_rate = float(table_data[row][6].replace('%', ''))
        
        if tcp_rate >= 99:
            table[(row, 3)].set_facecolor('#C8E6C9')
            table[(row, 4)].set_facecolor('#C8E6C9')
        elif tcp_rate >= 90:
            table[(row, 3)].set_facecolor('#FFF9C4')
            table[(row, 4)].set_facecolor('#FFF9C4')
        else:
            table[(row, 3)].set_facecolor('#FFCDD2')
            table[(row, 4)].set_facecolor('#FFCDD2')
        
        if quic_rate >= 99:
            table[(row, 5)].set_facecolor('#C8E6C9')
            table[(row, 6)].set_facecolor('#C8E6C9')
        elif quic_rate >= 90:
            table[(row, 5)].set_facecolor('#FFF9C4')
            table[(row, 6)].set_facecolor('#FFF9C4')
        else:
            table[(row, 5)].set_facecolor('#FFCDD2')
            table[(row, 6)].set_facecolor('#FFCDD2')
    
    ax4.set_title('Tableau Récapitulatif', fontsize=14, fontweight='bold', pad=20)
    
    plt.tight_layout(rect=[0, 0.03, 1, 0.95])
    
    output_file = os.path.join(WORK_DIR, 'TCP_vs_QUIC_FINAL.png')
    plt.savefig(output_file, dpi=150, bbox_inches='tight', facecolor='white')
    print(f"✅ Graphique sauvegardé: {output_file}")
    plt.close()
    
    return output_file


def print_final_results(all_results):
    """Affiche les résultats finaux"""
    print("\n" + "="*70)
    print("📋 RÉSULTATS FINAUX - TCP vs QUIC")
    print("="*70)
    
    print(f"\n{'Scénario':<12} {'Perte':<8} {'│ TCP':<20} {'│ QUIC':<20}")
    print(f"{'':12} {'':8} {'│ Reçues':<10} {'Taux':<10} {'│ Reçues':<10} {'Taux':<10}")
    print("─"*70)
    
    for r in all_results:
        s = r['scenario']
        t = r['results']['tcp']
        q = r['results']['quic']
        
        tcp_status = "✅" if t['rate'] >= 99 else "⚠️" if t['rate'] >= 90 else "❌"
        quic_status = "✅" if q['rate'] >= 99 else "⚠️" if q['rate'] >= 90 else "❌"
        
        print(f"{s['name']:<12} {s['loss']}%{'':<5} │ {t['received']:<9} {t['rate']:.1f}% {tcp_status:<3} │ {q['received']:<9} {q['rate']:.1f}% {quic_status}")
    
    print("─"*70)
    
    # Analyse
    print("\n" + "="*70)
    print("📊 ANALYSE")
    print("="*70)
    
    print("""
Les deux protocoles (TCP et QUIC) sont des protocoles FIABLES:
- Ils garantissent la livraison des données via retransmissions
- Le taux de livraison devrait être ~100% dans tous les cas

Différences observées:
- TCP: Implémenté dans le kernel Linux (optimisé)
- QUIC: Implémenté en userspace (aioquic en Python)

Pour le cloud gaming:
- TCP: Simple, fiable, mais Head-of-Line blocking
- QUIC: Streams multiplexés, pas de HoL blocking, 0-RTT
""")
    
    print("="*70)


def main():
    all_results = []
    
    for scenario in SCENARIOS:
        result = run_scenario(scenario)
        all_results.append(result)
        time.sleep(2)
    
    # Graphiques
    graph_file = generate_graphs(all_results)
    
    # Résultats
    print_final_results(all_results)
    
    # Sauvegarder JSON
    json_file = os.path.join(WORK_DIR, 'TCP_vs_QUIC_FINAL.json')
    with open(json_file, 'w') as f:
        # Retirer les latencies pour réduire la taille
        export_data = []
        for r in all_results:
            export_data.append({
                'scenario': r['scenario'],
                'tcp': {k: v for k, v in r['results']['tcp'].items() if k != 'latencies'},
                'quic': {k: v for k, v in r['results']['quic'].items() if k != 'latencies'}
            })
        json.dump(export_data, f, indent=2)
    
    print(f"\n📁 Fichiers générés:")
    print(f"   📊 {graph_file}")
    print(f"   📄 {json_file}")
    print("\n" + "="*70)
    print("✅ TESTS TERMINÉS!")
    print("="*70)


if __name__ == '__main__':
    main()
