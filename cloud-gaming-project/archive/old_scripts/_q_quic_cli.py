#!/usr/bin/env python3
import asyncio, struct, time, json, sys, ssl, random
from aioquic.asyncio import connect
from aioquic.quic.configuration import QuicConfiguration

host, port, num, fps, output = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4]), sys.argv[5]
results = {"sent": 0}

async def main():
    cfg = QuicConfiguration(is_client=True, alpn_protocols=["g"])
    cfg.verify_mode = ssl.CERT_NONE
    cfg.idle_timeout = 60.0
    await asyncio.sleep(0.5)
    
    try:
        async with connect(host, port, configuration=cfg) as p:
            sid = p._quic.get_next_available_stream_id()
            start = time.time()
            
            for i in range(num):
                size = random.randint(10000, 30000)
                data = b"X" * size
                p._quic.send_stream_data(sid, struct.pack("!IdI", i, time.time(), size) + data, end_stream=(i==num-1))
                p.transmit()
                results["sent"] += 1
                
                wait = start + (i+1)/fps - time.time()
                if wait > 0: await asyncio.sleep(wait)
            
            await asyncio.sleep(3)
            results["duration"] = time.time() - start
    except Exception as e:
        results["error"] = str(e)
        results["duration"] = 0
    
    json.dump(results, open(output, "w"))

asyncio.run(main())
