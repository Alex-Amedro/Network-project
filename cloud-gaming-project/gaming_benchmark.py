#!/usr/bin/env python3
"""
Benchmark Cloud Gaming - TCP vs QUIC
Teste 3 scénarios réseau avec trafic vidéo réaliste
Comparaison entre TCP (fiable traditionnel) et QUIC (fiable moderne)
"""

from mininet.net import Mininet
from mininet.node import OVSSwitch
from mininet.link import TCLink
from mininet.log import setLogLevel, info
import time
import os
import json
import sys

# Répertoire de travail
WORK_DIR = os.path.dirname(os.path.abspath(__file__))

# Scénarios de test
SCENARIOS = {
    'bon': {
        'name': 'Réseau Bon (Fibre)',
        'loss': 1,
        'delay': '10ms',
        'bandwidth': 100,
        'description': 'Connexion fibre optimale'
    },
    'moyen': {
        'name': 'Réseau Moyen (WiFi)',
        'loss': 3,
        'delay': '25ms',
        'bandwidth': 50,
        'description': 'WiFi standard avec quelques interférences'
    },
    'mauvais': {
        'name': 'Réseau Mauvais (4G)',
        'loss': 8,
        'delay': '60ms',
        'bandwidth': 20,
        'description': '4G avec connexion instable'
    }
}

def create_topology(scenario_config):
    """Crée la topologie Mininet avec les paramètres du scénario"""
    net = Mininet(link=TCLink, switch=OVSSwitch, controller=None, autoSetMacs=True)
    
    info('*** Création de la topologie\n')
    client = net.addHost('client', ip='10.0.0.1/24')
    server = net.addHost('server', ip='10.0.0.2/24')
    switch = net.addSwitch('s1', failMode='standalone')
    
    # Lien client -> switch (pas de dégradation)
    net.addLink(client, switch, cls=TCLink)
    
    # Lien switch -> serveur (avec conditions réseau du scénario)
    net.addLink(switch, server, cls=TCLink,
                delay=scenario_config['delay'],
                loss=scenario_config['loss'],
                bw=scenario_config['bandwidth'])
    
    net.start()
    
    # Configurer le switch
    switch.cmd('ovs-ofctl add-flow s1 action=normal')
    
    # Test de connectivité
    info('*** Test de connectivité\n')
    result = net.ping([client, server], timeout=2)
    
    return net, client, server

def run_video_server(host, protocol, port=5000):
    """Démarre le serveur de réception vidéo"""
    server_script = os.path.join(WORK_DIR, 'video_server.py')
    
    if protocol == 'QUIC':
        # Pour QUIC, on utilise UDP (QUIC est basé sur UDP)
        cmd = f'python3 {server_script} {port} QUIC > video_server_quic.log 2>&1 &'
    else:  # TCP
        cmd = f'python3 {server_script} {port} TCP > video_server_tcp.log 2>&1 &'
    
    host.cmd(cmd)
    time.sleep(1)
    info(f'*** Serveur {protocol} démarré sur port {port}\n')

def run_video_client(host, server_ip, protocol, duration, scenario_name):
    """Lance le client générateur de trafic vidéo"""
    client_script = os.path.join(WORK_DIR, 'video_traffic_gen.py')
    
    info(f'*** Lancement du client {protocol} (durée: {duration}s)\n')
    
    # Exécuter le script et attendre qu'il se termine
    cmd = f'python3 {client_script} {server_ip} {protocol} {duration} > video_client_{protocol.lower()}.log 2>&1'
    host.cmd(cmd)
    
    # Renommer les fichiers de résultats avec le nom du scénario
    old_file = os.path.join(WORK_DIR, f'video_traffic_{protocol.lower()}_results.json')
    new_file = os.path.join(WORK_DIR, f'results_{scenario_name}_{protocol.lower()}_client.json')
    
    host.cmd(f'mv {old_file} {new_file}')
    
    info(f'*** Client {protocol} terminé\n')
    
    # Attendre un peu pour s'assurer que les fichiers sont écrits
    time.sleep(1)

def run_scenario_test(scenario_name, scenario_config, protocol, duration=30):
    """Exécute un test complet pour un scénario et un protocole"""
    info(f'\n{"="*70}\n')
    info(f'SCÉNARIO: {scenario_config["name"]} - Protocole: {protocol}\n')
    info(f'{"="*70}\n')
    info(f'Paramètres: {scenario_config["loss"]}% perte, {scenario_config["delay"]} délai, {scenario_config["bandwidth"]} Mbps\n')
    
    # Créer la topologie
    net, client, server = create_topology(scenario_config)
    
    try:
        # Démarrer le serveur
        run_video_server(server, protocol, port=5000)
        
        # Lancer le client
        run_video_client(client, server.IP(), protocol, duration, scenario_name)
        
        # Attendre que tout soit bien terminé
        time.sleep(2)
        
        # Renommer les fichiers du serveur
        old_server_file = os.path.join(WORK_DIR, f'video_server_{protocol.lower()}_results.json')
        new_server_file = os.path.join(WORK_DIR, f'results_{scenario_name}_{protocol.lower()}_server.json')
        
        # Utiliser une commande système pour renommer
        import shutil
        if os.path.exists(old_server_file):
            shutil.move(old_server_file, new_server_file)
        
        # Arrêter le serveur
        if protocol == 'QUIC':
            server.cmd('pkill -f "video_server.py.*QUIC"')
        else:
            server.cmd('pkill -f "video_server.py.*TCP"')
        
        info(f'✅ Test {scenario_name} - {protocol} terminé\n')
        
        return True
        
    except Exception as e:
        info(f'❌ Erreur pendant le test: {e}\n')
        return False
    finally:
        net.stop()
        time.sleep(2)

def main():
    """Exécute tous les tests"""
    setLogLevel('info')
    
    print("\n" + "="*70)
    print("BENCHMARK CLOUD GAMING - TCP vs QUIC")
    print("="*70)
    print("\nℹ️  QUIC = UDP + Fiabilité + Multiplexing + Low Latency")
    print("   TCP  = Fiable mais Head-of-Line Blocking")
    print("\n📋 Scénarios à tester:")
    for name, config in SCENARIOS.items():
        print(f"  • {config['name']}: {config['loss']}% perte, {config['delay']} délai")
    
    input("\nAppuyez sur Entrée pour commencer les tests...")
    
    # Durée de chaque test (en secondes)
    test_duration = 30
    
    # Tester chaque scénario avec TCP et QUIC
    for scenario_name, scenario_config in SCENARIOS.items():
        for protocol in ['TCP', 'QUIC']:
            success = run_scenario_test(scenario_name, scenario_config, protocol, test_duration)
            
            if not success:
                print(f"⚠️  Échec du test {scenario_name} - {protocol}")
            
            # Pause entre les tests
            time.sleep(3)
    
    print("\n" + "="*70)
    print("✅ TOUS LES TESTS TERMINÉS !")
    print("="*70)
    print(f"\nRésultats sauvegardés dans: {WORK_DIR}")
    print("\nExécutez maintenant: python3 analyze_gaming_results.py")

if __name__ == '__main__':
    main()
