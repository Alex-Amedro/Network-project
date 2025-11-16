#!/usr/bin/env python3
"""
Test rapide du benchmark (durée réduite pour debug)
"""

from mininet.net import Mininet
from mininet.node import OVSSwitch
from mininet.link import TCLink
from mininet.log import setLogLevel, info
import time
import os
import json

WORK_DIR = os.path.dirname(os.path.abspath(__file__))

def test_one_scenario():
    """Test rapide d'un seul scénario"""
    setLogLevel('info')
    
    print("\n" + "="*70)
    print("TEST RAPIDE - Scénario Moyen avec QUIC")
    print("="*70)
    
    # Configuration réseau moyen
    loss = 3
    delay = '25ms'
    bandwidth = 50
    
    # Créer la topologie
    net = Mininet(link=TCLink, switch=OVSSwitch, controller=None, autoSetMacs=True)
    
    info('*** Création de la topologie\n')
    client = net.addHost('client', ip='10.0.0.1/24')
    server = net.addHost('server', ip='10.0.0.2/24')
    switch = net.addSwitch('s1', failMode='standalone')
    
    net.addLink(client, switch, cls=TCLink)
    net.addLink(switch, server, cls=TCLink, delay=delay, loss=loss, bw=bandwidth)
    
    net.start()
    switch.cmd('ovs-ofctl add-flow s1 action=normal')
    
    # Test de connectivité
    info('*** Test de connectivité\n')
    result = net.ping([client, server], timeout=2)
    
    try:
        # Démarrer le serveur QUIC
        server_script = os.path.join(WORK_DIR, 'video_server.py')
        log_file = os.path.join(WORK_DIR, 'server_test.log')
        info('*** Démarrage du serveur QUIC\n')
        server.cmd(f'cd {WORK_DIR} && python3 {server_script} 5000 QUIC > {log_file} 2>&1 &')
        time.sleep(2)
        
        # Vérifier que le serveur tourne
        ps_result = server.cmd('ps aux | grep video_server.py | grep -v grep')
        if ps_result:
            info(f'Serveur en cours: {ps_result}\n')
        else:
            info('⚠️  Serveur ne semble pas démarré\n')
        
        # Lancer le client pour 10 secondes
        client_script = os.path.join(WORK_DIR, 'video_traffic_gen.py')
        info('*** Lancement du client QUIC (10 secondes)\n')
        result = client.cmd(f'cd {WORK_DIR} && python3 {client_script} {server.IP()} QUIC 10')
        info(f'Résultat client: {result}\n')
        
        time.sleep(2)
        
        # Arrêter le serveur
        server.cmd('pkill -f "video_server.py"')
        
        info('*** Test terminé\n')
        
        # Vérifier les fichiers créés
        print("\n📁 Fichiers créés:")
        for f in ['video_traffic_udp_results.json', 'video_server_udp_results.json']:
            if os.path.exists(f):
                print(f"  ✅ {f}")
                with open(f, 'r') as file:
                    data = json.load(file)
                    print(f"     Frames envoyées/reçues: {data.get('frames_sent', data.get('frames_received', 'N/A'))}")
            else:
                print(f"  ❌ {f} - NON CRÉÉ")
        
    finally:
        net.stop()

if __name__ == '__main__':
    test_one_scenario()
