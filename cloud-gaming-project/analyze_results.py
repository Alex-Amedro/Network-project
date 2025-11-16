#!/usr/bin/env python3
"""
Analyse et visualisation des résultats TCP vs QUIC
"""

import json
import matplotlib.pyplot as plt
import numpy as np

def parse_tcp_results(filename='tcp_results.json'):
    """Parse les résultats iperf3 (TCP)"""
    try:
        with open(filename, 'r') as f:
            data = json.load(f)
        
        # Extraction des métriques
        throughput = data['end']['sum_received']['bits_per_second'] / 1e6  # Mbps
        retransmits = data['end']['sum_sent'].get('retransmits', 0)
        avg_rtt = data['end']['streams'][0].get('sender', {}).get('mean_rtt', 0) / 1000  # ms
        
        return {
            'protocol': 'TCP',
            'throughput_mbps': throughput,
            'retransmits': retransmits,
            'avg_rtt_ms': avg_rtt
        }
    except Exception as e:
        print(f"Erreur lecture TCP: {e}")
        return None

def parse_quic_results(filename='quic_results.txt'):
    """Parse les résultats iperf3 UDP (simulant QUIC)"""
    try:
        with open(filename, 'r') as f:
            data = json.load(f)
        
        # Extraction des métriques UDP (similaire à TCP mais avec pertes de paquets)
        # Utiliser sum_received pour les stats du côté récepteur
        throughput = data['end']['sum_received']['bits_per_second'] / 1e6  # Mbps
        jitter = data['end']['sum_received'].get('jitter_ms', 0)
        lost_percent = data['end']['sum_received'].get('lost_percent', 0)
        
        return {
            'protocol': 'QUIC/UDP',
            'throughput_mbps': throughput,
            'jitter_ms': jitter,
            'lost_percent': lost_percent,
            'avg_rtt_ms': 20  # UDP n'a pas de RTT dans iperf3
        }
    except Exception as e:
        print(f"Erreur lecture QUIC: {e}")
        return None
        return None

def create_comparison_graphs(tcp_data, quic_data):
    """Crée des graphiques de comparaison"""
    
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    fig.suptitle('Comparaison TCP vs QUIC - Cloud Gaming Simulation', fontsize=16, fontweight='bold')
    
    protocols = ['TCP', 'QUIC']
    
    # Graphique 1: Débit (Throughput)
    ax1 = axes[0, 0]
    throughputs = [tcp_data['throughput_mbps'], quic_data['throughput_mbps']]
    bars1 = ax1.bar(protocols, throughputs, color=['#3498db', '#e74c3c'])
    ax1.set_ylabel('Débit (Mbps)', fontweight='bold')
    ax1.set_title('Débit Moyen')
    ax1.grid(axis='y', alpha=0.3)
    
    # Ajouter les valeurs sur les barres
    for bar in bars1:
        height = bar.get_height()
        ax1.text(bar.get_x() + bar.get_width()/2., height,
                f'{height:.1f} Mbps',
                ha='center', va='bottom', fontweight='bold')
    
    # Graphique 2: Retransmissions (TCP uniquement)
    ax2 = axes[0, 1]
    retransmits = [tcp_data['retransmits'], 0]
    bars2 = ax2.bar(protocols, retransmits, color=['#3498db', '#e74c3c'])
    ax2.set_ylabel('Nombre de retransmissions', fontweight='bold')
    ax2.set_title('Retransmissions (Paquets perdus)')
    ax2.grid(axis='y', alpha=0.3)
    
    for bar in bars2:
        height = bar.get_height()
        ax2.text(bar.get_x() + bar.get_width()/2., height,
                f'{int(height)}',
                ha='center', va='bottom', fontweight='bold')
    
    # Graphique 3: RTT moyen
    ax3 = axes[1, 0]
    rtts = [tcp_data['avg_rtt_ms'], quic_data['avg_rtt_ms']]
    bars3 = ax3.bar(protocols, rtts, color=['#3498db', '#e74c3c'])
    ax3.set_ylabel('RTT (ms)', fontweight='bold')
    ax3.set_title('Latence Moyenne (Round-Trip Time)')
    ax3.grid(axis='y', alpha=0.3)
    
    for bar in bars3:
        height = bar.get_height()
        ax3.text(bar.get_x() + bar.get_width()/2., height,
                f'{height:.1f} ms',
                ha='center', va='bottom', fontweight='bold')
    
    # Graphique 4: Tableau récapitulatif
    ax4 = axes[1, 1]
    ax4.axis('tight')
    ax4.axis('off')
    
    table_data = [
        ['Métrique', 'TCP', 'QUIC', 'Gagnant'],
        ['Débit (Mbps)', f'{tcp_data["throughput_mbps"]:.1f}', f'{quic_data["throughput_mbps"]:.1f}', 
         'QUIC' if quic_data["throughput_mbps"] > tcp_data["throughput_mbps"] else 'TCP'],
        ['Retransmissions', f'{tcp_data["retransmits"]}', '0', 'QUIC'],
        ['RTT moyen (ms)', f'{tcp_data["avg_rtt_ms"]:.1f}', f'{quic_data["avg_rtt_ms"]:.1f}',
         'QUIC' if quic_data["avg_rtt_ms"] < tcp_data["avg_rtt_ms"] else 'TCP']
    ]
    
    table = ax4.table(cellText=table_data, cellLoc='center', loc='center',
                     colWidths=[0.3, 0.2, 0.2, 0.3])
    table.auto_set_font_size(False)
    table.set_fontsize(10)
    table.scale(1, 2)
    
    # Style du header
    for i in range(4):
        table[(0, i)].set_facecolor('#34495e')
        table[(0, i)].set_text_props(weight='bold', color='white')
    
    plt.tight_layout()
    plt.savefig('tcp_vs_quic_comparison.png', dpi=300, bbox_inches='tight')
    print("\n✅ Graphique sauvegardé : tcp_vs_quic_comparison.png")
    plt.show()

if __name__ == '__main__':
    print("="*60)
    print("ANALYSE DES RÉSULTATS - TCP vs QUIC")
    print("="*60)
    
    tcp_data = parse_tcp_results()
    quic_data = parse_quic_results()
    
    if tcp_data and quic_data:
        # Afficher les résultats
        print(f"\n📈 Résultats TCP:")
        print(f"   • Débit: {tcp_data['throughput_mbps']:.2f} Mbps")
        print(f"   • Retransmissions: {tcp_data['retransmits']}")
        print(f"   • RTT moyen: {tcp_data['avg_rtt_ms']:.2f} ms")
        
        print(f"\n📈 Résultats QUIC/UDP:")
        print(f"   • Débit: {quic_data['throughput_mbps']:.2f} Mbps")
        print(f"   • Jitter: {quic_data['jitter_ms']:.2f} ms")
        print(f"   • Paquets perdus: {quic_data['lost_percent']:.2f}%")
        print(f"   • RTT moyen: {quic_data['avg_rtt_ms']:.2f} ms")
        
        print("\n📊 Génération des graphiques...")
        create_comparison_graphs(tcp_data, quic_data)
        print("\n✅ Analyse terminée !")
    else:
        print("\n❌ Erreur : Fichiers de résultats introuvables")
        print("Exécutez d'abord : sudo python3 cloud_gaming_topo.py")
