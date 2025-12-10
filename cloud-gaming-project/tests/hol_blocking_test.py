#!/usr/bin/env python3
"""
HOL BLOCKING TEST - TCP vs QUIC
================================
Démontre que TCP bloque tout quand un paquet est perdu (Head-of-Line blocking)
alors que QUIC avec ses streams indépendants continue.

SIMPLE : On envoie 2 types de données (HIGH priority et LOW priority)
et on mesure si la perte sur HIGH bloque LOW.
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
# CONFIGURATION SIMPLE
# ==============================================================================
SERVER_PORT = 5555
NUM_MESSAGES = 50  # Messages par type
MESSAGE_SIZE = 500  # bytes
LOSS_PERCENT = 5  # % de perte pour voir l'effet

# ==============================================================================
# TCP SERVER - Reçoit HIGH et LOW sur la MÊME connexion
# ==============================================================================
TCP_SERVER_CODE = '''
import socket
import json
import time
import sys

PORT = 5555
NUM_EXPECTED = 100  # 50 HIGH + 50 LOW

results = {
    "high": {"received": [], "timestamps": []},
    "low": {"received": [], "timestamps": []},
    "blocked_events": 0
}

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
    last_high_seq = -1
    last_low_seq = -1
    
    start_time = time.time()
    
    while count < NUM_EXPECTED and (time.time() - start_time) < 20:
        try:
            data = conn.recv(4096)
            if not data:
                break
            buffer += data
            
            # Parse messages (format: TYPE:SEQ:TIMESTAMP:PADDING|)
            while b"|" in buffer:
                msg, buffer = buffer.split(b"|", 1)
                msg = msg.decode()
                parts = msg.split(":")
                if len(parts) >= 3:
                    msg_type = parts[0]  # HIGH or LOW
                    seq = int(parts[1])
                    send_ts = float(parts[2])
                    recv_ts = time.time()
                    
                    if msg_type == "HIGH":
                        # Vérifier si on a sauté des séquences (blocage)
                        if last_high_seq >= 0 and seq > last_high_seq + 1:
                            results["blocked_events"] += (seq - last_high_seq - 1)
                        last_high_seq = seq
                        results["high"]["received"].append(seq)
                        results["high"]["timestamps"].append(recv_ts - send_ts)
                    elif msg_type == "LOW":
                        if last_low_seq >= 0 and seq > last_low_seq + 1:
                            results["blocked_events"] += (seq - last_low_seq - 1)
                        last_low_seq = seq
                        results["low"]["received"].append(seq)
                        results["low"]["timestamps"].append(recv_ts - send_ts)
                    
                    count += 1
        except socket.timeout:
            break
    
    conn.close()
except Exception as e:
    print(f"Error: {e}", flush=True)

server.close()

# Calculer les métriques
results["high"]["count"] = len(results["high"]["received"])
results["low"]["count"] = len(results["low"]["received"])
results["high"]["avg_latency"] = sum(results["high"]["timestamps"]) / max(len(results["high"]["timestamps"]), 1) * 1000
results["low"]["avg_latency"] = sum(results["low"]["timestamps"]) / max(len(results["low"]["timestamps"]), 1) * 1000

# Calculer le "blocking time" - variance des latences (indique le blocage)
if len(results["high"]["timestamps"]) > 1:
    mean = sum(results["high"]["timestamps"]) / len(results["high"]["timestamps"])
    results["high"]["jitter"] = sum((x - mean) ** 2 for x in results["high"]["timestamps"]) / len(results["high"]["timestamps"]) * 1000
else:
    results["high"]["jitter"] = 0

if len(results["low"]["timestamps"]) > 1:
    mean = sum(results["low"]["timestamps"]) / len(results["low"]["timestamps"])
    results["low"]["jitter"] = sum((x - mean) ** 2 for x in results["low"]["timestamps"]) / len(results["low"]["timestamps"]) * 1000
else:
    results["low"]["jitter"] = 0

with open("_tcp_hol_server.json", "w") as f:
    json.dump(results, f)

print(f"TCP: HIGH={results['high']['count']}, LOW={results['low']['count']}, blocked={results['blocked_events']}", flush=True)
'''

# ==============================================================================
# TCP CLIENT - Envoie HIGH et LOW entrelacés sur la MÊME connexion
# ==============================================================================
TCP_CLIENT_CODE = '''
import socket
import time
import sys

HOST = sys.argv[1]
PORT = 5555
NUM_MESSAGES = 50
PADDING = "X" * 400  # Pour avoir des messages de ~500 bytes

sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.settimeout(10)

time.sleep(1)  # Attendre le serveur

try:
    sock.connect((HOST, PORT))
    
    # Envoyer HIGH et LOW entrelacés
    for i in range(NUM_MESSAGES):
        # HIGH priority message
        ts = time.time()
        msg_high = f"HIGH:{i}:{ts}:{PADDING}|"
        sock.sendall(msg_high.encode())
        
        # LOW priority message
        ts = time.time()
        msg_low = f"LOW:{i}:{ts}:{PADDING}|"
        sock.sendall(msg_low.encode())
        
        time.sleep(0.02)  # 20ms entre chaque paire
    
    time.sleep(0.5)
    sock.close()
    print("TCP Client done", flush=True)
except Exception as e:
    print(f"TCP Client error: {e}", flush=True)
'''

# ==============================================================================
# QUIC SERVER - Reçoit HIGH et LOW sur 2 STREAMS DIFFÉRENTS
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
from aioquic.quic.events import StreamDataReceived, ConnectionTerminated

PORT = 5555
NUM_EXPECTED = 100

results = {
    "high": {"received": [], "timestamps": []},
    "low": {"received": [], "timestamps": []},
    "blocked_events": 0
}

count = 0
done_event = asyncio.Event()

class ServerProtocol(QuicConnectionProtocol):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.buffers = {}  # buffer par stream
    
    def quic_event_received(self, event):
        global count, results
        
        if isinstance(event, StreamDataReceived):
            stream_id = event.stream_id
            if stream_id not in self.buffers:
                self.buffers[stream_id] = b""
            
            self.buffers[stream_id] += event.data
            
            # Parse messages
            while b"|" in self.buffers[stream_id]:
                msg, self.buffers[stream_id] = self.buffers[stream_id].split(b"|", 1)
                msg = msg.decode()
                parts = msg.split(":")
                if len(parts) >= 3:
                    msg_type = parts[0]
                    seq = int(parts[1])
                    send_ts = float(parts[2])
                    recv_ts = time.time()
                    
                    if msg_type == "HIGH":
                        results["high"]["received"].append(seq)
                        results["high"]["timestamps"].append(recv_ts - send_ts)
                    elif msg_type == "LOW":
                        results["low"]["received"].append(seq)
                        results["low"]["timestamps"].append(recv_ts - send_ts)
                    
                    count += 1
                    if count >= NUM_EXPECTED:
                        done_event.set()
        
        elif isinstance(event, ConnectionTerminated):
            done_event.set()

async def main():
    config = QuicConfiguration(is_client=False)
    config.load_cert_chain("server.cert", "server.key")
    config.verify_mode = False
    
    server = await serve(
        "0.0.0.0", PORT,
        configuration=config,
        create_protocol=ServerProtocol
    )
    
    print("QUIC Server ready", flush=True)
    
    try:
        await asyncio.wait_for(done_event.wait(), timeout=25)
    except asyncio.TimeoutError:
        pass
    
    server.close()
    
    # Calculer métriques
    results["high"]["count"] = len(results["high"]["received"])
    results["low"]["count"] = len(results["low"]["received"])
    results["high"]["avg_latency"] = sum(results["high"]["timestamps"]) / max(len(results["high"]["timestamps"]), 1) * 1000
    results["low"]["avg_latency"] = sum(results["low"]["timestamps"]) / max(len(results["low"]["timestamps"]), 1) * 1000
    
    # Jitter
    if len(results["high"]["timestamps"]) > 1:
        mean = sum(results["high"]["timestamps"]) / len(results["high"]["timestamps"])
        results["high"]["jitter"] = sum((x - mean) ** 2 for x in results["high"]["timestamps"]) / len(results["high"]["timestamps"]) * 1000
    else:
        results["high"]["jitter"] = 0
    
    if len(results["low"]["timestamps"]) > 1:
        mean = sum(results["low"]["timestamps"]) / len(results["low"]["timestamps"])
        results["low"]["jitter"] = sum((x - mean) ** 2 for x in results["low"]["timestamps"]) / len(results["low"]["timestamps"]) * 1000
    else:
        results["low"]["jitter"] = 0
    
    with open("_quic_hol_server.json", "w") as f:
        json.dump(results, f)
    
    print(f"QUIC: HIGH={results['high']['count']}, LOW={results['low']['count']}", flush=True)

asyncio.run(main())
'''

# ==============================================================================
# QUIC CLIENT - Envoie HIGH sur stream 0, LOW sur stream 4
# ==============================================================================
QUIC_CLIENT_CODE = '''
import asyncio
import time
import sys
sys.path.insert(0, "/home/fret/Bureau/exchange-NCKU/Network-project/cloud-gaming-project")

from aioquic.asyncio import connect
from aioquic.asyncio.protocol import QuicConnectionProtocol
from aioquic.quic.configuration import QuicConfiguration

HOST = sys.argv[1]
PORT = 5555
NUM_MESSAGES = 50
PADDING = "X" * 400

class ClientProtocol(QuicConnectionProtocol):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.done = asyncio.Event()

async def main():
    config = QuicConfiguration(is_client=True)
    config.verify_mode = False
    
    await asyncio.sleep(1)  # Attendre serveur
    
    try:
        async with connect(HOST, PORT, configuration=config, create_protocol=ClientProtocol) as protocol:
            # Créer 2 streams: HIGH (stream 0) et LOW (stream 4)
            stream_high = protocol._quic.get_next_available_stream_id()
            stream_low = protocol._quic.get_next_available_stream_id()
            
            for i in range(NUM_MESSAGES):
                # HIGH sur stream_high
                ts = time.time()
                msg_high = f"HIGH:{i}:{ts}:{PADDING}|"
                protocol._quic.send_stream_data(stream_high, msg_high.encode(), end_stream=False)
                
                # LOW sur stream_low (STREAM DIFFERENT!)
                ts = time.time()
                msg_low = f"LOW:{i}:{ts}:{PADDING}|"
                protocol._quic.send_stream_data(stream_low, msg_low.encode(), end_stream=False)
                
                protocol.transmit()
                await asyncio.sleep(0.02)
            
            # Fermer les streams
            protocol._quic.send_stream_data(stream_high, b"", end_stream=True)
            protocol._quic.send_stream_data(stream_low, b"", end_stream=True)
            protocol.transmit()
            
            await asyncio.sleep(0.5)
        
        print("QUIC Client done", flush=True)
    except Exception as e:
        print(f"QUIC Client error: {e}", flush=True)

asyncio.run(main())
'''


def run_tcp_test(net, loss_percent):
    """Exécute le test TCP avec perte"""
    h1, h2 = net.get('h1'), net.get('h2')
    
    # Écrire les scripts
    h2.cmd(f"cat > /tmp/tcp_server.py << 'ENDSCRIPT'\n{TCP_SERVER_CODE}\nENDSCRIPT")
    h1.cmd(f"cat > /tmp/tcp_client.py << 'ENDSCRIPT'\n{TCP_CLIENT_CODE}\nENDSCRIPT")
    
    # Lancer le serveur
    h2.cmd("cd /home/fret/Bureau/exchange-NCKU/Network-project/cloud-gaming-project && python3 /tmp/tcp_server.py &")
    time.sleep(2)
    
    # Lancer le client
    h1.cmd(f"python3 /tmp/tcp_client.py {h2.IP()}")
    time.sleep(3)
    
    # Récupérer les résultats
    h2.cmd("pkill -f tcp_server.py")
    time.sleep(1)
    
    try:
        with open("_tcp_hol_server.json", "r") as f:
            return json.load(f)
    except:
        return None


def run_quic_test(net, loss_percent):
    """Exécute le test QUIC avec perte"""
    h1, h2 = net.get('h1'), net.get('h2')
    
    # Écrire les scripts
    h2.cmd(f"cat > /tmp/quic_server.py << 'ENDSCRIPT'\n{QUIC_SERVER_CODE}\nENDSCRIPT")
    h1.cmd(f"cat > /tmp/quic_client.py << 'ENDSCRIPT'\n{QUIC_CLIENT_CODE}\nENDSCRIPT")
    
    # Lancer le serveur
    h2.cmd("cd /home/fret/Bureau/exchange-NCKU/Network-project/cloud-gaming-project && python3 /tmp/quic_server.py &")
    time.sleep(2)
    
    # Lancer le client
    h1.cmd(f"cd /home/fret/Bureau/exchange-NCKU/Network-project/cloud-gaming-project && python3 /tmp/quic_client.py {h2.IP()}")
    time.sleep(3)
    
    # Récupérer les résultats
    h2.cmd("pkill -f quic_server.py")
    time.sleep(1)
    
    try:
        with open("_quic_hol_server.json", "r") as f:
            return json.load(f)
    except:
        return None


def create_network(loss_percent, delay_ms):
    """Crée le réseau Mininet avec perte et délai"""
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
    print("HOL BLOCKING TEST - TCP vs QUIC")
    print("=" * 60)
    
    # Scénarios de test
    scenarios = [
        {"name": "Ideal", "loss": 0, "delay": 5},
        {"name": "5% Loss", "loss": 5, "delay": 10},
        {"name": "10% Loss", "loss": 10, "delay": 10},
    ]
    
    all_results = []
    
    for scenario in scenarios:
        print(f"\n--- Scénario: {scenario['name']} (loss={scenario['loss']}%, delay={scenario['delay']}ms) ---")
        
        result = {"scenario": scenario["name"], "loss": scenario["loss"]}
        
        # Test TCP
        print("  Running TCP test...")
        net = create_network(scenario["loss"], scenario["delay"])
        tcp_result = run_tcp_test(net, scenario["loss"])
        net.stop()
        
        if tcp_result:
            result["tcp"] = {
                "high_received": tcp_result["high"]["count"],
                "low_received": tcp_result["low"]["count"],
                "high_latency": round(tcp_result["high"]["avg_latency"], 2),
                "low_latency": round(tcp_result["low"]["avg_latency"], 2),
                "high_jitter": round(tcp_result["high"]["jitter"], 2),
                "low_jitter": round(tcp_result["low"]["jitter"], 2),
            }
            print(f"    TCP: HIGH={result['tcp']['high_received']}/50, LOW={result['tcp']['low_received']}/50")
            print(f"    TCP Jitter: HIGH={result['tcp']['high_jitter']:.2f}ms, LOW={result['tcp']['low_jitter']:.2f}ms")
        else:
            result["tcp"] = {"error": "failed"}
            print("    TCP: FAILED")
        
        time.sleep(2)
        
        # Test QUIC
        print("  Running QUIC test...")
        net = create_network(scenario["loss"], scenario["delay"])
        quic_result = run_quic_test(net, scenario["loss"])
        net.stop()
        
        if quic_result:
            result["quic"] = {
                "high_received": quic_result["high"]["count"],
                "low_received": quic_result["low"]["count"],
                "high_latency": round(quic_result["high"]["avg_latency"], 2),
                "low_latency": round(quic_result["low"]["avg_latency"], 2),
                "high_jitter": round(quic_result["high"]["jitter"], 2),
                "low_jitter": round(quic_result["low"]["jitter"], 2),
            }
            print(f"    QUIC: HIGH={result['quic']['high_received']}/50, LOW={result['quic']['low_received']}/50")
            print(f"    QUIC Jitter: HIGH={result['quic']['high_jitter']:.2f}ms, LOW={result['quic']['low_jitter']:.2f}ms")
        else:
            result["quic"] = {"error": "failed"}
            print("    QUIC: FAILED")
        
        all_results.append(result)
        time.sleep(2)
    
    # Sauvegarder les résultats
    with open("HOL_BLOCKING_RESULTS.json", "w") as f:
        json.dump(all_results, f, indent=2)
    
    print("\n" + "=" * 60)
    print("RÉSULTATS SAUVEGARDÉS: HOL_BLOCKING_RESULTS.json")
    print("=" * 60)
    
    # Générer le graphique
    generate_graph(all_results)


def generate_graph(results):
    """Génère le graphique matplotlib"""
    import matplotlib.pyplot as plt
    import numpy as np
    
    # Extraire les données
    scenarios = [r["scenario"] for r in results]
    
    tcp_high_jitter = []
    tcp_low_jitter = []
    quic_high_jitter = []
    quic_low_jitter = []
    
    for r in results:
        if "tcp" in r and "high_jitter" in r["tcp"]:
            tcp_high_jitter.append(r["tcp"]["high_jitter"])
            tcp_low_jitter.append(r["tcp"]["low_jitter"])
        else:
            tcp_high_jitter.append(0)
            tcp_low_jitter.append(0)
        
        if "quic" in r and "high_jitter" in r["quic"]:
            quic_high_jitter.append(r["quic"]["high_jitter"])
            quic_low_jitter.append(r["quic"]["low_jitter"])
        else:
            quic_high_jitter.append(0)
            quic_low_jitter.append(0)
    
    # Créer le graphique
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))
    
    x = np.arange(len(scenarios))
    width = 0.35
    
    # Graphique 1: Jitter comparison (indicateur de HoL blocking)
    ax1.bar(x - width/2, tcp_high_jitter, width, label='TCP HIGH', color='#e74c3c', alpha=0.8)
    ax1.bar(x + width/2, quic_high_jitter, width, label='QUIC HIGH', color='#3498db', alpha=0.8)
    
    ax1.set_xlabel('Scénario réseau', fontsize=12)
    ax1.set_ylabel('Jitter (variance latence) - ms²', fontsize=12)
    ax1.set_title('Head-of-Line Blocking: HIGH Priority Stream\n(Jitter élevé = blocage)', fontsize=14)
    ax1.set_xticks(x)
    ax1.set_xticklabels(scenarios)
    ax1.legend()
    ax1.grid(axis='y', alpha=0.3)
    
    # Graphique 2: LOW stream jitter
    ax2.bar(x - width/2, tcp_low_jitter, width, label='TCP LOW', color='#e74c3c', alpha=0.8)
    ax2.bar(x + width/2, quic_low_jitter, width, label='QUIC LOW', color='#3498db', alpha=0.8)
    
    ax2.set_xlabel('Scénario réseau', fontsize=12)
    ax2.set_ylabel('Jitter (variance latence) - ms²', fontsize=12)
    ax2.set_title('Head-of-Line Blocking: LOW Priority Stream\n(TCP LOW bloqué par HIGH perdu)', fontsize=14)
    ax2.set_xticks(x)
    ax2.set_xticklabels(scenarios)
    ax2.legend()
    ax2.grid(axis='y', alpha=0.3)
    
    plt.tight_layout()
    plt.savefig('HOL_BLOCKING_RESULTS.png', dpi=150, bbox_inches='tight')
    plt.close()
    
    print("Graphique sauvegardé: HOL_BLOCKING_RESULTS.png")


if __name__ == "__main__":
    main()
