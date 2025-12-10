#!/usr/bin/env python3
"""
CONNECTION TIME TEST - TCP+TLS vs QUIC vs rQUIC
================================================
Compares connection establishment time across protocols.
"""

import sys
import os
import json
import time
import socket
import ssl
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

NUM_CONNECTIONS = 5

# =============================================================================
# TCP+TLS
# =============================================================================
TCP_SERVER_CODE = '''
import socket
import ssl
import time
import json

context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
context.load_cert_chain("server.cert", "server.key")

server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
server.bind(("0.0.0.0", 5556))
server.listen(5)
server.settimeout(60)
print("TCP+TLS Server ready", flush=True)

results = {"times": []}
for i in range(5):
    try:
        conn, addr = server.accept()
        tls_conn = context.wrap_socket(conn, server_side=True)
        data = tls_conn.recv(1024)
        if data:
            client_start = float(data.decode())
            conn_time = (time.time() - client_start) * 1000
            results["times"].append(conn_time)
            print(f"  Connection {i+1}: {conn_time:.2f}ms", flush=True)
        tls_conn.close()
    except Exception as e:
        print(f"Error: {e}", flush=True)
        break

server.close()
results["avg"] = sum(results["times"]) / len(results["times"]) if results["times"] else 0
with open("_tcp_conn.json", "w") as f:
    json.dump(results, f)
'''

TCP_CLIENT_CODE = '''
import socket
import ssl
import time
import sys

SERVER = sys.argv[1]
context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
context.check_hostname = False
context.verify_mode = ssl.CERT_NONE

for i in range(5):
    start = time.time()
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((SERVER, 5556))
    tls_sock = context.wrap_socket(sock, server_hostname=SERVER)
    tls_sock.send(str(start).encode())
    time.sleep(0.1)
    tls_sock.close()
    time.sleep(0.5)

print("TCP+TLS Client done", flush=True)
'''

# =============================================================================
# QUIC
# =============================================================================
QUIC_SERVER_CODE = '''
import asyncio
import time
import json
from aioquic.asyncio import serve
from aioquic.asyncio.protocol import QuicConnectionProtocol
from aioquic.quic.configuration import QuicConfiguration
from aioquic.quic.events import StreamDataReceived, ConnectionTerminated

results = {"times": []}
count = 0
done = asyncio.Event()

class ServerProtocol(QuicConnectionProtocol):
    def quic_event_received(self, event):
        global count, results
        if isinstance(event, StreamDataReceived):
            try:
                client_start = float(event.data.decode())
                conn_time = (time.time() - client_start) * 1000
                results["times"].append(conn_time)
                print(f"  Connection {len(results['times'])}: {conn_time:.2f}ms", flush=True)
                count += 1
                if count >= 5:
                    done.set()
            except:
                pass

async def main():
    config = QuicConfiguration(is_client=False)
    config.load_cert_chain("server.cert", "server.key")
    config.idle_timeout = 30.0
    
    server = await serve("0.0.0.0", 5557, configuration=config, create_protocol=ServerProtocol)
    print("QUIC Server ready", flush=True)
    
    try:
        await asyncio.wait_for(done.wait(), timeout=30)
    except asyncio.TimeoutError:
        pass
    
    server.close()
    results["avg"] = sum(results["times"]) / len(results["times"]) if results["times"] else 0
    with open("_quic_conn.json", "w") as f:
        json.dump(results, f)

asyncio.run(main())
'''

QUIC_CLIENT_CODE = '''
import asyncio
import time
import sys
from aioquic.asyncio import connect
from aioquic.quic.configuration import QuicConfiguration

SERVER = sys.argv[1]

async def main():
    for i in range(5):
        config = QuicConfiguration(is_client=True)
        config.verify_mode = False
        config.idle_timeout = 30.0
        
        start = time.time()
        try:
            async with connect(SERVER, 5557, configuration=config) as protocol:
                stream_id = protocol._quic.get_next_available_stream_id()
                protocol._quic.send_stream_data(stream_id, str(start).encode(), end_stream=True)
                protocol.transmit()
                await asyncio.sleep(0.2)
        except Exception as e:
            print(f"Error: {e}", flush=True)
        await asyncio.sleep(0.5)
    print("QUIC Client done", flush=True)

asyncio.run(main())
'''

