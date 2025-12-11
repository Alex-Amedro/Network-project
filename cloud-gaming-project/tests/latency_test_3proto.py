#!/usr/bin/env python3
"""
LATENCY TEST - TCP vs QUIC vs rQUIC
====================================
Measures round-trip latency for each protocol under different network conditions.
"""

import sys
import os
import json
import time
import socket
import struct
import asyncio
import subprocess

# Force matplotlib to use non-interactive backend
import matplotlib
matplotlib.use('Agg')

from mininet.net import Mininet
from mininet.node import OVSSwitch
from mininet.link import TCLink
from mininet.log import setLogLevel

NUM_PINGS = 50

# =============================================================================
# TCP PING-PONG CODE
# =============================================================================
TCP_SERVER_CODE = '''
import socket
import json
import time

PORT = 5550
NUM_EXPECTED = 50

latencies = []

server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
server.bind(("0.0.0.0", PORT))
server.listen(1)
server.settimeout(30)

print("TCP Server ready", flush=True)

try:
    conn, addr = server.accept()
    conn.settimeout(20)
    
    for i in range(NUM_EXPECTED):
        try:
            data = conn.recv(1024)
            if not data:
                break
            # Echo back immediately
            conn.sendall(data)
        except socket.timeout:
            break
    
    conn.close()
except Exception as e:
    print(f"TCP Server error: {e}", flush=True)

server.close()

result = {
    "count": len(latencies),
    "latencies": latencies
}

with open("_tcp_latency.json", "w") as f:
    json.dump(result, f)

print(f"TCP Server done: {len(latencies)} pings", flush=True)
'''

TCP_CLIENT_CODE = '''
import socket
import time
import json

SERVER_IP = sys.argv[1]
PORT = 5550
NUM_PINGS = 50

latencies = []

sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.settimeout(10)

try:
    sock.connect((SERVER_IP, PORT))
    
    for i in range(NUM_PINGS):
        msg = f"PING:{i}".encode()
        
        start = time.time()
        sock.sendall(msg)
        data = sock.recv(1024)
        end = time.time()
        
        if data:
            latency = (end - start) * 1000  # ms
            latencies.append(latency)
        
        time.sleep(0.02)
    
    sock.close()
except Exception as e:
    print(f"TCP Client error: {e}", flush=True)

result = {
    "count": len(latencies),
    "latencies": latencies,
    "avg_latency": sum(latencies) / len(latencies) if latencies else 0,
    "min_latency": min(latencies) if latencies else 0,
    "max_latency": max(latencies) if latencies else 0
}

with open("_tcp_latency_client.json", "w") as f:
    json.dump(result, f)

print(f"TCP Client done: avg={result['avg_latency']:.2f}ms", flush=True)
'''

# =============================================================================
# QUIC PING-PONG CODE
# =============================================================================
QUIC_SERVER_CODE = '''
import asyncio
import json
import time
from aioquic.asyncio import serve
from aioquic.asyncio.protocol import QuicConnectionProtocol
from aioquic.quic.configuration import QuicConfiguration
from aioquic.quic.events import StreamDataReceived

latencies = []
done = asyncio.Event()

class ServerProtocol(QuicConnectionProtocol):
    def quic_event_received(self, event):
        if isinstance(event, StreamDataReceived):
            # Echo back immediately
            self._quic.send_stream_data(event.stream_id, event.data, end_stream=False)
            self.transmit()

async def main():
    config = QuicConfiguration(is_client=False)
    config.load_cert_chain("server.cert", "server.key")
    config.idle_timeout = 60.0
    
    server = await serve("0.0.0.0", 5551, configuration=config, create_protocol=ServerProtocol)
    print("QUIC Server ready", flush=True)
    
    await asyncio.sleep(15)
    server.close()

asyncio.run(main())
'''

