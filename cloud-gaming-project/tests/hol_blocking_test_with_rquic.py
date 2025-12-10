#!/usr/bin/env python3
"""
HOL BLOCKING TEST - TCP vs QUIC vs rQUIC
=========================================
Compares Head-of-Line blocking behavior across 3 protocols.

TCP: Single connection, all streams blocked when one packet lost
QUIC: Independent streams, no cross-stream blocking  
rQUIC: Custom UDP + ARQ, selective retransmission
"""

import sys
import os
import json
import time
import socket
import ssl
import asyncio
import subprocess
from pathlib import Path

# Force matplotlib to use non-interactive backend
import matplotlib
matplotlib.use('Agg')

from mininet.net import Mininet
from mininet.node import OVSSwitch
from mininet.link import TCLink
from mininet.log import setLogLevel

# Configuration
SERVER_PORT_TCP = 5555
SERVER_PORT_QUIC = 5556
SERVER_PORT_RQUIC = 5557
NUM_MESSAGES = 50
MESSAGE_SIZE = 500

# =============================================================================
# TCP SERVER CODE
# =============================================================================
TCP_SERVER_CODE = '''
import socket
import json
import time

PORT = 5555
NUM_EXPECTED = 100

results = {"high": {"received": [], "timestamps": []}, "low": {"received": [], "timestamps": []}}

server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
server.bind(("0.0.0.0", PORT))
server.listen(1)
server.settimeout(30)

print("TCP Server ready", flush=True)

try:
    conn, addr = server.accept()
    conn.settimeout(15)
    buffer = b""
    count = 0
    start_time = time.time()
    
    while count < NUM_EXPECTED and (time.time() - start_time) < 20:
        try:
            data = conn.recv(4096)
            if not data:
                break
            buffer += data
            
            while b"|" in buffer:
                msg, buffer = buffer.split(b"|", 1)
                msg = msg.decode()
                parts = msg.split(":")
                if len(parts) >= 3:
                    msg_type, seq, send_ts = parts[0], int(parts[1]), float(parts[2])
                    recv_ts = time.time()
                    
                    if msg_type == "HIGH":
                        results["high"]["received"].append(seq)
                        results["high"]["timestamps"].append(recv_ts - send_ts)
                    elif msg_type == "LOW":
                        results["low"]["received"].append(seq)
                        results["low"]["timestamps"].append(recv_ts - send_ts)
                    count += 1
        except socket.timeout:
            break
    conn.close()
except Exception as e:
    print(f"Error: {e}", flush=True)

server.close()

# Calculate stats
for stream in ["high", "low"]:
    ts = results[stream]["timestamps"]
    results[stream]["count"] = len(ts)
    results[stream]["avg_latency"] = sum(ts) / len(ts) * 1000 if ts else 0
    if len(ts) > 1:
        delays = [abs(ts[i] - ts[i-1]) * 1000 for i in range(1, len(ts))]
        results[stream]["jitter"] = sum(delays) / len(delays) if delays else 0
    else:
        results[stream]["jitter"] = 0

with open("_tcp_hol_server.json", "w") as f:
    json.dump(results, f)

print(f"TCP done: HIGH={results['high']['count']}, LOW={results['low']['count']}", flush=True)
'''

# =============================================================================
# TCP CLIENT CODE
# =============================================================================
TCP_CLIENT_CODE = '''
import socket
import time
import sys

SERVER_IP = sys.argv[1]
PORT = 5555
NUM_MESSAGES = 50
MESSAGE_SIZE = 500

sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.connect((SERVER_IP, PORT))

padding = "X" * MESSAGE_SIZE

for i in range(NUM_MESSAGES):
    for msg_type in ["HIGH", "LOW"]:
        msg = f"{msg_type}:{i}:{time.time()}:{padding}|"
        sock.sendall(msg.encode())
    time.sleep(0.01)

time.sleep(1)
sock.close()
print("TCP Client done", flush=True)
'''

