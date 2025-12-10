#!/usr/bin/env python3
"""
Analyse des résultats des tests Cloud Gaming
Génère les graphiques et tableaux comparatifs TCP vs QUIC
"""

import json
import os
import matplotlib.pyplot as plt
import numpy as np
from pathlib import Path

WORK_DIR = os.path.dirname(os.path.abspath(__file__))

SCENARIOS = {
    'bon': 'Réseau Bon (Fibre)',
    'moyen': 'Réseau Moyen (WiFi)',
    'mauvais': 'Réseau Mauvais (4G)'
}

def load_results():
    """Charge tous les résultats des tests"""
    results = {}
    
    for scenario in ['bon', 'moyen', 'mauvais']:
        results[scenario] = {}
        for protocol in ['tcp', 'quic']:
            # Charger les résultats client
            client_file = os.path.join(WORK_DIR, f'video_traffic_{protocol}_results.json')
            server_file = os.path.join(WORK_DIR, f'video_server_{protocol}_results.json')
            
            # Renommer temporairement si les fichiers existent avec le bon nom
            scenario_client_file = os.path.join(WORK_DIR, f'results_{scenario}_{protocol}_client.json')
            scenario_server_file = os.path.join(WORK_DIR, f'results_{scenario}_{protocol}_server.json')
            
            client_data = None
            server_data = None
            
            # Essayer de charger depuis plusieurs sources
            for cf in [scenario_client_file, client_file]:
                if os.path.exists(cf):
                    try:
                        with open(cf, 'r') as f:
                            client_data = json.load(f)
                        break
                    except:
                        pass
            
            for sf in [scenario_server_file, server_file]:
                if os.path.exists(sf):
                    try:
                        with open(sf, 'r') as f:
                            server_data = json.load(f)
                        break
                    except:
                        pass
            
            if client_data and server_data:
                results[scenario][protocol] = {
                    'client': client_data,
                    'server': server_data
                }
    
    return results

def calculate_gaming_metrics(client_data, server_data):
    """Calcule les métriques spécifiques au gaming"""
    metrics = {}
    
    # Frame Delivery Rate
    frames_sent = client_data.get('frames_sent', 0)
    frames_received = server_data.get('frames_received', 0)
    
    if frames_sent > 0:
        metrics['frame_delivery_rate'] = (frames_received / frames_sent) * 100
    else:
        metrics['frame_delivery_rate'] = 0
    
    # FPS reçus
    metrics['fps_received'] = server_data.get('avg_fps', 0)
    
    # Latence moyenne par frame (estimation)
    metrics['avg_latency_ms'] = server_data.get('avg_inter_frame_delay_ms', 0)
    
    # Jitter
    metrics['jitter_ms'] = server_data.get('jitter_ms', 0)
    
    # Débit
    metrics['throughput_mbps'] = server_data.get('throughput_mbps', 0)
    
    # Données envoyées vs reçues
    metrics['bytes_sent'] = client_data.get('total_bytes', 0)
    metrics['bytes_received'] = server_data.get('total_bytes', 0)
    
    return metrics