QUIC_CLIENT_CODE = '''
import asyncio
import sys
import time
import json
from aioquic.asyncio import connect
from aioquic.asyncio.protocol import QuicConnectionProtocol
from aioquic.quic.configuration import QuicConfiguration
from aioquic.quic.events import StreamDataReceived

SERVER_IP = sys.argv[1]
NUM_PINGS = 50

latencies = []
pending = {}

class ClientProtocol(QuicConnectionProtocol):
    def quic_event_received(self, event):
        if isinstance(event, StreamDataReceived):
            data = event.data.decode()
            if data in pending:
                latency = (time.time() - pending[data]) * 1000
                latencies.append(latency)
                del pending[data]

async def main():
    config = QuicConfiguration(is_client=True)
    config.verify_mode = False
    config.idle_timeout = 60.0
    
    await asyncio.sleep(1)
    
    try:
        async with connect(SERVER_IP, 5551, configuration=config, create_protocol=ClientProtocol) as protocol:
            stream_id = protocol._quic.get_next_available_stream_id()
            
            for i in range(NUM_PINGS):
                msg = f"PING:{i}"
                pending[msg] = time.time()
                
                protocol._quic.send_stream_data(stream_id, msg.encode(), end_stream=False)
                protocol.transmit()
                await asyncio.sleep(0.03)
            
            # Wait for remaining responses
            await asyncio.sleep(2)
            
    except Exception as e:
        print(f"QUIC Client error: {e}", flush=True)

    result = {
        "count": len(latencies),
        "latencies": latencies,
        "avg_latency": sum(latencies) / len(latencies) if latencies else 0,
        "min_latency": min(latencies) if latencies else 0,
        "max_latency": max(latencies) if latencies else 0
    }
    
    with open("_quic_latency_client.json", "w") as f:
        json.dump(result, f)
    
    print(f"QUIC Client done: avg={result['avg_latency']:.2f}ms", flush=True)

asyncio.run(main())
'''

# =============================================================================
# rQUIC PING-PONG CODE
# =============================================================================
RQUIC_SERVER_CODE = '''
import socket
import struct
import json
import time

PORT = 5552
NUM_EXPECTED = 50

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
sock.bind(("0.0.0.0", PORT))
sock.settimeout(1.0)

print("rQUIC Server ready", flush=True)

count = 0
start = time.time()

while count < NUM_EXPECTED and (time.time() - start) < 30:
    try:
        data, addr = sock.recvfrom(65535)
        # Echo back immediately
        sock.sendto(data, addr)
        count += 1
    except socket.timeout:
        continue

sock.close()
print(f"rQUIC Server done: {count} pings", flush=True)
'''

RQUIC_CLIENT_CODE = '''
import socket
import struct
import time
import json
import sys

SERVER_IP = sys.argv[1]
PORT = 5552
NUM_PINGS = 50

latencies = []

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.settimeout(2.0)

for i in range(NUM_PINGS):
    msg = f"PING:{i}".encode()
    
    start = time.time()
    sock.sendto(msg, (SERVER_IP, PORT))
    
    try:
        data, addr = sock.recvfrom(65535)
        end = time.time()
        
        if data:
            latency = (end - start) * 1000
            latencies.append(latency)
    except socket.timeout:
        pass
    
    time.sleep(0.02)

sock.close()

result = {
    "count": len(latencies),
    "latencies": latencies,
    "avg_latency": sum(latencies) / len(latencies) if latencies else 0,
    "min_latency": min(latencies) if latencies else 0,
    "max_latency": max(latencies) if latencies else 0
}

with open("_rquic_latency_client.json", "w") as f:
    json.dump(result, f)

print(f"rQUIC Client done: avg={result['avg_latency']:.2f}ms", flush=True)
'''


def run_tcp_test(net):
    h1, h2 = net.get('h1'), net.get('h2')
    h2.cmd(f"cat > /tmp/tcp_server_lat.py << 'ENDSCRIPT'\n{TCP_SERVER_CODE}\nENDSCRIPT")
    h1.cmd(f"cat > /tmp/tcp_client_lat.py << 'ENDSCRIPT'\nimport sys\n{TCP_CLIENT_CODE}\nENDSCRIPT")
    
    h2.cmd("cd /home/fret/Bureau/exchange-NCKU/Network-project/cloud-gaming-project && python3 /tmp/tcp_server_lat.py &")
    time.sleep(2)
    h1.cmd(f"python3 /tmp/tcp_client_lat.py {h2.IP()}")
    time.sleep(2)
    h2.cmd("pkill -f tcp_server_lat.py")
    time.sleep(1)
    
    try:
        with open("_tcp_latency_client.json", "r") as f:
            return json.load(f)
    except:
        return None


