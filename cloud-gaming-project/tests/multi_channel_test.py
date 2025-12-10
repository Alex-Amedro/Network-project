#!/usr/bin/env python3
"""
HOL BLOCKING TEST - Multi-Channel Version
==========================================
Tests with 4 priority channels instead of 2.
Simulates real gaming traffic: Video, Audio, Input, Chat
"""

import sys
import os
import json
import time
import socket
import asyncio
import subprocess

# Force matplotlib to use non-interactive backend
import matplotlib
matplotlib.use('Agg')

from mininet.net import Mininet
from mininet.node import OVSSwitch
from mininet.link import TCLink
from mininet.log import setLogLevel

SERVER_PORT = 5560
NUM_MESSAGES = 30  # Per channel
CHANNELS = ["VIDEO", "AUDIO", "INPUT", "CHAT"]

# =============================================================================
# TCP SERVER - 4 channels on same connection
# =============================================================================
TCP_SERVER_CODE = '''
import socket
import json
import time

PORT = 5560
CHANNELS = ["VIDEO", "AUDIO", "INPUT", "CHAT"]
NUM_PER_CHANNEL = 30
NUM_EXPECTED = NUM_PER_CHANNEL * len(CHANNELS)

results = {ch: {"received": [], "timestamps": []} for ch in CHANNELS}

server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
server.bind(("0.0.0.0", PORT))
server.listen(1)
server.settimeout(30)

print("TCP Server ready", flush=True)

try:
    conn, addr = server.accept()
    conn.settimeout(20)
    buffer = b""
    count = 0
    start = time.time()
    
    while count < NUM_EXPECTED and (time.time() - start) < 25:
        try:
            data = conn.recv(4096)
            if not data:
                break
            buffer += data
            
            while b"|" in buffer:
                msg, buffer = buffer.split(b"|", 1)
                parts = msg.decode().split(":")
                if len(parts) >= 3:
                    ch, seq, ts = parts[0], int(parts[1]), float(parts[2])
                    if ch in results:
                        results[ch]["received"].append(seq)
                        results[ch]["timestamps"].append(time.time() - ts)
                        count += 1
        except socket.timeout:
            break
    conn.close()
except Exception as e:
    print(f"Error: {e}", flush=True)

server.close()

# Calculate stats
for ch in CHANNELS:
    ts = results[ch]["timestamps"]
    results[ch]["count"] = len(ts)
    results[ch]["avg_latency"] = sum(ts) / len(ts) * 1000 if ts else 0
    if len(ts) > 1:
        delays = [abs(ts[i] - ts[i-1]) * 1000 for i in range(1, len(ts))]
        results[ch]["jitter"] = sum(delays) / len(delays) if delays else 0
    else:
        results[ch]["jitter"] = 0

with open("_tcp_multi_server.json", "w") as f:
    json.dump(results, f)

print(f"TCP: " + ", ".join([f"{ch}={results[ch]['count']}" for ch in CHANNELS]), flush=True)
'''

TCP_CLIENT_CODE = '''
import socket
import time
import sys

SERVER_IP = sys.argv[1]
PORT = 5560
CHANNELS = ["VIDEO", "AUDIO", "INPUT", "CHAT"]
NUM_MESSAGES = 30
PADDING = "X" * 400

sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.connect((SERVER_IP, PORT))

for i in range(NUM_MESSAGES):
    for ch in CHANNELS:
        msg = f"{ch}:{i}:{time.time()}:{PADDING}|"
        sock.sendall(msg.encode())
    time.sleep(0.02)

time.sleep(1)
sock.close()
print("TCP Client done", flush=True)
'''

