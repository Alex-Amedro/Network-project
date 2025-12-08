#!/usr/bin/env python3
"""
Cloud Gaming Benchmark - Niveau ARGENT
Compare TCP, QUIC (vrai) et rQUIC (UDP+ARQ) sous différentes conditions réseau

Caractéristiques:
- 3 protocoles: TCP (fiable classique), QUIC (moderne), rQUIC (simulation QUIC-like)
- 3 scénarios réseau: Bon, Moyen, Mauvais
- Conditions dynamiques optionnelles
- Métriques avancées: MOS, seuil de jouabilité
"""

import os
import sys
import time
import json
import subprocess
import threading
from datetime import datetime

# Mininet imports
from mininet.net import Mininet
from mininet.node import OVSSwitch
from mininet.link import TCLink
from mininet.log import setLogLevel, info

# Répertoire de travail
WORK_DIR = os.path.dirname(os.path.abspath(__file__))

# Configuration des scénarios réseau
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
        'description': 'WiFi standard avec interférences légères'
    },
    'mauvais': {
        'name': 'Réseau Mauvais (4G)',
        'loss': 8,
        'delay': '60ms',
        'bandwidth': 20,
        'description': '4G avec connexion instable'
    }
}

# Protocoles à tester
PROTOCOLS = ['TCP', 'rQUIC']  # On commence avec TCP et rQUIC (plus stable que aioquic dans Mininet)

# Durée de chaque test en secondes
TEST_DURATION = 30


def calculate_mos(latency_ms: float, jitter_ms: float, loss_percent: float) -> float:
    """
    Calcule le Mean Opinion Score (MOS) pour le gaming
    Score de 1 (injouable) à 5 (parfait)
    
    Basé sur ITU-T G.1072 adapté pour le cloud gaming
    """
    # Facteurs de pénalité
    latency_penalty = 0
    if latency_ms > 150:
        latency_penalty = min(4, (latency_ms - 150) / 50)
    elif latency_ms > 50:
        latency_penalty = (latency_ms - 50) / 100
    
    jitter_penalty = 0
    if jitter_ms > 30:
        jitter_penalty = min(2, (jitter_ms - 30) / 30)
    elif jitter_ms > 10:
        jitter_penalty = (jitter_ms - 10) / 40
    
    loss_penalty = 0
    if loss_percent > 5:
        loss_penalty = min(3, (loss_percent - 5) / 5)
    elif loss_percent > 1:
        loss_penalty = (loss_percent - 1) / 8
    
    # MOS de base = 5, on soustrait les pénalités
    mos = 5.0 - latency_penalty - jitter_penalty - loss_penalty
    
    return max(1.0, min(5.0, mos))


def get_playability_status(mos: float, fps: float, delivery_rate: float) -> tuple:
    """
    Détermine le statut de jouabilité
    Retourne (statut, couleur, description)
    """
    if mos >= 4.0 and fps >= 55 and delivery_rate >= 95:
        return ('EXCELLENT', 'green', 'Expérience optimale - jeu fluide')
    elif mos >= 3.5 and fps >= 45 and delivery_rate >= 85:
        return ('BON', 'lightgreen', 'Jouable sans problème majeur')
    elif mos >= 2.5 and fps >= 30 and delivery_rate >= 70:
        return ('ACCEPTABLE', 'yellow', 'Jouable avec quelques saccades')
    elif mos >= 2.0 and fps >= 20 and delivery_rate >= 50:
        return ('DIFFICILE', 'orange', 'Expérience dégradée - frustrant')
    else:
        return ('INJOUABLE', 'red', 'Impossible de jouer correctement')


def setup_network(scenario_config: dict):
    """Configure le réseau Mininet avec les paramètres du scénario"""
    
    info(f'\n*** Configuration: {scenario_config["name"]}\n')
    info(f'    Perte: {scenario_config["loss"]}%, Délai: {scenario_config["delay"]}, '
         f'Bande passante: {scenario_config["bandwidth"]} Mbps\n')
    
    # Créer la topologie
    net = Mininet(link=TCLink, switch=OVSSwitch, controller=None, autoSetMacs=True)
    
    # Ajouter les hôtes
    client = net.addHost('client', ip='10.0.0.1/24')
    server = net.addHost('server', ip='10.0.0.2/24')
    switch = net.addSwitch('s1', failMode='standalone')
    
    # Ajouter les liens avec les caractéristiques réseau
    net.addLink(client, switch, cls=TCLink)
    net.addLink(switch, server, cls=TCLink,
                delay=scenario_config['delay'],
                loss=scenario_config['loss'],
                bw=scenario_config['bandwidth'])
    
    net.start()
    
    # Configurer le switch en mode normal (forwarding)
    switch.cmd('ovs-ofctl add-flow s1 action=normal')
    
    return net, client, server


