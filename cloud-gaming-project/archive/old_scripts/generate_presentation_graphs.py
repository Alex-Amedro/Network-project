#!/usr/bin/env python3
"""
GRAPHIQUES DE PRÉSENTATION - QUIC vs TCP
=========================================
Haute résolution pour vidéoprojecteur
"""

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

# Configuration globale pour présentation
plt.rcParams['font.size'] = 14
plt.rcParams['axes.titlesize'] = 18
plt.rcParams['axes.labelsize'] = 16
plt.rcParams['xtick.labelsize'] = 14
plt.rcParams['ytick.labelsize'] = 14
plt.rcParams['figure.facecolor'] = 'white'
plt.rcParams['axes.facecolor'] = 'white'
plt.rcParams['savefig.facecolor'] = 'white'

# Couleurs
TCP_COLOR = '#d62728'   # Rouge
QUIC_COLOR = '#2ca02c'  # Vert


def create_hol_blocking_graph():
    """Graphique 1 : Head-of-Line Blocking"""
    
    fig, ax = plt.subplots(figsize=(10, 7))
    
    # Données
    protocols = ['TCP', 'QUIC']
    jitter = [60, 1.3]
    colors = [TCP_COLOR, QUIC_COLOR]
    
    # Barres
    bars = ax.bar(protocols, jitter, color=colors, width=0.5, edgecolor='black', linewidth=1.5)
    
    # Annotations au-dessus des barres
    ax.annotate('Lag Critique\n(HoL Blocking)', 
                xy=(0, 60), xytext=(0, 70),
                ha='center', va='bottom',
                fontsize=14, fontweight='bold', color=TCP_COLOR,
                bbox=dict(boxstyle='round,pad=0.3', facecolor='#ffcccc', edgecolor=TCP_COLOR))
    
    ax.annotate('Stable\n(40x mieux)', 
                xy=(1, 1.3), xytext=(1, 15),
                ha='center', va='bottom',
                fontsize=14, fontweight='bold', color=QUIC_COLOR,
                arrowprops=dict(arrowstyle='->', color=QUIC_COLOR, lw=2),
                bbox=dict(boxstyle='round,pad=0.3', facecolor='#ccffcc', edgecolor=QUIC_COLOR))
    
    # Valeurs sur les barres
    ax.text(0, 60/2, '60 ms', ha='center', va='center', fontsize=16, fontweight='bold', color='white')
    ax.text(1, 1.3 + 3, '1.3 ms', ha='center', va='bottom', fontsize=16, fontweight='bold', color=QUIC_COLOR)
    
    # Labels et titre
    ax.set_ylabel('Jitter (ms)', fontsize=16, fontweight='bold')
    ax.set_title('Impact des Pertes (5%) sur la Fluidité', fontsize=20, fontweight='bold', pad=20)
    
    # Limites et style
    ax.set_ylim(0, 90)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.spines['left'].set_linewidth(1.5)
    ax.spines['bottom'].set_linewidth(1.5)
    
    # Grille légère
    ax.yaxis.grid(True, linestyle='--', alpha=0.3)
    ax.set_axisbelow(True)
    
    plt.tight_layout()
    plt.savefig('final_hol_graph.png', dpi=300, bbox_inches='tight')
    plt.close()
    
    print("✅ Sauvegardé: final_hol_graph.png")


def create_connection_time_graph():
    """Graphique 2 : Temps de Connexion"""
    
    fig, ax = plt.subplots(figsize=(10, 7))
    
    # Données
    protocols = ['TCP+TLS', 'QUIC']
    times = [1043, 649]
    colors = [TCP_COLOR, QUIC_COLOR]
    
    # Barres
    bars = ax.bar(protocols, times, color=colors, width=0.5, edgecolor='black', linewidth=1.5)
    
    # Valeurs sur les barres
    ax.text(0, 1043/2, '1043 ms', ha='center', va='center', fontsize=16, fontweight='bold', color='white')
    ax.text(1, 649/2, '649 ms', ha='center', va='center', fontsize=16, fontweight='bold', color='white')
    
    # Flèche et annotation du gain
    ax.annotate('', 
                xy=(1, 1043), xytext=(0, 1043),
                arrowprops=dict(arrowstyle='<->', color='#333333', lw=3))
    
    ax.annotate('-40%\nLatence au\ndémarrage', 
                xy=(0.5, 1043), xytext=(0.5, 1150),
                ha='center', va='bottom',
                fontsize=15, fontweight='bold', color='#333333',
                bbox=dict(boxstyle='round,pad=0.4', facecolor='#ffffcc', edgecolor='#333333', linewidth=2))
    
    # Labels et titre
    ax.set_ylabel('Temps (ms)', fontsize=16, fontweight='bold')
    ax.set_title('Vitesse de Lancement du Jeu (RTT 200ms)', fontsize=20, fontweight='bold', pad=20)
    
    # Limites et style
    ax.set_ylim(0, 1300)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.spines['left'].set_linewidth(1.5)
    ax.spines['bottom'].set_linewidth(1.5)
    
    # Grille légère
    ax.yaxis.grid(True, linestyle='--', alpha=0.3)
    ax.set_axisbelow(True)
    
    plt.tight_layout()
    plt.savefig('final_conn_graph.png', dpi=300, bbox_inches='tight')
    plt.close()
    
    print("✅ Sauvegardé: final_conn_graph.png")


if __name__ == "__main__":
    print("Génération des graphiques de présentation...\n")
    
    create_hol_blocking_graph()
    create_connection_time_graph()
    
    print("\n✅ Tous les graphiques générés!")
    print("   - final_hol_graph.png")
    print("   - final_conn_graph.png")
