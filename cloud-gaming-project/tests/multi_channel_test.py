#!/usr/bin/env python3
"""
HOL BLOCKING TEST - Multi-Channel Version with rQUIC Priority System
====================================================================
Tests with 4 priority channels: VIDEO, AUDIO, INPUT, CHAT
Compares TCP, QUIC, and rQUIC with adaptive TTL per channel
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

# =============================================================================
# rQUIC SERVER - 4 channels with adaptive TTL priorities (SIMPLIFIÉ)
# =============================================================================
RQUIC_SERVER_CODE = '''
import socket
import json
import time
import struct
import threading

CHANNELS = ["VIDEO", "AUDIO", "INPUT", "CHAT"]
NUM_PER_CHANNEL = 30

# Map channels to ports
CHANNEL_PORTS = {"VIDEO": 5560, "AUDIO": 5561, "INPUT": 5562, "CHAT": 5563}

results = {ch: {"received": [], "timestamps": [], "dropped_ttl": 0} for ch in CHANNELS}

def run_channel_server(channel, port):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("0.0.0.0", port))
    sock.settimeout(1.0)
    
    received = set()
    start = time.time()
    no_data_count = 0
    
    print(f"[{channel}] Server ready on port {port}", flush=True)
    
    while (time.time() - start) < 30:
        try:
            data, addr = sock.recvfrom(65535)
            no_data_count = 0
            
            if len(data) < 10:
                continue
            
            packet_type = data[0]
            if packet_type == 0x01:  # DATA
                frame_id, frame_size, priority = struct.unpack('!IIB', data[1:10])
                
                try:
                    msg_data = data[10:10+frame_size].decode()
                    parts = msg_data.split(":")
                    if len(parts) >= 3:
                        ch, seq, ts = parts[0], int(parts[1]), float(parts[2])
                        if seq not in received:
                            received.add(seq)
                            results[channel]["received"].append(seq)
                            results[channel]["timestamps"].append(time.time() - ts)
                except:
                    pass
                
                # Send ACK
                ack = struct.pack('!BI', 0x02, frame_id)
                sock.sendto(ack, addr)
                
        except socket.timeout:
            no_data_count += 1
            if no_data_count > 5:  # 5 secondes sans données
                break
            continue
    
    sock.close()
    print(f"[{channel}] Done: received {len(received)}", flush=True)

threads = []
for ch in CHANNELS:
    t = threading.Thread(target=run_channel_server, args=(ch, CHANNEL_PORTS[ch]))
    t.daemon = True
    t.start()
    threads.append(t)

print("All servers started", flush=True)

for t in threads:
    t.join(timeout=35)

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

with open("_rquic_multi_server.json", "w") as f:
    json.dump(results, f)

print(f"rQUIC: " + ", ".join([f"{ch}={results[ch]['count']}" for ch in CHANNELS]), flush=True)
'''

RQUIC_CLIENT_CODE = '''
import time
import struct
import socket
import sys
import json

SERVER_IP = sys.argv[1]
CHANNELS = ["VIDEO", "AUDIO", "INPUT", "CHAT"]
NUM_MESSAGES = 30
PADDING = "X" * 400

# Map channels to priorities (numeric values) and their TTL
# CRITICAL=0 (500ms), HIGH=1 (100ms), MEDIUM=2 (50ms), LOW=3 (20ms)
CHANNEL_PRIORITIES = {
    "VIDEO": 2,   # MEDIUM - TTL 50ms
    "AUDIO": 1,   # HIGH - TTL 100ms
    "INPUT": 0,   # CRITICAL - TTL 500ms
    "CHAT": 3     # LOW - TTL 20ms
}

TTL_BY_PRIORITY = {
    0: 0.5,    # CRITICAL: 500ms
    1: 0.1,    # HIGH: 100ms
    2: 0.050,  # MEDIUM: 50ms
    3: 0.020   # LOW: 20ms
}

CHANNEL_PORTS = {"VIDEO": 5560, "AUDIO": 5561, "INPUT": 5562, "CHAT": 5563}

# Track pending ACKs and drops per channel
pending_acks = {ch: {} for ch in CHANNELS}
dropped_by_ttl = {ch: 0 for ch in CHANNELS}

# Create 4 sockets (one per channel)
sockets = {}
for ch in CHANNELS:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(0.001)
    sockets[ch] = sock

print("rQUIC Client starting...", flush=True)
time.sleep(2)

# Send messages
frame_id_by_ch = {ch: 0 for ch in CHANNELS}
last_check_time = time.time()

for i in range(NUM_MESSAGES):
    current_time = time.time()
    
    # Check TTL periodically (every 100ms) for frames awaiting retransmission
    # Only drop frames that are BOTH old AND not ACKed (=lost frames)
    if current_time - last_check_time > 0.1:  # Check every 100ms
        for ch in CHANNELS:
            priority = CHANNEL_PRIORITIES[ch]
            ttl = TTL_BY_PRIORITY[priority]
            
            to_drop = []
            for fid, send_time in pending_acks[ch].items():
                frame_age = current_time - send_time
                # Drop only if: frame is old (>TTL) AND waiting for retransmission (>50ms without ACK)
                if frame_age > ttl and frame_age > 0.05:  # At least 50ms old = probably lost
                    to_drop.append(fid)
            
            for fid in to_drop:
                del pending_acks[ch][fid]
                dropped_by_ttl[ch] += 1
        
        last_check_time = current_time
    
    # Send new messages
    for ch in CHANNELS:
        msg = f"{ch}:{i}:{time.time()}:{PADDING}"
        data = msg.encode()
        priority = CHANNEL_PRIORITIES[ch]
        fid = frame_id_by_ch[ch]
        
        # Build rQUIC packet: [type][frame_id][size][priority][data]
        packet = struct.pack('!BIIB', 0x01, fid, len(data), priority) + data
        sockets[ch].sendto(packet, (SERVER_IP, CHANNEL_PORTS[ch]))
        
        pending_acks[ch][fid] = time.time()
        frame_id_by_ch[ch] += 1
    
    # Try to receive ACKs
    for ch in CHANNELS:
        try:
            data, addr = sockets[ch].recvfrom(1024)
            if len(data) >= 5:
                packet_type = data[0]
                if packet_type == 0x02:  # ACK
                    fid = struct.unpack('!I', data[1:5])[0]
                    if fid in pending_acks[ch]:
                        del pending_acks[ch][fid]
        except:
            pass
    
    time.sleep(0.02)

time.sleep(2)

# Final ACK collection
for _ in range(10):
    for ch in CHANNELS:
        try:
            data, addr = sockets[ch].recvfrom(1024)
            if len(data) >= 5:
                packet_type = data[0]
                if packet_type == 0x02:  # ACK
                    fid = struct.unpack('!I', data[1:5])[0]
                    if fid in pending_acks[ch]:
                        del pending_acks[ch][fid]
        except:
            pass
    time.sleep(0.1)

for sock in sockets.values():
    sock.close()

# Save drops to file
with open("_rquic_client_drops.json", "w") as f:
    json.dump(dropped_by_ttl, f)

print(f"rQUIC Client done - Dropped: {dropped_by_ttl}", flush=True)
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


def run_rquic_test(net):
    h1, h2 = net.get('h1'), net.get('h2')
    h2.cmd(f"cat > /tmp/rquic_server.py << 'ENDSCRIPT'\n{RQUIC_SERVER_CODE}\nENDSCRIPT")
    h1.cmd(f"cat > /tmp/rquic_client.py << 'ENDSCRIPT'\n{RQUIC_CLIENT_CODE}\nENDSCRIPT")
    h2.cmd("cd /home/fret/Bureau/exchange-NCKU/Network-project/cloud-gaming-project && python3 /tmp/rquic_server.py &")
    time.sleep(2)
    h1.cmd(f"cd /home/fret/Bureau/exchange-NCKU/Network-project/cloud-gaming-project && python3 /tmp/rquic_client.py {h2.IP()}")
    time.sleep(3)
    h2.cmd("pkill -f rquic_server.py")
    time.sleep(1)
    try:
        with open("_rquic_multi_server.json", "r") as f:
            results = json.load(f)
        # Add drops from client
        try:
            with open("_rquic_client_drops.json", "r") as f:
                drops = json.load(f)
                for ch in CHANNELS:
                    results[ch]["dropped_ttl"] = drops.get(ch, 0)
        except:
            pass
        return results
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
    
    print("=" * 80)
    print("MULTI-CHANNEL HOL BLOCKING TEST with rQUIC Priority System")
    print("Channels: VIDEO, AUDIO, INPUT, CHAT")
    print("rQUIC Priorities: INPUT=CRITICAL(500ms), AUDIO=HIGH(100ms),")
    print("                  VIDEO=MEDIUM(50ms), CHAT=LOW(20ms)")
    print("=" * 80)
    
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
        
        time.sleep(2)
        
        # rQUIC
        print("  rQUIC...")
        net = create_network(scenario["loss"], scenario["delay"])
        rquic = run_rquic_test(net)
        net.stop()
        
        if rquic:
            result["rquic"] = {ch: {"jitter": round(rquic[ch]["jitter"], 2), "count": rquic[ch]["count"], "dropped": rquic[ch].get("dropped_ttl", 0)} for ch in CHANNELS}
            print(f"    Jitter: " + ", ".join([f"{ch}={rquic[ch]['jitter']:.2f}ms" for ch in CHANNELS]))
            print(f"    Dropped (TTL): " + ", ".join([f"{ch}={rquic[ch].get('dropped_ttl', 0)}" for ch in CHANNELS]))
        
        all_results.append(result)
        time.sleep(2)
    
    with open("MULTI_CHANNEL_RESULTS.json", "w") as f:
        json.dump(all_results, f, indent=2)
    
    print("\n" + "=" * 80)
    print("RESULTS SAVED: MULTI_CHANNEL_RESULTS.json")
    print("=" * 80)
    
    generate_graph(all_results)
    
    # Force cleanup and exit
    subprocess.run(['pkill', '-9', '-f', 'quic_'], capture_output=True)
    subprocess.run(['pkill', '-9', '-f', 'tcp_'], capture_output=True)
    subprocess.run(['pkill', '-9', '-f', 'rquic_'], capture_output=True)
    subprocess.run(['sudo', 'mn', '-c'], capture_output=True)
    os._exit(0)


def generate_graph(results):
    import matplotlib.pyplot as plt
    import numpy as np
    
    plt.switch_backend('Agg')
    
    channels = ["VIDEO", "AUDIO", "INPUT", "CHAT"]
    scenarios = [r["scenario"] for r in results]
    
    fig, axes = plt.subplots(2, 2, figsize=(15, 10))
    fig.subplots_adjust(hspace=0.35, wspace=0.3, top=0.95, bottom=0.08)
    
    for idx, scenario in enumerate(scenarios):
        r = results[idx]
        
        # Graphique 1 : Jitter par canal
        ax1 = axes[idx, 0]
        
        x = np.arange(len(channels))
        width = 0.25
        
        tcp_jitter = [r.get("tcp", {}).get(ch, {}).get("jitter", 0) for ch in channels]
        quic_jitter = [r.get("quic", {}).get(ch, {}).get("jitter", 0) for ch in channels]
        rquic_jitter = [r.get("rquic", {}).get(ch, {}).get("jitter", 0) for ch in channels]
        
        ax1.bar(x - width, tcp_jitter, width, label='TCP', color='#e74c3c', alpha=0.8)
        ax1.bar(x, quic_jitter, width, label='QUIC', color='#3498db', alpha=0.8)
        ax1.bar(x + width, rquic_jitter, width, label='rQUIC (TTL)', color='#2ecc71', alpha=0.8)
        
        ax1.set_xlabel('Channel', fontsize=11, fontweight='bold')
        ax1.set_ylabel('Jitter (ms)', fontsize=11, fontweight='bold')
        ax1.set_title(f'Jitter: {scenario}', fontsize=12, fontweight='bold')
        ax1.set_xticks(x)
        ax1.set_xticklabels(channels)
        ax1.legend(fontsize=9)
        ax1.grid(axis='y', alpha=0.3)
        
        # Graphique 2 : Frames droppées par rQUIC (TTL)
        ax2 = axes[idx, 1]
        
        rquic_dropped = [r.get("rquic", {}).get(ch, {}).get("dropped", 0) for ch in channels]
        rquic_received = [r.get("rquic", {}).get(ch, {}).get("count", 0) for ch in channels]
        
        colors_priority = ['#f39c12', '#e67e22', '#c0392b', '#95a5a6']  # VIDEO, AUDIO, INPUT, CHAT
        
        ax2.bar(channels, rquic_dropped, color=colors_priority, alpha=0.8, edgecolor='black', linewidth=1.5)
        
        # Annotations : % dropped
        for i, (ch, dropped, received) in enumerate(zip(channels, rquic_dropped, rquic_received)):
            total = dropped + received
            pct = (dropped / total * 100) if total > 0 else 0
            ax2.text(i, dropped + 0.5, f'{pct:.1f}%', ha='center', va='bottom', fontsize=9, fontweight='bold')
        
        ax2.set_xlabel('Channel', fontsize=11, fontweight='bold')
        ax2.set_ylabel('Frames Dropped (TTL)', fontsize=11, fontweight='bold')
        ax2.set_title(f'rQUIC Drops: {scenario}', fontsize=12, fontweight='bold')
        ax2.grid(axis='y', alpha=0.3)
    
    plt.savefig('MULTI_CHANNEL_RESULTS.png', dpi=150, bbox_inches='tight')
    plt.close('all')
    print("Graph saved: MULTI_CHANNEL_RESULTS.png")


if __name__ == "__main__":
    main()
