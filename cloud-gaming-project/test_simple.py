#!/usr/bin/env python3
"""
Test simplifié TCP vs rQUIC
Comparaison fiable avec sauvegarde des résultats
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
TEST_DURATION = 12


def test_tcp(net, client, server):
    """Test TCP standard"""
    info('\n*** TEST TCP\n')
    
    server_script = os.path.join(WORK_DIR, 'video_server.py')
    client_script = os.path.join(WORK_DIR, 'video_traffic_gen.py')
    
    # Démarrer serveur
    server.cmd(f'cd {WORK_DIR} && python3 {server_script} 5000 TCP {TEST_DURATION + 5} &')
    time.sleep(2)
    
    # Lancer client
    client.cmd(f'cd {WORK_DIR} && timeout {TEST_DURATION + 3} python3 {client_script} {server.IP()} TCP {TEST_DURATION}')
    
    time.sleep(3)
    server.cmd('pkill -f video_server.py')
    time.sleep(1)
    
    # Déplacer les résultats
    client.cmd(f'mv {WORK_DIR}/video_traffic_tcp_results.json {WORK_DIR}/results_tcp_client.json 2>/dev/null')
    server.cmd(f'mv {WORK_DIR}/video_server_tcp_results.json {WORK_DIR}/results_tcp_server.json 2>/dev/null')
    
    return True


def test_rquic(net, client, server):
    """Test rQUIC (UDP+ARQ)"""
    info('\n*** TEST rQUIC\n')
    
    rquic_script = os.path.join(WORK_DIR, 'rquic_protocol.py')
    
    # Démarrer serveur rQUIC - NE PAS mettre en background, lancer puis client
    # Le serveur doit tourner assez longtemps
    server.cmd(f'cd {WORK_DIR} && timeout {TEST_DURATION + 8} python3 {rquic_script} server --port 5001 --duration {TEST_DURATION + 5} --output results_rquic_server.json > rquic_server.log 2>&1 &')
    time.sleep(3)
    
    # Vérifier que le serveur tourne
    ps = server.cmd('ps aux | grep rquic_protocol | grep -v grep')
    if not ps.strip():
        info('⚠️ Serveur rQUIC non démarré!\n')
        log = server.cmd(f'cat {WORK_DIR}/rquic_server.log')
        info(f'Log: {log}\n')
        return False
    
    info(f'Serveur rQUIC démarré\n')
    
    # Lancer client
    result = client.cmd(f'cd {WORK_DIR} && python3 {rquic_script} client --host {server.IP()} --port 5001 --duration {TEST_DURATION} --output results_rquic_client.json')
    info(f'Client terminé\n')
    
    # Attendre que le serveur finisse et sauvegarde
    time.sleep(5)
    server.cmd('pkill -f rquic_protocol')
    time.sleep(2)
    
    # Vérifier les fichiers
    server_exists = server.cmd(f'ls -la {WORK_DIR}/results_rquic_server.json 2>/dev/null')
    client_exists = client.cmd(f'ls -la {WORK_DIR}/results_rquic_client.json 2>/dev/null')
    
    info(f'Fichiers: server={bool(server_exists.strip())}, client={bool(client_exists.strip())}\n')
    
    return True


def display_results():
    """Affiche le tableau des résultats"""
    
    print("\n" + "="*80)
    print("TABLEAU COMPARATIF - TCP vs rQUIC")
    print("Réseau: 3% perte, 25ms délai, 50Mbps")
    print("="*80)
    
    protocols = [
        ('TCP', 'results_tcp'),
        ('rQUIC', 'results_rquic'),
    ]
    
    data = []
    
    for name, prefix in protocols:
        client_file = os.path.join(WORK_DIR, f'{prefix}_client.json')
        server_file = os.path.join(WORK_DIR, f'{prefix}_server.json')
        
        row = {'name': name}
        
        if os.path.exists(client_file):
            with open(client_file) as f:
                c = json.load(f)
            row['frames_sent'] = c.get('frames_sent', 0)
            row['retrans'] = c.get('retransmissions', 0)
            row['rtt'] = c.get('avg_rtt_ms', 0)
        else:
            print(f"\n⚠️ {name}: Pas de données client")
            continue
        
        if os.path.exists(server_file):
            with open(server_file) as f:
                s = json.load(f)
            row['frames_recv'] = s.get('frames_received', 0)
            row['fps'] = s.get('avg_fps', 0)
            row['latency'] = s.get('avg_inter_frame_delay_ms', 0)
            row['jitter'] = s.get('jitter_ms', 0)
            row['throughput'] = s.get('throughput_mbps', 0)
        else:
            print(f"\n⚠️ {name}: Pas de données serveur")
            row['frames_recv'] = 0
            row['fps'] = 0
            row['latency'] = 0
            row['jitter'] = 0
            row['throughput'] = 0
        
        # Calculer delivery
        if row['frames_sent'] > 0:
            row['delivery'] = min(100, (row['frames_recv'] / row['frames_sent']) * 100)
        else:
            row['delivery'] = 0
        
        data.append(row)
        
        print(f"\n📊 {name}:")
        print(f"   Frames envoyées:     {row['frames_sent']}")
        print(f"   Frames reçues:       {row['frames_recv']}")
        print(f"   Taux de livraison:   {row['delivery']:.1f}%")
        if row.get('retrans', 0) > 0:
            print(f"   🔄 Retransmissions:  {row['retrans']}")
            print(f"   RTT moyen:           {row.get('rtt', 0):.1f}ms")
        print(f"   FPS effectifs:       {row['fps']:.1f}")
        print(f"   Latence moyenne:     {row['latency']:.1f}ms")
        print(f"   Jitter:              {row['jitter']:.1f}ms")
    
    # Comparer
    if len(data) >= 2:
        print("\n" + "="*80)
        print("🎮 COMPARAISON")
        print("="*80)
        
        tcp = next((d for d in data if d['name'] == 'TCP'), None)
        rquic = next((d for d in data if d['name'] == 'rQUIC'), None)
        
        if tcp and rquic:
            print(f"\n{'Métrique':<25} {'TCP':>15} {'rQUIC':>15} {'Gagnant':>15}")
            print("-"*70)
            
            # Delivery
            tcp_d = tcp['delivery']
            rq_d = rquic['delivery']
            winner = 'TCP' if tcp_d >= rq_d else 'rQUIC'
            print(f"{'Taux de livraison':<25} {tcp_d:>14.1f}% {rq_d:>14.1f}% {winner:>15}")
            
            # FPS
            tcp_fps = tcp['fps']
            rq_fps = rquic['fps']
            winner = 'TCP' if tcp_fps >= rq_fps else 'rQUIC'
            print(f"{'FPS':<25} {tcp_fps:>15.1f} {rq_fps:>15.1f} {winner:>15}")
            
            # Latence
            tcp_lat = tcp['latency']
            rq_lat = rquic['latency']
            winner = 'TCP' if tcp_lat <= rq_lat and tcp_lat > 0 else 'rQUIC'
            print(f"{'Latence (ms)':<25} {tcp_lat:>15.1f} {rq_lat:>15.1f} {winner:>15}")
            
            # Jitter
            tcp_jit = tcp['jitter']
            rq_jit = rquic['jitter']
            winner = 'TCP' if tcp_jit <= rq_jit and tcp_jit > 0 else 'rQUIC'
            print(f"{'Jitter (ms)':<25} {tcp_jit:>15.1f} {rq_jit:>15.1f} {winner:>15}")
            
            # Retransmissions
            print(f"{'Retransmissions':<25} {'-':>15} {rquic.get('retrans', 0):>15}")
            
            print("\n💡 rQUIC simule le comportement de QUIC avec ARQ (retransmissions sélectives)")
            print("   sur UDP, offrant fiabilité sans le overhead TCP.")
    
    print("\n" + "="*80)


def main():
    setLogLevel('info')
    
    print("\n" + "="*70)
    print("TEST COMPARATIF - TCP vs rQUIC")
    print("="*70)
    
    # Configuration réseau
    loss = 3
    delay = '25ms'
    bandwidth = 50
    
    # Créer topologie
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
    
    try:
        # Test TCP
        test_tcp(net, client, server)
        time.sleep(2)
        
        # Test rQUIC
        test_rquic(net, client, server)
        
    finally:
        info('\n*** Arrêt du réseau\n')
        net.stop()
    
    # Afficher les résultats
    display_results()
    
    print("\n✅ Test terminé!")


if __name__ == '__main__':
    main()
