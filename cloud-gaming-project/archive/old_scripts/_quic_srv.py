#!/usr/bin/env python3
import asyncio, struct, time, json, sys

from aioquic.asyncio import serve
from aioquic.asyncio.protocol import QuicConnectionProtocol
from aioquic.quic.configuration import QuicConfiguration
from aioquic.quic.events import StreamDataReceived, ConnectionTerminated

port = int(sys.argv[1])
output = sys.argv[2]
cert = sys.argv[3]
key = sys.argv[4]

results = {"frames_received": 0, "bytes": 0, "latencies": [], "status": "starting"}

def save():
    with open(output, "w") as f:
        json.dump(results, f)

class Server(QuicConnectionProtocol):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.buffer = b""
    
    def quic_event_received(self, event):
        global results
        if isinstance(event, StreamDataReceived):
            self.buffer += event.data
            
            while len(self.buffer) >= 12:
                frame_size, send_ts = struct.unpack("!Id", self.buffer[:12])
                total = 12 + frame_size
                
                if len(self.buffer) >= total:
                    self.buffer = self.buffer[total:]
                    recv_time = time.time()
                    results["frames_received"] += 1
                    results["bytes"] += frame_size
                    results["latencies"].append((recv_time - send_ts) * 1000)
                    if results["frames_received"] % 60 == 0:
                        save()
                else:
                    break
        
        elif isinstance(event, ConnectionTerminated):
            results["status"] = "terminated"
            save()

async def main():
    results["status"] = "configuring"
    save()
    
    config = QuicConfiguration(is_client=False, alpn_protocols=["gaming"])
    config.load_cert_chain(cert, key)
    
    server = await serve("0.0.0.0", port, configuration=config, create_protocol=Server)
    results["status"] = "running"
    save()
    
    await asyncio.sleep(30)
    
    results["status"] = "done"
    save()
    server.close()

asyncio.run(main())
