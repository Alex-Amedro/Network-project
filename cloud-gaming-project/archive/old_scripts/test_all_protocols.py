#!/usr/bin/env python3
"""
Test complet : TCP vs QUIC vs rQUIC
Compare les 3 protocoles sur le même scénario réseau
"""

import os
import sys
import time
import json
import asyncio
import subprocess

from mininet.net import Mininet
from mininet.node import OVSSwitch
from mininet.link import TCLink
from mininet.log import setLogLevel, info

WORK_DIR = os.path.dirname(os.path.abspath(__file__))
VENV_PYTHON = os.path.join(WORK_DIR, 'venv', 'bin', 'python3')
TEST_DURATION = 15


def main():
    setLogLevel('info')
    
    print("\n" + "="*70)
    print("TEST COMPLET - TCP vs QUIC vs rQUIC")
    print("Scénario: Réseau Moyen (3% perte, 25ms délai)")
    print("="*70)
    
    # Configuration
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
    
    info('*** Test de connectivité\n')
    net.ping([client, server], timeout=2)
    
    results = {}
    
    try:
        # ============ TEST 1: TCP ============
        info('\n' + '='*50 + '\n')
        info('*** TEST 1: TCP\n')
        info('='*50 + '\n')
        
        server_script = os.path.join(WORK_DIR, 'video_server.py')
        client_script = os.path.join(WORK_DIR, 'video_traffic_gen.py')
        
        server.cmd(f'cd {WORK_DIR} && python3 {server_script} 5000 TCP {TEST_DURATION} > /dev/null 2>&1 &')
        time.sleep(2)
        
        tcp_result = client.cmd(f'cd {WORK_DIR} && python3 {client_script} {server.IP()} TCP {TEST_DURATION}')
        info(f'{tcp_result[:200]}...\n')
        
        time.sleep(2)
        server.cmd('pkill -f video_server.py')
        
        client.cmd(f'cd {WORK_DIR} && mv video_traffic_tcp_results.json results_full_tcp_client.json 2>/dev/null')
        server.cmd(f'cd {WORK_DIR} && mv video_server_tcp_results.json results_full_tcp_server.json 2>/dev/null')
        
        # ============ TEST 2: QUIC (vrai) ============
        info('\n' + '='*50 + '\n')
        info('*** TEST 2: QUIC (aioquic)\n')
        info('='*50 + '\n')
        
        quic_script = os.path.join(WORK_DIR, 'quic_test.py')
        
        # Démarrer serveur QUIC avec le venv
        server.cmd(f'cd {WORK_DIR} && {VENV_PYTHON} {quic_script} server --host 0.0.0.0 --port 4433 --duration {TEST_DURATION} --output results_full_quic_server.json > quic_server.log 2>&1 &')
        time.sleep(3)
        
        ps = server.cmd('ps aux | grep quic_test | grep -v grep')
        if ps.strip():
            info(f'Serveur QUIC démarré: {ps[:60]}...\n')
            
            # Client QUIC avec le venv
            quic_result = client.cmd(f'cd {WORK_DIR} && {VENV_PYTHON} {quic_script} client --host {server.IP()} --port 4433 --duration {TEST_DURATION} --output results_full_quic_client.json 2>&1')
            info(f'{quic_result[:300]}...\n')
        else:
            info('⚠️ Serveur QUIC non démarré\n')
            # Afficher le log
            log = server.cmd(f'cat {WORK_DIR}/quic_server.log 2>/dev/null')
            info(f'Log: {log[:500]}\n')
        
        time.sleep(2)
        server.cmd('pkill -f quic_test.py')
        
        # ============ TEST 3: rQUIC ============
        info('\n' + '='*50 + '\n')
        info('*** TEST 3: rQUIC (UDP+ARQ)\n')
        info('='*50 + '\n')
        
        rquic_script = os.path.join(WORK_DIR, 'rquic_protocol.py')
        
        server.cmd(f'cd {WORK_DIR} && python3 {rquic_script} server --port 5001 --duration {TEST_DURATION} --output results_full_rquic_server.json > /dev/null 2>&1 &')
        time.sleep(2)
        
        rquic_result = client.cmd(f'cd {WORK_DIR} && python3 {rquic_script} client --host {server.IP()} --port 5001 --duration {TEST_DURATION} --output results_full_rquic_client.json')
        info(f'{rquic_result[:300]}...\n')
        
        time.sleep(2)
        server.cmd('pkill -f rquic_protocol.py')
        
    finally:
        info('\n*** Arrêt du réseau\n')
        net.stop()
    
    # ============ RÉSULTATS ============
    print("\n" + "="*70)
    print("RÉSULTATS COMPARATIFS")
    print("="*70)
    
    protocols = [
        ('TCP', 'results_full_tcp'),
        ('QUIC', 'results_full_quic'),
        ('rQUIC', 'results_full_rquic'),
    ]
    
    for name, prefix in protocols:
        client_file = os.path.join(WORK_DIR, f'{prefix}_client.json')
        server_file = os.path.join(WORK_DIR, f'{prefix}_server.json')
        
        print(f"\n📊 {name}:")
        
        if os.path.exists(client_file):
            with open(client_file) as f:
                c = json.load(f)
            print(f"   Frames envoyées: {c.get('frames_sent', 'N/A')}")
            if 'retransmissions' in c:
                print(f"   🔄 Retransmissions: {c['retransmissions']}")
        else:
            print(f"   ⚠️ Pas de données client")
            continue
        
        if os.path.exists(server_file):
            with open(server_file) as f:
                s = json.load(f)
            frames_sent = c.get('frames_sent', 1)
            frames_recv = s.get('frames_received', 0)
            delivery = (frames_recv / frames_sent) * 100 if frames_sent > 0 else 0
            
            print(f"   Frames reçues: {frames_recv}")
            print(f"   Taux de livraison: {delivery:.1f}%")
            print(f"   FPS: {s.get('avg_fps', 0):.1f}")
            print(f"   Latence: {s.get('avg_inter_frame_delay_ms', 0):.2f} ms")
            print(f"   Jitter: {s.get('jitter_ms', 0):.2f} ms")
        else:
            print(f"   ⚠️ Pas de données serveur")
    
    print("\n" + "="*70)
    print("✅ Test complet terminé!")
    print("="*70)


if __name__ == '__main__':
    main()