# =============================================================================
# rQUIC (UDP + handshake)
# =============================================================================
RQUIC_SERVER_CODE = '''
import socket
import struct
import time
import json

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
sock.bind(("0.0.0.0", 5558))
sock.settimeout(30)
print("rQUIC Server ready", flush=True)

results = {"times": []}

for i in range(5):
    try:
        # Wait for SYN
        data, addr = sock.recvfrom(1024)
        if data[:3] == b"SYN":
            client_start = struct.unpack("!d", data[3:11])[0]
            # Send SYN-ACK
            sock.sendto(b"SYNACK", addr)
            # Wait for ACK
            data, addr = sock.recvfrom(1024)
            if data[:3] == b"ACK":
                conn_time = (time.time() - client_start) * 1000
                results["times"].append(conn_time)
                print(f"  Connection {i+1}: {conn_time:.2f}ms", flush=True)
    except socket.timeout:
        break

sock.close()
results["avg"] = sum(results["times"]) / len(results["times"]) if results["times"] else 0
with open("_rquic_conn.json", "w") as f:
    json.dump(results, f)
'''

RQUIC_CLIENT_CODE = '''
import socket
import struct
import time
import sys

SERVER = sys.argv[1]

for i in range(5):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(5)
    
    start = time.time()
    try:
        # Send SYN with timestamp
        syn = b"SYN" + struct.pack("!d", start)
        sock.sendto(syn, (SERVER, 5558))
        
        # Wait for SYN-ACK
        data, addr = sock.recvfrom(1024)
        if data[:6] == b"SYNACK":
            # Send ACK
            sock.sendto(b"ACK", (SERVER, 5558))
    except Exception as e:
        print(f"Error: {e}", flush=True)
    
    sock.close()
    time.sleep(0.5)

print("rQUIC Client done", flush=True)
'''


def run_tcp_test(net):
    h1, h2 = net.get('h1'), net.get('h2')
    h2.cmd(f"cat > /tmp/tcp_server.py << 'ENDSCRIPT'\n{TCP_SERVER_CODE}\nENDSCRIPT")
    h1.cmd(f"cat > /tmp/tcp_client.py << 'ENDSCRIPT'\n{TCP_CLIENT_CODE}\nENDSCRIPT")
    h2.cmd("cd /home/fret/Bureau/exchange-NCKU/Network-project/cloud-gaming-project && python3 /tmp/tcp_server.py &")
    time.sleep(2)
    h1.cmd(f"cd /home/fret/Bureau/exchange-NCKU/Network-project/cloud-gaming-project && python3 /tmp/tcp_client.py {h2.IP()}")
    time.sleep(5)
    h2.cmd("pkill -f tcp_server.py")
    time.sleep(1)
    try:
        with open("_tcp_conn.json", "r") as f:
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
    time.sleep(5)
    h2.cmd("pkill -f quic_server.py")
    time.sleep(1)
    try:
        with open("_quic_conn.json", "r") as f:
            return json.load(f)
    except:
        return None


def run_rquic_test(net):
    h1, h2 = net.get('h1'), net.get('h2')
    h2.cmd(f"cat > /tmp/rquic_server.py << 'ENDSCRIPT'\n{RQUIC_SERVER_CODE}\nENDSCRIPT")
    h1.cmd(f"cat > /tmp/rquic_client.py << 'ENDSCRIPT'\n{RQUIC_CLIENT_CODE}\nENDSCRIPT")
    h2.cmd("cd /home/fret/Bureau/exchange-NCKU/Network-project/cloud-gaming-project && python3 /tmp/rquic_server.py &")
    time.sleep(2)
    h1.cmd(f"python3 /tmp/rquic_client.py {h2.IP()}")
    time.sleep(5)
    h2.cmd("pkill -f rquic_server.py")
    time.sleep(1)
    try:
        with open("_rquic_conn.json", "r") as f:
            return json.load(f)
    except:
        return None


def create_network(delay_ms):
    net = Mininet(switch=OVSSwitch, link=TCLink)
    h1 = net.addHost('h1')
    h2 = net.addHost('h2')
    s1 = net.addSwitch('s1', failMode='standalone')
    net.addLink(h1, s1, delay=f'{delay_ms}ms')
    net.addLink(h2, s1, delay=f'{delay_ms}ms')
    net.start()
    return net


