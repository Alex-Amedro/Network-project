#!/usr/bin/env python3
"""
Topologie Mininet pour simuler Cloud Gaming
Client <---> Switch <---> Router <---> Server
         (avec pertes et délai configurable)
"""

from mininet.net import Mininet
from mininet.node import OVSSwitch
from mininet.cli import CLI
from mininet.link import TCLink
from mininet.log import setLogLevel, info
import time
import os

# Répertoire de travail pour les résultats
WORK_DIR = os.path.dirname(os.path.abspath(__file__))

def create_topology(loss_rate=0, delay='10ms', bandwidth=100):
    """
    Crée une topologie simple client-serveur avec conditions réseau contrôlées
    
    Args:
        loss_rate: Taux de perte de paquets (0-100%)
        delay: Délai de propagation (ex: '10ms', '50ms')
        bandwidth: Bande passante en Mbps
    """
    
    net = Mininet(link=TCLink, switch=OVSSwitch, controller=None, autoSetMacs=True)
    
    info('*** Ajout des hôtes\n')
    client = net.addHost('client', ip='10.0.0.1/24')
    server = net.addHost('server', ip='10.0.0.2/24')
    
    info('*** Ajout du switch\n')
    switch = net.addSwitch('s1', failMode='standalone')
    
    info('*** Création des liens\n')
    # Lien client vers switch (pas de dégradation)
    net.addLink(client, switch, cls=TCLink)
    
    # Lien switch vers serveur (avec conditions réseau)
    net.addLink(switch, server, cls=TCLink,
                delay=delay,
                loss=loss_rate,
                bw=bandwidth)
    
    info('*** Démarrage du réseau\n')
    net.start()
    
    # Configurer le switch en mode learning
    switch.cmd('ovs-ofctl add-flow s1 action=normal')
    
    # Test de connectivité
    info('*** Test de connectivité\n')
    result = net.ping([client, server], timeout=2)
    
    info('\n*** Configuration terminée\n')
    info(f'Client IP: {client.IP()}\n')
    info(f'Server IP: {server.IP()}\n')
    info(f'Conditions réseau: {loss_rate}% perte, {delay} délai, {bandwidth}Mbps\n')
    
    return net, client, server

def run_test(protocol, duration=30):
    """Lance un test avec un protocole donné"""
    info(f'\n*** Lancement du test {protocol} ***\n')
    
    # Conditions réseau réalistes pour cloud gaming
    # Tu peux modifier ces valeurs
    loss_rate = 2  # 2% de perte (réaliste pour WiFi/4G)
    delay = '20ms'  # 20ms de délai (bon cas)
    bandwidth = 50  # 50 Mbps
    
    net, client, server = create_topology(loss_rate, delay, bandwidth)
    
    # Chemins absolus pour les fichiers de résultats
    tcp_results = os.path.join(WORK_DIR, 'tcp_results.json')
    quic_results = os.path.join(WORK_DIR, 'quic_results.txt')
    quicsample_path = os.path.join(WORK_DIR, 'msquic/build/bin/Release/quicsample')
    
    try:
        if protocol == 'TCP':
            # Test avec iperf3 (TCP)
            info('*** Démarrage du serveur iperf3\n')
            server.cmd('iperf3 -s &')
            time.sleep(3)
            
            # Test de connectivité avant le test
            info('*** Vérification de la connectivité\n')
            ping_result = client.cmd(f'ping -c 1 {server.IP()}')
            if 'bytes from' not in ping_result:
                info('⚠️  ERREUR: Pas de connectivité réseau!\n')
                info(ping_result)
                return
            
            info('*** Lancement du test client\n')
            result = client.cmd(f'iperf3 -c {server.IP()} -t {duration} -J > {tcp_results}')
            info(f'Résultats TCP sauvegardés dans {tcp_results}\n')
            
            # Vérifier que le fichier a été créé
            if os.path.exists(tcp_results):
                info(f'✅ Fichier de résultats TCP créé avec succès\n')
            else:
                info(f'⚠️  Attention: fichier de résultats TCP non créé\n')
            
            # Arrêt du serveur
            server.cmd('pkill iperf3')
            
        elif protocol == 'QUIC':
            # Pour simuler QUIC, on utilise iperf3 en mode UDP
            # QUIC est basé sur UDP, donc cela donne une bonne approximation
            info('*** Démarrage du serveur iperf3 (UDP pour simuler QUIC)\n')
            server.cmd('iperf3 -s &')
            time.sleep(3)
            
            # Test de connectivité avant le test
            info('*** Vérification de la connectivité\n')
            ping_result = client.cmd(f'ping -c 1 {server.IP()}')
            if 'bytes from' not in ping_result:
                info('⚠️  ERREUR: Pas de connectivité réseau!\n')
                info(ping_result)
                return
            
            info('*** Lancement du test client (UDP)\n')
            # Test UDP à 50 Mbps (bande passante du lien)
            result = client.cmd(f'iperf3 -c {server.IP()} -u -b 50M -t {duration} -J > {quic_results}')
            info(f'Résultats QUIC/UDP sauvegardés dans {quic_results}\n')
            
            # Vérifier que le fichier a été créé
            if os.path.exists(quic_results):
                info(f'✅ Fichier de résultats QUIC/UDP créé avec succès\n')
            else:
                info(f'⚠️  Attention: fichier de résultats QUIC/UDP non créé\n')
            
            # Arrêt du serveur
            server.cmd('pkill iperf3')
        
        info(f'\n*** Test {protocol} terminé ***\n')
        
    finally:
        net.stop()

if __name__ == '__main__':
    setLogLevel('info')
    
    # Menu interactif
    print("\n" + "="*60)
    print("SIMULATEUR CLOUD GAMING - TCP vs QUIC")
    print("="*60)
    print("\nChoisissez un test:")
    print("1. Test TCP")
    print("2. Test QUIC")
    print("3. Test complet (TCP puis QUIC)")
    print("4. Mode interactif (CLI Mininet)")
    
    choice = input("\nVotre choix (1-4): ")
    
    if choice == '1':
        run_test('TCP', duration=30)
    elif choice == '2':
        run_test('QUIC', duration=30)
    elif choice == '3':
        print("\n>>> Lancement du test TCP...")
        run_test('TCP', duration=30)
        print("\n>>> Lancement du test QUIC...")
        run_test('QUIC', duration=30)
        print("\n✅ Tests terminés ! Consultez tcp_results.json et quic_results.txt")
    elif choice == '4':
        net, client, server = create_topology(loss_rate=2, delay='20ms', bandwidth=50)
        CLI(net)
        net.stop()
    else:
        print("Choix invalide")