# =============================================================================
# QUIC SERVER CODE (using aioquic)
# =============================================================================
QUIC_SERVER_CODE = '''
import asyncio
import json
import time
from aioquic.asyncio import serve
from aioquic.asyncio.protocol import QuicConnectionProtocol
from aioquic.quic.configuration import QuicConfiguration
from aioquic.quic.events import StreamDataReceived, ConnectionTerminated

results = {"high": {"received": [], "timestamps": []}, "low": {"received": [], "timestamps": []}}
count = 0
done_event = asyncio.Event()

class ServerProtocol(QuicConnectionProtocol):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.buffers = {}
    
    def quic_event_received(self, event):
        global count, results
        if isinstance(event, StreamDataReceived):
            stream_id = event.stream_id
            if stream_id not in self.buffers:
                self.buffers[stream_id] = b""
            self.buffers[stream_id] += event.data
            
            while b"|" in self.buffers[stream_id]:
                msg, self.buffers[stream_id] = self.buffers[stream_id].split(b"|", 1)
                parts = msg.decode().split(":")
                if len(parts) >= 3:
                    msg_type, seq, send_ts = parts[0], int(parts[1]), float(parts[2])
                    recv_ts = time.time()
                    if msg_type == "HIGH":
                        results["high"]["received"].append(seq)
                        results["high"]["timestamps"].append(recv_ts - send_ts)
                    elif msg_type == "LOW":
                        results["low"]["received"].append(seq)
                        results["low"]["timestamps"].append(recv_ts - send_ts)
                    count += 1
                    if count >= 100:
                        done_event.set()
        elif isinstance(event, ConnectionTerminated):
            done_event.set()

async def main():
    config = QuicConfiguration(is_client=False)
    config.load_cert_chain("server.cert", "server.key")
    
    server = await serve("0.0.0.0", 5556, configuration=config, create_protocol=ServerProtocol)
    print("QUIC Server ready", flush=True)
    
    try:
        await asyncio.wait_for(done_event.wait(), timeout=20)
    except asyncio.TimeoutError:
        pass
    
    server.close()
    
    for stream in ["high", "low"]:
        ts = results[stream]["timestamps"]
        results[stream]["count"] = len(ts)
        results[stream]["avg_latency"] = sum(ts) / len(ts) * 1000 if ts else 0
        if len(ts) > 1:
            delays = [abs(ts[i] - ts[i-1]) * 1000 for i in range(1, len(ts))]
            results[stream]["jitter"] = sum(delays) / len(delays) if delays else 0
        else:
            results[stream]["jitter"] = 0
    
    with open("_quic_hol_server.json", "w") as f:
        json.dump(results, f)
    
    print(f"QUIC done: HIGH={results['high']['count']}, LOW={results['low']['count']}", flush=True)

asyncio.run(main())
'''

# =============================================================================
# QUIC CLIENT CODE
# =============================================================================
QUIC_CLIENT_CODE = '''
import asyncio
import sys
import time
from aioquic.asyncio import connect
from aioquic.asyncio.protocol import QuicConnectionProtocol
from aioquic.quic.configuration import QuicConfiguration

SERVER_IP = sys.argv[1]
NUM_MESSAGES = 50
MESSAGE_SIZE = 500

async def main():
    config = QuicConfiguration(is_client=True)
    config.verify_mode = False
    
    async with connect(SERVER_IP, 5556, configuration=config) as protocol:
        padding = "X" * MESSAGE_SIZE
        high_stream = protocol._quic.get_next_available_stream_id()
        low_stream = protocol._quic.get_next_available_stream_id()
        
        for i in range(NUM_MESSAGES):
            high_msg = f"HIGH:{i}:{time.time()}:{padding}|"
            low_msg = f"LOW:{i}:{time.time()}:{padding}|"
            
            protocol._quic.send_stream_data(high_stream, high_msg.encode(), end_stream=False)
            protocol._quic.send_stream_data(low_stream, low_msg.encode(), end_stream=False)
            protocol.transmit()
            await asyncio.sleep(0.01)
        
        protocol._quic.send_stream_data(high_stream, b"", end_stream=True)
        protocol._quic.send_stream_data(low_stream, b"", end_stream=True)
        protocol.transmit()
        await asyncio.sleep(1)

asyncio.run(main())
print("QUIC Client done", flush=True)
'''

