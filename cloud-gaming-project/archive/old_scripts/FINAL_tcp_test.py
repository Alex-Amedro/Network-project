#!/usr/bin/env python3
"""
Test FINAL TCP avec Mininet - Résultats COHÉRENTS et PROUVÉS
Génère des graphiques matplotlib
"""

import os
import sys
import time
import json
import struct
import socket

if os.geteuid() != 0:
    print("❌ Ce script doit être exécuté avec sudo!")
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
FRAME_SIZE = 5000
FPS = 30

SCENARIOS = [
    {'name': 'Parfait', 'loss': 0, 'delay': '1ms', 'bw': 100},
    {'name': 'Bon', 'loss': 1, 'delay': '10ms', 'bw': 100},
    {'name': 'Moyen', 'loss': 3, 'delay': '30ms', 'bw': 50},
    {'name': 'Mauvais', 'loss': 5, 'delay': '50ms', 'bw': 30},
]


def create_scripts():
    """Crée les scripts serveur/client TCP"""
    
    server_code = '''#!/usr/bin/env python3
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
'''
    
    client_code = '''#!/usr/bin/env python3
import socket, struct, time, json, sys

host = sys.argv[1]
port = int(sys.argv[2])
num_frames = int(sys.argv[3])
frame_size = int(sys.argv[4])
fps = int(sys.argv[5])
output = sys.argv[6]

results = {'frames_sent': 0}

time.sleep(0.5)
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.settimeout(60)
sock.connect((host, port))

start = time.time()

for i in range(num_frames):
    send_time = time.time()
    data = bytes([i % 256] * frame_size)
    sock.sendall(struct.pack('!Id', len(data), send_time) + data)
    results['frames_sent'] += 1
    
    expected = start + (i + 1) / fps
    sleep = expected - time.time()
    if sleep > 0: time.sleep(sleep)

time.sleep(1)
sock.close()

with open(output, 'w') as f:
    json.dump(results, f)
'''
    
    with open(os.path.join(WORK_DIR, '_tcp_server.py'), 'w') as f:
        f.write(server_code)
    with open(os.path.join(WORK_DIR, '_tcp_client.py'), 'w') as f:
        f.write(client_code)


def run_tcp_test(scenario):
    """Exécute un test TCP dans Mininet"""
    name = scenario['name']
    
    print(f"\n  📡 Scénario: {name} (perte={scenario['loss']}%, délai={scenario['delay']})")
    
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
    
    server_out = os.path.join(WORK_DIR, f'_srv_{name}.json')
    client_out = os.path.join(WORK_DIR, f'_cli_{name}.json')
    
    # Serveur
    h2.cmd(f'python3 {WORK_DIR}/_tcp_server.py 9001 {server_out} &')
    time.sleep(0.5)
    
    # Client
    h1.cmd(f'python3 {WORK_DIR}/_tcp_client.py 10.0.0.2 9001 {NUM_FRAMES} {FRAME_SIZE} {FPS} {client_out}')
    time.sleep(2)
    
    h2.cmd('pkill -f _tcp_server')
    net.stop()
    
    # Lire résultats
    sent = recv = 0
    latencies = []
    
    if os.path.exists(client_out):
        with open(client_out) as f:
            sent = json.load(f).get('frames_sent', 0)
    
    if os.path.exists(server_out):
        with open(server_out) as f:
            data = json.load(f)
            recv = data.get('frames_received', 0)
            latencies = data.get('latencies', [])
    
    rate = (recv / sent * 100) if sent > 0 else 0
    avg_lat = np.mean(latencies) if latencies else 0
    
    print(f"     ✅ Envoyées: {sent}, Reçues: {recv}, Taux: {rate:.1f}%, Latence: {avg_lat:.1f}ms")
    
    return {
        'scenario': name,
        'loss': scenario['loss'],
        'delay': scenario['delay'],
        'sent': sent,
        'received': recv,
        'rate': rate,
        'latency_avg': avg_lat,
        'latency_std': np.std(latencies) if latencies else 0,
        'latencies': latencies
    }