def run_quic_test(net):
    h1, h2 = net.get('h1'), net.get('h2')
    h2.cmd(f"cat > /tmp/quic_server_lat.py << 'ENDSCRIPT'\n{QUIC_SERVER_CODE}\nENDSCRIPT")
    h1.cmd(f"cat > /tmp/quic_client_lat.py << 'ENDSCRIPT'\n{QUIC_CLIENT_CODE}\nENDSCRIPT")
    
    h2.cmd("cd /home/fret/Bureau/exchange-NCKU/Network-project/cloud-gaming-project && python3 /tmp/quic_server_lat.py &")
    time.sleep(2)
    h1.cmd(f"cd /home/fret/Bureau/exchange-NCKU/Network-project/cloud-gaming-project && python3 /tmp/quic_client_lat.py {h2.IP()}")
    time.sleep(2)
    h2.cmd("pkill -f quic_server_lat.py")
    time.sleep(1)
    
    try:
        with open("_quic_latency_client.json", "r") as f:
            return json.load(f)
    except:
        return None


def run_rquic_test(net):
    h1, h2 = net.get('h1'), net.get('h2')
    h2.cmd(f"cat > /tmp/rquic_server_lat.py << 'ENDSCRIPT'\n{RQUIC_SERVER_CODE}\nENDSCRIPT")
    h1.cmd(f"cat > /tmp/rquic_client_lat.py << 'ENDSCRIPT'\n{RQUIC_CLIENT_CODE}\nENDSCRIPT")
    
    h2.cmd("python3 /tmp/rquic_server_lat.py &")
    time.sleep(2)
    h1.cmd(f"python3 /tmp/rquic_client_lat.py {h2.IP()}")
    time.sleep(2)
    h2.cmd("pkill -f rquic_server_lat.py")
    time.sleep(1)
    
    try:
        with open("_rquic_latency_client.json", "r") as f:
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
    
    # Clean old result files
    for f in ["_tcp_latency_client.json", "_quic_latency_client.json", "_rquic_latency_client.json"]:
        if os.path.exists(f):
            os.remove(f)
    
    print("=" * 60)
    print("LATENCY TEST - TCP vs QUIC vs rQUIC")
    print("=" * 60)
    
    scenarios = [
        {"name": "No Loss", "loss": 0, "delay": 20},
        {"name": "1% Loss", "loss": 1, "delay": 20},
        {"name": "3% Loss", "loss": 3, "delay": 20},
        {"name": "5% Loss", "loss": 5, "delay": 20},
        {"name": "10% Loss", "loss": 10, "delay": 20},
    ]
    
    all_results = []
    
    for scenario in scenarios:
        print(f"\n--- {scenario['name']} (loss={scenario['loss']}%, delay={scenario['delay']}ms) ---")
        result = {"scenario": scenario["name"], "loss": scenario["loss"], "delay": scenario["delay"]}
        
        # Clean result files
        for f in ["_tcp_latency_client.json", "_quic_latency_client.json", "_rquic_latency_client.json"]:
            if os.path.exists(f):
                os.remove(f)
        
        # TCP
        print("  TCP...")
        net = create_network(scenario["loss"], scenario["delay"])
        tcp = run_tcp_test(net)
        net.stop()
        
        if tcp and tcp.get("count", 0) > 0:
            result["tcp"] = {
                "avg": round(tcp["avg_latency"], 2),
                "min": round(tcp["min_latency"], 2),
                "max": round(tcp["max_latency"], 2),
                "count": tcp["count"]
            }
            print(f"    TCP: avg={result['tcp']['avg']:.2f}ms, count={result['tcp']['count']}")
        else:
            result["tcp"] = {"avg": 0, "min": 0, "max": 0, "count": 0}
        
        time.sleep(2)
        
        # QUIC
        print("  QUIC...")
        net = create_network(scenario["loss"], scenario["delay"])
        quic = run_quic_test(net)
        net.stop()
        
        if quic and quic.get("count", 0) > 0:
            result["quic"] = {
                "avg": round(quic["avg_latency"], 2),
                "min": round(quic["min_latency"], 2),
                "max": round(quic["max_latency"], 2),
                "count": quic["count"]
            }
            print(f"    QUIC: avg={result['quic']['avg']:.2f}ms, count={result['quic']['count']}")
        else:
            result["quic"] = {"avg": 0, "min": 0, "max": 0, "count": 0}
        
        time.sleep(2)
        
        # rQUIC
        print("  rQUIC...")
        net = create_network(scenario["loss"], scenario["delay"])
        rquic = run_rquic_test(net)
        net.stop()
        
        if rquic and rquic.get("count", 0) > 0:
            result["rquic"] = {
                "avg": round(rquic["avg_latency"], 2),
                "min": round(rquic["min_latency"], 2),
                "max": round(rquic["max_latency"], 2),
                "count": rquic["count"]
            }
            print(f"    rQUIC: avg={result['rquic']['avg']:.2f}ms, count={result['rquic']['count']}")
        else:
            result["rquic"] = {"avg": 0, "min": 0, "max": 0, "count": 0}
        
        all_results.append(result)
        time.sleep(2)
    
    with open("LATENCY_3PROTO_RESULTS.json", "w") as f:
        json.dump(all_results, f, indent=2)
    
    print("\n" + "=" * 60)
    print("RESULTS SAVED: LATENCY_3PROTO_RESULTS.json")
    print("=" * 60)
    
    generate_graph(all_results)
    
    # Cleanup
    subprocess.run(['pkill', '-9', '-f', 'tcp_server_lat'], capture_output=True)
    subprocess.run(['pkill', '-9', '-f', 'quic_server_lat'], capture_output=True)
    subprocess.run(['pkill', '-9', '-f', 'rquic_server_lat'], capture_output=True)
    subprocess.run(['sudo', 'mn', '-c'], capture_output=True)
    os._exit(0)


