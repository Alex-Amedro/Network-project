#!/usr/bin/env python3
"""
CONNECTION TIME TEST - TCP+TLS vs QUIC
======================================
Démontre que QUIC établit une connexion plus vite que TCP+TLS.

TCP+TLS = 3-way handshake (1.5 RTT) + TLS handshake (2 RTT) = ~3.5 RTT
QUIC = handshake crypto intégré = 1 RTT
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

# Mininet imports
from mininet.net import Mininet
from mininet.node import OVSSwitch
from mininet.link import TCLink
from mininet.log import setLogLevel

# ==============================================================================
# CONFIGURATION
# ==============================================================================
SERVER_PORT = 5556
NUM_CONNECTIONS = 10  # Nombre de connexions pour faire la moyenne

# ==============================================================================
# TCP+TLS SERVER
# ==============================================================================
TCP_TLS_SERVER_CODE = '''
import socket
import ssl
import time
import json
import sys

PORT = 5556

# Créer le contexte SSL
context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
context.load_cert_chain("server.cert", "server.key")

server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
server.bind(("0.0.0.0", PORT))
server.listen(5)
server.settimeout(60)

print("TCP+TLS Server ready", flush=True)

results = {"connections": []}

for i in range(10):
    try:
        conn, addr = server.accept()
        
        # Wrap avec TLS
        tls_conn = context.wrap_socket(conn, server_side=True)
        
        # Recevoir le timestamp du client
        data = tls_conn.recv(1024)
        recv_time = time.time()
        
        if data:
            client_start = float(data.decode())
            connection_time = (recv_time - client_start) * 1000  # en ms
            results["connections"].append(connection_time)
            print(f"  Connection {i+1}: {connection_time:.2f}ms", flush=True)
        
        tls_conn.close()
    except Exception as e:
        print(f"Error: {e}", flush=True)
        break

server.close()

results["avg_time"] = sum(results["connections"]) / max(len(results["connections"]), 1)
results["count"] = len(results["connections"])

with open("_tcp_tls_conn_server.json", "w") as f:
    json.dump(results, f)

print(f"TCP+TLS avg: {results['avg_time']:.2f}ms over {results['count']} connections", flush=True)
'''

# ==============================================================================
# TCP+TLS CLIENT
# ==============================================================================
TCP_TLS_CLIENT_CODE = '''
import socket
import ssl
import time
import sys

HOST = sys.argv[1]
PORT = 5556

# Contexte SSL client (pas de vérification pour le test)
context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
context.check_hostname = False
context.verify_mode = ssl.CERT_NONE

results = []

time.sleep(1)  # Attendre le serveur

for i in range(10):
    try:
        start_time = time.time()
        
        # Connexion TCP
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(10)
        sock.connect((HOST, PORT))
        
        # Handshake TLS
        tls_sock = context.wrap_socket(sock, server_hostname=HOST)
        
        # Envoyer le timestamp de départ
        tls_sock.sendall(str(start_time).encode())
        
        end_time = time.time()
        conn_time = (end_time - start_time) * 1000
        results.append(conn_time)
        
        tls_sock.close()
        time.sleep(0.1)
    except Exception as e:
        print(f"Connection {i+1} error: {e}", flush=True)

print(f"TCP+TLS Client done: avg={sum(results)/max(len(results),1):.2f}ms", flush=True)
'''

# ==============================================================================
# QUIC SERVER
# ==============================================================================
QUIC_SERVER_CODE = '''
import asyncio
import json
import time
import sys
sys.path.insert(0, "/home/fret/Bureau/exchange-NCKU/Network-project/cloud-gaming-project")

from aioquic.asyncio import serve
from aioquic.asyncio.protocol import QuicConnectionProtocol
from aioquic.quic.configuration import QuicConfiguration
from aioquic.quic.events import StreamDataReceived, ConnectionTerminated, HandshakeCompleted

PORT = 5556

results = {"connections": []}
connection_count = 0

class ServerProtocol(QuicConnectionProtocol):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.handshake_time = None
    
    def quic_event_received(self, event):
        global connection_count, results
        
        if isinstance(event, HandshakeCompleted):
            self.handshake_time = time.time()
        
        elif isinstance(event, StreamDataReceived):
            if self.handshake_time:
                try:
                    client_start = float(event.data.decode())
                    connection_time = (self.handshake_time - client_start) * 1000
                    results["connections"].append(connection_time)
                    connection_count += 1
                    print(f"  Connection {connection_count}: {connection_time:.2f}ms", flush=True)
                except:
                    pass

async def main():
    global connection_count
    
    config = QuicConfiguration(is_client=False)
    config.load_cert_chain("server.cert", "server.key")
    config.verify_mode = False
    
    server = await serve(
        "0.0.0.0", PORT,
        configuration=config,
        create_protocol=ServerProtocol
    )
    
    print("QUIC Server ready", flush=True)
    
    # Attendre 10 connexions ou timeout
    start = time.time()
    while connection_count < 10 and (time.time() - start) < 60:
        await asyncio.sleep(0.5)
    
    server.close()
    
    results["avg_time"] = sum(results["connections"]) / max(len(results["connections"]), 1)
    results["count"] = len(results["connections"])
    
    with open("_quic_conn_server.json", "w") as f:
        json.dump(results, f)
    
    print(f"QUIC avg: {results['avg_time']:.2f}ms over {results['count']} connections", flush=True)

asyncio.run(main())
'''

# ==============================================================================
# QUIC CLIENT
# ==============================================================================
QUIC_CLIENT_CODE = '''
import asyncio
import time
import sys
sys.path.insert(0, "/home/fret/Bureau/exchange-NCKU/Network-project/cloud-gaming-project")

from aioquic.asyncio import connect
from aioquic.asyncio.protocol import QuicConnectionProtocol
from aioquic.quic.configuration import QuicConfiguration
from aioquic.quic.events import HandshakeCompleted

HOST = sys.argv[1]
PORT = 5556

results = []

async def single_connection(i):
    config = QuicConfiguration(is_client=True)
    config.verify_mode = False
    
    try:
        start_time = time.time()
        
        async with connect(HOST, PORT, configuration=config) as protocol:
            # Connexion établie, envoyer le timestamp
            stream_id = protocol._quic.get_next_available_stream_id()
            protocol._quic.send_stream_data(stream_id, str(start_time).encode(), end_stream=True)
            protocol.transmit()
            
            end_time = time.time()
            conn_time = (end_time - start_time) * 1000
            results.append(conn_time)
            
            await asyncio.sleep(0.1)
    except Exception as e:
        print(f"Connection {i+1} error: {e}", flush=True)

async def main():
    await asyncio.sleep(1)  # Attendre serveur
    
    for i in range(10):
        await single_connection(i)
        await asyncio.sleep(0.1)
    
    print(f"QUIC Client done: avg={sum(results)/max(len(results),1):.2f}ms", flush=True)

asyncio.run(main())
'''


def run_tcp_tls_test(net):
    """Test TCP+TLS connection time"""
    h1, h2 = net.get('h1'), net.get('h2')
    
    # Écrire les scripts
    h2.cmd(f"cat > /tmp/tcp_tls_server.py << 'ENDSCRIPT'\n{TCP_TLS_SERVER_CODE}\nENDSCRIPT")
    h1.cmd(f"cat > /tmp/tcp_tls_client.py << 'ENDSCRIPT'\n{TCP_TLS_CLIENT_CODE}\nENDSCRIPT")
    
    # Lancer le serveur
    h2.cmd("cd /home/fret/Bureau/exchange-NCKU/Network-project/cloud-gaming-project && python3 /tmp/tcp_tls_server.py &")
    time.sleep(2)
    
    # Lancer le client
    h1.cmd(f"python3 /tmp/tcp_tls_client.py {h2.IP()}")
    time.sleep(5)
    
    h2.cmd("pkill -f tcp_tls_server.py")
    time.sleep(1)
    
    try:
        with open("_tcp_tls_conn_server.json", "r") as f:
            return json.load(f)
    except:
        return None


def run_quic_test(net):
    """Test QUIC connection time"""
    h1, h2 = net.get('h1'), net.get('h2')
    
    # Écrire les scripts
    h2.cmd(f"cat > /tmp/quic_server.py << 'ENDSCRIPT'\n{QUIC_SERVER_CODE}\nENDSCRIPT")
    h1.cmd(f"cat > /tmp/quic_client.py << 'ENDSCRIPT'\n{QUIC_CLIENT_CODE}\nENDSCRIPT")
    
    # Lancer le serveur
    h2.cmd("cd /home/fret/Bureau/exchange-NCKU/Network-project/cloud-gaming-project && python3 /tmp/quic_server.py &")
    time.sleep(2)
    
    # Lancer le client
    h1.cmd(f"cd /home/fret/Bureau/exchange-NCKU/Network-project/cloud-gaming-project && python3 /tmp/quic_client.py {h2.IP()}")
    time.sleep(5)
    
    h2.cmd("pkill -f quic_server.py")
    time.sleep(1)
    
    try:
        with open("_quic_conn_server.json", "r") as f:
            return json.load(f)
    except:
        return None


def create_network(delay_ms):
    """Crée le réseau avec un délai spécifique (pas de perte)"""
    net = Mininet(switch=OVSSwitch, link=TCLink)
    
    h1 = net.addHost('h1')
    h2 = net.addHost('h2')
    s1 = net.addSwitch('s1', failMode='standalone')
    
    # Pas de perte, juste du délai
    net.addLink(h1, s1, delay=f'{delay_ms}ms')
    net.addLink(h2, s1, delay=f'{delay_ms}ms')
    
    net.start()
    return net


def main():
    setLogLevel('warning')
    
    print("=" * 60)
    print("CONNECTION TIME TEST - TCP+TLS vs QUIC")
    print("=" * 60)
    
    # Différentes latences réseau (RTT = 2 * delay)
    delays = [5, 25, 50, 100]  # ms (RTT = 10, 50, 100, 200ms)
    
    all_results = []
    
    for delay in delays:
        rtt = delay * 2
        print(f"\n--- RTT = {rtt}ms (delay={delay}ms) ---")
        
        result = {"rtt": rtt, "delay": delay}
        
        # Test TCP+TLS
        print("  Running TCP+TLS test...")
        net = create_network(delay)
        tcp_result = run_tcp_tls_test(net)
        net.stop()
        
        if tcp_result and tcp_result.get("count", 0) > 0:
            result["tcp_tls"] = {
                "avg_time": round(tcp_result["avg_time"], 2),
                "count": tcp_result["count"],
                "connections": tcp_result["connections"][:5]  # Garder les 5 premiers
            }
            # Calculer le ratio par rapport au RTT
            result["tcp_tls"]["rtt_ratio"] = round(tcp_result["avg_time"] / rtt, 2)
            print(f"    TCP+TLS: {result['tcp_tls']['avg_time']:.2f}ms ({result['tcp_tls']['rtt_ratio']}x RTT)")
        else:
            result["tcp_tls"] = {"error": "failed"}
            print("    TCP+TLS: FAILED")
        
        time.sleep(2)
        
        # Test QUIC
        print("  Running QUIC test...")
        net = create_network(delay)
        quic_result = run_quic_test(net)
        net.stop()
        
        if quic_result and quic_result.get("count", 0) > 0:
            result["quic"] = {
                "avg_time": round(quic_result["avg_time"], 2),
                "count": quic_result["count"],
                "connections": quic_result["connections"][:5]
            }
            result["quic"]["rtt_ratio"] = round(quic_result["avg_time"] / rtt, 2)
            print(f"    QUIC: {result['quic']['avg_time']:.2f}ms ({result['quic']['rtt_ratio']}x RTT)")
        else:
            result["quic"] = {"error": "failed"}
            print("    QUIC: FAILED")
        
        all_results.append(result)
        time.sleep(2)
    
    # Sauvegarder
    with open("CONNECTION_TIME_RESULTS.json", "w") as f:
        json.dump(all_results, f, indent=2)
    
    print("\n" + "=" * 60)
    print("RÉSULTATS SAUVEGARDÉS: CONNECTION_TIME_RESULTS.json")
    print("=" * 60)
    
    # Générer le graphique
    generate_graph(all_results)


def generate_graph(results):
    """Génère le graphique"""
    import matplotlib.pyplot as plt
    import numpy as np
    
    # Extraire les données
    rtts = []
    tcp_times = []
    quic_times = []
    tcp_ratios = []
    quic_ratios = []
    
    for r in results:
        rtts.append(r["rtt"])
        
        if "tcp_tls" in r and "avg_time" in r["tcp_tls"]:
            tcp_times.append(r["tcp_tls"]["avg_time"])
            tcp_ratios.append(r["tcp_tls"]["rtt_ratio"])
        else:
            tcp_times.append(0)
            tcp_ratios.append(0)
        
        if "quic" in r and "avg_time" in r["quic"]:
            quic_times.append(r["quic"]["avg_time"])
            quic_ratios.append(r["quic"]["rtt_ratio"])
        else:
            quic_times.append(0)
            quic_ratios.append(0)
    
    # Créer le graphique
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))
    
    # Graphique 1: Temps de connexion absolu
    ax1.plot(rtts, tcp_times, 'o-', label='TCP+TLS', color='#e74c3c', linewidth=2, markersize=10)
    ax1.plot(rtts, quic_times, 's-', label='QUIC', color='#3498db', linewidth=2, markersize=10)
    
    ax1.set_xlabel('RTT réseau (ms)', fontsize=12)
    ax1.set_ylabel('Temps de connexion (ms)', fontsize=12)
    ax1.set_title('Temps d\'établissement de connexion\nTCP+TLS vs QUIC', fontsize=14)
    ax1.legend(fontsize=11)
    ax1.grid(True, alpha=0.3)
    
    # Ajouter les valeurs sur le graphique
    for i, (rtt, tcp, quic) in enumerate(zip(rtts, tcp_times, quic_times)):
        ax1.annotate(f'{tcp:.0f}ms', (rtt, tcp), textcoords="offset points", xytext=(0,10), ha='center', fontsize=9)
        ax1.annotate(f'{quic:.0f}ms', (rtt, quic), textcoords="offset points", xytext=(0,-15), ha='center', fontsize=9)
    
    # Graphique 2: Ratio par rapport au RTT
    x = np.arange(len(rtts))
    width = 0.35
    
    bars1 = ax2.bar(x - width/2, tcp_ratios, width, label='TCP+TLS', color='#e74c3c', alpha=0.8)
    bars2 = ax2.bar(x + width/2, quic_ratios, width, label='QUIC', color='#3498db', alpha=0.8)
    
    # Lignes de référence théoriques
    ax2.axhline(y=3.5, color='#e74c3c', linestyle='--', alpha=0.5, label='TCP+TLS théorique (3.5 RTT)')
    ax2.axhline(y=1.0, color='#3498db', linestyle='--', alpha=0.5, label='QUIC théorique (1 RTT)')
    
    ax2.set_xlabel('RTT réseau (ms)', fontsize=12)
    ax2.set_ylabel('Temps / RTT (ratio)', fontsize=12)
    ax2.set_title('Ratio temps de connexion / RTT\n(Plus bas = meilleur)', fontsize=14)
    ax2.set_xticks(x)
    ax2.set_xticklabels([f'{r}ms' for r in rtts])
    ax2.legend(fontsize=9, loc='upper right')
    ax2.grid(axis='y', alpha=0.3)
    
    # Ajouter les valeurs sur les barres
    for bar, ratio in zip(bars1, tcp_ratios):
        ax2.annotate(f'{ratio:.1f}x', (bar.get_x() + bar.get_width()/2, bar.get_height()),
                    textcoords="offset points", xytext=(0,3), ha='center', fontsize=9)
    for bar, ratio in zip(bars2, quic_ratios):
        ax2.annotate(f'{ratio:.1f}x', (bar.get_x() + bar.get_width()/2, bar.get_height()),
                    textcoords="offset points", xytext=(0,3), ha='center', fontsize=9)
    
    plt.tight_layout()
    plt.savefig('CONNECTION_TIME_RESULTS.png', dpi=150, bbox_inches='tight')
    plt.close()
    
    print("Graphique sauvegardé: CONNECTION_TIME_RESULTS.png")


if __name__ == "__main__":
    main()
