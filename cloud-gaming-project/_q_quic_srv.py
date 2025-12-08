#!/usr/bin/env python3
import asyncio, struct, time, json, sys, ssl
from aioquic.asyncio import serve
from aioquic.asyncio.protocol import QuicConnectionProtocol
from aioquic.quic.configuration import QuicConfiguration
from aioquic.quic.events import StreamDataReceived

port, output, cert, key, expected = int(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4], int(sys.argv[5])
results = {"received": 0, "first_time": None, "last_time": None}
done = asyncio.Event()

class Server(QuicConnectionProtocol):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.buf = b""
    
    def quic_event_received(self, e):
        global results
        if isinstance(e, StreamDataReceived):
            self.buf += e.data
            while len(self.buf) >= 16:
                seq, ts, size = struct.unpack("!IdI", self.buf[:16])
                if len(self.buf) < 16 + size: break
                now = time.time()
                if not results["first_time"]: results["first_time"] = now
                results["last_time"] = now
                results["received"] += 1
                self.buf = self.buf[16+size:]
                if results["received"] >= expected: done.set()

async def main():
    cfg = QuicConfiguration(is_client=False, alpn_protocols=["g"])
    cfg.load_cert_chain(cert, key)
    cfg.idle_timeout = 60.0
    srv = await serve("0.0.0.0", port, configuration=cfg, create_protocol=Server)
    try: await asyncio.wait_for(done.wait(), 60)
    except: pass
    results["total_time"] = (results["last_time"] - results["first_time"]) if results["first_time"] else 0
    json.dump(results, open(output, "w"))
    srv.close()

asyncio.run(main())
