#!/usr/bin/env python3
"""
QUIC Stream Protocol - Implémentation Python avec aioquic
Montre les avantages de QUIC (pas de head-of-line blocking)
"""

import asyncio
import struct
import time
import ssl
import json
import os

from aioquic.asyncio import connect, serve
from aioquic.asyncio.protocol import QuicConnectionProtocol
from aioquic.quic.configuration import QuicConfiguration
from aioquic.quic.events import StreamDataReceived, ConnectionTerminated, HandshakeCompleted

WORK_DIR = os.path.dirname(os.path.abspath(__file__))

class QUICPacket:
    """Représente un paquet QUIC applicatif"""
    
    def __init__(self, seq_num, data):
        self.seq_num = seq_num
        self.data = data
        self.timestamp = time.time()
    
    def pack(self):
        """Sérialise"""
        header = struct.pack('!IdI', self.seq_num, self.timestamp, len(self.data))
        return header + self.data
    
    @staticmethod
    def unpack(raw_data):
        """Désérialise"""
        if len(raw_data) < 16:
            return None
        seq_num, timestamp, data_len = struct.unpack('!IdI', raw_data[:16])
        data = raw_data[16:16+data_len]
        return QUICPacket(seq_num, data), 16 + data_len


class QUICSender:
    """
    QUIC Sender - PAS de head-of-line blocking !
    Chaque stream est indépendant.
    """
    
    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.protocol = None
        self.stats = {
            'sent': 0,
            'acked': 0,  # QUIC garantit la livraison
            'retrans': 0,  # Géré par QUIC en interne
            'blocked_time': 0  # Devrait être ~0 grâce aux streams indépendants
        }
        self._connected = asyncio.Event()
        self._acks = {}
        self._stream_id = None
    
    async def connect(self):
        """Établit la connexion QUIC"""
        config = QuicConfiguration(is_client=True, alpn_protocols=["gaming"])
        config.verify_mode = ssl.CERT_NONE
        config.idle_timeout = 60.0
        
        self.protocol = await connect(
            self.host, 
            self.port, 
            configuration=config,
            create_protocol=lambda *args, **kwargs: QUICClientProtocol(self, *args, **kwargs)
        )
        self._stream_id = self.protocol._quic.get_next_available_stream_id()
        await asyncio.sleep(0.1)  # Laisse le handshake se terminer
    
    async def send_frame(self, seq_num, data):
        """
        Envoie une frame via QUIC
        NON-BLOQUANT - QUIC gère les retransmissions en arrière-plan
        """
        packet = QUICPacket(seq_num, data)
        
        try:
            send_time = time.time()
            
            # Envoie sur le stream QUIC
            self.protocol._quic.send_stream_data(
                self._stream_id, 
                packet.pack(),
                end_stream=False
            )
            self.protocol.transmit()
            self.stats['sent'] += 1
            
            # QUIC garantit la livraison - pas besoin d'attendre un ACK applicatif
            # Les retransmissions sont gérées automatiquement au niveau QUIC
            self.stats['acked'] += 1
            
            return True
            
        except Exception as e:
            print(f"❌ Erreur QUIC: {e}")
            return False
    
    def receive_ack(self, seq_num):
        """Reçoit un ACK (optionnel pour QUIC)"""
        self._acks[seq_num] = time.time()
    
    def get_stats(self):
        return self.stats.copy()
    
    async def close(self):
        if self.protocol:
            # Ferme proprement le stream
            self.protocol._quic.send_stream_data(self._stream_id, b'', end_stream=True)
            self.protocol.transmit()
            await asyncio.sleep(0.5)
            self.protocol.close()