# =============================================================================
# rQUIC SERVER CODE (UDP + Selective Retransmission)
# =============================================================================
RQUIC_SERVER_CODE = '''
import socket
import struct
import json
import time

PORT = 5557
NUM_EXPECTED = 100

results = {"high": {"received": [], "timestamps": []}, "low": {"received": [], "timestamps": []}}
received_seqs = {"HIGH": set(), "LOW": set()}

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
sock.bind(("0.0.0.0", PORT))
sock.settimeout(1.0)

print("rQUIC Server ready", flush=True)

count = 0
start_time = time.time()
client_addr = None

while count < NUM_EXPECTED and (time.time() - start_time) < 20:
    try:
        data, addr = sock.recvfrom(65535)
        client_addr = addr
        recv_ts = time.time()
        
        # Packet format: type(1) + seq(4) + send_ts(8) + msg_type(1) + padding
        if len(data) < 14:
            continue
        
        pkt_type = data[0]
        seq = struct.unpack("!I", data[1:5])[0]
        send_ts = struct.unpack("!d", data[5:13])[0]
        msg_type = "HIGH" if data[13] == 0 else "LOW"
        
        if seq not in received_seqs[msg_type]:
            received_seqs[msg_type].add(seq)
            
            if msg_type == "HIGH":
                results["high"]["received"].append(seq)
                results["high"]["timestamps"].append(recv_ts - send_ts)
            else:
                results["low"]["received"].append(seq)
                results["low"]["timestamps"].append(recv_ts - send_ts)
            count += 1
        
        # Send ACK
        ack = struct.pack("!BI", 0x02, seq)
        sock.sendto(ack, addr)
        
    except socket.timeout:
        continue

sock.close()

for stream in ["high", "low"]:
    ts = results[stream]["timestamps"]
    results[stream]["count"] = len(ts)
    results[stream]["avg_latency"] = sum(ts) / len(ts) * 1000 if ts else 0
    if len(ts) > 1:
        delays = [abs(ts[i] - ts[i-1]) * 1000 for i in range(1, len(ts))]
        results[stream]["jitter"] = sum(delays) / len(delays) if delays else 0
    else:
        results[stream]["jitter"] = 0

with open("_rquic_hol_server.json", "w") as f:
    json.dump(results, f)

print(f"rQUIC done: HIGH={results['high']['count']}, LOW={results['low']['count']}", flush=True)
'''

# =============================================================================
# rQUIC CLIENT CODE
# =============================================================================
RQUIC_CLIENT_CODE = '''
import socket
import struct
import time
import sys

SERVER_IP = sys.argv[1]
PORT = 5557
NUM_MESSAGES = 50
MESSAGE_SIZE = 500

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.settimeout(0.001)

pending = {}  # seq -> (data, send_time, retries)
acked = set()
padding = b"X" * MESSAGE_SIZE

def send_packet(msg_type, seq):
    send_ts = time.time()
    # Packet: type(1) + seq(4) + send_ts(8) + msg_type(1) + padding
    pkt = struct.pack("!BId", 0x01, seq, send_ts) + bytes([0 if msg_type == "HIGH" else 1]) + padding
    sock.sendto(pkt, (SERVER_IP, PORT))
    pending[(msg_type, seq)] = (pkt, send_ts, 0)

def process_acks():
    while True:
        try:
            data, addr = sock.recvfrom(1024)
            if len(data) >= 5 and data[0] == 0x02:
                seq = struct.unpack("!I", data[1:5])[0]
                for key in list(pending.keys()):
                    if key[1] == seq:
                        del pending[key]
                        acked.add(key)
        except:
            break

def retransmit():
    current = time.time()
    for key, (pkt, send_time, retries) in list(pending.items()):
        if current - send_time > 0.1 and retries < 3:  # 100ms timeout
            sock.sendto(pkt, (SERVER_IP, PORT))
            pending[key] = (pkt, current, retries + 1)

for i in range(NUM_MESSAGES):
    send_packet("HIGH", i)
    send_packet("LOW", i)
    process_acks()
    retransmit()
    time.sleep(0.01)

# Final retransmissions
for _ in range(10):
    process_acks()
    retransmit()
    time.sleep(0.05)

sock.close()
print(f"rQUIC Client done: sent {NUM_MESSAGES*2}, acked {len(acked)}", flush=True)
'''


