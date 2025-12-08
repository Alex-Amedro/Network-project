#!/usr/bin/env python3
"""
Client QUIC pour Cloud Gaming - Utilise aioquic pour un vrai protocole QUIC
Envoie des frames vidéo simulées avec fiabilité garantie
"""

import asyncio
import json
import time
import struct
import random
import argparse
from dataclasses import dataclass, field

from aioquic.asyncio import connect
from aioquic.asyncio.protocol import QuicConnectionProtocol
from aioquic.quic.configuration import QuicConfiguration
from aioquic.quic.events import StreamDataReceived, ConnectionTerminated


@dataclass 
class SendStats:
    """Statistiques d'envoi des frames"""
    frames_sent: int = 0
    total_bytes: int = 0
    frame_sizes: list = field(default_factory=list)
    start_time: str = ""
    retransmissions: int = 0  # QUIC gère ça automatiquement


class VideoClientProtocol(QuicConnectionProtocol):
    """Protocole client QUIC pour envoyer les frames vidéo"""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.stream_id = None
        
    def quic_event_received(self, event):
        if isinstance(event, ConnectionTerminated):
            print(f"Connexion terminée: {event.reason_phrase}")


class VideoFrameGenerator:
    """Générateur de frames vidéo simulées"""
    
    def __init__(self, fps: int = 60, avg_frame_size: int = 50000):
        self.fps = fps
        self.avg_frame_size = avg_frame_size
        self.frame_interval = 1.0 / fps
        self.i_frame_ratio = 0.1  # 10% I-frames
        self.max_frame_size = 60000  # Limite pour éviter fragmentation
        
    def generate_frame_size(self) -> int:
        """Génère une taille de frame réaliste"""
        is_i_frame = random.random() < self.i_frame_ratio
        
        if is_i_frame:
            # I-frame: plus grande (2-3x la taille moyenne)
            size = int(random.gauss(self.avg_frame_size * 2.5, self.avg_frame_size * 0.5))
        else:
            # P-frame: plus petite
            size = int(random.gauss(self.avg_frame_size * 0.7, self.avg_frame_size * 0.2))
        
        return max(1000, min(size, self.max_frame_size))
    
    def generate_frame_data(self, frame_id: int) -> bytes:
        """Génère les données d'une frame"""
        size = self.generate_frame_size()
        # Header: frame_id (4 bytes) + size (4 bytes)
        header = struct.pack('!II', frame_id, size)
        # Données simulées
        data = bytes(random.getrandbits(8) for _ in range(size))
        return header + data, size


async def run_client(server_host: str, server_port: int, duration: int, output_file: str):
    """Lance le client QUIC"""
    
    stats = SendStats()
    stats.start_time = time.strftime("%Y-%m-%dT%H:%M:%S")
    
    generator = VideoFrameGenerator(fps=60, avg_frame_size=50000)
    
    # Configuration QUIC
    configuration = QuicConfiguration(
        is_client=True,
        max_datagram_frame_size=65536,
    )
    # Désactiver la vérification du certificat pour les tests
    configuration.verify_mode = False
    
    print(f"[QUIC Client] Connexion à {server_host}:{server_port}")
    print(f"[QUIC Client] Durée: {duration}s, FPS: {generator.fps}")
    
    try:
        async with connect(
            server_host, server_port,
            configuration=configuration,
        ) as protocol:
            
            # Ouvrir un stream pour envoyer les frames
            stream_id = protocol._quic.get_next_available_stream_id()
            
            start_time = time.time()
            frame_id = 0
            last_report = start_time
            bytes_sent = 0
            
            while time.time() - start_time < duration:
                frame_start = time.time()
                
                # Générer et envoyer une frame
                frame_data, frame_size = generator.generate_frame_data(frame_id)
                
                protocol._quic.send_stream_data(stream_id, frame_data, end_stream=False)
                protocol.transmit()
                
                stats.frames_sent += 1
                stats.total_bytes += len(frame_data)
                stats.frame_sizes.append(frame_size)
                bytes_sent += len(frame_data)
                frame_id += 1
                
                # Rapport toutes les secondes
                if time.time() - last_report >= 1.0:
                    elapsed = time.time() - start_time
                    print(f"[{elapsed:.1f}s] {stats.frames_sent} frames envoyées ({bytes_sent/1024/1024:.2f} MB)")
                    last_report = time.time()
                
                # Maintenir le FPS
                elapsed_frame = time.time() - frame_start
                sleep_time = generator.frame_interval - elapsed_frame
                if sleep_time > 0:
                    await asyncio.sleep(sleep_time)
            
            # Fermer le stream proprement
            protocol._quic.send_stream_data(stream_id, b"", end_stream=True)
            protocol.transmit()
            
            # Attendre un peu pour les dernières retransmissions
            await asyncio.sleep(1)
            
            # Récupérer les stats de retransmission depuis QUIC
            # aioquic ne fournit pas directement ce compteur, mais QUIC retransmet automatiquement
            
    except Exception as e:
        print(f"Erreur client QUIC: {e}")
        import traceback
        traceback.print_exc()
    
    # Sauvegarder les résultats
    results = {
        'frames_sent': stats.frames_sent,
        'total_bytes': stats.total_bytes,
        'start_time': stats.start_time,
        'protocol': 'QUIC',
        'fps': generator.fps,
        'frame_sizes': stats.frame_sizes,
        'avg_frame_size_kb': sum(stats.frame_sizes) / len(stats.frame_sizes) / 1024 if stats.frame_sizes else 0,
    }
    
    with open(output_file, 'w') as f:
        json.dump(results, f, indent=2)
    
    print(f"\n✅ [QUIC] Résultats sauvegardés: {output_file}")
    print(f"[QUIC] Frames envoyées: {stats.frames_sent}")
    print(f"[QUIC] Total données: {stats.total_bytes/1024/1024:.2f} MB")
    
    return results


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Client QUIC pour Cloud Gaming')
    parser.add_argument('server', help='Adresse du serveur')
    parser.add_argument('--port', type=int, default=5000, help='Port du serveur')
    parser.add_argument('--duration', type=int, default=30, help='Durée du test en secondes')
    parser.add_argument('--output', default='quic_client_results.json', help='Fichier de sortie')
    
    args = parser.parse_args()
    
    asyncio.run(run_client(args.server, args.port, args.duration, args.output))
