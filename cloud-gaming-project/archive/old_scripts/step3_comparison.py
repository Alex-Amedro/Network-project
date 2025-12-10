#!/usr/bin/env python3
"""
ÉTAPE 3 : Comparaison TCP vs QUIC sur localhost
Avec mesures de latence et génération de graphiques
"""

import socket
import struct
import time
import threading
import asyncio
import json
import ssl
import os
import sys

# Imports QUIC
from aioquic.asyncio import connect, serve
from aioquic.asyncio.protocol import QuicConnectionProtocol
from aioquic.quic.configuration import QuicConfiguration
from aioquic.quic.events import StreamDataReceived, ConnectionTerminated

# Import matplotlib
import matplotlib
matplotlib.use('Agg')  # Backend non-interactif
import matplotlib.pyplot as plt
import numpy as np

# Paramètres
HOST = '127.0.0.1'
NUM_FRAMES = 200
FRAME_SIZE = 10000  # 10 KB
FPS = 60

CERT_FILE = 'server.cert'
KEY_FILE = 'server.key'

print("="*70)
print("ÉTAPE 3 : COMPARAISON TCP vs QUIC")
print("="*70)
print(f"Configuration: {NUM_FRAMES} frames, {FRAME_SIZE} bytes, {FPS} FPS")
print("="*70)

# ================== TCP ==================

def test_tcp():
    """Test TCP complet"""
    print("\n" + "-"*50)
    print("🔵 TEST TCP")
    print("-"*50)
    
    results = {
        'frames_sent': 0,
        'frames_received': 0,
        'send_times': [],
        'recv_times': [],
        'latencies': []
    }
    
    server_ready = threading.Event()
    stop_server = threading.Event()
    
    def server():
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((HOST, 7001))
        sock.listen(1)
        sock.settimeout(30)
        server_ready.set()
        
        try:
            conn, _ = sock.accept()
            conn.settimeout(10)
            
            while not stop_server.is_set():
                try:
                    # Lire header (4 bytes taille + 8 bytes timestamp)
                    header = b''
                    while len(header) < 12:
                        chunk = conn.recv(12 - len(header))
                        if not chunk:
                            return
                        header += chunk
                    
                    frame_size, send_ts = struct.unpack('!Id', header)
                    
                    # Lire données
                    data = b''
                    while len(data) < frame_size:
                        chunk = conn.recv(min(65536, frame_size - len(data)))
                        if not chunk:
                            return
                        data += chunk
                    
                    recv_time = time.time()
                    results['frames_received'] += 1
                    results['recv_times'].append(recv_time)
                    results['latencies'].append((recv_time - send_ts) * 1000)  # ms
                    
                except socket.timeout:
                    continue
                except:
                    break
            
            conn.close()
        except:
            pass
        finally:
            sock.close()
    
    # Lancer serveur
    server_thread = threading.Thread(target=server)
    server_thread.start()
    server_ready.wait()
    time.sleep(0.3)
    
    # Client
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((HOST, 7001))
    
    start_time = time.time()
    
    for i in range(NUM_FRAMES):
        send_time = time.time()
        frame_data = bytes([i % 256] * FRAME_SIZE)
        
        # Envoyer: taille + timestamp + données
        sock.sendall(struct.pack('!Id', len(frame_data), send_time))
        sock.sendall(frame_data)
        
        results['frames_sent'] += 1
        results['send_times'].append(send_time)
        
        # FPS timing
        expected = start_time + (i + 1) / FPS
        sleep_time = expected - time.time()
        if sleep_time > 0:
            time.sleep(sleep_time)
    
    duration = time.time() - start_time
    
    time.sleep(0.5)
    sock.close()
    stop_server.set()
    server_thread.join(timeout=3)
    
    results['duration'] = duration
    results['actual_fps'] = results['frames_sent'] / duration
    results['avg_latency'] = np.mean(results['latencies']) if results['latencies'] else 0
    results['jitter'] = np.std(results['latencies']) if results['latencies'] else 0
    
    print(f"   Envoyées: {results['frames_sent']}, Reçues: {results['frames_received']}")
    print(f"   Taux: {results['frames_received']/results['frames_sent']*100:.1f}%")
    print(f"   FPS: {results['actual_fps']:.1f}")
    print(f"   Latence moyenne: {results['avg_latency']:.2f} ms")
    print(f"   Jitter: {results['jitter']:.2f} ms")
    
    return results