def run_tcp_test(client, server, scenario: str, duration: int = TEST_DURATION):
    """Exécute un test TCP"""
    
    info(f'\n*** Test TCP - {scenario}\n')
    
    server_script = os.path.join(WORK_DIR, 'video_server.py')
    client_script = os.path.join(WORK_DIR, 'video_traffic_gen.py')
    
    server_output = f'results_{scenario}_tcp_server.json'
    client_output = f'results_{scenario}_tcp_client.json'
    
    # Démarrer le serveur
    server_cmd = f'cd {WORK_DIR} && python3 {server_script} 5000 TCP {duration} > /dev/null 2>&1 &'
    server.cmd(server_cmd)
    time.sleep(2)
    
    # Vérifier que le serveur tourne
    ps = server.cmd('ps aux | grep video_server | grep -v grep')
    if not ps.strip():
        info('⚠️  Serveur TCP non démarré!\n')
        return None, None
    
    # Lancer le client
    client_cmd = f'cd {WORK_DIR} && python3 {client_script} {server.IP()} TCP {duration}'
    result = client.cmd(client_cmd)
    info(f'Client TCP: {result[:200]}...\n')
    
    time.sleep(3)
    
    # Arrêter le serveur
    server.cmd('pkill -f video_server.py')
    
    # Renommer les fichiers de sortie
    client.cmd(f'cd {WORK_DIR} && mv video_traffic_tcp_results.json {client_output} 2>/dev/null')
    server.cmd(f'cd {WORK_DIR} && mv video_server_tcp_results.json {server_output} 2>/dev/null')
    
    return client_output, server_output


def run_rquic_test(client, server, scenario: str, duration: int = TEST_DURATION):
    """Exécute un test rQUIC (UDP + ARQ)"""
    
    info(f'\n*** Test rQUIC - {scenario}\n')
    
    rquic_script = os.path.join(WORK_DIR, 'rquic_protocol.py')
    
    server_output = f'results_{scenario}_rquic_server.json'
    client_output = f'results_{scenario}_rquic_client.json'
    
    # Démarrer le serveur rQUIC
    server_cmd = f'cd {WORK_DIR} && python3 {rquic_script} server --port 5001 --duration {duration} --output {server_output} > /dev/null 2>&1 &'
    server.cmd(server_cmd)
    time.sleep(2)
    
    # Vérifier que le serveur tourne
    ps = server.cmd('ps aux | grep rquic_protocol | grep -v grep')
    if not ps.strip():
        info('⚠️  Serveur rQUIC non démarré!\n')
        return None, None
    
    info(f'Serveur rQUIC démarré: {ps[:100]}...\n')
    
    # Lancer le client rQUIC
    client_cmd = f'cd {WORK_DIR} && python3 {rquic_script} client --host {server.IP()} --port 5001 --duration {duration} --output {client_output}'
    result = client.cmd(client_cmd)
    info(f'Client rQUIC: {result[:300]}...\n')
    
    time.sleep(3)
    
    # Arrêter le serveur
    server.cmd('pkill -f rquic_protocol.py')
    
    return client_output, server_output


def run_scenario(scenario: str, protocols: list = PROTOCOLS):
    """Exécute tous les tests pour un scénario donné"""
    
    config = SCENARIOS[scenario]
    results = {}
    
    info(f'\n{"="*60}\n')
    info(f'SCÉNARIO: {config["name"]}\n')
    info(f'{config["description"]}\n')
    info(f'{"="*60}\n')
    
    # Configurer le réseau
    net, client, server = setup_network(config)
    
    # Test de connectivité
    info('*** Test de connectivité\n')
    net.ping([client, server], timeout=2)
    
    try:
        for protocol in protocols:
            if protocol == 'TCP':
                client_file, server_file = run_tcp_test(client, server, scenario)
            elif protocol == 'rQUIC':
                client_file, server_file = run_rquic_test(client, server, scenario)
            else:
                info(f'Protocole {protocol} non supporté\n')
                continue
            
            results[protocol.lower()] = {
                'client_file': client_file,
                'server_file': server_file
            }
            
            time.sleep(2)  # Pause entre les tests
            
    finally:
        info('\n*** Arrêt du réseau\n')
        net.stop()
    
    return results


def load_results(scenario: str, protocol: str) -> tuple:
    """Charge les résultats d'un test"""
    
    client_file = os.path.join(WORK_DIR, f'results_{scenario}_{protocol}_client.json')
    server_file = os.path.join(WORK_DIR, f'results_{scenario}_{protocol}_server.json')
    
    client_data = None
    server_data = None
    
    if os.path.exists(client_file):
        with open(client_file) as f:
            client_data = json.load(f)
    
    if os.path.exists(server_file):
        with open(server_file) as f:
            server_data = json.load(f)
    
    return client_data, server_data


