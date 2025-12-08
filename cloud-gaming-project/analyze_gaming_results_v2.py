#!/usr/bin/env python3
"""
Analyse et Visualisation - Cloud Gaming Benchmark Niveau ARGENT
Génère des graphiques comparatifs TCP vs rQUIC avec métriques avancées (MOS, jouabilité)
"""

import os
import json
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from datetime import datetime

# Répertoire de travail
WORK_DIR = os.path.dirname(os.path.abspath(__file__))

# Configuration des scénarios
SCENARIOS = {
    'bon': 'Réseau Bon (Fibre)',
    'moyen': 'Réseau Moyen (WiFi)', 
    'mauvais': 'Réseau Mauvais (4G)'
}

# Couleurs par protocole
COLORS = {
    'tcp': '#3498db',      # Bleu
    'rquic': '#2ecc71',    # Vert
    'quic': '#9b59b6',     # Violet
}

# Couleurs de jouabilité
PLAYABILITY_COLORS = {
    'EXCELLENT': '#27ae60',
    'BON': '#2ecc71',
    'ACCEPTABLE': '#f1c40f',
    'DIFFICILE': '#e67e22',
    'INJOUABLE': '#e74c3c',
}


def calculate_mos(latency_ms: float, jitter_ms: float, loss_percent: float) -> float:
    """Calcule le Mean Opinion Score (MOS) pour le gaming"""
    
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
    
    mos = 5.0 - latency_penalty - jitter_penalty - loss_penalty
    return max(1.0, min(5.0, mos))


def get_playability(mos: float, fps: float, delivery_rate: float) -> str:
    """Détermine le statut de jouabilité"""
    if mos >= 4.0 and fps >= 55 and delivery_rate >= 95:
        return 'EXCELLENT'
    elif mos >= 3.5 and fps >= 45 and delivery_rate >= 85:
        return 'BON'
    elif mos >= 2.5 and fps >= 30 and delivery_rate >= 70:
        return 'ACCEPTABLE'
    elif mos >= 2.0 and fps >= 20 and delivery_rate >= 50:
        return 'DIFFICILE'
    else:
        return 'INJOUABLE'


def load_results() -> dict:
    """Charge tous les résultats disponibles"""
    
    results = {}
    protocols = ['tcp', 'rquic', 'quic']
    
    for scenario in SCENARIOS:
        results[scenario] = {}
        
        for protocol in protocols:
            client_file = os.path.join(WORK_DIR, f'results_{scenario}_{protocol}_client.json')
            server_file = os.path.join(WORK_DIR, f'results_{scenario}_{protocol}_server.json')
            
            if os.path.exists(client_file) and os.path.exists(server_file):
                with open(client_file) as f:
                    client_data = json.load(f)
                with open(server_file) as f:
                    server_data = json.load(f)
                
                results[scenario][protocol] = {
                    'client': client_data,
                    'server': server_data
                }
    
    return results


def calculate_metrics(client_data: dict, server_data: dict) -> dict:
    """Calcule toutes les métriques à partir des données brutes"""
    
    frames_sent = client_data.get('frames_sent', 0)
    frames_received = server_data.get('frames_received', 0)
    
    if frames_sent == 0:
        return None
    
    delivery_rate = (frames_received / frames_sent) * 100
    fps = server_data.get('avg_fps', 0)
    latency = server_data.get('avg_inter_frame_delay_ms', 0)
    jitter = server_data.get('jitter_ms', 0)
    throughput = server_data.get('throughput_mbps', 0)
    retransmissions = client_data.get('retransmissions', 0)
    
    # Calculer MOS
    loss_percent = 100 - delivery_rate
    mos = calculate_mos(latency, jitter, loss_percent)
    playability = get_playability(mos, fps, delivery_rate)
    
    return {
        'frames_sent': frames_sent,
        'frames_received': frames_received,
        'frame_delivery_rate': delivery_rate,
        'fps_received': fps,
        'avg_latency_ms': latency,
        'jitter_ms': jitter,
        'throughput_mbps': throughput,
        'retransmissions': retransmissions,
        'mos': mos,
        'playability': playability,
    }


