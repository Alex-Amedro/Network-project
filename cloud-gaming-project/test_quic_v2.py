#!/usr/bin/env python3
"""
Test SIMPLE v2 : QUIC (aioquic) dans Mininet
Avec meilleure synchronisation
"""

import os
import sys
import time
import json

if os.geteuid() != 0:
    print("❌ Exécuter avec sudo!")
    sys.exit(1)

from mininet.net import Mininet
from mininet.node import OVSSwitch
from mininet.link import TCLink
from mininet.log import setLogLevel

WORK_DIR = os.path.dirname(os.path.abspath(__file__))

NUM_FRAMES = 30
FRAME_SIZE = 1000
FPS = 10

print("="*60)
print("TEST QUIC v2 (aioquic) DANS MININET")
print("="*60)

# Script serveur amélioré - sauvegarde immédiate
server_code = '''#!/usr/bin/env python3
import asyncio
import struct
import time
import json
import sys
import os

from aioquic.asyncio import serve
from aioquic.asyncio.protocol import QuicConnectionProtocol
from aioquic.quic.configuration import QuicConfiguration
from aioquic.quic.events import StreamDataReceived, ConnectionTerminated

port = int(sys.argv[1])
output = sys.argv[2]
cert = sys.argv[3]
key = sys.argv[4]

results = {"frames_received": 0, "bytes": 0, "status": "starting"}

def save():
    with open(output, "w") as f:
        json.dump(results, f)

class MyServer(QuicConnectionProtocol):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.buffer = b""
    
    def quic_event_received(self, event):
        global results
        if isinstance(event, StreamDataReceived):
            self.buffer += event.data
            
            while len(self.buffer) >= 4:
                frame_size = struct.unpack("!I", self.buffer[:4])[0]
                total = 4 + frame_size
                
                if len(self.buffer) >= total:
                    self.buffer = self.buffer[total:]
                    results["frames_received"] += 1
                    results["bytes"] += frame_size
                    # Sauvegarder apres chaque frame
                    save()
                else:
                    break
        
        elif isinstance(event, ConnectionTerminated):
            results["status"] = "terminated"
            save()

async def main():
    results["status"] = "configuring"
    save()
    
    config = QuicConfiguration(is_client=False, alpn_protocols=["test"])
    config.load_cert_chain(cert, key)
    
    results["status"] = "listening"
    save()
    
    server = await serve("0.0.0.0", port, configuration=config, create_protocol=MyServer)
    
    results["status"] = "running"
    save()
    
    # Attendre les connexions
    await asyncio.sleep(20)
    
    results["status"] = "done"
    save()
    
    server.close()

try:
    asyncio.run(main())
except Exception as e:
    results["status"] = f"error: {e}"
    save()
'''

# Script client
client_code = '''#!/usr/bin/env python3
import asyncio
import struct
import time
import json
import sys
import ssl

from aioquic.asyncio import connect
from aioquic.quic.configuration import QuicConfiguration

host = sys.argv[1]
port = int(sys.argv[2])
num_frames = int(sys.argv[3])
frame_size = int(sys.argv[4])
fps = int(sys.argv[5])
output = sys.argv[6]

results = {"frames_sent": 0, "status": "starting"}

def save():
    with open(output, "w") as f:
        json.dump(results, f)

async def main():
    global results
    config = QuicConfiguration(is_client=True, alpn_protocols=["test"])
    config.verify_mode = ssl.CERT_NONE
    
    results["status"] = "waiting"
    save()
    
    await asyncio.sleep(2)
    
    results["status"] = "connecting"
    save()
    
    try:
        async with connect(host, port, configuration=config) as protocol:
            results["status"] = "connected"
            save()
            
            stream_id = protocol._quic.get_next_available_stream_id()
            start = time.time()
            
            for i in range(num_frames):
                data = bytes([i % 256] * frame_size)
                msg = struct.pack("!I", len(data)) + data
                protocol._quic.send_stream_data(stream_id, msg, end_stream=(i == num_frames - 1))
                protocol.transmit()
                results["frames_sent"] += 1
                save()
                
                expected = start + (i + 1) / fps
                sleep = expected - time.time()
                if sleep > 0:
                    await asyncio.sleep(sleep)
            
            results["status"] = "flushing"
            save()
            
            await asyncio.sleep(2)
            
        results["status"] = "done"
        save()
    
    except Exception as e:
        results["status"] = f"error: {e}"
        results["error"] = str(e)
        save()

asyncio.run(main())
'''

