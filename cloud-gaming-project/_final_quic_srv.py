#!/usr/bin/env python3
import asyncio, struct, time, json, sys, ssl

from aioquic.asyncio import serve
from aioquic.asyncio.protocol import QuicConnectionProtocol
from aioquic.quic.configuration import QuicConfiguration
from aioquic.quic.events import StreamDataReceived

port = int(sys.argv[1])
output = sys.argv[2]
cert = sys.argv[3]
key = sys.argv[4]
expected = int(sys.argv[5])

results = {"received": 0, "first_time": None, "last_time": None}
done = asyncio.Event()

class Server(QuicConnectionProtocol):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.buffer = b""
    
    def quic_event_received(self, event):
        global results
        if isinstance(event, StreamDataReceived):
            self.buffer += event.data
            
            while len(self.buffer) >= 16:
                seq, ts, size = struct.unpack("!IdI", self.buffer[:16])
                total = 16 + size
                if len(self.buffer) < total: break
                
                now = time.time()
                if results["first_time"] is None:
                    results["first_time"] = now
                results["last_time"] = now
                results["received"] += 1
                self.buffer = self.buffer[total:]
                
                if results["received"] >= expected:
                    done.set()

async def main():
    config = QuicConfiguration(is_client=False, alpn_protocols=["gaming"])
    config.load_cert_chain(cert, key)
    config.idle_timeout = 120.0
    
    server = await serve("0.0.0.0", port, configuration=config, create_protocol=Server)
    
    try:
        await asyncio.wait_for(done.wait(), timeout=120)
    except: pass
    
    if results["first_time"] and results["last_time"]:
        results["total_time"] = results["last_time"] - results["first_time"]
    else:
        results["total_time"] = 0
    
    with open(output, "w") as f:
        json.dump(results, f)
    server.close()

asyncio.run(main())
