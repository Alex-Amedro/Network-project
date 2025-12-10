#!/usr/bin/env python3
"""
Test SIMPLE : QUIC (aioquic) dans Mininet
Objectif : Vérifier que aioquic fonctionne dans Mininet
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

# Paramètres simples
NUM_FRAMES = 50
FRAME_SIZE = 1000  # 1 KB - petit pour éviter problèmes
FPS = 10

print("="*60)
print("TEST SIMPLE QUIC (aioquic) DANS MININET")
print("="*60)

# Créer le script serveur QUIC
server_code = '''#!/usr/bin/env python3
import asyncio
import struct
import time
import json
import sys

from aioquic.asyncio import serve
from aioquic.asyncio.protocol import QuicConnectionProtocol
from aioquic.quic.configuration import QuicConfiguration
from aioquic.quic.events import StreamDataReceived, ConnectionTerminated

port = int(sys.argv[1])
output = sys.argv[2]
cert = sys.argv[3]
key = sys.argv[4]

print(f"[SERVER] Demarrage sur port {port}...")

results = {"frames_received": 0, "bytes": 0}

class MyServer(QuicConnectionProtocol):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.buffer = b""
    
    def quic_event_received(self, event):
        if isinstance(event, StreamDataReceived):
            self.buffer += event.data
            
            # Extraire frames (4 bytes header = taille)
            while len(self.buffer) >= 4:
                frame_size = struct.unpack("!I", self.buffer[:4])[0]
                total = 4 + frame_size
                
                if len(self.buffer) >= total:
                    self.buffer = self.buffer[total:]
                    results["frames_received"] += 1
                    results["bytes"] += frame_size
                    print(f"[SERVER] Frame {results['frames_received']} recue")
                else:
                    break
        
        elif isinstance(event, ConnectionTerminated):
            print("[SERVER] Connexion terminee")

async def main():
    config = QuicConfiguration(is_client=False, alpn_protocols=["test"])
    config.load_cert_chain(cert, key)
    
    server = await serve("0.0.0.0", port, configuration=config, create_protocol=MyServer)
    print(f"[SERVER] En ecoute sur 0.0.0.0:{port}")
    
    # Attendre 30 secondes max
    await asyncio.sleep(30)
    
    server.close()
    print(f"[SERVER] Termine: {results['frames_received']} frames recues")
    
    with open(output, "w") as f:
        json.dump(results, f)

asyncio.run(main())
'''

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

print(f"[CLIENT] Connexion a {host}:{port}...")

results = {"frames_sent": 0}

async def main():
    config = QuicConfiguration(is_client=True, alpn_protocols=["test"])
    config.verify_mode = ssl.CERT_NONE
    
    # Attendre que le serveur demarre
    await asyncio.sleep(2)
    
    try:
        async with connect(host, port, configuration=config) as protocol:
            print(f"[CLIENT] Connecte!")
            stream_id = protocol._quic.get_next_available_stream_id()
            
            start = time.time()
            
            for i in range(num_frames):
                data = bytes([i % 256] * frame_size)
                msg = struct.pack("!I", len(data)) + data
                protocol._quic.send_stream_data(stream_id, msg, end_stream=(i == num_frames - 1))
                protocol.transmit()
                results["frames_sent"] += 1
                print(f"[CLIENT] Frame {i+1} envoyee")
                
                # Timing FPS
                expected = start + (i + 1) / fps
                sleep = expected - time.time()
                if sleep > 0:
                    await asyncio.sleep(sleep)
            
            # Attendre que les donnees arrivent
            await asyncio.sleep(3)
            
        print(f"[CLIENT] Termine: {results['frames_sent']} frames envoyees")
    
    except Exception as e:
        print(f"[CLIENT] ERREUR: {e}")
        results["error"] = str(e)
    
    with open(output, "w") as f:
        json.dump(results, f)

asyncio.run(main())
'''

# Sauvegarder les scripts
server_script = os.path.join(WORK_DIR, '_quic_srv.py')
client_script = os.path.join(WORK_DIR, '_quic_cli.py')

with open(server_script, 'w') as f:
    f.write(server_code)
with open(client_script, 'w') as f:
    f.write(client_code)

print(f"Scripts créés: {server_script}, {client_script}")

# Certificats
cert = os.path.join(WORK_DIR, 'server.cert')
key = os.path.join(WORK_DIR, 'server.key')

if not os.path.exists(cert):
    print("❌ Certificats manquants! Générer avec:")
    print("   openssl req -nodes -new -x509 -keyout server.key -out server.cert -days 365 -subj '/CN=localhost'")
    sys.exit(1)

print(f"Certificats: {cert}, {key}")

# Créer réseau Mininet simple
print("\n" + "-"*60)
print("Création du réseau Mininet...")
print("-"*60)

setLogLevel('info')

net = Mininet(link=TCLink, switch=OVSSwitch)

h1 = net.addHost('h1', ip='10.0.0.1')
h2 = net.addHost('h2', ip='10.0.0.2')
s1 = net.addSwitch('s1', failMode='standalone')

# Lien simple sans perte
net.addLink(h1, s1, delay='5ms', bw=100)
net.addLink(h2, s1, delay='5ms', bw=100)

net.start()
s1.cmd('ovs-ofctl add-flow s1 action=normal')

print("\nTest de connectivité...")
result = h1.cmd('ping -c 2 10.0.0.2')
print(result)

# Fichiers de sortie
server_out = os.path.join(WORK_DIR, '_quic_server_result.json')
client_out = os.path.join(WORK_DIR, '_quic_client_result.json')

# Supprimer anciens fichiers
for f in [server_out, client_out]:
    if os.path.exists(f):
        os.remove(f)

print("\n" + "-"*60)
print("Lancement du serveur QUIC sur h2...")
print("-"*60)

# Lancer serveur en background
h2.cmd(f'python3 {server_script} 4433 {server_out} {cert} {key} > /tmp/quic_server.log 2>&1 &')
time.sleep(2)

# Vérifier que le serveur tourne
ps = h2.cmd('ps aux | grep _quic_srv')
print(f"Processus serveur: {ps}")

print("\n" + "-"*60)
print("Lancement du client QUIC sur h1...")
print("-"*60)

# Lancer client
output = h1.cmd(f'python3 {client_script} 10.0.0.2 4433 {NUM_FRAMES} {FRAME_SIZE} {FPS} {client_out} 2>&1')
print(output)

# Attendre et récupérer les logs serveur
time.sleep(3)
h2.cmd('pkill -f _quic_srv')

print("\n" + "-"*60)
print("Logs du serveur:")
print("-"*60)
server_log = h2.cmd('cat /tmp/quic_server.log')
print(server_log)

# Arrêter Mininet
net.stop()

# Lire les résultats
print("\n" + "="*60)
print("RÉSULTATS")
print("="*60)

client_res = {}
server_res = {}

if os.path.exists(client_out):
    with open(client_out) as f:
        client_res = json.load(f)
    print(f"Client: {client_res}")
else:
    print("❌ Pas de résultat client")

if os.path.exists(server_out):
    with open(server_out) as f:
        server_res = json.load(f)
    print(f"Serveur: {server_res}")
else:
    print("❌ Pas de résultat serveur")

# Vérification
sent = client_res.get('frames_sent', 0)
recv = server_res.get('frames_received', 0)

print("\n" + "="*60)
if sent > 0 and recv > 0:
    rate = recv / sent * 100
    print(f"✅ QUIC FONCTIONNE!")
    print(f"   Envoyées: {sent}")
    print(f"   Reçues: {recv}")
    print(f"   Taux: {rate:.1f}%")
else:
    print(f"❌ PROBLÈME QUIC")
    print(f"   Envoyées: {sent}")
    print(f"   Reçues: {recv}")
    if client_res.get('error'):
        print(f"   Erreur client: {client_res['error']}")
print("="*60)