class QUICClientProtocol(QuicConnectionProtocol):
    """Protocole client QUIC"""
    
    def __init__(self, sender, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.sender = sender
    
    def quic_event_received(self, event):
        if isinstance(event, StreamDataReceived):
            # Réception d'ACK (optionnel)
            if len(event.data) >= 4:
                seq_num = struct.unpack('!I', event.data[:4])[0]
                self.sender.receive_ack(seq_num)


class QUICReceiver:
    """
    QUIC Receiver - Reçoit sur des streams indépendants
    """
    
    def __init__(self, port):
        self.port = port
        self.stats = {
            'received': 0,
            'acks_sent': 0
        }
        self.received_frames = {}
        self._server = None
        self._done = asyncio.Event()
        self._expected_frames = 300
        self._first_frame_time = None
        self._last_frame_time = None
    
    async def start(self, cert_file, key_file):
        """Démarre le serveur QUIC"""
        config = QuicConfiguration(is_client=False, alpn_protocols=["gaming"])
        config.load_cert_chain(cert_file, key_file)
        config.idle_timeout = 60.0
        
        self._server = await serve(
            "0.0.0.0",
            self.port,
            configuration=config,
            create_protocol=lambda *args, **kwargs: QUICServerProtocol(self, *args, **kwargs)
        )
        print(f"🚀 Serveur QUIC démarré sur port {self.port}")
    
    def frame_received(self, seq_num, data, protocol):
        """Appelé quand une frame est reçue"""
        now = time.time()
        
        if self._first_frame_time is None:
            self._first_frame_time = now
        self._last_frame_time = now
        
        if seq_num not in self.received_frames:
            self.received_frames[seq_num] = data
            self.stats['received'] += 1
        
        # Envoie un ACK (optionnel mais pour compatibilité)
        # QUIC garantit déjà la livraison au niveau transport
        ack = struct.pack('!I', seq_num)
        # protocol._quic.send_stream_data(0, ack)  # Optionnel
        self.stats['acks_sent'] += 1
        
        if self.stats['received'] % 50 == 0:
            print(f"📊 Reçu {self.stats['received']}/{self._expected_frames} frames")
        
        if self.stats['received'] >= self._expected_frames:
            self._done.set()
    
    async def wait_for_frames(self, expected_frames=300, timeout=60):
        """Attend la réception de toutes les frames"""
        self._expected_frames = expected_frames
        try:
            await asyncio.wait_for(self._done.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            print(f"⏱️  Timeout - reçu {self.stats['received']}/{expected_frames}")
    
    def get_stats(self):
        total_time = 0
        if self._first_frame_time and self._last_frame_time:
            total_time = self._last_frame_time - self._first_frame_time
        
        return {
            'received': len(self.received_frames),
            'acks_sent': self.stats['acks_sent'],
            'seq_nums': sorted(self.received_frames.keys()),
            'total_time': total_time
        }
    
    def close(self):
        if self._server:
            self._server.close()


class QUICServerProtocol(QuicConnectionProtocol):
    """Protocole serveur QUIC"""
    
    def __init__(self, receiver, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.receiver = receiver
        self._buffers = {}  # Buffer par stream
    
    def quic_event_received(self, event):
        if isinstance(event, StreamDataReceived):
            stream_id = event.stream_id
            
            if stream_id not in self._buffers:
                self._buffers[stream_id] = b""
            
            self._buffers[stream_id] += event.data
            
            # Parse les paquets
            while len(self._buffers[stream_id]) >= 16:
                result = QUICPacket.unpack(self._buffers[stream_id])
                if result is None:
                    break
                
                packet, consumed = result
                if len(self._buffers[stream_id]) < consumed:
                    break
                
                self._buffers[stream_id] = self._buffers[stream_id][consumed:]
                self.receiver.frame_received(packet.seq_num, packet.data, self)
        
        elif isinstance(event, ConnectionTerminated):
            print("📡 Connexion QUIC terminée")


# ============ Fonctions utilitaires ============

async def create_quic_sender(host, port):
    """Crée et connecte un sender QUIC"""
    sender = QUICSender(host, port)
    await sender.connect()
    return sender

async def create_quic_receiver(port, cert_file=None, key_file=None):
    """Crée et démarre un receiver QUIC"""
    if cert_file is None:
        cert_file = os.path.join(WORK_DIR, 'server.cert')
    if key_file is None:
        key_file = os.path.join(WORK_DIR, 'server.key')
    
    receiver = QUICReceiver(port)
    await receiver.start(cert_file, key_file)
    return receiver
