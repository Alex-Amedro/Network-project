#!/usr/bin/env python3
import asyncio, struct, time, json, sys, ssl

from aioquic.asyncio import connect
from aioquic.quic.configuration import QuicConfiguration

host = sys.argv[1]
port = int(sys.argv[2])
num_frames = int(sys.argv[3])
frame_size = int(sys.argv[4])
fps = int(sys.argv[5])
output = sys.argv[6]

results = {"frames_sent": 0, "status": "starting"}

def save():
    with open(output, "w") as f:
        json.dump(results, f)

async def main():
    global results
    config = QuicConfiguration(is_client=True, alpn_protocols=["gaming"])
    config.verify_mode = ssl.CERT_NONE
    
    await asyncio.sleep(1)
    
    try:
        async with connect(host, port, configuration=config) as protocol:
            results["status"] = "connected"
            save()
            
            stream_id = protocol._quic.get_next_available_stream_id()
            start = time.time()
            
            for i in range(num_frames):
                send_time = time.time()
                data = bytes([i % 256] * frame_size)
                msg = struct.pack("!Id", len(data), send_time) + data
                protocol._quic.send_stream_data(stream_id, msg, end_stream=(i == num_frames - 1))
                protocol.transmit()
                results["frames_sent"] += 1
                
                expected = start + (i + 1) / fps
                sleep = expected - time.time()
                if sleep > 0:
                    await asyncio.sleep(sleep)
            
            await asyncio.sleep(2)
            results["status"] = "done"
            save()
    
    except Exception as e:
        results["error"] = str(e)
        results["status"] = "error"
        save()

asyncio.run(main())
