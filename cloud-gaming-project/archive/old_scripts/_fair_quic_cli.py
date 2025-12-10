#!/usr/bin/env python3
"""QUIC Client - 4 streams VRAIMENT indépendants"""
import asyncio, struct, time, json, sys, ssl

from aioquic.asyncio import connect
from aioquic.quic.configuration import QuicConfiguration

host = sys.argv[1]
port = int(sys.argv[2])
num_frames = int(sys.argv[3])
frame_size = int(sys.argv[4])
num_streams = int(sys.argv[5])
output = sys.argv[6]

results = {"frames_sent": 0, "start_time": None, "end_time": None, "status": "starting"}

def save():
    with open(output, "w") as f:
        json.dump(results, f)

async def main():
    global results
    
    config = QuicConfiguration(is_client=True, alpn_protocols=["gaming"])
    config.verify_mode = ssl.CERT_NONE
    config.idle_timeout = 120.0
    
    await asyncio.sleep(1)
    
    try:
        async with connect(host, port, configuration=config) as protocol:
            results["status"] = "connected"
            results["start_time"] = time.time()
            save()
            
            # Créer 4 streams QUIC indépendants
            stream_ids = [protocol._quic.get_next_available_stream_id() for _ in range(num_streams)]
            
            # Envoyer les frames sur chaque stream
            for frame_id in range(num_frames):
                for i, stream_id in enumerate(stream_ids):
                    send_time = time.time()
                    data = bytes([frame_id % 256] * frame_size)
                    
                    # Header: frame_id (4) + timestamp (8) + size (4)
                    header = struct.pack("!IdI", frame_id, send_time, len(data))
                    is_last = (frame_id == num_frames - 1) and (i == num_streams - 1)
                    
                    protocol._quic.send_stream_data(stream_id, header + data, end_stream=is_last)
                    results["frames_sent"] += 1
                
                protocol.transmit()
                await asyncio.sleep(0.001)  # Simuler 60 FPS
            
            results["end_time"] = time.time()
            
            # Attendre que les retransmissions soient faites
            await asyncio.sleep(10)
            results["status"] = "done"
            save()
    
    except Exception as e:
        results["error"] = str(e)
        results["status"] = "error"
        save()

asyncio.run(main())