# ================== QUIC ==================

quic_results = {
    'frames_sent': 0,
    'frames_received': 0,
    'send_times': [],
    'recv_times': [],
    'latencies': []
}

class QuicServer(QuicConnectionProtocol):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.buffer = b''
    
    def quic_event_received(self, event):
        if isinstance(event, StreamDataReceived):
            self.buffer += event.data
            
            # Extraire frames (12 bytes header: 4 taille + 8 timestamp)
            while len(self.buffer) >= 12:
                frame_size, send_ts = struct.unpack('!Id', self.buffer[:12])
                total = 12 + frame_size
                
                if len(self.buffer) >= total:
                    self.buffer = self.buffer[total:]
                    recv_time = time.time()
                    quic_results['frames_received'] += 1
                    quic_results['recv_times'].append(recv_time)
                    quic_results['latencies'].append((recv_time - send_ts) * 1000)
                else:
                    break


async def test_quic():
    """Test QUIC complet"""
    print("\n" + "-"*50)
    print("🟢 TEST QUIC")
    print("-"*50)
    
    global quic_results
    quic_results = {
        'frames_sent': 0,
        'frames_received': 0,
        'send_times': [],
        'recv_times': [],
        'latencies': []
    }
    
    # Serveur
    config = QuicConfiguration(is_client=False, alpn_protocols=["test"])
    config.load_cert_chain(CERT_FILE, KEY_FILE)
    
    server = await serve(HOST, 7002, configuration=config, create_protocol=QuicServer)
    await asyncio.sleep(0.3)
    
    # Client
    config_client = QuicConfiguration(is_client=True, alpn_protocols=["test"])
    config_client.verify_mode = ssl.CERT_NONE
    
    start_time = time.time()
    
    async with connect(HOST, 7002, configuration=config_client) as protocol:
        stream_id = protocol._quic.get_next_available_stream_id()
        
        for i in range(NUM_FRAMES):
            send_time = time.time()
            frame_data = bytes([i % 256] * FRAME_SIZE)
            
            msg = struct.pack('!Id', len(frame_data), send_time) + frame_data
            protocol._quic.send_stream_data(stream_id, msg, end_stream=(i == NUM_FRAMES - 1))
            protocol.transmit()
            
            quic_results['frames_sent'] += 1
            quic_results['send_times'].append(send_time)
            
            expected = start_time + (i + 1) / FPS
            sleep_time = expected - time.time()
            if sleep_time > 0:
                await asyncio.sleep(sleep_time)
        
        await asyncio.sleep(1)
    
    duration = time.time() - start_time
    server.close()
    
    quic_results['duration'] = duration
    quic_results['actual_fps'] = quic_results['frames_sent'] / duration
    quic_results['avg_latency'] = np.mean(quic_results['latencies']) if quic_results['latencies'] else 0
    quic_results['jitter'] = np.std(quic_results['latencies']) if quic_results['latencies'] else 0
    
    print(f"   Envoyées: {quic_results['frames_sent']}, Reçues: {quic_results['frames_received']}")
    print(f"   Taux: {quic_results['frames_received']/quic_results['frames_sent']*100:.1f}%")
    print(f"   FPS: {quic_results['actual_fps']:.1f}")
    print(f"   Latence moyenne: {quic_results['avg_latency']:.2f} ms")
    print(f"   Jitter: {quic_results['jitter']:.2f} ms")
    
    return quic_results


