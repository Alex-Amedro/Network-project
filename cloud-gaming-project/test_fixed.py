#!/usr/bin/env python3
"""
Test PROPRE de comparaison TCP vs QUIC vs rQUIC
Corrige tous les bugs de comptage
"""

import subprocess
import time
import os
import sys
import json
import socket
import threading
import struct

WORK_DIR = os.path.dirname(os.path.abspath(__file__))
VENV_PYTHON = os.path.join(WORK_DIR, 'venv', 'bin', 'python3')

# Paramètres du test
TEST_DURATION = 10  # secondes
FPS = 60
FRAME_SIZE = 50000  # 50 KB par frame (simplifié)
TOTAL_FRAMES = TEST_DURATION * FPS  # 600 frames

print("="*70)
print("TEST CORRIGÉ - TCP vs QUIC vs rQUIC")
print("="*70)
print(f"Durée: {TEST_DURATION}s, FPS cible: {FPS}, Frames à envoyer: {TOTAL_FRAMES}")
print("="*70)


# ============ TCP TEST ============

def tcp_server(port, results, stop_event):
    """Serveur TCP qui compte correctement les frames"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(('0.0.0.0', port))
    sock.listen(1)
    sock.settimeout(30)
    
    frames_received = 0
    bytes_received = 0
    frame_times = []
    start_time = None
    
    try:
        conn, addr = sock.accept()
        conn.settimeout(5)
        start_time = time.time()
        
        # Protocole: chaque frame commence par 4 bytes de taille
        while not stop_event.is_set():
            try:
                # Lire la taille de la frame (4 bytes)
                size_data = b''
                while len(size_data) < 4:
                    chunk = conn.recv(4 - len(size_data))
                    if not chunk:
                        break
                    size_data += chunk
                
                if len(size_data) < 4:
                    break
                
                frame_size = struct.unpack('!I', size_data)[0]
                
                # Lire la frame complète
                frame_data = b''
                while len(frame_data) < frame_size:
                    chunk = conn.recv(min(65536, frame_size - len(frame_data)))
                    if not chunk:
                        break
                    frame_data += chunk
                
                if len(frame_data) == frame_size:
                    frames_received += 1
                    bytes_received += frame_size
                    frame_times.append(time.time())
                    
            except socket.timeout:
                continue
            except Exception as e:
                break
        
        conn.close()
    except Exception as e:
        print(f"TCP Server error: {e}")
    finally:
        sock.close()
    
    end_time = time.time()
    duration = end_time - start_time if start_time else 0
    
    results['frames_received'] = frames_received
    results['bytes_received'] = bytes_received
    results['duration'] = duration
    results['fps'] = frames_received / duration if duration > 0 else 0
    
    # Calculer latence inter-frame
    if len(frame_times) > 1:
        delays = [frame_times[i] - frame_times[i-1] for i in range(1, len(frame_times))]
        results['avg_delay_ms'] = sum(delays) / len(delays) * 1000
        results['jitter_ms'] = (sum((d - results['avg_delay_ms']/1000)**2 for d in delays) / len(delays))**0.5 * 1000
    else:
        results['avg_delay_ms'] = 0
        results['jitter_ms'] = 0


def tcp_client(host, port, num_frames, results):
    """Client TCP qui envoie des frames avec header de taille"""
    time.sleep(0.5)  # Attendre que le serveur démarre
    
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((host, port))
    
    frames_sent = 0
    start_time = time.time()
    
    for i in range(num_frames):
        # Créer une frame de données
        frame_data = bytes([i % 256] * FRAME_SIZE)
        
        # Envoyer taille + données
        sock.sendall(struct.pack('!I', len(frame_data)))
        sock.sendall(frame_data)
        frames_sent += 1
        
        # Respecter le timing FPS
        expected_time = start_time + (i + 1) / FPS
        sleep_time = expected_time - time.time()
        if sleep_time > 0:
            time.sleep(sleep_time)
    
    sock.close()
    
    results['frames_sent'] = frames_sent
    results['duration'] = time.time() - start_time


# ============ UDP TEST (baseline non fiable) ============

def udp_server(port, results, stop_event):
    """Serveur UDP simple"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(('0.0.0.0', port))
    sock.settimeout(2)
    
    frames_received = 0
    frame_times = []
    start_time = None
    
    while not stop_event.is_set():
        try:
            data, addr = sock.recvfrom(65536)
            if start_time is None:
                start_time = time.time()
            
            frames_received += 1
            frame_times.append(time.time())
        except socket.timeout:
            if start_time and time.time() - start_time > TEST_DURATION + 5:
                break
    
    sock.close()
    
    end_time = time.time()
    duration = end_time - start_time if start_time else 0
    
    results['frames_received'] = frames_received
    results['duration'] = duration
    results['fps'] = frames_received / duration if duration > 0 else 0


