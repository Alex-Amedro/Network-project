#!/usr/bin/env python3
"""
Serveur de réception pour trafic vidéo cloud gaming
Enregistre les statistiques de réception des frames
"""

import socket
import time
import json
import sys
from datetime import datetime

class VideoReceiver:
    def __init__(self, port, protocol='QUIC'):
        self.port = port
        self.protocol = protocol
        self.stats = {
            'protocol': protocol,
            'port': port,
            'frames_received': 0,
            'total_bytes': 0,
            'frame_times': [],
            'frame_sizes': [],
            'start_time': None,
            'end_time': None
        }
    
    def receive_udp(self, timeout=40):
        """Reçoit les frames en UDP"""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(('0.0.0.0', self.port))
        sock.settimeout(2.0)
        
        print(f"Serveur UDP en écoute sur port {self.port}")
        
        start_time = time.time()
        last_frame_time = start_time
        no_data_timeout = 5  # Arrêter si pas de données pendant 5s
        
        try:
            while time.time() - start_time < timeout:
                try:
                    data, addr = sock.recvfrom(65536)
                    current_time = time.time()
                    
                    if self.stats['start_time'] is None:
                        self.stats['start_time'] = current_time
                    
                    self.stats['frames_received'] += 1
                    self.stats['total_bytes'] += len(data)
                    self.stats['frame_times'].append(current_time)
                    self.stats['frame_sizes'].append(len(data))
                    
                    last_frame_time = current_time
                    
                    # Affichage périodique
                    if self.stats['frames_received'] % 60 == 0:
                        elapsed = current_time - start_time
                        fps = self.stats['frames_received'] / elapsed
                        print(f"[{elapsed:.1f}s] {self.stats['frames_received']} frames reçues ({fps:.1f} FPS)")
                
                except socket.timeout:
                    # Vérifier si on doit arrêter
                    if time.time() - last_frame_time > no_data_timeout:
                        print("Timeout: aucune donnée reçue depuis 5s")
                        break
                    continue
        
        except KeyboardInterrupt:
            print("\nInterruption par l'utilisateur")
        finally:
            sock.close()
            self.stats['end_time'] = time.time()
    
    def receive_tcp(self, timeout=40):
        """Reçoit les frames en TCP"""
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(('0.0.0.0', self.port))
        sock.listen(1)
        sock.settimeout(timeout)
        
        print(f"Serveur TCP en écoute sur port {self.port}")
        
        try:
            conn, addr = sock.accept()
            print(f"Connexion acceptée de {addr}")
            
            start_time = time.time()
            self.stats['start_time'] = start_time
            
            buffer = b''
            frame_size = 0
            
            while time.time() - start_time < timeout:
                try:
                    data = conn.recv(65536)
                    if not data:
                        break
                    
                    current_time = time.time()
                    buffer += data
                    
                    # Simple détection de frame (toutes les données 'F')
                    # Dans un vrai cas, on aurait un marqueur de frame
                    while len(buffer) >= 1024:  # Taille minimale d'une frame
                        # Extraire une frame (simplifié)
                        frame_data = buffer[:51200]  # Taille moyenne ~50KB
                        buffer = buffer[51200:]
                        
                        self.stats['frames_received'] += 1
                        self.stats['total_bytes'] += len(frame_data)
                        self.stats['frame_times'].append(current_time)
                        self.stats['frame_sizes'].append(len(frame_data))
                        
                        if self.stats['frames_received'] % 60 == 0:
                            elapsed = current_time - start_time
                            fps = self.stats['frames_received'] / elapsed
                            print(f"[{elapsed:.1f}s] {self.stats['frames_received']} frames reçues ({fps:.1f} FPS)")
                
                except socket.timeout:
                    break
            
            conn.close()
        
        except socket.timeout:
            print("Timeout en attente de connexion")
        except KeyboardInterrupt:
            print("\nInterruption par l'utilisateur")
        finally:
            sock.close()
            self.stats['end_time'] = time.time()
    
    def save_results(self, filename=None):
        """Sauvegarde les statistiques"""
        if filename is None:
            filename = f'video_server_{self.protocol.lower()}_results.json'
        
        # Calculer les métriques
        if self.stats['start_time'] and self.stats['end_time']:
            duration = self.stats['end_time'] - self.stats['start_time']
            self.stats['duration_sec'] = duration
            
            if duration > 0:
                self.stats['avg_fps'] = self.stats['frames_received'] / duration
                self.stats['throughput_mbps'] = (self.stats['total_bytes'] * 8) / (duration * 1e6)
            
            # Calculer le jitter (variation du délai inter-frame)
            if len(self.stats['frame_times']) > 1:
                inter_frame_delays = []
                for i in range(1, len(self.stats['frame_times'])):
                    delay = self.stats['frame_times'][i] - self.stats['frame_times'][i-1]
                    inter_frame_delays.append(delay * 1000)  # en ms
                
                if inter_frame_delays:
                    self.stats['avg_inter_frame_delay_ms'] = sum(inter_frame_delays) / len(inter_frame_delays)
                    # Jitter = écart-type des délais
                    mean = self.stats['avg_inter_frame_delay_ms']
                    variance = sum((x - mean) ** 2 for x in inter_frame_delays) / len(inter_frame_delays)
                    self.stats['jitter_ms'] = variance ** 0.5
        
        # Ne pas sauvegarder les listes complètes (trop gros)
        stats_to_save = self.stats.copy()
        stats_to_save['num_frame_times'] = len(self.stats['frame_times'])
        stats_to_save['num_frame_sizes'] = len(self.stats['frame_sizes'])
        del stats_to_save['frame_times']
        del stats_to_save['frame_sizes']
        
        with open(filename, 'w') as f:
            json.dump(stats_to_save, f, indent=2)
        
        print(f"\n✅ Résultats sauvegardés dans {filename}")
        print(f"Frames reçues: {self.stats['frames_received']}")
        if 'avg_fps' in self.stats:
            print(f"FPS moyen: {self.stats['avg_fps']:.1f}")
        if 'throughput_mbps' in self.stats:
            print(f"Débit: {self.stats['throughput_mbps']:.2f} Mbps")

if __name__ == '__main__':
    if len(sys.argv) < 3:
        print("Usage: python3 video_server.py <port> <protocol>")
        print("Exemple: python3 video_server.py 5000 QUIC")
        sys.exit(1)
    
    port = int(sys.argv[1])
    protocol = sys.argv[2].upper()
    
    receiver = VideoReceiver(port, protocol)
    
    # QUIC utilise UDP sous le capot
    if protocol == 'QUIC' or protocol == 'UDP':
        receiver.receive_udp()
    else:
        receiver.receive_tcp()
    
    receiver.save_results()