# ================== MAIN ==================

def generate_graphs(tcp_res, quic_res):
    """Génère les graphiques de comparaison"""
    print("\n" + "-"*50)
    print("📊 GÉNÉRATION DES GRAPHIQUES")
    print("-"*50)
    
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    fig.suptitle('Comparaison TCP vs QUIC - Cloud Gaming Simulation', fontsize=14, fontweight='bold')
    
    # 1. Taux de livraison
    ax1 = axes[0, 0]
    protocols = ['TCP', 'QUIC']
    delivery = [
        tcp_res['frames_received'] / tcp_res['frames_sent'] * 100,
        quic_res['frames_received'] / quic_res['frames_sent'] * 100
    ]
    colors = ['#2196F3', '#4CAF50']
    bars = ax1.bar(protocols, delivery, color=colors, edgecolor='black', linewidth=1.5)
    ax1.set_ylabel('Taux de livraison (%)')
    ax1.set_title('Taux de Livraison')
    ax1.set_ylim(0, 110)
    ax1.axhline(y=100, color='red', linestyle='--', alpha=0.5, label='100%')
    for bar, val in zip(bars, delivery):
        ax1.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 2, 
                f'{val:.1f}%', ha='center', fontweight='bold')
    
    # 2. Latence moyenne
    ax2 = axes[0, 1]
    latencies = [tcp_res['avg_latency'], quic_res['avg_latency']]
    bars = ax2.bar(protocols, latencies, color=colors, edgecolor='black', linewidth=1.5)
    ax2.set_ylabel('Latence moyenne (ms)')
    ax2.set_title('Latence Moyenne')
    for bar, val in zip(bars, latencies):
        ax2.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.02, 
                f'{val:.2f} ms', ha='center', fontweight='bold')
    
    # 3. Distribution des latences
    ax3 = axes[1, 0]
    if tcp_res['latencies'] and quic_res['latencies']:
        ax3.hist(tcp_res['latencies'], bins=30, alpha=0.7, label='TCP', color='#2196F3')
        ax3.hist(quic_res['latencies'], bins=30, alpha=0.7, label='QUIC', color='#4CAF50')
        ax3.set_xlabel('Latence (ms)')
        ax3.set_ylabel('Nombre de frames')
        ax3.set_title('Distribution des Latences')
        ax3.legend()
    
    # 4. Jitter
    ax4 = axes[1, 1]
    jitter = [tcp_res['jitter'], quic_res['jitter']]
    bars = ax4.bar(protocols, jitter, color=colors, edgecolor='black', linewidth=1.5)
    ax4.set_ylabel('Jitter (ms)')
    ax4.set_title('Jitter (écart-type de la latence)')
    for bar, val in zip(bars, jitter):
        ax4.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.01, 
                f'{val:.2f} ms', ha='center', fontweight='bold')
    
    plt.tight_layout()
    
    # Sauvegarder
    output_file = 'tcp_vs_quic_comparison.png'
    plt.savefig(output_file, dpi=150, bbox_inches='tight')
    print(f"✅ Graphique sauvegardé: {output_file}")
    
    plt.close()


