#!/usr/bin/env python3
"""
Test du vrai protocole QUIC avec aioquic
Serveur et client QUIC pour cloud gaming
"""

import asyncio
import os
import sys
import json
import time
import struct
import random
import tempfile
import datetime
from dataclasses import dataclass, field

# aioquic imports
from aioquic.asyncio import QuicConnectionProtocol, serve, connect
from aioquic.quic.configuration import QuicConfiguration
from aioquic.quic.events import StreamDataReceived, ConnectionTerminated, HandshakeCompleted

# Pour les certificats auto-signés
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.asymmetric import rsa


WORK_DIR = os.path.dirname(os.path.abspath(__file__))


@dataclass
class ServerStats:
    frames_received: int = 0
    total_bytes: int = 0
    frame_times: list = field(default_factory=list)
    start_time: float = 0
    end_time: float = 0


@dataclass
class ClientStats:
    frames_sent: int = 0
    total_bytes: int = 0
    frame_sizes: list = field(default_factory=list)
    start_time: str = ""


def generate_self_signed_cert():
    """Génère un certificat auto-signé pour les tests QUIC"""
    
    # Clé privée
    key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
        backend=default_backend()
    )
    
    # Certificat
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
    ).add_extension(
        x509.SubjectAlternativeName([
            x509.DNSName("localhost"),
            x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
            x509.IPAddress(ipaddress.IPv4Address("10.0.0.2")),
        ]),
        critical=False,
    ).sign(key, hashes.SHA256(), default_backend())
    
    # Sauvegarder dans des fichiers temporaires
    cert_file = os.path.join(WORK_DIR, "test_cert.pem")
    key_file = os.path.join(WORK_DIR, "test_key.pem")
    
    with open(cert_file, 'wb') as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))
    
    with open(key_file, 'wb') as f:
        f.write(key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption()
        ))
    
    return cert_file, key_file


import ipaddress


class QuicServerProtocol(QuicConnectionProtocol):
    """Protocole serveur QUIC"""
    
    def __init__(self, *args, stats: ServerStats, **kwargs):
        super().__init__(*args, **kwargs)
        self.stats = stats
        self.buffer = b""
    
    def quic_event_received(self, event):
        if isinstance(event, HandshakeCompleted):
            print(f"[QUIC Server] Handshake terminé!")
        elif isinstance(event, StreamDataReceived):
            self.handle_data(event.data)
        elif isinstance(event, ConnectionTerminated):
            print(f"[QUIC Server] Connexion terminée")
    
    def handle_data(self, data: bytes):
        self.buffer += data
        
        # Parser les frames (header 8 bytes: frame_id + size)
        while len(self.buffer) >= 8:
            frame_id, frame_size = struct.unpack('!II', self.buffer[:8])
            
            if len(self.buffer) < 8 + frame_size:
                break
            
            frame_data = self.buffer[8:8+frame_size]
            self.buffer = self.buffer[8+frame_size:]
            
            recv_time = time.time()
            if self.stats.start_time == 0:
                self.stats.start_time = recv_time
            
            self.stats.frames_received += 1
            self.stats.total_bytes += len(frame_data)
            self.stats.frame_times.append(recv_time)
            self.stats.end_time = recv_time
            
            if self.stats.frames_received % 60 == 0:
                print(f"[QUIC] Frames reçues: {self.stats.frames_received}")


async def run_quic_server(host: str, port: int, duration: int, output_file: str):
    """Lance le serveur QUIC"""
    
    stats = ServerStats()
    
    # Générer les certificats
    cert_file, key_file = generate_self_signed_cert()
    
    # Configuration QUIC
    config = QuicConfiguration(is_client=False)
    config.load_cert_chain(cert_file, key_file)
    
    print(f"[QUIC Server] Démarrage sur {host}:{port}")
    
    def create_protocol(*args, **kwargs):
        return QuicServerProtocol(*args, stats=stats, **kwargs)
    
    server = await serve(host, port, configuration=config, create_protocol=create_protocol)
    
    # Attendre la durée spécifiée
    await asyncio.sleep(duration + 5)
    
    server.close()
    
    # Calculer les métriques
    duration_actual = stats.end_time - stats.start_time if stats.end_time > stats.start_time else 1
    
    delays = []
    for i in range(1, len(stats.frame_times)):
        delays.append((stats.frame_times[i] - stats.frame_times[i-1]) * 1000)
    
    avg_delay = sum(delays) / len(delays) if delays else 0
    jitter = 0
    if len(delays) > 1:
        jitter = sum(abs(delays[i] - delays[i-1]) for i in range(1, len(delays))) / (len(delays) - 1)
    
    results = {
        'protocol': 'QUIC',
        'port': port,
        'frames_received': stats.frames_received,
        'total_bytes': stats.total_bytes,
        'duration_sec': duration_actual,
        'avg_fps': stats.frames_received / duration_actual if duration_actual > 0 else 0,
        'throughput_mbps': (stats.total_bytes * 8) / (duration_actual * 1_000_000) if duration_actual > 0 else 0,
        'avg_inter_frame_delay_ms': avg_delay,
        'jitter_ms': jitter,
    }
    
    with open(output_file, 'w') as f:
        json.dump(results, f, indent=2)
    
    print(f"\n✅ [QUIC Server] Résultats: {output_file}")
    print(f"   Frames reçues: {stats.frames_received}")
    
    # Nettoyer les certificats
    os.unlink(cert_file)
    os.unlink(key_file)
    
    return results