# =============================================================================
# QUIC SERVER - 4 independent streams
# =============================================================================
QUIC_SERVER_CODE = '''
import asyncio
import json
import time
from aioquic.asyncio import serve
from aioquic.asyncio.protocol import QuicConnectionProtocol
from aioquic.quic.configuration import QuicConfiguration
from aioquic.quic.events import StreamDataReceived, ConnectionTerminated

CHANNELS = ["VIDEO", "AUDIO", "INPUT", "CHAT"]
NUM_PER_CHANNEL = 30
NUM_EXPECTED = NUM_PER_CHANNEL * len(CHANNELS)

results = {ch: {"received": [], "timestamps": []} for ch in CHANNELS}
count = 0
done = asyncio.Event()

class ServerProtocol(QuicConnectionProtocol):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.buffers = {}
    
    def quic_event_received(self, event):
        global count, results
        if isinstance(event, StreamDataReceived):
            sid = event.stream_id
            if sid not in self.buffers:
                self.buffers[sid] = b""
            self.buffers[sid] += event.data
            
            while b"|" in self.buffers[sid]:
                msg, self.buffers[sid] = self.buffers[sid].split(b"|", 1)
                parts = msg.decode().split(":")
                if len(parts) >= 3:
                    ch, seq, ts = parts[0], int(parts[1]), float(parts[2])
                    if ch in results:
                        results[ch]["received"].append(seq)
                        results[ch]["timestamps"].append(time.time() - ts)
                        count += 1
                        if count >= NUM_EXPECTED:
                            done.set()
        elif isinstance(event, ConnectionTerminated):
            done.set()

async def main():
    config = QuicConfiguration(is_client=False)
    config.load_cert_chain("server.cert", "server.key")
    config.verify_mode = False
    config.idle_timeout = 30.0
    
    server = await serve("0.0.0.0", 5560, configuration=config, create_protocol=ServerProtocol)
    print("QUIC Server ready", flush=True)
    
    try:
        await asyncio.wait_for(done.wait(), timeout=25)
    except asyncio.TimeoutError:
        pass
    
    server.close()
    
    for ch in CHANNELS:
        ts = results[ch]["timestamps"]
        results[ch]["count"] = len(ts)
        results[ch]["avg_latency"] = sum(ts) / len(ts) * 1000 if ts else 0
        if len(ts) > 1:
            delays = [abs(ts[i] - ts[i-1]) * 1000 for i in range(1, len(ts))]
            results[ch]["jitter"] = sum(delays) / len(delays) if delays else 0
        else:
            results[ch]["jitter"] = 0
    
    with open("_quic_multi_server.json", "w") as f:
        json.dump(results, f)
    
    print(f"QUIC: " + ", ".join([f"{ch}={results[ch]['count']}" for ch in CHANNELS]), flush=True)

asyncio.run(main())
'''

QUIC_CLIENT_CODE = '''
import asyncio
import time
import sys
from aioquic.asyncio import connect
from aioquic.quic.configuration import QuicConfiguration

SERVER_IP = sys.argv[1]
CHANNELS = ["VIDEO", "AUDIO", "INPUT", "CHAT"]
NUM_MESSAGES = 30
PADDING = "X" * 400

async def main():
    config = QuicConfiguration(is_client=True)
    config.verify_mode = False
    config.idle_timeout = 30.0
    
    await asyncio.sleep(1)
    
    try:
        async with connect(SERVER_IP, 5560, configuration=config) as protocol:
            streams = {ch: protocol._quic.get_next_available_stream_id() for ch in CHANNELS}
            
            for i in range(NUM_MESSAGES):
                for ch in CHANNELS:
                    msg = f"{ch}:{i}:{time.time()}:{PADDING}|"
                    protocol._quic.send_stream_data(streams[ch], msg.encode(), end_stream=False)
                protocol.transmit()
                await asyncio.sleep(0.02)
            
            for ch in CHANNELS:
                protocol._quic.send_stream_data(streams[ch], b"", end_stream=True)
            protocol.transmit()
            await asyncio.sleep(0.5)
        print("QUIC Client done", flush=True)
    except Exception as e:
        print(f"QUIC Error: {e}", flush=True)

asyncio.run(main())
'''


def run_tcp_test(net):
    h1, h2 = net.get('h1'), net.get('h2')
    h2.cmd(f"cat > /tmp/tcp_server.py << 'ENDSCRIPT'\n{TCP_SERVER_CODE}\nENDSCRIPT")
    h1.cmd(f"cat > /tmp/tcp_client.py << 'ENDSCRIPT'\n{TCP_CLIENT_CODE}\nENDSCRIPT")
    h2.cmd("cd /home/fret/Bureau/exchange-NCKU/Network-project/cloud-gaming-project && python3 /tmp/tcp_server.py &")
    time.sleep(2)
    h1.cmd(f"python3 /tmp/tcp_client.py {h2.IP()}")
    time.sleep(3)
    h2.cmd("pkill -f tcp_server.py")
    time.sleep(1)
    try:
        with open("_tcp_multi_server.json", "r") as f:
            return json.load(f)
    except:
        return None


def run_quic_test(net):
    h1, h2 = net.get('h1'), net.get('h2')
    h2.cmd(f"cat > /tmp/quic_server.py << 'ENDSCRIPT'\n{QUIC_SERVER_CODE}\nENDSCRIPT")
    h1.cmd(f"cat > /tmp/quic_client.py << 'ENDSCRIPT'\n{QUIC_CLIENT_CODE}\nENDSCRIPT")
    h2.cmd("cd /home/fret/Bureau/exchange-NCKU/Network-project/cloud-gaming-project && python3 /tmp/quic_server.py &")
    time.sleep(2)
    h1.cmd(f"cd /home/fret/Bureau/exchange-NCKU/Network-project/cloud-gaming-project && python3 /tmp/quic_client.py {h2.IP()}")
    time.sleep(3)
    h2.cmd("pkill -f quic_server.py")
    time.sleep(1)
    try:
        with open("_quic_multi_server.json", "r") as f:
            return json.load(f)
    except:
        return None


