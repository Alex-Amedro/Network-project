#!/usr/bin/env python3
"""
ÉTAPE 2 : Test QUIC avec aioquic sur localhost
Objectif : Prouver que QUIC fonctionne et que le comptage est CORRECT
"""

import asyncio
import time
import struct
import json
import os
import ssl
from typing import Dict, Optional

# Vérifier aioquic
try:
    from aioquic.asyncio import connect, serve
    from aioquic.asyncio.protocol import QuicConnectionProtocol
    from aioquic.quic.configuration import QuicConfiguration
    from aioquic.quic.events import StreamDataReceived, ConnectionTerminated
    print("✅ aioquic importé avec succès")
except ImportError as e:
    print(f"❌ Erreur import aioquic: {e}")
    print("   Installer avec: pip install aioquic")
    exit(1)

# Paramètres
HOST = '127.0.0.1'
PORT = 6002
NUM_FRAMES = 100
FRAME_SIZE = 10000  # 10 KB
FPS = 30

# Résultats globaux
results = {
    'client': {'frames_sent': 0, 'bytes_sent': 0, 'start_time': 0, 'end_time': 0},
    'server': {'frames_received': 0, 'bytes_received': 0, 'frame_sizes': []}
}

# Fichiers certificats
CERT_FILE = 'server.cert'
KEY_FILE = 'server.key'


class QuicServerProtocol(QuicConnectionProtocol):
    """Protocole serveur QUIC"""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.buffer = b''
    
    def quic_event_received(self, event):
        if isinstance(event, StreamDataReceived):
            self.buffer += event.data
            
            # Extraire les frames complètes
            while len(self.buffer) >= 4:
                frame_size = struct.unpack('!I', self.buffer[:4])[0]
                total_size = 4 + frame_size
                
                if len(self.buffer) >= total_size:
                    # Frame complète reçue
                    frame_data = self.buffer[4:total_size]
                    self.buffer = self.buffer[total_size:]
                    
                    results['server']['frames_received'] += 1
                    results['server']['bytes_received'] += frame_size
                    results['server']['frame_sizes'].append(frame_size)
                    
                    if results['server']['frames_received'] % 20 == 0:
                        print(f"[QUIC SERVER] {results['server']['frames_received']} frames reçues")
                else:
                    break
        
        elif isinstance(event, ConnectionTerminated):
            print(f"[QUIC SERVER] Connexion terminée")


async def run_server(ready_event, stop_event):
    """Lance le serveur QUIC"""
    configuration = QuicConfiguration(
        is_client=False,
        alpn_protocols=["gaming"],
    )
    configuration.load_cert_chain(CERT_FILE, KEY_FILE)
    
    print(f"[QUIC SERVER] Démarrage sur {HOST}:{PORT}")
    
    server = await serve(
        HOST, PORT,
        configuration=configuration,
        create_protocol=QuicServerProtocol,
    )
    
    ready_event.set()
    print("[QUIC SERVER] Prêt")
    
    # Attendre le signal d'arrêt
    while not stop_event.is_set():
        await asyncio.sleep(0.1)
    
    server.close()
    print("[QUIC SERVER] Arrêté")


async def run_client(ready_event):
    """Lance le client QUIC"""
    # Attendre que le serveur soit prêt
    await ready_event.wait()
    await asyncio.sleep(0.5)
    
    configuration = QuicConfiguration(
        is_client=True,
        alpn_protocols=["gaming"],
    )
    configuration.verify_mode = ssl.CERT_NONE  # Auto-signé
    
    print(f"[QUIC CLIENT] Connexion à {HOST}:{PORT}")
    
    async with connect(HOST, PORT, configuration=configuration) as protocol:
        # Ouvrir un stream
        stream_id = protocol._quic.get_next_available_stream_id()
        
        print(f"[QUIC CLIENT] Envoi de {NUM_FRAMES} frames de {FRAME_SIZE} bytes à {FPS} FPS")
        
        results['client']['start_time'] = time.time()
        
        for i in range(NUM_FRAMES):
            # Créer la frame
            frame_data = bytes([i % 256] * FRAME_SIZE)
            
            # Envoyer: taille (4 bytes) + données
            message = struct.pack('!I', len(frame_data)) + frame_data
            protocol._quic.send_stream_data(stream_id, message, end_stream=(i == NUM_FRAMES - 1))
            protocol.transmit()
            
            results['client']['frames_sent'] += 1
            results['client']['bytes_sent'] += len(frame_data)
            
            # Respecter le FPS
            expected_time = results['client']['start_time'] + (i + 1) / FPS
            sleep_time = expected_time - time.time()
            if sleep_time > 0:
                await asyncio.sleep(sleep_time)
        
        results['client']['end_time'] = time.time()
        duration = results['client']['end_time'] - results['client']['start_time']
        print(f"[QUIC CLIENT] Terminé en {duration:.2f}s ({results['client']['frames_sent']/duration:.1f} FPS)")
        
        # Attendre que les données soient reçues
        await asyncio.sleep(1)


async def main():
    print("="*60)
    print("TEST QUIC (aioquic) - ÉTAPE 2 : Validation du comptage")
    print("="*60)
    print(f"Frames à envoyer: {NUM_FRAMES}")
    print(f"Taille par frame: {FRAME_SIZE} bytes")
    print(f"FPS cible: {FPS}")
    print("="*60)
    
    ready_event = asyncio.Event()
    stop_event = asyncio.Event()
    
    # Lancer serveur et client
    server_task = asyncio.create_task(run_server(ready_event, stop_event))
    
    try:
        await run_client(ready_event)
    finally:
        stop_event.set()
        await asyncio.sleep(0.5)
        server_task.cancel()
        try:
            await server_task
        except asyncio.CancelledError:
            pass
    
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
        taux = results['server']['frames_received'] / results['client']['frames_sent'] * 100 if results['client']['frames_sent'] > 0 else 0
    
    print(f"   Taux de livraison: {taux:.1f}%")
    
    if results['client']['bytes_sent'] == results['server']['bytes_received']:
        print(f"✅ Bytes OK: {results['client']['bytes_sent']} = {results['server']['bytes_received']}")
    else:
        print(f"⚠️  Bytes différents: {results['client']['bytes_sent']} != {results['server']['bytes_received']}")
    
    print("="*60)
    
    # Sauvegarder
    with open('step2_quic_results.json', 'w') as f:
        json.dump(results, f, indent=2, default=str)
    
    return taux >= 99.0  # Accepter 99%+ pour QUIC


if __name__ == '__main__':
    success = asyncio.run(main())
    exit(0 if success else 1)
