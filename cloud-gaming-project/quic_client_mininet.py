#!/usr/bin/env python3
import asyncio
import struct
import time
import json
import sys
import ssl
import os

venv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'venv', 'lib', 'python3.12', 'site-packages')
sys.path.insert(0, venv_path)

from aioquic.asyncio import connect
from aioquic.quic.configuration import QuicConfiguration

host = sys.argv[1]
port = int(sys.argv[2])
num_frames = int(sys.argv[3])
frame_size = int(sys.argv[4])
fps = int(sys.argv[5])
output = sys.argv[6]

results = {'frames_sent': 0}

async def main():
    config = QuicConfiguration(is_client=True, alpn_protocols=["test"])
    config.verify_mode = ssl.CERT_NONE
    
    await asyncio.sleep(1)
    
    async with connect(host, port, configuration=config) as protocol:
        stream_id = protocol._quic.get_next_available_stream_id()
        
        start = time.time()
        
        for i in range(num_frames):
            send_time = time.time()
            data = bytes([i % 256] * frame_size)
            msg = struct.pack('!Id', len(data), send_time) + data
            protocol._quic.send_stream_data(stream_id, msg, end_stream=(i == num_frames - 1))
            protocol.transmit()
            results['frames_sent'] += 1
            
            expected = start + (i + 1) / fps
            sleep = expected - time.time()
            if sleep > 0:
                await asyncio.sleep(sleep)
        
        await asyncio.sleep(2)
    
    with open(output, 'w') as f:
        json.dump(results, f)

asyncio.run(main())