def create_scenario_comparison(scenario_name, tcp_metrics, quic_metrics):
    """Crée un graphique de comparaison pour un scénario"""
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    fig.suptitle(f'Cloud Gaming - {SCENARIOS[scenario_name]}', 
                 fontsize=16, fontweight='bold')
    
    protocols = ['TCP', 'QUIC']
    colors = ['#3498db', '#2ecc71']
    
    # 1. Frame Delivery Rate
    ax1 = axes[0, 0]
    delivery_rates = [tcp_metrics['frame_delivery_rate'], quic_metrics['frame_delivery_rate']]
    bars1 = ax1.bar(protocols, delivery_rates, color=colors, alpha=0.8)
    ax1.set_ylabel('Taux de livraison (%)', fontweight='bold')
    ax1.set_title('Frame Delivery Rate')
    ax1.set_ylim(0, 105)
    ax1.axhline(y=95, color='green', linestyle='--', alpha=0.5, label='Seuil acceptable (95%)')
    ax1.grid(axis='y', alpha=0.3)
    ax1.legend()
    
    for bar, val in zip(bars1, delivery_rates):
        ax1.text(bar.get_x() + bar.get_width()/2., bar.get_height() + 1,
                f'{val:.1f}%', ha='center', va='bottom', fontweight='bold')
    
    # 2. FPS Reçus
    ax2 = axes[0, 1]
    fps_values = [tcp_metrics['fps_received'], quic_metrics['fps_received']]
    bars2 = ax2.bar(protocols, fps_values, color=colors, alpha=0.8)
    ax2.set_ylabel('FPS', fontweight='bold')
    ax2.set_title('Frames Par Seconde Reçues')
    ax2.axhline(y=60, color='green', linestyle='--', alpha=0.5, label='Cible (60 FPS)')
    ax2.axhline(y=30, color='orange', linestyle='--', alpha=0.5, label='Minimum (30 FPS)')
    ax2.grid(axis='y', alpha=0.3)
    ax2.legend()
    
    for bar, val in zip(bars2, fps_values):
        ax2.text(bar.get_x() + bar.get_width()/2., bar.get_height() + 1,
                f'{val:.1f}', ha='center', va='bottom', fontweight='bold')
    
    # 3. Latence moyenne
    ax3 = axes[1, 0]
    latencies = [tcp_metrics['avg_latency_ms'], quic_metrics['avg_latency_ms']]
    bars3 = ax3.bar(protocols, latencies, color=colors, alpha=0.8)
    ax3.set_ylabel('Latence (ms)', fontweight='bold')
    ax3.set_title('Latence Moyenne Inter-Frame')
    ax3.axhline(y=16.67, color='green', linestyle='--', alpha=0.5, label='Cible 60 FPS (16.67ms)')
    ax3.grid(axis='y', alpha=0.3)
    ax3.legend()
    
    for bar, val in zip(bars3, latencies):
        ax3.text(bar.get_x() + bar.get_width()/2., bar.get_height() + 0.5,
                f'{val:.2f}ms', ha='center', va='bottom', fontweight='bold')
    
    # 4. Jitter
    ax4 = axes[1, 1]
    jitters = [tcp_metrics['jitter_ms'], quic_metrics['jitter_ms']]
    bars4 = ax4.bar(protocols, jitters, color=colors, alpha=0.8)
    ax4.set_ylabel('Jitter (ms)', fontweight='bold')
    ax4.set_title('Variation de Latence (Jitter)')
    ax4.axhline(y=5, color='green', linestyle='--', alpha=0.5, label='Seuil acceptable (5ms)')
    ax4.grid(axis='y', alpha=0.3)
    ax4.legend()
    
    for bar, val in zip(bars4, jitters):
        ax4.text(bar.get_x() + bar.get_width()/2., bar.get_height() + 0.2,
                f'{val:.2f}ms', ha='center', va='bottom', fontweight='bold')
    
    plt.tight_layout()
    filename = f'gaming_comparison_{scenario_name}.png'
    plt.savefig(filename, dpi=300, bbox_inches='tight')
    print(f"✅ Graphique sauvegardé: {filename}")
    plt.close()

def create_summary_table(all_metrics):
    """Crée un tableau récapitulatif de tous les scénarios"""
    fig, ax = plt.subplots(figsize=(16, 8))
    ax.axis('tight')
    ax.axis('off')
    
    # En-têtes du tableau
    headers = ['Scénario', 'Protocole', 'Delivery\nRate (%)', 'FPS\nReçus', 
               'Latence\n(ms)', 'Jitter\n(ms)', 'Débit\n(Mbps)', 'Note']
    
    table_data = []
    
    for scenario in ['bon', 'moyen', 'mauvais']:
        if scenario not in all_metrics:
            continue
        
        for protocol in ['tcp', 'quic']:
            if protocol not in all_metrics[scenario]:
                continue
            
            metrics = all_metrics[scenario][protocol]
            
            # Calculer une note globale (0-100)
            note = 0
            # Delivery rate (40%)
            note += (metrics['frame_delivery_rate'] / 100) * 40
            # FPS (30%)
            note += min(metrics['fps_received'] / 60, 1.0) * 30
            # Latence inversée (15%)
            latency_score = max(0, 1 - (metrics['avg_latency_ms'] / 100))
            note += latency_score * 15
            # Jitter inversé (15%)
            jitter_score = max(0, 1 - (metrics['jitter_ms'] / 20))
            note += jitter_score * 15
            
            # Couleur selon la note
            if note >= 80:
                color = '#2ecc71'  # Vert
            elif note >= 60:
                color = '#f39c12'  # Orange
            else:
                color = '#e74c3c'  # Rouge
            
            row = [
                SCENARIOS[scenario],
                protocol.upper(),
                f"{metrics['frame_delivery_rate']:.1f}",
                f"{metrics['fps_received']:.1f}",
                f"{metrics['avg_latency_ms']:.2f}",
                f"{metrics['jitter_ms']:.2f}",
                f"{metrics['throughput_mbps']:.2f}",
                f"{note:.0f}/100"
            ]
            table_data.append(row)
    
    table = ax.table(cellText=table_data, colLabels=headers,
                    cellLoc='center', loc='center',
                    colWidths=[0.18, 0.10, 0.12, 0.10, 0.12, 0.12, 0.12, 0.14])
    
    table.auto_set_font_size(False)
    table.set_fontsize(10)
    table.scale(1, 2.5)
    
    # Style de l'en-tête
    for i in range(len(headers)):
        table[(0, i)].set_facecolor('#34495e')
        table[(0, i)].set_text_props(weight='bold', color='white')
    
    # Alterner les couleurs des lignes
    for i in range(1, len(table_data) + 1):
        for j in range(len(headers)):
            if i % 2 == 0:
                table[(i, j)].set_facecolor('#ecf0f1')
    
    plt.title('Tableau Récapitulatif - Cloud Gaming TCP vs QUIC', 
              fontsize=16, fontweight='bold', pad=20)
    
    plt.savefig('gaming_summary_table.png', dpi=300, bbox_inches='tight')
    print(f"✅ Tableau récapitulatif sauvegardé: gaming_summary_table.png")
    plt.close()