def generate_graph(results):
    import matplotlib.pyplot as plt
    import numpy as np
    
    plt.switch_backend('Agg')
    
    scenarios = [r["scenario"] for r in results]
    loss_rates = [r["loss"] for r in results]
    
    tcp_avg = [r.get("tcp", {}).get("avg", 0) for r in results]
    quic_avg = [r.get("quic", {}).get("avg", 0) for r in results]
    rquic_avg = [r.get("rquic", {}).get("avg", 0) for r in results]
    
    fig, ax = plt.subplots(figsize=(12, 7))
    
    x = np.arange(len(scenarios))
    width = 0.25
    
    bars1 = ax.bar(x - width, tcp_avg, width, label='TCP', color='#e74c3c', alpha=0.8)
    bars2 = ax.bar(x, quic_avg, width, label='QUIC', color='#3498db', alpha=0.8)
    bars3 = ax.bar(x + width, rquic_avg, width, label='rQUIC', color='#2ecc71', alpha=0.8)
    
    ax.set_xlabel('Packet Loss Rate', fontsize=13, fontweight='bold')
    ax.set_ylabel('Round-Trip Latency (ms)', fontsize=13, fontweight='bold')
    ax.set_title('Impact of Packet Loss on Latency\n(Base RTT = 40ms, Lower = Better)', fontsize=15, fontweight='bold')
    ax.set_xticks(x)
    ax.set_xticklabels([f"{loss}%" for loss in loss_rates], fontsize=11)
    ax.legend(fontsize=11, loc='upper left')
    ax.grid(axis='y', alpha=0.3, linestyle='--')
    
    # Add values on bars
    for bars in [bars1, bars2, bars3]:
        for bar in bars:
            height = bar.get_height()
            if height > 0:
                ax.annotate(f'{height:.1f}',
                    xy=(bar.get_x() + bar.get_width() / 2, height),
                    xytext=(0, 3),
                    textcoords="offset points",
                    ha='center', va='bottom',
                    fontsize=9)
    
    plt.tight_layout()
    plt.savefig('LATENCY_3PROTO_RESULTS.png', dpi=150, bbox_inches='tight')
    plt.close('all')
    
    print("Graph saved: LATENCY_3PROTO_RESULTS.png")


if __name__ == "__main__":
    main()