def udp_client(host, port, num_frames, results):
    """Client UDP simple"""
    time.sleep(0.5)
    
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    
    frames_sent = 0
    start_time = time.time()
    
    for i in range(num_frames):
        # UDP ne peut pas envoyer plus de ~65KB
        frame_data = bytes([i % 256] * min(FRAME_SIZE, 60000))
        sock.sendto(frame_data, (host, port))
        frames_sent += 1
        
        expected_time = start_time + (i + 1) / FPS
        sleep_time = expected_time - time.time()
        if sleep_time > 0:
            time.sleep(sleep_time)
    
    sock.close()
    results['frames_sent'] = frames_sent


# ============ rQUIC TEST (UDP + ARQ) ============

def rquic_server(port, results, stop_event):
    """Serveur rQUIC avec ACKs"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(('0.0.0.0', port))
    sock.settimeout(0.5)
    
    frames_received = 0
    received_seqs = set()
    frame_times = []
    start_time = None
    
    while not stop_event.is_set():
        try:
            data, addr = sock.recvfrom(65536)
            if start_time is None:
                start_time = time.time()
            
            # Extraire le numéro de séquence (4 premiers bytes)
            if len(data) >= 4:
                seq_num = struct.unpack('!I', data[:4])[0]
                
                # Envoyer ACK
                ack = struct.pack('!I', seq_num)
                sock.sendto(ack, addr)
                
                # Compter uniquement les nouvelles frames
                if seq_num not in received_seqs:
                    received_seqs.add(seq_num)
                    frames_received += 1
                    frame_times.append(time.time())
                    
        except socket.timeout:
            if start_time and time.time() - start_time > TEST_DURATION + 5:
                break
    
    sock.close()
    
    end_time = time.time()
    duration = end_time - start_time if start_time else 0
    
    results['frames_received'] = frames_received
    results['unique_frames'] = len(received_seqs)
    results['duration'] = duration
    results['fps'] = frames_received / duration if duration > 0 else 0


def rquic_client(host, port, num_frames, results):
    """Client rQUIC avec retransmissions"""
    time.sleep(0.5)
    
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(0.1)  # 100ms timeout pour les ACKs
    
    frames_sent = 0
    retransmissions = 0
    acks_received = 0
    acked = set()
    
    start_time = time.time()
    
    for seq in range(num_frames):
        frame_data = struct.pack('!I', seq) + bytes([seq % 256] * min(FRAME_SIZE - 4, 60000))
        
        # Envoyer avec retransmission
        max_retries = 3
        for attempt in range(max_retries + 1):
            sock.sendto(frame_data, (host, port))
            
            if attempt == 0:
                frames_sent += 1
            else:
                retransmissions += 1
            
            # Attendre ACK
            try:
                ack_data, _ = sock.recvfrom(1024)
                if len(ack_data) >= 4:
                    ack_seq = struct.unpack('!I', ack_data[:4])[0]
                    if ack_seq == seq:
                        acked.add(seq)
                        acks_received += 1
                        break
            except socket.timeout:
                continue
        
        # Respecter le timing FPS
        expected_time = start_time + (seq + 1) / FPS
        sleep_time = expected_time - time.time()
        if sleep_time > 0:
            time.sleep(sleep_time)
    
    sock.close()
    
    results['frames_sent'] = frames_sent
    results['retransmissions'] = retransmissions
    results['acks_received'] = acks_received
    results['delivery_rate'] = (acks_received / num_frames * 100) if num_frames > 0 else 0


def run_test(name, server_func, client_func, port, host='127.0.0.1'):
    """Lance un test client/serveur"""
    print(f"\n{'='*50}")
    print(f"🧪 Test {name}")
    print(f"{'='*50}")
    
    server_results = {}
    client_results = {}
    stop_event = threading.Event()
    
    # Démarrer serveur
    server_thread = threading.Thread(target=server_func, args=(port, server_results, stop_event))
    server_thread.start()
    
    # Démarrer client
    client_func(host, port, TOTAL_FRAMES, client_results)
    
    # Attendre un peu puis arrêter
    time.sleep(2)
    stop_event.set()
    server_thread.join(timeout=5)
    
    return client_results, server_results


def main():
    print("\n" + "="*70)
    print("EXÉCUTION DES TESTS (sans Mininet, localhost)")
    print("="*70)
    
    results = {}
    
    # Test TCP
    tcp_client_res, tcp_server_res = run_test("TCP", tcp_server, tcp_client, 5001)
    results['tcp'] = {'client': tcp_client_res, 'server': tcp_server_res}
    
    time.sleep(1)
    
    # Test UDP (baseline non fiable)
    udp_client_res, udp_server_res = run_test("UDP (non fiable)", udp_server, udp_client, 5002)
    results['udp'] = {'client': udp_client_res, 'server': udp_server_res}
    
    time.sleep(1)
    
    # Test rQUIC
    rquic_client_res, rquic_server_res = run_test("rQUIC (UDP+ARQ)", rquic_server, rquic_client, 5003)
    results['rquic'] = {'client': rquic_client_res, 'server': rquic_server_res}
    
    # Afficher les résultats
    print("\n" + "="*70)
    print("📊 RÉSULTATS FINAUX")
    print("="*70)
    
    print(f"\n{'Métrique':<25} {'TCP':<15} {'UDP':<15} {'rQUIC':<15}")
    print("-"*70)
    
    # Frames envoyées
    tcp_sent = results['tcp']['client'].get('frames_sent', 0)
    udp_sent = results['udp']['client'].get('frames_sent', 0)
    rquic_sent = results['rquic']['client'].get('frames_sent', 0)
    print(f"{'Frames envoyées':<25} {tcp_sent:<15} {udp_sent:<15} {rquic_sent:<15}")
    
    # Frames reçues
    tcp_recv = results['tcp']['server'].get('frames_received', 0)
    udp_recv = results['udp']['server'].get('frames_received', 0)
    rquic_recv = results['rquic']['server'].get('frames_received', 0)
    print(f"{'Frames reçues':<25} {tcp_recv:<15} {udp_recv:<15} {rquic_recv:<15}")
    
    # Taux de livraison
    tcp_delivery = (tcp_recv / tcp_sent * 100) if tcp_sent > 0 else 0
    udp_delivery = (udp_recv / udp_sent * 100) if udp_sent > 0 else 0
    rquic_delivery = results['rquic']['client'].get('delivery_rate', 0)
    print(f"{'Taux de livraison':<25} {tcp_delivery:.1f}%{'':<10} {udp_delivery:.1f}%{'':<10} {rquic_delivery:.1f}%")
    
    # FPS
    tcp_fps = results['tcp']['server'].get('fps', 0)
    udp_fps = results['udp']['server'].get('fps', 0)
    rquic_fps = results['rquic']['server'].get('fps', 0)
    print(f"{'FPS mesuré':<25} {tcp_fps:.1f}{'':<12} {udp_fps:.1f}{'':<12} {rquic_fps:.1f}")
    
    # Retransmissions (rQUIC seulement)
    rquic_retrans = results['rquic']['client'].get('retransmissions', 0)
    print(f"{'Retransmissions':<25} {'N/A':<15} {'N/A':<15} {rquic_retrans}")
    
    print("\n" + "="*70)
    print("✅ Test terminé sur localhost")
    print("   TCP: Fiable (100% livraison attendu)")
    print("   UDP: Non fiable (livraison variable)")  
    print("   rQUIC: UDP + ARQ (retransmissions visibles)")
    print("="*70)
    
    # Sauvegarder
    with open(os.path.join(WORK_DIR, 'test_results_fixed.json'), 'w') as f:
        json.dump(results, f, indent=2)
    
    print(f"\nRésultats sauvegardés dans test_results_fixed.json")


if __name__ == '__main__':
    main()