async def run_quic_client(server_host: str, server_port: int, duration: int, output_file: str):
    """Lance le client QUIC"""
    
    stats = ClientStats()
    stats.start_time = time.strftime("%Y-%m-%dT%H:%M:%S")
    
    # Configuration QUIC (désactiver vérification certificat pour tests)
    config = QuicConfiguration(is_client=True)
    config.verify_mode = False  # Accepter certificats auto-signés
    
    print(f"[QUIC Client] Connexion à {server_host}:{server_port}")
    
    fps = 60
    frame_interval = 1.0 / fps
    avg_frame_size = 50000
    max_frame_size = 60000
    
    try:
        async with connect(server_host, server_port, configuration=config) as protocol:
            print("[QUIC Client] Connecté!")
            
            stream_id = protocol._quic.get_next_available_stream_id()
            
            start_time = time.time()
            frame_id = 0
            last_report = start_time
            
            while time.time() - start_time < duration:
                frame_start = time.time()
                
                # Générer une frame
                is_i_frame = random.random() < 0.1
                if is_i_frame:
                    size = int(random.gauss(avg_frame_size * 2.5, avg_frame_size * 0.5))
                else:
                    size = int(random.gauss(avg_frame_size * 0.7, avg_frame_size * 0.2))
                size = max(1000, min(size, max_frame_size))
                
                # Envoyer
                header = struct.pack('!II', frame_id, size)
                data = bytes(random.getrandbits(8) for _ in range(size))
                
                protocol._quic.send_stream_data(stream_id, header + data, end_stream=False)
                protocol.transmit()
                
                stats.frames_sent += 1
                stats.total_bytes += len(header) + len(data)
                stats.frame_sizes.append(size)
                frame_id += 1
                
                # Rapport
                if time.time() - last_report >= 1.0:
                    elapsed = time.time() - start_time
                    print(f"[{elapsed:.1f}s] {stats.frames_sent} frames envoyées")
                    last_report = time.time()
                
                # Maintenir FPS
                elapsed_frame = time.time() - frame_start
                if elapsed_frame < frame_interval:
                    await asyncio.sleep(frame_interval - elapsed_frame)
            
            # Fermer proprement
            protocol._quic.send_stream_data(stream_id, b"", end_stream=True)
            protocol.transmit()
            await asyncio.sleep(1)
            
    except Exception as e:
        print(f"[QUIC Client] Erreur: {e}")
        import traceback
        traceback.print_exc()
    
    results = {
        'frames_sent': stats.frames_sent,
        'total_bytes': stats.total_bytes,
        'start_time': stats.start_time,
        'protocol': 'QUIC',
        'fps': fps,
        'frame_sizes': stats.frame_sizes[:100],  # Limiter pour le JSON
    }
    
    with open(output_file, 'w') as f:
        json.dump(results, f, indent=2)
    
    print(f"\n✅ [QUIC Client] Résultats: {output_file}")
    print(f"   Frames envoyées: {stats.frames_sent}")
    
    return results


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='Test QUIC pour Cloud Gaming')
    parser.add_argument('mode', choices=['server', 'client'])
    parser.add_argument('--host', default='0.0.0.0')
    parser.add_argument('--port', type=int, default=4433)
    parser.add_argument('--duration', type=int, default=15)
    parser.add_argument('--output', default='quic_results.json')
    
    args = parser.parse_args()
    
    if args.mode == 'server':
        asyncio.run(run_quic_server(args.host, args.port, args.duration, args.output))
    else:
        asyncio.run(run_quic_client(args.host, args.port, args.duration, args.output))
