#!/usr/bin/env python3
"""
Générateur de trafic vidéo pour cloud gaming
Simule l'envoi de trames à 60 FPS avec taille variable
"""

import socket
import time
import random
import json
from datetime import datetime

class VideoFrameGenerator:
    def __init__(self, fps=60, avg_frame_size_kb=50, protocol='QUIC'):
        self.fps = fps
        self.frame_interval = 1.0 / fps  # Temps entre frames
        self.avg_frame_size = avg_frame_size_kb * 1024  # En bytes
        self.protocol = protocol
        # Taille max pour UDP/QUIC : ~65KB - headers = 60KB max
        self.max_udp_packet = 60000
        
    def generate_frame_size(self):
        """
        Génère une taille de frame réaliste
        Distribution : I-frames (gros) et P-frames (petits)
        """
        # 10% de I-frames (3x plus gros)
        if random.random() < 0.1:
            size = int(self.avg_frame_size * random.uniform(2.5, 3.5))
        # 90% de P-frames
        else:
            size = int(self.avg_frame_size * random.uniform(0.3, 1.2))
        
        # Limiter la taille pour UDP/QUIC
        if self.protocol in ['UDP', 'QUIC']:
            size = min(size, self.max_udp_packet)
        
        return size
    
    def send_traffic(self, server_ip, port, duration_sec=30):
        """Envoie du trafic vidéo simulé"""
        
        results = {
            'frames_sent': 0,
            'total_bytes': 0,
            'start_time': datetime.now().isoformat(),
            'protocol': self.protocol,
            'fps': self.fps,
            'frame_sizes': []
        }
        
        # Créer le socket
        # QUIC utilise UDP sous le capot
        if self.protocol in ['UDP', 'QUIC']:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        else:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.connect((server_ip, port))
        
        print(f"Envoi de {self.fps} FPS vers {server_ip}:{port} pendant {duration_sec}s")
        print(f"Taille moyenne frame: {self.avg_frame_size/1024:.1f} KB")
        
        start_time = time.time()
        frame_count = 0
        
        try:
            while time.time() - start_time < duration_sec:
                frame_start = time.time()
                
                # Génère et envoie une frame
                frame_size = self.generate_frame_size()
                frame_data = b'F' * frame_size  # Données factices
                
                if self.protocol in ['UDP', 'QUIC']:
                    sock.sendto(frame_data, (server_ip, port))
                else:
                    sock.send(frame_data)
                
                frame_count += 1
                results['frames_sent'] += 1
                results['total_bytes'] += frame_size
                results['frame_sizes'].append(frame_size)
                
                # Affichage progression
                if frame_count % 60 == 0:
                    elapsed = time.time() - start_time
                    print(f"[{elapsed:.1f}s] {frame_count} frames envoyées ({results['total_bytes']/1024/1024:.2f} MB)")
                
                # Attendre pour respecter le FPS
                frame_duration = time.time() - frame_start
                sleep_time = max(0, self.frame_interval - frame_duration)
                time.sleep(sleep_time)
                
        except KeyboardInterrupt:
            print("\nInterruption par l'utilisateur")
        finally:
            sock.close()
            results['end_time'] = datetime.now().isoformat()
            results['duration_sec'] = time.time() - start_time
            
        return results

if __name__ == '__main__':
    import sys
    
    if len(sys.argv) < 3:
        print("Usage: python3 video_traffic_gen.py <server_ip> <protocol> [duration]")
        print("Exemple: python3 video_traffic_gen.py 10.0.0.2 QUIC 30")
        sys.exit(1)
    
    server_ip = sys.argv[1]
    protocol = sys.argv[2].upper()
    duration = int(sys.argv[3]) if len(sys.argv) > 3 else 30
    
    generator = VideoFrameGenerator(fps=60, avg_frame_size_kb=50, protocol=protocol)
    results = generator.send_traffic(server_ip, port=5000, duration_sec=duration)
    
    # Sauvegarde les résultats
    filename = f'video_traffic_{protocol.lower()}_results.json'
    with open(filename, 'w') as f:
        json.dump(results, f, indent=2)
    
    print(f"\n✅ Résultats sauvegardés dans {filename}")
    print(f"Frames envoyées: {results['frames_sent']}")
    print(f"Total données: {results['total_bytes']/1024/1024:.2f} MB")
    print(f"Débit moyen: {results['total_bytes']/results['duration_sec']/1024/1024:.2f} MB/s")
