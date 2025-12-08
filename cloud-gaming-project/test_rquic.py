#!/usr/bin/env python3
"""
Test rapide pour valider rQUIC (UDP + ARQ avec retransmissions)
Compare TCP et rQUIC sur un scénario moyen (3% perte)
"""

import os
import sys
import time
import json

from mininet.net import Mininet
from mininet.node import OVSSwitch
from mininet.link import TCLink
from mininet.log import setLogLevel, info

WORK_DIR = os.path.dirname(os.path.abspath(__file__))
TEST_DURATION = 15  # 15 secondes pour un test rapide


def main():
    setLogLevel('info')
    
    print("\n" + "="*70)
    print("TEST RAPIDE - TCP vs rQUIC (avec retransmissions)")
    print("Scénario: Réseau Moyen (3% perte, 25ms délai)")
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
    
    results = {}
    
    try:
        # ============ TEST TCP ============
        info('\n*** TEST 1: TCP\n')
        
        server_script = os.path.join(WORK_DIR, 'video_server.py')
        client_script = os.path.join(WORK_DIR, 'video_traffic_gen.py')
        
        # Démarrer serveur TCP
        info('*** Démarrage du serveur TCP\n')
        server.cmd(f'cd {WORK_DIR} && python3 {server_script} 5000 TCP {TEST_DURATION} > /dev/null 2>&1 &')
        time.sleep(2)
        
        # Client TCP
        info(f'*** Lancement du client TCP ({TEST_DURATION}s)\n')
        tcp_result = client.cmd(f'cd {WORK_DIR} && python3 {client_script} {server.IP()} TCP {TEST_DURATION}')
        info(f'Résultat TCP: {tcp_result[:200]}...\n')
        
        time.sleep(2)
        server.cmd('pkill -f video_server.py')
        
        # Renommer les résultats
        client.cmd(f'cd {WORK_DIR} && mv video_traffic_tcp_results.json results_test_tcp_client.json 2>/dev/null')
        server.cmd(f'cd {WORK_DIR} && mv video_server_tcp_results.json results_test_tcp_server.json 2>/dev/null')
        
        # ============ TEST rQUIC ============
        info('\n*** TEST 2: rQUIC (UDP + ARQ)\n')
        
        rquic_script = os.path.join(WORK_DIR, 'rquic_protocol.py')
        
        # Démarrer serveur rQUIC
        info('*** Démarrage du serveur rQUIC\n')
        server.cmd(f'cd {WORK_DIR} && python3 {rquic_script} server --port 5001 --duration {TEST_DURATION} --output results_test_rquic_server.json > /dev/null 2>&1 &')
        time.sleep(2)
        
        ps = server.cmd('ps aux | grep rquic_protocol | grep -v grep')
        info(f'Serveur rQUIC: {ps[:80]}...\n')
        
        # Client rQUIC
        info(f'*** Lancement du client rQUIC ({TEST_DURATION}s)\n')
        rquic_result = client.cmd(f'cd {WORK_DIR} && python3 {rquic_script} client --host {server.IP()} --port 5001 --duration {TEST_DURATION} --output results_test_rquic_client.json')
        info(f'Résultat rQUIC: {rquic_result[:300]}...\n')
        
        time.sleep(2)
        server.cmd('pkill -f rquic_protocol.py')
        
    finally:
        info('\n*** Arrêt du réseau\n')
        net.stop()
    
    # ============ AFFICHER LES RÉSULTATS ============
    print("\n" + "="*70)
    print("RÉSULTATS")
    print("="*70)
    
    # Charger et afficher les résultats TCP
    tcp_client = os.path.join(WORK_DIR, 'results_test_tcp_client.json')
    tcp_server = os.path.join(WORK_DIR, 'results_test_tcp_server.json')
    
    if os.path.exists(tcp_client) and os.path.exists(tcp_server):
        with open(tcp_client) as f:
            tc = json.load(f)
        with open(tcp_server) as f:
            ts = json.load(f)
        
        print("\n📊 TCP:")
        print(f"   Frames envoyées: {tc.get('frames_sent', 0)}")
        print(f"   Frames reçues: {ts.get('frames_received', 0)}")
        delivery = (ts.get('frames_received', 0) / tc.get('frames_sent', 1)) * 100
        print(f"   Taux de livraison: {delivery:.1f}%")
        print(f"   FPS reçus: {ts.get('avg_fps', 0):.1f}")
        print(f"   Latence: {ts.get('avg_inter_frame_delay_ms', 0):.2f} ms")
        print(f"   Retransmissions: 0 (TCP gère en interne)")
    else:
        print("\n⚠️ Résultats TCP non trouvés")
    
    # Charger et afficher les résultats rQUIC
    rquic_client = os.path.join(WORK_DIR, 'results_test_rquic_client.json')
    rquic_server = os.path.join(WORK_DIR, 'results_test_rquic_server.json')
    
    if os.path.exists(rquic_client) and os.path.exists(rquic_server):
        with open(rquic_client) as f:
            rc = json.load(f)
        with open(rquic_server) as f:
            rs = json.load(f)
        
        print("\n📊 rQUIC (UDP + ARQ):")
        print(f"   Frames envoyées: {rc.get('frames_sent', 0)}")
        print(f"   Frames reçues: {rs.get('frames_received', 0)}")
        delivery = (rs.get('frames_received', 0) / rc.get('frames_sent', 1)) * 100
        print(f"   Taux de livraison: {delivery:.1f}%")
        print(f"   FPS reçus: {rs.get('avg_fps', 0):.1f}")
        print(f"   Latence: {rs.get('avg_inter_frame_delay_ms', 0):.2f} ms")
        print(f"   🔄 Retransmissions: {rc.get('retransmissions', 0)}")
        print(f"   ACKs reçus: {rc.get('acks_received', 0)}")
        print(f"   NACKs envoyés (serveur): {rs.get('nacks_sent', 0)}")
    else:
        print("\n⚠️ Résultats rQUIC non trouvés")
    
    print("\n" + "="*70)
    print("✅ Test terminé!")
    print("\n💡 Si rQUIC montre des retransmissions > 0, cela prouve que")
    print("   le mécanisme ARQ fonctionne et récupère les paquets perdus!")
    print("="*70)


if __name__ == '__main__':
    main()