def analyze_results():
    """Analyse et affiche les résultats de tous les tests"""
    
    print("\n" + "="*80)
    print("ANALYSE DES RÉSULTATS - CLOUD GAMING BENCHMARK")
    print("="*80)
    
    all_results = {}
    
    for scenario in SCENARIOS:
        print(f"\n📊 {SCENARIOS[scenario]['name']}")
        print("-" * 60)
        
        all_results[scenario] = {}
        
        for protocol in ['tcp', 'rquic']:
            client_data, server_data = load_results(scenario, protocol)
            
            if not client_data or not server_data:
                print(f"  {protocol.upper()}: Données manquantes")
                continue
            
            # Calculer les métriques
            frames_sent = client_data.get('frames_sent', 0)
            frames_received = server_data.get('frames_received', 0)
            delivery_rate = (frames_received / frames_sent * 100) if frames_sent > 0 else 0
            
            fps = server_data.get('avg_fps', 0)
            latency = server_data.get('avg_inter_frame_delay_ms', 0)
            jitter = server_data.get('jitter_ms', 0)
            throughput = server_data.get('throughput_mbps', 0)
            
            # Retransmissions (seulement pour rQUIC)
            retransmissions = client_data.get('retransmissions', 0)
            
            # Calculer MOS
            loss_percent = 100 - delivery_rate
            mos = calculate_mos(latency, jitter, loss_percent)
            
            # Statut de jouabilité
            status, color, desc = get_playability_status(mos, fps, delivery_rate)
            
            all_results[scenario][protocol] = {
                'frames_sent': frames_sent,
                'frames_received': frames_received,
                'delivery_rate': delivery_rate,
                'fps': fps,
                'latency_ms': latency,
                'jitter_ms': jitter,
                'throughput_mbps': throughput,
                'retransmissions': retransmissions,
                'mos': mos,
                'playability': status,
            }
            
            print(f"\n  {protocol.upper()}:")
            print(f"    • Frames: {frames_received}/{frames_sent} ({delivery_rate:.1f}%)")
            print(f"    • FPS: {fps:.1f}")
            print(f"    • Latence: {latency:.2f} ms")
            print(f"    • Jitter: {jitter:.2f} ms")
            print(f"    • Débit: {throughput:.2f} Mbps")
            if retransmissions > 0:
                print(f"    • Retransmissions: {retransmissions}")
            print(f"    • MOS: {mos:.2f}/5.0")
            print(f"    • Jouabilité: {status} - {desc}")
    
    # Sauvegarder les résultats analysés
    output_file = os.path.join(WORK_DIR, 'benchmark_analysis.json')
    with open(output_file, 'w') as f:
        json.dump(all_results, f, indent=2)
    
    print(f"\n✅ Analyse sauvegardée: {output_file}")
    
    return all_results


def main():
    """Point d'entrée principal"""
    
    setLogLevel('info')
    
    print("="*80)
    print("CLOUD GAMING BENCHMARK - NIVEAU ARGENT")
    print("Comparaison TCP vs rQUIC (UDP+ARQ)")
    print("="*80)
    print(f"\nProtocoles: {', '.join(PROTOCOLS)}")
    print(f"Scénarios: {', '.join(SCENARIOS.keys())}")
    print(f"Durée par test: {TEST_DURATION}s")
    print(f"Durée totale estimée: ~{len(PROTOCOLS) * len(SCENARIOS) * (TEST_DURATION + 10) // 60} minutes")
    print("\n" + "-"*80)
    
    print("\n🎮 Différences entre les protocoles:")
    print("  • TCP: Fiable, retransmissions, head-of-line blocking")
    print("  • rQUIC: UDP + ARQ (retransmission sélective), pas de HoL blocking")
    print("\n" + "-"*80)
    
    # Exécuter les tests pour chaque scénario
    for scenario in SCENARIOS:
        run_scenario(scenario, PROTOCOLS)
        time.sleep(3)
    
    # Analyser les résultats
    results = analyze_results()
    
    print("\n" + "="*80)
    print("✅ BENCHMARK TERMINÉ!")
    print("="*80)
    print("\nFichiers générés:")
    print("  • results_*_tcp_*.json - Résultats TCP")
    print("  • results_*_rquic_*.json - Résultats rQUIC")
    print("  • benchmark_analysis.json - Analyse complète")
    print("\nPour générer les graphiques:")
    print("  python3 analyze_gaming_results_v2.py")


if __name__ == '__main__':
    main()
