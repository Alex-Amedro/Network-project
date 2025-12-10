#!/usr/bin/env python3
"""
ÉTAPE 1 : Test TCP simple sur localhost
Objectif : Prouver que le comptage des frames est CORRECT
"""

import socket
import struct
import time
import threading
import json

# Paramètres
PORT = 6001
NUM_FRAMES = 100
FRAME_SIZE = 10000  # 10 KB par frame
FPS = 30

results = {
    'client': {'frames_sent': 0, 'bytes_sent': 0},
    'server': {'frames_received': 0, 'bytes_received': 0, 'frame_sizes': []}
}

def tcp_server(stop_event):
    """Serveur TCP qui compte EXACTEMENT les frames reçues"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(('127.0.0.1', PORT))
    sock.listen(1)
    sock.settimeout(30)
    
    print("[SERVER] En attente de connexion...")
    
    try:
        conn, addr = sock.accept()
        print(f"[SERVER] Connexion de {addr}")
        conn.settimeout(10)
        
        while not stop_event.is_set():
            try:
                # Lire l'en-tête : 4 bytes = taille de la frame
                header = b''
                while len(header) < 4:
                    chunk = conn.recv(4 - len(header))
                    if not chunk:
                        print("[SERVER] Connexion fermée par le client")
                        return
                    header += chunk
                
                frame_size = struct.unpack('!I', header)[0]
                
                # Lire la frame complète
                frame_data = b''
                while len(frame_data) < frame_size:
                    chunk = conn.recv(min(65536, frame_size - len(frame_data)))
                    if not chunk:
                        break
                    frame_data += chunk
                
                if len(frame_data) == frame_size:
                    results['server']['frames_received'] += 1
                    results['server']['bytes_received'] += frame_size
                    results['server']['frame_sizes'].append(frame_size)
                    
                    if results['server']['frames_received'] % 20 == 0:
                        print(f"[SERVER] {results['server']['frames_received']} frames reçues")
                
            except socket.timeout:
                continue
            except Exception as e:
                print(f"[SERVER] Erreur: {e}")
                break
        
        conn.close()
    except Exception as e:
        print(f"[SERVER] Exception: {e}")
    finally:
        sock.close()


def tcp_client():
    """Client TCP qui envoie des frames avec header de taille"""
    time.sleep(0.5)  # Attendre le serveur
    
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect(('127.0.0.1', PORT))
    
    print(f"[CLIENT] Envoi de {NUM_FRAMES} frames de {FRAME_SIZE} bytes à {FPS} FPS")
    
    start_time = time.time()
    
    for i in range(NUM_FRAMES):
        # Créer une frame avec un pattern identifiable
        frame_data = bytes([i % 256] * FRAME_SIZE)
        
        # Envoyer: 4 bytes taille + données
        sock.sendall(struct.pack('!I', len(frame_data)))
        sock.sendall(frame_data)
        
        results['client']['frames_sent'] += 1
        results['client']['bytes_sent'] += len(frame_data)
        
        # Respecter le FPS
        expected_time = start_time + (i + 1) / FPS
        sleep_time = expected_time - time.time()
        if sleep_time > 0:
            time.sleep(sleep_time)
    
    duration = time.time() - start_time
    print(f"[CLIENT] Terminé en {duration:.2f}s ({results['client']['frames_sent']/duration:.1f} FPS)")
    
    time.sleep(0.5)  # Laisser le serveur finir
    sock.close()


def main():
    print("="*60)
    print("TEST TCP - ÉTAPE 1 : Validation du comptage")
    print("="*60)
    print(f"Frames à envoyer: {NUM_FRAMES}")
    print(f"Taille par frame: {FRAME_SIZE} bytes")
    print(f"FPS cible: {FPS}")
    print("="*60)
    
    stop_event = threading.Event()
    
    # Lancer serveur
    server_thread = threading.Thread(target=tcp_server, args=(stop_event,))
    server_thread.start()
    
    # Lancer client
    tcp_client()
    
    # Arrêter
    stop_event.set()
    server_thread.join(timeout=5)
    
    # Résultats
    print("\n" + "="*60)
    print("RÉSULTATS")
    print("="*60)
    print(f"Client - Frames envoyées:    {results['client']['frames_sent']}")
    print(f"Client - Bytes envoyés:      {results['client']['bytes_sent']}")
    print(f"Server - Frames reçues:      {results['server']['frames_received']}")
    print(f"Server - Bytes reçus:        {results['server']['bytes_received']}")
    
    # Vérification
    print("\n" + "="*60)
    print("VÉRIFICATION")
    print("="*60)
    
    if results['client']['frames_sent'] == results['server']['frames_received']:
        print(f"✅ SUCCÈS: {results['client']['frames_sent']} envoyées = {results['server']['frames_received']} reçues")
        taux = 100.0
    else:
        print(f"❌ ÉCHEC: {results['client']['frames_sent']} envoyées != {results['server']['frames_received']} reçues")
        taux = results['server']['frames_received'] / results['client']['frames_sent'] * 100
    
    print(f"   Taux de livraison: {taux:.1f}%")
    
    if results['client']['bytes_sent'] == results['server']['bytes_received']:
        print(f"✅ Bytes OK: {results['client']['bytes_sent']} = {results['server']['bytes_received']}")
    else:
        print(f"❌ Bytes différents: {results['client']['bytes_sent']} != {results['server']['bytes_received']}")
    
    print("="*60)
    
    # Sauvegarder
    with open('step1_tcp_results.json', 'w') as f:
        json.dump(results, f, indent=2)
    
    return taux == 100.0


if __name__ == '__main__':
    success = main()
    exit(0 if success else 1)