def print_text_summary(all_metrics):
    """Affiche un résumé textuel des résultats"""
    print("\n" + "="*80)
    print("RÉSUMÉ DES RÉSULTATS - CLOUD GAMING TCP vs QUIC")
    print("="*80)
    
    for scenario in ['bon', 'moyen', 'mauvais']:
        if scenario not in all_metrics:
            continue
        
        print(f"\n📊 {SCENARIOS[scenario]}")
        print("-" * 80)
        
        for protocol in ['tcp', 'quic']:
            if protocol not in all_metrics[scenario]:
                continue
            
            metrics = all_metrics[scenario][protocol]
            print(f"\n  {protocol.upper()}:")
            print(f"    • Frame Delivery Rate: {metrics['frame_delivery_rate']:.1f}%")
            print(f"    • FPS Reçus: {metrics['fps_received']:.1f}")
            print(f"    • Latence Moyenne: {metrics['avg_latency_ms']:.2f} ms")
            print(f"    • Jitter: {metrics['jitter_ms']:.2f} ms")
            print(f"    • Débit: {metrics['throughput_mbps']:.2f} Mbps")

def main():
    print("="*80)
    print("ANALYSE DES RÉSULTATS - CLOUD GAMING BENCHMARK")
    print("="*80)
    
    # Charger les résultats
    results = load_results()
    
    if not results or all(not v for v in results.values()):
        print("\n❌ Aucun résultat trouvé!")
        print("Exécutez d'abord: sudo python3 gaming_benchmark.py")
        return
    
    # Calculer les métriques pour chaque scénario
    all_metrics = {}
    
    for scenario in ['bon', 'moyen', 'mauvais']:
        if scenario not in results or not results[scenario]:
            continue
        
        all_metrics[scenario] = {}
        
        for protocol in ['tcp', 'quic']:
            if protocol not in results[scenario]:
                continue
            
            data = results[scenario][protocol]
            metrics = calculate_gaming_metrics(data['client'], data['server'])
            all_metrics[scenario][protocol] = metrics
    
    if not all_metrics:
        print("\n❌ Impossible de calculer les métriques!")
        return
    
    # Afficher le résumé textuel
    print_text_summary(all_metrics)
    
    # Générer les graphiques
    print(f"\n📊 Génération des graphiques...")
    
    for scenario in ['bon', 'moyen', 'mauvais']:
        if scenario in all_metrics and 'tcp' in all_metrics[scenario] and 'quic' in all_metrics[scenario]:
            create_scenario_comparison(scenario, 
                                      all_metrics[scenario]['tcp'],
                                      all_metrics[scenario]['quic'])
    
    # Créer le tableau récapitulatif
    create_summary_table(all_metrics)
    
    print(f"\n✅ Analyse terminée!")
    print(f"Fichiers générés dans: {WORK_DIR}")

if __name__ == '__main__':
    main()