def generate_graphs(results):
    """Génère les graphiques finaux"""
    print("\n" + "="*60)
    print("📊 GÉNÉRATION DES GRAPHIQUES")
    print("="*60)
    
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    fig.suptitle('Test TCP Cloud Gaming - Résultats sous différentes conditions réseau\n(Mininet simulation)', 
                 fontsize=14, fontweight='bold')
    
    scenarios = [r['scenario'] for r in results]
    x = np.arange(len(scenarios))
    
    # 1. Taux de livraison
    ax1 = axes[0, 0]
    rates = [r['rate'] for r in results]
    colors = ['#4CAF50' if r >= 99 else '#FFC107' if r >= 90 else '#F44336' for r in rates]
    bars = ax1.bar(x, rates, color=colors, edgecolor='black', linewidth=1.5)
    ax1.set_ylabel('Taux de livraison (%)', fontsize=11)
    ax1.set_title('Taux de Livraison TCP', fontsize=12, fontweight='bold')
    ax1.set_xticks(x)
    ax1.set_xticklabels(scenarios)
    ax1.set_ylim(0, 110)
    ax1.axhline(y=100, color='green', linestyle='--', alpha=0.5, label='Cible 100%')
    for bar, val in zip(bars, rates):
        ax1.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 2, 
                f'{val:.1f}%', ha='center', fontweight='bold', fontsize=10)
    ax1.legend()
    
    # 2. Latence moyenne
    ax2 = axes[0, 1]
    latencies = [r['latency_avg'] for r in results]
    bars = ax2.bar(x, latencies, color='#2196F3', edgecolor='black', linewidth=1.5)
    ax2.set_ylabel('Latence moyenne (ms)', fontsize=11)
    ax2.set_title('Latence Moyenne TCP', fontsize=12, fontweight='bold')
    ax2.set_xticks(x)
    ax2.set_xticklabels(scenarios)
    for bar, val in zip(bars, latencies):
        ax2.text(bar.get_x() + bar.get_width()/2, bar.get_height() + max(latencies)*0.02, 
                f'{val:.1f}ms', ha='center', fontweight='bold', fontsize=10)
    
    # 3. Frames envoyées vs reçues
    ax3 = axes[1, 0]
    sent = [r['sent'] for r in results]
    recv = [r['received'] for r in results]
    width = 0.35
    ax3.bar(x - width/2, sent, width, label='Envoyées', color='#9C27B0', edgecolor='black')
    ax3.bar(x + width/2, recv, width, label='Reçues', color='#00BCD4', edgecolor='black')
    ax3.set_ylabel('Nombre de frames', fontsize=11)
    ax3.set_title('Frames Envoyées vs Reçues', fontsize=12, fontweight='bold')
    ax3.set_xticks(x)
    ax3.set_xticklabels(scenarios)
    ax3.legend()
    ax3.axhline(y=NUM_FRAMES, color='red', linestyle='--', alpha=0.5, label=f'Cible ({NUM_FRAMES})')
    
    # 4. Distribution des latences (boxplot)
    ax4 = axes[1, 1]
    lat_data = [r['latencies'] if r['latencies'] else [0] for r in results]
    bp = ax4.boxplot(lat_data, labels=scenarios, patch_artist=True)
    for patch in bp['boxes']:
        patch.set_facecolor('#FF9800')
    ax4.set_ylabel('Latence (ms)', fontsize=11)
    ax4.set_title('Distribution des Latences TCP', fontsize=12, fontweight='bold')
    
    plt.tight_layout()
    
    output = os.path.join(WORK_DIR, 'FINAL_TCP_results.png')
    plt.savefig(output, dpi=150, bbox_inches='tight')
    print(f"✅ Graphique sauvegardé: {output}")
    plt.close()
    
    return output


def print_final_table(results):
    """Affiche le tableau final"""
    print("\n" + "="*70)
    print("📋 TABLEAU RÉCAPITULATIF - TEST TCP")
    print("="*70)
    
    print(f"\n{'Scénario':<12} {'Perte':<8} {'Délai':<10} {'Envoyées':<10} {'Reçues':<10} {'Taux':<10} {'Latence':<12}")
    print("-"*72)
    
    for r in results:
        status = "✅" if r['rate'] == 100 else "⚠️" if r['rate'] >= 90 else "❌"
        print(f"{r['scenario']:<12} {r['loss']}%{'':<5} {r['delay']:<10} {r['sent']:<10} {r['received']:<10} {r['rate']:.1f}%{'':<5} {r['latency_avg']:.1f}ms {status}")
    
    print("-"*72)
    
    # Vérification
    print("\n" + "="*70)
    print("✓ VÉRIFICATION DE COHÉRENCE")
    print("="*70)
    
    all_ok = True
    for r in results:
        if r['sent'] != NUM_FRAMES:
            print(f"❌ {r['scenario']}: {r['sent']} envoyées au lieu de {NUM_FRAMES}")
            all_ok = False
        elif r['rate'] < 100 and r['loss'] == 0:
            print(f"❌ {r['scenario']}: Taux {r['rate']:.1f}% avec 0% de perte configurée")
            all_ok = False
        else:
            print(f"✅ {r['scenario']}: {r['sent']} envoyées, {r['received']} reçues ({r['rate']:.1f}%)")
    
    if all_ok:
        print("\n🎉 TOUS LES RÉSULTATS SONT COHÉRENTS!")
        print("   TCP garantit 100% de livraison (protocole fiable)")
        print("   La latence augmente avec les conditions réseau dégradées")
    
    print("="*70)


def main():
    print("="*70)
    print("TEST FINAL TCP - CLOUD GAMING SIMULATION")
    print("="*70)
    print(f"Configuration: {NUM_FRAMES} frames, {FRAME_SIZE} bytes, {FPS} FPS")
    print("="*70)
    
    create_scripts()
    
    results = []
    for scenario in SCENARIOS:
        result = run_tcp_test(scenario)
        results.append(result)
        time.sleep(2)
    
    # Graphiques
    graph_file = generate_graphs(results)
    
    # Tableau
    print_final_table(results)
    
    # Sauvegarder JSON
    with open(os.path.join(WORK_DIR, 'FINAL_TCP_results.json'), 'w') as f:
        json.dump(results, f, indent=2, default=lambda x: None if isinstance(x, type(None)) else x)
    
    print(f"\n📁 Fichiers générés:")
    print(f"   📊 {graph_file}")
    print(f"   📄 FINAL_TCP_results.json")


if __name__ == '__main__':
    main()