def create_comparison_chart(all_metrics: dict, output_file: str = 'gaming_comparison_v2.png'):
    """Crée un graphique de comparaison multi-scénarios"""
    
    fig, axes = plt.subplots(2, 3, figsize=(18, 12))
    fig.suptitle('Cloud Gaming Benchmark - TCP vs rQUIC\nComparaison par Scénario Réseau', 
                 fontsize=16, fontweight='bold')
    
    scenarios = list(SCENARIOS.keys())
    metrics_to_plot = [
        ('frame_delivery_rate', 'Taux de Livraison (%)', 0, 100),
        ('fps_received', 'FPS Reçus', 0, 70),
        ('avg_latency_ms', 'Latence (ms)', 0, None),
        ('jitter_ms', 'Jitter (ms)', 0, None),
        ('mos', 'MOS (1-5)', 1, 5),
        ('retransmissions', 'Retransmissions', 0, None),
    ]
    
    for idx, (metric, title, ymin, ymax) in enumerate(metrics_to_plot):
        ax = axes[idx // 3, idx % 3]
        
        x = np.arange(len(scenarios))
        width = 0.35
        
        tcp_values = []
        rquic_values = []
        
        for scenario in scenarios:
            if scenario in all_metrics:
                tcp_val = all_metrics[scenario].get('tcp', {}).get(metric, 0)
                rquic_val = all_metrics[scenario].get('rquic', {}).get(metric, 0)
            else:
                tcp_val = 0
                rquic_val = 0
            
            tcp_values.append(tcp_val)
            rquic_values.append(rquic_val)
        
        bars1 = ax.bar(x - width/2, tcp_values, width, label='TCP', color=COLORS['tcp'])
        bars2 = ax.bar(x + width/2, rquic_values, width, label='rQUIC', color=COLORS['rquic'])
        
        ax.set_ylabel(title)
        ax.set_xticks(x)
        ax.set_xticklabels([SCENARIOS[s].split('(')[0].strip() for s in scenarios])
        ax.legend()
        ax.grid(axis='y', alpha=0.3)
        
        if ymin is not None:
            ax.set_ylim(bottom=ymin)
        if ymax is not None:
            ax.set_ylim(top=ymax)
        
        # Ajouter les valeurs sur les barres
        for bar, val in zip(bars1, tcp_values):
            if val > 0:
                ax.annotate(f'{val:.1f}', xy=(bar.get_x() + bar.get_width()/2, bar.get_height()),
                           ha='center', va='bottom', fontsize=8)
        for bar, val in zip(bars2, rquic_values):
            if val > 0:
                ax.annotate(f'{val:.1f}', xy=(bar.get_x() + bar.get_width()/2, bar.get_height()),
                           ha='center', va='bottom', fontsize=8)
    
    plt.tight_layout()
    plt.savefig(os.path.join(WORK_DIR, output_file), dpi=300, bbox_inches='tight')
    print(f"✅ Graphique sauvegardé: {output_file}")
    plt.close()


def create_mos_dashboard(all_metrics: dict, output_file: str = 'gaming_mos_dashboard.png'):
    """Crée un dashboard MOS et jouabilité"""
    
    fig, axes = plt.subplots(1, 3, figsize=(16, 6))
    fig.suptitle('Dashboard Qualité d\'Expérience (QoE) - Cloud Gaming', 
                 fontsize=14, fontweight='bold')
    
    scenarios = list(SCENARIOS.keys())
    
    for idx, scenario in enumerate(scenarios):
        ax = axes[idx]
        
        if scenario not in all_metrics:
            ax.text(0.5, 0.5, 'Pas de données', ha='center', va='center')
            ax.set_title(SCENARIOS[scenario])
            continue
        
        protocols = []
        mos_values = []
        playability_colors = []
        
        for protocol in ['tcp', 'rquic']:
            if protocol in all_metrics[scenario]:
                metrics = all_metrics[scenario][protocol]
                protocols.append(protocol.upper())
                mos_values.append(metrics['mos'])
                playability_colors.append(PLAYABILITY_COLORS.get(metrics['playability'], 'gray'))
        
        if not protocols:
            ax.text(0.5, 0.5, 'Pas de données', ha='center', va='center')
            ax.set_title(SCENARIOS[scenario])
            continue
        
        bars = ax.bar(protocols, mos_values, color=playability_colors, edgecolor='black', linewidth=2)
        
        ax.set_ylim(0, 5.5)
        ax.set_ylabel('MOS Score')
        ax.set_title(SCENARIOS[scenario], fontweight='bold')
        
        # Lignes de seuil
        ax.axhline(y=4.0, color='green', linestyle='--', alpha=0.5, label='Excellent (4.0)')
        ax.axhline(y=3.0, color='orange', linestyle='--', alpha=0.5, label='Acceptable (3.0)')
        ax.axhline(y=2.0, color='red', linestyle='--', alpha=0.5, label='Difficile (2.0)')
        
        # Annotations
        for bar, mos, protocol in zip(bars, mos_values, protocols):
            playability = all_metrics[scenario][protocol.lower()]['playability']
            ax.annotate(f'{mos:.2f}\n{playability}', 
                       xy=(bar.get_x() + bar.get_width()/2, bar.get_height()),
                       ha='center', va='bottom', fontsize=10, fontweight='bold')
        
        ax.grid(axis='y', alpha=0.3)
    
    # Légende globale
    legend_patches = [
        mpatches.Patch(color=PLAYABILITY_COLORS['EXCELLENT'], label='Excellent'),
        mpatches.Patch(color=PLAYABILITY_COLORS['BON'], label='Bon'),
        mpatches.Patch(color=PLAYABILITY_COLORS['ACCEPTABLE'], label='Acceptable'),
        mpatches.Patch(color=PLAYABILITY_COLORS['DIFFICILE'], label='Difficile'),
        mpatches.Patch(color=PLAYABILITY_COLORS['INJOUABLE'], label='Injouable'),
    ]
    fig.legend(handles=legend_patches, loc='lower center', ncol=5, bbox_to_anchor=(0.5, -0.02))
    
    plt.tight_layout()
    plt.savefig(os.path.join(WORK_DIR, output_file), dpi=300, bbox_inches='tight')
    print(f"✅ Dashboard MOS sauvegardé: {output_file}")
    plt.close()


def create_summary_table(all_metrics: dict, output_file: str = 'gaming_summary_v2.png'):
    """Crée un tableau récapitulatif complet"""
    
    fig, ax = plt.subplots(figsize=(16, 10))
    ax.axis('off')
    
    # En-têtes
    headers = ['Scénario', 'Protocole', 'Livraison %', 'FPS', 'Latence (ms)', 
               'Jitter (ms)', 'Retrans.', 'MOS', 'Jouabilité']
    
    # Données
    data = []
    colors = []
    
    for scenario in SCENARIOS:
        if scenario not in all_metrics:
            continue
        
        for protocol in ['tcp', 'rquic']:
            if protocol not in all_metrics[scenario]:
                continue
            
            m = all_metrics[scenario][protocol]
            row = [
                SCENARIOS[scenario].split('(')[0].strip(),
                protocol.upper(),
                f"{m['frame_delivery_rate']:.1f}%",
                f"{m['fps_received']:.1f}",
                f"{m['avg_latency_ms']:.1f}",
                f"{m['jitter_ms']:.1f}",
                str(m['retransmissions']),
                f"{m['mos']:.2f}",
                m['playability'],
            ]
            data.append(row)
            
            # Couleur de ligne selon protocole
            if protocol == 'tcp':
                colors.append([COLORS['tcp'] + '40'] * len(headers))
            else:
                colors.append([COLORS['rquic'] + '40'] * len(headers))
    
    if not data:
        ax.text(0.5, 0.5, 'Pas de données disponibles', ha='center', va='center', fontsize=14)
        plt.savefig(os.path.join(WORK_DIR, output_file), dpi=300, bbox_inches='tight')
        plt.close()
        return
    
    table = ax.table(
        cellText=data,
        colLabels=headers,
        cellColours=colors if colors else None,
        loc='center',
        cellLoc='center',
    )
    
    table.auto_set_font_size(False)
    table.set_fontsize(10)
    table.scale(1.2, 2)
    
    # Style des en-têtes
    for i, header in enumerate(headers):
        table[(0, i)].set_facecolor('#2c3e50')
        table[(0, i)].set_text_props(color='white', fontweight='bold')
    
    # Colorer la colonne Jouabilité
    for i, row in enumerate(data):
        playability = row[-1]
        color = PLAYABILITY_COLORS.get(playability, 'white')
        table[(i+1, len(headers)-1)].set_facecolor(color)
        if playability in ['INJOUABLE', 'DIFFICILE']:
            table[(i+1, len(headers)-1)].set_text_props(color='white')
    
    plt.title('Tableau Récapitulatif - Cloud Gaming TCP vs rQUIC', 
              fontsize=16, fontweight='bold', pad=20)
    
    plt.savefig(os.path.join(WORK_DIR, output_file), dpi=300, bbox_inches='tight')
    print(f"✅ Tableau récapitulatif sauvegardé: {output_file}")
    plt.close()


def print_summary(all_metrics: dict):
    """Affiche un résumé textuel"""
    
    print("\n" + "="*80)
    print("RÉSUMÉ DES RÉSULTATS - CLOUD GAMING TCP vs rQUIC")
    print("="*80)
    
    for scenario in SCENARIOS:
        if scenario not in all_metrics:
            continue
        
        print(f"\n📊 {SCENARIOS[scenario]}")
        print("-" * 60)
        
        for protocol in ['tcp', 'rquic']:
            if protocol not in all_metrics[scenario]:
                continue
            
            m = all_metrics[scenario][protocol]
            
            print(f"\n  {protocol.upper()}:")
            print(f"    • Livraison: {m['frame_delivery_rate']:.1f}%")
            print(f"    • FPS: {m['fps_received']:.1f}")
            print(f"    • Latence: {m['avg_latency_ms']:.2f} ms")
            print(f"    • Jitter: {m['jitter_ms']:.2f} ms")
            if m['retransmissions'] > 0:
                print(f"    • Retransmissions: {m['retransmissions']}")
            print(f"    • MOS: {m['mos']:.2f}/5.0")
            print(f"    • Jouabilité: {m['playability']}")
    
    # Comparaison globale
    print("\n" + "="*80)
    print("🎮 CONCLUSION")
    print("="*80)
    
    tcp_wins = 0
    rquic_wins = 0
    
    for scenario in all_metrics:
        if 'tcp' in all_metrics[scenario] and 'rquic' in all_metrics[scenario]:
            tcp_mos = all_metrics[scenario]['tcp']['mos']
            rquic_mos = all_metrics[scenario]['rquic']['mos']
            
            if tcp_mos > rquic_mos:
                tcp_wins += 1
            elif rquic_mos > tcp_mos:
                rquic_wins += 1
    
    if tcp_wins > rquic_wins:
        print(f"\n✅ TCP gagne sur {tcp_wins} scénarios (meilleur MOS)")
    elif rquic_wins > tcp_wins:
        print(f"\n✅ rQUIC gagne sur {rquic_wins} scénarios (meilleur MOS)")
    else:
        print("\n🤝 Égalité entre TCP et rQUIC")
    
    print("\n💡 Note: rQUIC montre son avantage avec les retransmissions sélectives")
    print("   qui permettent de récupérer les paquets perdus sans head-of-line blocking.")


def main():
    """Point d'entrée principal"""
    
    print("="*80)
    print("ANALYSE DES RÉSULTATS - CLOUD GAMING BENCHMARK")
    print("="*80)
    
    # Charger les résultats
    results = load_results()
    
    if not results:
        print("\n❌ Aucun résultat trouvé!")
        print("Lancez d'abord: sudo python3 gaming_benchmark_v2.py")
        return
    
    # Calculer les métriques
    all_metrics = {}
    
    for scenario in results:
        all_metrics[scenario] = {}
        
        for protocol in results[scenario]:
            data = results[scenario][protocol]
            metrics = calculate_metrics(data['client'], data['server'])
            
            if metrics:
                all_metrics[scenario][protocol] = metrics
    
    # Afficher le résumé
    print_summary(all_metrics)
    
    # Générer les graphiques
    print("\n📊 Génération des graphiques...")
    
    create_comparison_chart(all_metrics)
    create_mos_dashboard(all_metrics)
    create_summary_table(all_metrics)
    
    print(f"\n✅ Analyse terminée!")
    print(f"Fichiers générés dans: {WORK_DIR}")


if __name__ == '__main__':
    main()