def run_tcp_test(net, loss_percent):
    """Run TCP test"""
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
        with open("_tcp_hol_server.json", "r") as f:
            return json.load(f)
    except:
        return None


def run_quic_test(net, loss_percent):
    """Run QUIC test"""
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
        with open("_quic_hol_server.json", "r") as f:
            return json.load(f)
    except:
        return None


def run_rquic_test(net, loss_percent):
    """Run rQUIC test"""
    h1, h2 = net.get('h1'), net.get('h2')
    
    h2.cmd(f"cat > /tmp/rquic_server.py << 'ENDSCRIPT'\n{RQUIC_SERVER_CODE}\nENDSCRIPT")
    h1.cmd(f"cat > /tmp/rquic_client.py << 'ENDSCRIPT'\n{RQUIC_CLIENT_CODE}\nENDSCRIPT")
    
    h2.cmd("cd /home/fret/Bureau/exchange-NCKU/Network-project/cloud-gaming-project && python3 /tmp/rquic_server.py &")
    time.sleep(2)
    h1.cmd(f"python3 /tmp/rquic_client.py {h2.IP()}")
    time.sleep(3)
    h2.cmd("pkill -f rquic_server.py")
    time.sleep(1)
    
    try:
        with open("_rquic_hol_server.json", "r") as f:
            return json.load(f)
    except:
        return None


def create_network(loss_percent, delay_ms):
    """Create Mininet network"""
    net = Mininet(switch=OVSSwitch, link=TCLink)
    h1 = net.addHost('h1')
    h2 = net.addHost('h2')
    s1 = net.addSwitch('s1', failMode='standalone')
    net.addLink(h1, s1, loss=loss_percent, delay=f'{delay_ms}ms')
    net.addLink(h2, s1, loss=loss_percent, delay=f'{delay_ms}ms')
    net.start()
    return net


def main():
    setLogLevel('warning')
    
    print("=" * 60)
    print("HOL BLOCKING TEST - TCP vs QUIC vs rQUIC")
    print("=" * 60)
    
    scenarios = [
        {"name": "Ideal", "loss": 0, "delay": 5},
        {"name": "5% Loss", "loss": 5, "delay": 10},
        {"name": "10% Loss", "loss": 10, "delay": 10},
    ]
    
    all_results = []
    
    for scenario in scenarios:
        print(f"\n--- {scenario['name']} (loss={scenario['loss']}%, delay={scenario['delay']}ms) ---")
        result = {"scenario": scenario["name"], "loss": scenario["loss"]}
        
        # TCP Test
        print("  TCP...")
        net = create_network(scenario["loss"], scenario["delay"])
        tcp = run_tcp_test(net, scenario["loss"])
        net.stop()
        
        if tcp:
            result["tcp"] = {
                "high_jitter": round(tcp["high"]["jitter"], 2),
                "low_jitter": round(tcp["low"]["jitter"], 2),
            }
            print(f"    Jitter: HIGH={result['tcp']['high_jitter']:.2f}ms, LOW={result['tcp']['low_jitter']:.2f}ms")
        else:
            result["tcp"] = {"high_jitter": 0, "low_jitter": 0}
        
        time.sleep(2)
        
        # QUIC Test
        print("  QUIC...")
        net = create_network(scenario["loss"], scenario["delay"])
        quic = run_quic_test(net, scenario["loss"])
        net.stop()
        
        if quic:
            result["quic"] = {
                "high_jitter": round(quic["high"]["jitter"], 2),
                "low_jitter": round(quic["low"]["jitter"], 2),
            }
            print(f"    Jitter: HIGH={result['quic']['high_jitter']:.2f}ms, LOW={result['quic']['low_jitter']:.2f}ms")
        else:
            result["quic"] = {"high_jitter": 0, "low_jitter": 0}
        
        time.sleep(2)
        
        # rQUIC Test
        print("  rQUIC...")
        net = create_network(scenario["loss"], scenario["delay"])
        rquic = run_rquic_test(net, scenario["loss"])
        net.stop()
        
        if rquic:
            result["rquic"] = {
                "high_jitter": round(rquic["high"]["jitter"], 2),
                "low_jitter": round(rquic["low"]["jitter"], 2),
            }
            print(f"    Jitter: HIGH={result['rquic']['high_jitter']:.2f}ms, LOW={result['rquic']['low_jitter']:.2f}ms")
        else:
            result["rquic"] = {"high_jitter": 0, "low_jitter": 0}
        
        all_results.append(result)
        time.sleep(2)
    
    with open("HOL_BLOCKING_RESULTS.json", "w") as f:
        json.dump(all_results, f, indent=2)
    
    print("\n" + "=" * 60)
    print("RESULTS SAVED: HOL_BLOCKING_RESULTS.json")
    print("=" * 60)
    
    generate_graph(all_results)
    
    # Force kill all remaining processes and exit
    subprocess.run(['pkill', '-9', '-f', 'quic_server'], capture_output=True)
    subprocess.run(['pkill', '-9', '-f', 'tcp_server'], capture_output=True)
    subprocess.run(['pkill', '-9', '-f', 'rquic_server'], capture_output=True)
    subprocess.run(['sudo', 'mn', '-c'], capture_output=True)
    os._exit(0)