server_script = os.path.join(WORK_DIR, '_quic_srv2.py')
client_script = os.path.join(WORK_DIR, '_quic_cli2.py')

with open(server_script, 'w') as f:
    f.write(server_code)
with open(client_script, 'w') as f:
    f.write(client_code)

cert = os.path.join(WORK_DIR, 'server.cert')
key = os.path.join(WORK_DIR, 'server.key')

print(f"Frames: {NUM_FRAMES}, Taille: {FRAME_SIZE} bytes, FPS: {FPS}")

# Réseau Mininet
setLogLevel('warning')

net = Mininet(link=TCLink, switch=OVSSwitch)
h1 = net.addHost('h1', ip='10.0.0.1')
h2 = net.addHost('h2', ip='10.0.0.2')
s1 = net.addSwitch('s1', failMode='standalone')

net.addLink(h1, s1, delay='5ms', bw=100)
net.addLink(h2, s1, delay='5ms', bw=100)

net.start()
s1.cmd('ovs-ofctl add-flow s1 action=normal')
time.sleep(1)

print("\n✓ Réseau Mininet créé")

# Ping test
ping = h1.cmd('ping -c 1 10.0.0.2')
if '1 received' in ping:
    print("✓ Connectivité OK")
else:
    print("❌ Pas de connectivité!")
    net.stop()
    sys.exit(1)

server_out = os.path.join(WORK_DIR, '_quic_srv_result.json')
client_out = os.path.join(WORK_DIR, '_quic_cli_result.json')

for f in [server_out, client_out]:
    if os.path.exists(f):
        os.remove(f)

# Lancer serveur
print("\n→ Lancement serveur QUIC...")
h2.cmd(f'python3 {server_script} 4433 {server_out} {cert} {key} &')
time.sleep(2)

# Vérifier état serveur
if os.path.exists(server_out):
    with open(server_out) as f:
        status = json.load(f).get('status', 'unknown')
    print(f"  Serveur status: {status}")
else:
    print("  ⚠ Serveur pas encore démarré")

# Lancer client
print("\n→ Lancement client QUIC...")
h1.cmd(f'python3 {client_script} 10.0.0.2 4433 {NUM_FRAMES} {FRAME_SIZE} {FPS} {client_out}')

# Attendre un peu
print("\n→ Attente synchronisation...")
time.sleep(3)

# Lire résultats
print("\n" + "="*60)
print("RÉSULTATS")
print("="*60)

client_res = {}
server_res = {}

if os.path.exists(client_out):
    with open(client_out) as f:
        client_res = json.load(f)
    print(f"Client: {client_res}")

if os.path.exists(server_out):
    with open(server_out) as f:
        server_res = json.load(f)
    print(f"Serveur: {server_res}")

# Arrêter
h2.cmd('pkill -f _quic_srv2')
net.stop()

# Verdict
sent = client_res.get('frames_sent', 0)
recv = server_res.get('frames_received', 0)

print("\n" + "="*60)
if sent > 0 and recv > 0:
    rate = recv / sent * 100
    print(f"✅ QUIC FONCTIONNE DANS MININET!")
    print(f"   Envoyées: {sent}")
    print(f"   Reçues: {recv}")
    print(f"   Taux de livraison: {rate:.1f}%")
    if rate == 100:
        print("   → PARFAIT: 100% de livraison!")
else:
    print(f"❌ PROBLÈME")
    print(f"   Client envoyées: {sent}")
    print(f"   Serveur reçues: {recv}")
    print(f"   Client status: {client_res.get('status', 'N/A')}")
    print(f"   Serveur status: {server_res.get('status', 'N/A')}")
print("="*60)
