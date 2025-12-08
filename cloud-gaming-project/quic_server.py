#!/usr/bin/env python3
"""
Serveur QUIC pour Cloud Gaming - Utilise aioquic pour un vrai protocole QUIC
Supporte la fiabilité, les retransmissions et le multiplexage de streams
"""

import asyncio
import json
import time
import struct
import argparse
from typing import Dict, Optional
from dataclasses import dataclass, field

from aioquic.asyncio import serve
from aioquic.asyncio.protocol import QuicConnectionProtocol
from aioquic.quic.configuration import QuicConfiguration
from aioquic.quic.events import StreamDataReceived, ConnectionTerminated


@dataclass
class FrameStats:
    """Statistiques de réception des frames"""
    frames_received: int = 0
    total_bytes: int = 0
    frame_times: list = field(default_factory=list)
    frame_sizes: list = field(default_factory=list)
    start_time: float = 0
    end_time: float = 0


class VideoServerProtocol(QuicConnectionProtocol):
    """Protocole serveur QUIC pour recevoir les frames vidéo"""
    
    def __init__(self, *args, stats: FrameStats, **kwargs):
        super().__init__(*args, **kwargs)
        self.stats = stats
        self.buffer = b""
        
    def quic_event_received(self, event):
        if isinstance(event, StreamDataReceived):
            self.handle_stream_data(event.stream_id, event.data, event.end_stream)
        elif isinstance(event, ConnectionTerminated):
            print(f"Connexion terminée: {event.reason_phrase}")
    
    def handle_stream_data(self, stream_id: int, data: bytes, end_stream: bool):
        """Traite les données reçues sur un stream"""
        self.buffer += data
        
        # Traiter les frames complètes (header 8 bytes: frame_id + size)
        while len(self.buffer) >= 8:
            frame_id, frame_size = struct.unpack('!II', self.buffer[:8])
            
            total_frame_size = 8 + frame_size
            if len(self.buffer) < total_frame_size:
                break  # Attendre plus de données
            
            # Frame complète reçue
            frame_data = self.buffer[8:total_frame_size]
            self.buffer = self.buffer[total_frame_size:]
            
            # Enregistrer les stats
            recv_time = time.time()
            if self.stats.start_time == 0:
                self.stats.start_time = recv_time
            
            self.stats.frames_received += 1
            self.stats.total_bytes += len(frame_data)
            self.stats.frame_times.append(recv_time)
            self.stats.frame_sizes.append(len(frame_data))
            self.stats.end_time = recv_time
            
            if self.stats.frames_received % 60 == 0:
                print(f"[QUIC] Frames reçues: {self.stats.frames_received}")


async def run_server(host: str, port: int, duration: int, output_file: str):
    """Lance le serveur QUIC"""
    
    stats = FrameStats()
    
    # Configuration QUIC (auto-signé pour les tests)
    configuration = QuicConfiguration(
        is_client=False,
        max_datagram_frame_size=65536,
    )
    
    # Générer un certificat auto-signé pour les tests
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.backends import default_backend
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives import serialization
    import datetime
    import tempfile
    import os
    
    # Générer clé privée
    key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
        backend=default_backend()
    )
    
    # Générer certificat auto-signé
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "TW"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Cloud Gaming Test"),
        x509.NameAttribute(NameOID.COMMON_NAME, "localhost"),
    ])
    
    cert = x509.CertificateBuilder().subject_name(
        subject
    ).issuer_name(
        issuer
    ).public_key(
        key.public_key()
    ).serial_number(
        x509.random_serial_number()
    ).not_valid_before(
        datetime.datetime.utcnow()
    ).not_valid_after(
        datetime.datetime.utcnow() + datetime.timedelta(days=1)
    ).sign(key, hashes.SHA256(), default_backend())
    
    # Sauvegarder temporairement
    with tempfile.NamedTemporaryFile(mode='wb', suffix='.pem', delete=False) as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))
        cert_file = f.name
    
    with tempfile.NamedTemporaryFile(mode='wb', suffix='.pem', delete=False) as f:
        f.write(key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption()
        ))
        key_file = f.name
    
    configuration.load_cert_chain(cert_file, key_file)
    
    print(f"[QUIC] Serveur démarré sur {host}:{port}")
    print(f"[QUIC] Durée: {duration}s")
    
    def create_protocol():
        return VideoServerProtocol(
            configuration=configuration,
            stats=stats
        )
    
    try:
        server = await serve(
            host, port,
            configuration=configuration,
            create_protocol=lambda *args, **kwargs: VideoServerProtocol(
                *args, stats=stats, **kwargs
            ),
        )
        
        # Attendre la durée spécifiée
        await asyncio.sleep(duration + 5)  # +5s de marge
        
        server.close()
        
    except Exception as e:
        print(f"Erreur serveur QUIC: {e}")
    finally:
        # Nettoyer les fichiers temporaires
        os.unlink(cert_file)
        os.unlink(key_file)
    
    # Calculer les métriques
    results = calculate_metrics(stats)
    
    # Sauvegarder les résultats
    with open(output_file, 'w') as f:
        json.dump(results, f, indent=2)
    
    print(f"\n[QUIC] Résultats sauvegardés: {output_file}")
    print(f"[QUIC] Frames reçues: {stats.frames_received}")
    
    return results


def calculate_metrics(stats: FrameStats) -> dict:
    """Calcule les métriques de performance"""
    
    if stats.frames_received == 0:
        return {
            'protocol': 'QUIC',
            'frames_received': 0,
            'total_bytes': 0,
            'avg_fps': 0,
            'throughput_mbps': 0,
            'avg_inter_frame_delay_ms': 0,
            'jitter_ms': 0,
        }
    
    duration = stats.end_time - stats.start_time if stats.end_time > stats.start_time else 1
    
    # Calcul des délais inter-frames
    delays = []
    for i in range(1, len(stats.frame_times)):
        delay = (stats.frame_times[i] - stats.frame_times[i-1]) * 1000
        delays.append(delay)
    
    avg_delay = sum(delays) / len(delays) if delays else 0
    
    # Calcul du jitter (variation des délais)
    jitter = 0
    if len(delays) > 1:
        jitter = sum(abs(delays[i] - delays[i-1]) for i in range(1, len(delays))) / (len(delays) - 1)
    
    return {
        'protocol': 'QUIC',
        'port': 5000,
        'frames_received': stats.frames_received,
        'total_bytes': stats.total_bytes,
        'start_time': stats.start_time,
        'end_time': stats.end_time,
        'duration_sec': duration,
        'avg_fps': stats.frames_received / duration,
        'throughput_mbps': (stats.total_bytes * 8) / (duration * 1_000_000),
        'avg_inter_frame_delay_ms': avg_delay,
        'jitter_ms': jitter,
        'num_frame_times': len(stats.frame_times),
        'num_frame_sizes': len(stats.frame_sizes),
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Serveur QUIC pour Cloud Gaming')
    parser.add_argument('--host', default='0.0.0.0', help='Adresse d\'écoute')
    parser.add_argument('--port', type=int, default=5000, help='Port d\'écoute')
    parser.add_argument('--duration', type=int, default=30, help='Durée du test en secondes')
    parser.add_argument('--output', default='quic_server_results.json', help='Fichier de sortie')
    
    args = parser.parse_args()
    
    asyncio.run(run_server(args.host, args.port, args.duration, args.output))
