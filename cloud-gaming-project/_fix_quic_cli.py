#!/usr/bin/env python3
import asyncio
import struct
import time
import json
import sys
import ssl

from aioquic.asyncio import connect
from aioquic.quic.configuration import QuicConfiguration

host = sys.argv[1]
port = int(sys.argv[2])
num_frames = int(sys.argv[3])
frame_size = int(sys.argv[4])
fps = int(sys.argv[5])
output = sys.argv[6]

results = {"frames_sent": 0}

async def main():
    config = QuicConfiguration(is_client=True, alpn_protocols=["test"])
    config.verify_mode = ssl.CERT_NONE
    config.idle_timeout = 60.0
    
    await asyncio.sleep(1)  # Attendre que le serveur soit prêt
    
    try:
        async with connect(host, port, configuration=config) as protocol:
            stream_id = protocol._quic.get_next_available_stream_id()
            
            start = time.time()
            frame_interval = 1.0 / fps
            
            for i in range(num_frames):
                data = bytes([i % 256] * frame_size)
                msg = struct.pack("!I", len(data)) + data
                
                is_last = (i == num_frames - 1)
                protocol._quic.send_stream_data(stream_id, msg, end_stream=is_last)
                protocol.transmit()
                results["frames_sent"] += 1
                
                # Respect du FPS
                next_frame = start + (i + 1) * frame_interval
                sleep_time = next_frame - time.time()
                if sleep_time > 0:
                    await asyncio.sleep(sleep_time)
            
            # Attendre que les retransmissions finissent
            await asyncio.sleep(5)
            results["duration"] = time.time() - start
            
    except Exception as e:
        results["error"] = str(e)
        results["duration"] = 0
    
    with open(output, "w") as f:
        json.dump(results, f)

asyncio.run(main())
