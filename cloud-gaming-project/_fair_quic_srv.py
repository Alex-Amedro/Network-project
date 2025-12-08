#!/usr/bin/env python3
"""QUIC Server - 4 streams VRAIMENT indépendants (pas de HoL blocking)"""
import asyncio, struct, time, json, sys

from aioquic.asyncio import serve
from aioquic.asyncio.protocol import QuicConnectionProtocol
from aioquic.quic.configuration import QuicConfiguration
from aioquic.quic.events import StreamDataReceived, ConnectionTerminated

port = int(sys.argv[1])
output = sys.argv[2]
cert = sys.argv[3]
key = sys.argv[4]
expected_total = int(sys.argv[5])

results = {
    "frames_received": 0,
    "streams": {},
    "first_frame_time": None,
    "last_frame_time": None,
    "latencies": [],
    "status": "starting"
}
stream_buffers = {}

def save():
    with open(output, "w") as f:
        json.dump(results, f)

class Server(QuicConnectionProtocol):
    def quic_event_received(self, event):
        global results, stream_buffers
        
        if isinstance(event, StreamDataReceived):
            stream_id = event.stream_id
            
            if stream_id not in stream_buffers:
                stream_buffers[stream_id] = b""
            stream_buffers[stream_id] += event.data
            
            # Header: frame_id (4) + timestamp (8) + size (4) = 16 bytes
            while len(stream_buffers[stream_id]) >= 16:
                buf = stream_buffers[stream_id]
                frame_id, send_ts, frame_size = struct.unpack("!IdI", buf[:16])
                total_needed = 16 + frame_size
                
                if len(buf) >= total_needed:
                    recv_time = time.time()
                    
                    if results["first_frame_time"] is None:
                        results["first_frame_time"] = recv_time
                    results["last_frame_time"] = recv_time
                    
                    results["frames_received"] += 1
                    results["streams"][str(stream_id)] = results["streams"].get(str(stream_id), 0) + 1
                    results["latencies"].append((recv_time - send_ts) * 1000)
                    
                    stream_buffers[stream_id] = buf[total_needed:]
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
    config.idle_timeout = 120.0
    
    server = await serve("0.0.0.0", port, configuration=config, create_protocol=Server)
    results["status"] = "running"
    save()
    
    # Attendre que toutes les frames arrivent
    start = time.time()
    while results["frames_received"] < expected_total and (time.time() - start) < 120:
        await asyncio.sleep(0.1)
        save()
    
    if results["first_frame_time"] and results["last_frame_time"]:
        results["total_time"] = results["last_frame_time"] - results["first_frame_time"]
    
    results["status"] = "done"
    save()
    server.close()

asyncio.run(main())
