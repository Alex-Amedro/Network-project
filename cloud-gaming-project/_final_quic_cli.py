#!/usr/bin/env python3
import asyncio, struct, time, json, sys, ssl, random

from aioquic.asyncio import connect
from aioquic.quic.configuration import QuicConfiguration

host = sys.argv[1]
port = int(sys.argv[2])
num_frames = int(sys.argv[3])
fps = int(sys.argv[4])
output = sys.argv[5]

results = {"sent": 0, "blocked_time": 0}

def gen_frame(n):
    size = random.randint(100000, 150000) if n % 30 == 0 else random.randint(20000, 60000)
    return b"X" * size

async def main():
    config = QuicConfiguration(is_client=True, alpn_protocols=["gaming"])
    config.verify_mode = ssl.CERT_NONE
    config.idle_timeout = 120.0
    
    await asyncio.sleep(1)
    
    try:
        async with connect(host, port, configuration=config) as protocol:
            stream_id = protocol._quic.get_next_available_stream_id()
            start = time.time()
            
            for i in range(num_frames):
                data = gen_frame(i)
                ts = time.time()
                header = struct.pack("!IdI", i, ts, len(data))
                
                # QUIC: NON-BLOQUANT - pas d'attente d'ACK !
                protocol._quic.send_stream_data(stream_id, header + data, end_stream=(i == num_frames-1))
                protocol.transmit()
                results["sent"] += 1
                
                # FPS timing
                expected_time = start + (i + 1) / fps
                sleep_time = expected_time - time.time()
                if sleep_time > 0:
                    await asyncio.sleep(sleep_time)
            
            # Attend les retransmissions QUIC
            await asyncio.sleep(5)
            results["duration"] = time.time() - start
            
    except Exception as e:
        results["error"] = str(e)
        results["duration"] = 0
    
    with open(output, "w") as f:
        json.dump(results, f)

asyncio.run(main())
