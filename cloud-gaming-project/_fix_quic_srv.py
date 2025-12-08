#!/usr/bin/env python3
import asyncio
import struct
import time
import json
import sys

from aioquic.asyncio import serve
from aioquic.asyncio.protocol import QuicConnectionProtocol
from aioquic.quic.configuration import QuicConfiguration
from aioquic.quic.events import StreamDataReceived, ConnectionTerminated

port = int(sys.argv[1])
output = sys.argv[2]
cert = sys.argv[3]
key = sys.argv[4]
expected = int(sys.argv[5]) if len(sys.argv) > 5 else 60

results = {"frames_received": 0, "first_time": None, "last_time": None, "total_time": 0}

def save():
    # Calcul du temps à chaque sauvegarde
    if results["first_time"] and results["last_time"]:
        results["total_time"] = results["last_time"] - results["first_time"]
    tmp = output + ".tmp"
    with open(tmp, "w") as f:
        json.dump(results, f)
    import os
    os.rename(tmp, output)

class Server(QuicConnectionProtocol):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.buffer = b""
    
    def quic_event_received(self, event):
        global results
        if isinstance(event, StreamDataReceived):
            self.buffer += event.data
            
            while len(self.buffer) >= 4:
                frame_size = struct.unpack("!I", self.buffer[:4])[0]
                total = 4 + frame_size
                
                if len(self.buffer) >= total:
                    now = time.time()
                    if results["first_time"] is None:
                        results["first_time"] = now
                    results["last_time"] = now
                    results["frames_received"] += 1
                    self.buffer = self.buffer[total:]
                    save()
                else:
                    break
        
        elif isinstance(event, ConnectionTerminated):
            save()

async def main():
    config = QuicConfiguration(is_client=False, alpn_protocols=["test"])
    config.load_cert_chain(cert, key)
    config.idle_timeout = 60.0
    
    server = await serve("0.0.0.0", port, configuration=config, create_protocol=Server)
    save()
    
    # Attendre que toutes les frames arrivent
    start = time.time()
    while results["frames_received"] < expected and (time.time() - start) < 30:
        await asyncio.sleep(0.1)
    
    save()
    server.close()

asyncio.run(main())