def print_summary(tcp_res, quic_res):
    """Affiche un résumé comparatif"""
    print("\n" + "="*70)
    print("📋 RÉSUMÉ COMPARATIF")
    print("="*70)
    
    print(f"\n{'Métrique':<25} {'TCP':<20} {'QUIC':<20}")
    print("-"*65)
    
    print(f"{'Frames envoyées':<25} {tcp_res['frames_sent']:<20} {quic_res['frames_sent']:<20}")
    print(f"{'Frames reçues':<25} {tcp_res['frames_received']:<20} {quic_res['frames_received']:<20}")
    
    tcp_rate = tcp_res['frames_received'] / tcp_res['frames_sent'] * 100
    quic_rate = quic_res['frames_received'] / quic_res['frames_sent'] * 100
    print(f"{'Taux de livraison':<25} {tcp_rate:.1f}%{'':<16} {quic_rate:.1f}%")
    
    print(f"{'FPS réel':<25} {tcp_res['actual_fps']:.1f}{'':<17} {quic_res['actual_fps']:.1f}")
    print(f"{'Latence moyenne (ms)':<25} {tcp_res['avg_latency']:.2f}{'':<17} {quic_res['avg_latency']:.2f}")
    print(f"{'Jitter (ms)':<25} {tcp_res['jitter']:.2f}{'':<17} {quic_res['jitter']:.2f}")
    
    print("\n" + "="*70)
    print("VÉRIFICATION DES RÉSULTATS")
    print("="*70)
    
    all_ok = True
    
    # Vérifier TCP
    if tcp_rate == 100.0:
        print("✅ TCP: 100% de livraison (attendu pour un protocole fiable)")
    else:
        print(f"⚠️  TCP: {tcp_rate:.1f}% de livraison (devrait être 100%)")
        all_ok = False
    
    # Vérifier QUIC
    if quic_rate >= 99.0:
        print(f"✅ QUIC: {quic_rate:.1f}% de livraison (attendu pour un protocole fiable)")
    else:
        print(f"⚠️  QUIC: {quic_rate:.1f}% de livraison (devrait être ~100%)")
        all_ok = False
    
    # Vérifier cohérence
    if tcp_res['frames_sent'] == NUM_FRAMES:
        print(f"✅ TCP a bien envoyé {NUM_FRAMES} frames")
    else:
        print(f"❌ TCP a envoyé {tcp_res['frames_sent']} frames au lieu de {NUM_FRAMES}")
        all_ok = False
    
    if quic_res['frames_sent'] == NUM_FRAMES:
        print(f"✅ QUIC a bien envoyé {NUM_FRAMES} frames")
    else:
        print(f"❌ QUIC a envoyé {quic_res['frames_sent']} frames au lieu de {NUM_FRAMES}")
        all_ok = False
    
    print("="*70)
    
    if all_ok:
        print("🎉 TOUS LES TESTS SONT COHÉRENTS ET VALIDES!")
    else:
        print("⚠️  Certains tests ont des problèmes - vérifier les résultats")
    
    print("="*70)
    
    return all_ok


async def main():
    # Test TCP
    tcp_results = test_tcp()
    
    await asyncio.sleep(1)
    
    # Test QUIC
    quic_results = await test_quic()
    
    # Générer graphiques
    generate_graphs(tcp_results, quic_results)
    
    # Résumé
    success = print_summary(tcp_results, quic_results)
    
    # Sauvegarder résultats JSON
    all_results = {
        'config': {
            'num_frames': NUM_FRAMES,
            'frame_size': FRAME_SIZE,
            'fps': FPS
        },
        'tcp': {
            'frames_sent': tcp_results['frames_sent'],
            'frames_received': tcp_results['frames_received'],
            'delivery_rate': tcp_results['frames_received'] / tcp_results['frames_sent'] * 100,
            'actual_fps': tcp_results['actual_fps'],
            'avg_latency_ms': tcp_results['avg_latency'],
            'jitter_ms': tcp_results['jitter']
        },
        'quic': {
            'frames_sent': quic_results['frames_sent'],
            'frames_received': quic_results['frames_received'],
            'delivery_rate': quic_results['frames_received'] / quic_results['frames_sent'] * 100,
            'actual_fps': quic_results['actual_fps'],
            'avg_latency_ms': quic_results['avg_latency'],
            'jitter_ms': quic_results['jitter']
        }
    }
    
    with open('step3_comparison_results.json', 'w') as f:
        json.dump(all_results, f, indent=2)
    
    print(f"\n📁 Résultats sauvegardés dans step3_comparison_results.json")
    print(f"📊 Graphique: tcp_vs_quic_comparison.png")
    
    return success


if __name__ == '__main__':
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
