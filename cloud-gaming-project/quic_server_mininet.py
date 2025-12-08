#!/usr/bin/env python3
import asyncio
import struct
import time
import json
import sys
import ssl
import os

# Ajouter le venv au path
venv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'venv', 'lib', 'python3.12', 'site-packages')
sys.path.insert(0, venv_path)

from aioquic.asyncio import serve
from aioquic.asyncio.protocol import QuicConnectionProtocol
from aioquic.quic.configuration import QuicConfiguration
from aioquic.quic.events import StreamDataReceived

port = int(sys.argv[1])
output = sys.argv[2]
duration = int(sys.argv[3])
cert = sys.argv[4]
key = sys.argv[5]

results = {'frames_received': 0, 'bytes': 0, 'latencies': []}

class Server(QuicConnectionProtocol):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.buf = b''
    
    def quic_event_received(self, event):
        if isinstance(event, StreamDataReceived):
            self.buf += event.data
            while len(self.buf) >= 12:
                frame_size, send_ts = struct.unpack('!Id', self.buf[:12])
                total = 12 + frame_size
                if len(self.buf) >= total:
                    self.buf = self.buf[total:]
                    recv_time = time.time()
                    results['frames_received'] += 1
                    results['bytes'] += frame_size
                    results['latencies'].append((recv_time - send_ts) * 1000)
                else:
                    break

async def main():
    config = QuicConfiguration(is_client=False, alpn_protocols=["test"])
    config.load_cert_chain(cert, key)
    
    server = await serve('0.0.0.0', port, configuration=config, create_protocol=Server)
    
    await asyncio.sleep(duration + 5)
    server.close()
    
    with open(output, 'w') as f:
        json.dump(results, f)

asyncio.run(main())