def main():
    setLogLevel('warning')
    
    print("=" * 60)
    print("CONNECTION TIME: TCP+TLS vs QUIC vs rQUIC")
    print("=" * 60)
    
    delays = [5, 25, 50, 100]  # RTT = 10, 50, 100, 200ms
    all_results = []
    
    for delay in delays:
        rtt = delay * 2
        print(f"\n--- RTT = {rtt}ms ---")
        result = {"rtt": rtt}
        
        # TCP+TLS
        print("  TCP+TLS...")
        net = create_network(delay)
        tcp = run_tcp_test(net)
        net.stop()
        if tcp:
            result["tcp"] = round(tcp["avg"], 2)
            result["tcp_ratio"] = round(tcp["avg"] / rtt, 2)
            print(f"    {result['tcp']}ms ({result['tcp_ratio']}x RTT)")
        time.sleep(2)
        
        # QUIC
        print("  QUIC...")
        net = create_network(delay)
        quic = run_quic_test(net)
        net.stop()
        if quic:
            result["quic"] = round(quic["avg"], 2)
            result["quic_ratio"] = round(quic["avg"] / rtt, 2)
            print(f"    {result['quic']}ms ({result['quic_ratio']}x RTT)")
        time.sleep(2)
        
        # rQUIC
        print("  rQUIC...")
        net = create_network(delay)
        rquic = run_rquic_test(net)
        net.stop()
        if rquic:
            result["rquic"] = round(rquic["avg"], 2)
            result["rquic_ratio"] = round(rquic["avg"] / rtt, 2)
            print(f"    {result['rquic']}ms ({result['rquic_ratio']}x RTT)")
        
        all_results.append(result)
        time.sleep(2)
    
    with open("CONNECTION_3PROTO_RESULTS.json", "w") as f:
        json.dump(all_results, f, indent=2)
    
    print("\n" + "=" * 60)
    print("RESULTS SAVED: CONNECTION_3PROTO_RESULTS.json")
    print("=" * 60)
    
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
    
    rtts = [r["rtt"] for r in results]
    tcp = [r.get("tcp", 0) for r in results]
    quic = [r.get("quic", 0) for r in results]
    rquic = [r.get("rquic", 0) for r in results]
    
    tcp_ratio = [r.get("tcp_ratio", 0) for r in results]
    quic_ratio = [r.get("quic_ratio", 0) for r in results]
    rquic_ratio = [r.get("rquic_ratio", 0) for r in results]
    
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))
    
    # Graph 1: Absolute times
    ax1.plot(rtts, tcp, 'o-', label='TCP+TLS', color='#e74c3c', linewidth=2, markersize=10)
    ax1.plot(rtts, quic, 's-', label='QUIC', color='#3498db', linewidth=2, markersize=10)
    ax1.plot(rtts, rquic, '^-', label='rQUIC', color='#2ecc71', linewidth=2, markersize=10)
    
    ax1.set_xlabel('Network RTT (ms)', fontsize=12)
    ax1.set_ylabel('Connection Time (ms)', fontsize=12)
    ax1.set_title('Connection Establishment Time\nTCP+TLS vs QUIC vs rQUIC', fontsize=14)
    ax1.legend(fontsize=11)
    ax1.grid(True, alpha=0.3)
    
    for i, (rtt, t, q, r) in enumerate(zip(rtts, tcp, quic, rquic)):
        ax1.annotate(f'{t:.0f}ms', (rtt, t), textcoords="offset points", xytext=(0,10), ha='center', fontsize=9)
        ax1.annotate(f'{q:.0f}ms', (rtt, q), textcoords="offset points", xytext=(0,-15), ha='center', fontsize=9)
        ax1.annotate(f'{r:.0f}ms', (rtt, r), textcoords="offset points", xytext=(15,0), ha='left', fontsize=9)
    
    # Graph 2: RTT ratios
    x = np.arange(len(rtts))
    width = 0.25
    
    ax2.bar(x - width, tcp_ratio, width, label='TCP+TLS', color='#e74c3c', alpha=0.8)
    ax2.bar(x, quic_ratio, width, label='QUIC', color='#3498db', alpha=0.8)
    ax2.bar(x + width, rquic_ratio, width, label='rQUIC', color='#2ecc71', alpha=0.8)
    
    ax2.axhline(y=3.5, color='#e74c3c', linestyle='--', alpha=0.5, label='TCP theoretical (3.5 RTT)')
    ax2.axhline(y=1.0, color='#3498db', linestyle='--', alpha=0.5, label='QUIC theoretical (1 RTT)')
    
    ax2.set_xlabel('Network RTT (ms)', fontsize=12)
    ax2.set_ylabel('Time / RTT (ratio)', fontsize=12)
    ax2.set_title('Connection Time / RTT Ratio\n(Lower = better)', fontsize=14)
    ax2.set_xticks(x)
    ax2.set_xticklabels([f'{r}ms' for r in rtts])
    ax2.legend(fontsize=9, loc='upper right')
    ax2.grid(axis='y', alpha=0.3)
    
    plt.tight_layout()
    plt.savefig('CONNECTION_3PROTO_RESULTS.png', dpi=150, bbox_inches='tight')
    plt.close('all')
    print("Graph saved: CONNECTION_3PROTO_RESULTS.png")


if __name__ == "__main__":
    main()