def create_network(loss, delay):
    net = Mininet(switch=OVSSwitch, link=TCLink)
    h1 = net.addHost('h1')
    h2 = net.addHost('h2')
    s1 = net.addSwitch('s1', failMode='standalone')
    net.addLink(h1, s1, loss=loss, delay=f'{delay}ms')
    net.addLink(h2, s1, loss=loss, delay=f'{delay}ms')
    net.start()
    return net


def main():
    setLogLevel('warning')
    
    print("=" * 60)
    print("MULTI-CHANNEL HOL BLOCKING TEST")
    print("Channels: VIDEO, AUDIO, INPUT, CHAT")
    print("=" * 60)
    
    scenarios = [
        {"name": "Ideal", "loss": 0, "delay": 5},
        {"name": "5% Loss", "loss": 5, "delay": 10},
    ]
    
    all_results = []
    
    for scenario in scenarios:
        print(f"\n--- {scenario['name']} ---")
        result = {"scenario": scenario["name"]}
        
        # TCP
        print("  TCP...")
        net = create_network(scenario["loss"], scenario["delay"])
        tcp = run_tcp_test(net)
        net.stop()
        
        if tcp:
            result["tcp"] = {ch: {"jitter": round(tcp[ch]["jitter"], 2), "count": tcp[ch]["count"]} for ch in CHANNELS}
            print(f"    Jitter: " + ", ".join([f"{ch}={tcp[ch]['jitter']:.2f}ms" for ch in CHANNELS]))
        
        time.sleep(2)
        
        # QUIC
        print("  QUIC...")
        net = create_network(scenario["loss"], scenario["delay"])
        quic = run_quic_test(net)
        net.stop()
        
        if quic:
            result["quic"] = {ch: {"jitter": round(quic[ch]["jitter"], 2), "count": quic[ch]["count"]} for ch in CHANNELS}
            print(f"    Jitter: " + ", ".join([f"{ch}={quic[ch]['jitter']:.2f}ms" for ch in CHANNELS]))
        
        all_results.append(result)
        time.sleep(2)
    
    with open("MULTI_CHANNEL_RESULTS.json", "w") as f:
        json.dump(all_results, f, indent=2)
    
    print("\n" + "=" * 60)
    print("RESULTS SAVED: MULTI_CHANNEL_RESULTS.json")
    print("=" * 60)
    
    generate_graph(all_results)
    
    # Force cleanup and exit
    subprocess.run(['pkill', '-9', '-f', 'quic_'], capture_output=True)
    subprocess.run(['pkill', '-9', '-f', 'tcp_'], capture_output=True)
    subprocess.run(['sudo', 'mn', '-c'], capture_output=True)
    os._exit(0)


def generate_graph(results):
    import matplotlib.pyplot as plt
    import numpy as np
    
    plt.switch_backend('Agg')
    
    channels = ["VIDEO", "AUDIO", "INPUT", "CHAT"]
    scenarios = [r["scenario"] for r in results]
    
    fig, axes = plt.subplots(1, 2, figsize=(14, 6))
    
    for idx, scenario in enumerate(scenarios):
        r = results[idx]
        ax = axes[idx]
        
        x = np.arange(len(channels))
        width = 0.35
        
        tcp_jitter = [r.get("tcp", {}).get(ch, {}).get("jitter", 0) for ch in channels]
        quic_jitter = [r.get("quic", {}).get(ch, {}).get("jitter", 0) for ch in channels]
        
        ax.bar(x - width/2, tcp_jitter, width, label='TCP', color='#e74c3c', alpha=0.8)
        ax.bar(x + width/2, quic_jitter, width, label='QUIC', color='#3498db', alpha=0.8)
        
        ax.set_xlabel('Channel', fontsize=12)
        ax.set_ylabel('Jitter (ms)', fontsize=12)
        ax.set_title(f'Multi-Channel HoL Blocking: {scenario}', fontsize=14)
        ax.set_xticks(x)
        ax.set_xticklabels(channels)
        ax.legend()
        ax.grid(axis='y', alpha=0.3)
    
    plt.tight_layout()
    plt.savefig('MULTI_CHANNEL_RESULTS.png', dpi=150, bbox_inches='tight')
    plt.close('all')
    print("Graph saved: MULTI_CHANNEL_RESULTS.png")


if __name__ == "__main__":
    main()
