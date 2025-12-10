#!/usr/bin/env python3
"""
QUIC Receiver - Reçoit les frames vidéo via QUIC
"""

import sys
import time
import asyncio
import os

# Ajoute le répertoire au path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from quic_protocol import create_quic_receiver

async def main():
    print("🚀 Serveur QUIC démarré sur port 5001")
    
    receiver = await create_quic_receiver(5001)
    
    try:
        print("⏳ Réception des frames...")
        start = time.time()
        
        await receiver.wait_for_frames(expected_frames=300, timeout=120)
        
        duration = time.time() - start
        stats = receiver.get_stats()
        
        print(f"\n✅ Résultats QUIC:")
        print(f"   Frames reçues: {stats['received']}")
        print(f"   Temps total: {stats['total_time']:.2f}s")
        print(f"   Durée totale: {duration:.2f}s")
        
        # Sauvegarde des stats
        import json
        with open('quic_receiver_stats.json', 'w') as f:
            json.dump({
                'received': stats['received'],
                'total_time': stats['total_time'],
                'duration': duration
            }, f)
        
    except KeyboardInterrupt:
        print("\n⚠️  Interrompu")
    finally:
        receiver.close()

if __name__ == '__main__':
    asyncio.run(main())
