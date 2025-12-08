#!/usr/bin/env python3
"""
QUIC Sender - Envoie des frames vidéo via QUIC
"""

import sys
import time
import random
import asyncio
import os
import json

# Ajoute le répertoire au path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from quic_protocol import create_quic_sender

def generate_video_frame(frame_num, avg_size=50000):
    """Génère une frame vidéo simulée"""
    is_iframe = (frame_num % 30 == 0)
    size = random.randint(100000, 150000) if is_iframe else random.randint(20000, 60000)
    
    header = f"FRAME_{frame_num}_".encode()
    data = header + b'X' * (size - len(header))
    return data

async def main():
    if len(sys.argv) < 2:
        print("Usage: python3 quic_sender.py <server_ip>")
        sys.exit(1)
    
    server_ip = sys.argv[1]
    num_frames = 300
    fps = 60
    
    print(f"📡 Connexion QUIC vers {server_ip}:5001")
    
    try:
        sender = await create_quic_sender(server_ip, 5001)
        print("✅ Connecté !")
        
        print(f"🎮 Envoi de {num_frames} frames à {fps} FPS...")
        
        start_time = time.time()
        successful = 0
        failed = 0
        
        for frame_num in range(num_frames):
            frame_data = generate_video_frame(frame_num)
            
            # Envoie via QUIC (NON-BLOQUANT contrairement à TCP)
            if await sender.send_frame(frame_num, frame_data):
                successful += 1
            else:
                failed += 1
                print(f"❌ Frame {frame_num} échouée")
            
            # Affichage progression
            if (frame_num + 1) % 50 == 0:
                print(f"📊 Progression : {frame_num+1}/{num_frames}")
            
            # Respect du FPS
            await asyncio.sleep(max(0, 1/fps))
        
        # Attend un peu pour les dernières retransmissions QUIC
        await asyncio.sleep(2)
        
        duration = time.time() - start_time
        stats = sender.get_stats()
        
        print(f"\n✅ Résultats QUIC:")
        print(f"   Frames envoyées: {stats['sent']}")
        print(f"   Frames ackées: {stats['acked']}")
        print(f"   Temps bloqué: {stats['blocked_time']:.2f}s (devrait être ~0)")
        print(f"   Taux de succès: {successful/num_frames*100:.1f}%")
        print(f"   Durée totale: {duration:.2f}s")
        print(f"   FPS réel: {successful/duration:.1f}")
        
        # Calcul latence moyenne
        avg_latency = (duration / num_frames) * 1000
        print(f"   Latence moyenne: {avg_latency:.2f} ms")
        
        # Sauvegarde
        with open('quic_stats.json', 'w') as f:
            json.dump({
                'sent': stats['sent'],
                'acked': stats['acked'],
                'blocked_time': stats['blocked_time'],
                'duration': duration,
                'avg_latency': avg_latency,
                'success_rate': successful/num_frames
            }, f)
        
        await sender.close()
        
    except Exception as e:
        print(f"❌ Erreur: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    asyncio.run(main())