def generate_graph(results):
    """Generate matplotlib graph"""
    import matplotlib.pyplot as plt
    import numpy as np
    
    plt.switch_backend('Agg')
    
    scenarios = [r["scenario"] for r in results]
    
    tcp_high = [r.get("tcp", {}).get("high_jitter", 0) for r in results]
    tcp_low = [r.get("tcp", {}).get("low_jitter", 0) for r in results]
    quic_high = [r.get("quic", {}).get("high_jitter", 0) for r in results]
    quic_low = [r.get("quic", {}).get("low_jitter", 0) for r in results]
    rquic_high = [r.get("rquic", {}).get("high_jitter", 0) for r in results]
    rquic_low = [r.get("rquic", {}).get("low_jitter", 0) for r in results]
    
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))
    
    x = np.arange(len(scenarios))
    width = 0.25
    
    # Graph 1: HIGH Priority Stream
    ax1.bar(x - width, tcp_high, width, label='TCP', color='#e74c3c', alpha=0.8)
    ax1.bar(x, quic_high, width, label='QUIC', color='#3498db', alpha=0.8)
    ax1.bar(x + width, rquic_high, width, label='rQUIC', color='#2ecc71', alpha=0.8)
    
    ax1.set_xlabel('Network Scenario', fontsize=12)
    ax1.set_ylabel('Jitter (ms²)', fontsize=12)
    ax1.set_title('Head-of-Line Blocking: HIGH Priority\n(High jitter = blocking)', fontsize=14)
    ax1.set_xticks(x)
    ax1.set_xticklabels(scenarios)
    ax1.legend()
    ax1.grid(axis='y', alpha=0.3)
    
    # Graph 2: LOW Priority Stream
    ax2.bar(x - width, tcp_low, width, label='TCP', color='#e74c3c', alpha=0.8)
    ax2.bar(x, quic_low, width, label='QUIC', color='#3498db', alpha=0.8)
    ax2.bar(x + width, rquic_low, width, label='rQUIC', color='#2ecc71', alpha=0.8)
    
    ax2.set_xlabel('Network Scenario', fontsize=12)
    ax2.set_ylabel('Jitter (ms²)', fontsize=12)
    ax2.set_title('Head-of-Line Blocking: LOW Priority\n(TCP LOW blocked by lost HIGH)', fontsize=14)
    ax2.set_xticks(x)
    ax2.set_xticklabels(scenarios)
    ax2.legend()
    ax2.grid(axis='y', alpha=0.3)
    
    plt.tight_layout()
    plt.savefig('HOL_BLOCKING_RESULTS.png', dpi=150, bbox_inches='tight')
    plt.close('all')
    
    print("Graph saved: HOL_BLOCKING_RESULTS.png")


if __name__ == "__main__":
    main()
