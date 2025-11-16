# Cloud Gaming Network Performance Benchmark

## Description

Ce projet compare les performances de **TCP** et **QUIC** pour le streaming de jeu vidéo dans le cloud (Cloud Gaming) sous différentes conditions réseau.

Le benchmark simule un flux vidéo de 60 FPS avec des frames de taille variable (I-frames et P-frames) et mesure les performances dans 3 scénarios réseau différents.

**Note**: QUIC est un protocole de transport moderne basé sur UDP mais offrant la fiabilité de TCP avec de meilleures performances (réduction de latence, multiplexage sans blocage de tête de ligne).

## Architecture

```
Client (Générateur vidéo) <---> Switch <---> Serveur (Récepteur)
                            Conditions réseau variables
```

## Scénarios Testés

| Scénario | Description | Perte | Délai | Bande passante |
|----------|-------------|-------|-------|----------------|
| **Bon** | Connexion fibre optimale | 1% | 10ms | 100 Mbps |
| **Moyen** | WiFi standard avec interférences | 3% | 25ms | 50 Mbps |
| **Mauvais** | 4G avec connexion instable | 8% | 60ms | 20 Mbps |

## Métriques Mesurées

### 1. Frame Delivery Rate (%)
Pourcentage de frames vidéo reçues par rapport aux frames envoyées.

### 2. FPS Reçus
Nombre de frames par seconde effectivement reçues par le serveur.

### 3. Latence Moyenne (ms)
Délai moyen entre la réception de deux frames consécutives.

### 4. Jitter (ms)
Variation de la latence inter-frame (stabilité du flux).

### 5. Débit (Mbps)
Bande passante effective utilisée.

## Fichiers du Projet

- `gaming_benchmark.py` : Script principal pour lancer les benchmarks
- `video_traffic_gen.py` : Générateur de trafic vidéo (client)
- `video_server.py` : Serveur de réception vidéo
- `analyze_gaming_results.py` : Analyse et visualisation des résultats
- `cloud_gaming_topo.py` : Ancien script (iperf3)
- `analyze_results.py` : Ancien script d'analyse

## Installation

### Prérequis

```bash
# Installer Mininet
sudo apt-get install mininet

# Installer Python et les dépendances
sudo apt-get install python3 python3-pip
pip3 install matplotlib numpy
```

## Utilisation

### 1. Lancer les Benchmarks

```bash
sudo python3 gaming_benchmark.py
```

Le script va :
- Tester les 3 scénarios réseau (Bon, Moyen, Mauvais)
- Pour chaque scénario, tester TCP et QUIC
- Chaque test dure 30 secondes
- **Durée totale** : ~5 minutes

### 2. Analyser les Résultats

```bash
python3 analyze_gaming_results.py
```

Cela génère :
- 3 graphiques de comparaison (un par scénario)
- 1 tableau récapitulatif global
- Un résumé textuel dans le terminal

## Résultats Attendus

### Réseau Bon (Fibre)
- **TCP** et **QUIC** devraient tous deux bien performer
- Frame Delivery Rate > 95%
- FPS proche de 60

### Réseau Moyen (WiFi)
- **QUIC** devrait commencer à montrer des avantages
- TCP pourrait avoir plus de retransmissions
- FPS entre 50-60

### Réseau Mauvais (4G)
- **TCP** souffrira significativement des pertes
- **QUIC** maintiendra un meilleur débit grâce à l'absence de Head-of-Line Blocking
- Différence marquée entre les deux protocoles

## Interprétation des Résultats

### TCP (Transmission Control Protocol)
- ✅ **Fiable** : Garantit la livraison de toutes les données
- ✅ **Ordre garanti** : Les frames arrivent dans l'ordre
- ❌ **Sensible aux pertes** : Les retransmissions ralentissent le flux
- ❌ **Head-of-Line Blocking** : Une frame perdue bloque les suivantes

### QUIC (Quick UDP Internet Connections)
- ✅ **Fiable** : Garantit la livraison comme TCP
- ✅ **Faible latence** : Basé sur UDP, pas d'attente inutile
- ✅ **Pas de Head-of-Line Blocking** : Les streams sont indépendants
- ✅ **Multiplexage** : Plusieurs flux simultanés sans blocage
- ✅ **0-RTT** : Connexions plus rapides
- Combine les avantages de TCP (fiabilité) et UDP (performance)

### Comparaison

Dans ce benchmark, QUIC devrait montrer :
- Une fiabilité similaire à TCP
- De meilleures performances sous conditions réseau dégradées
- Moins de latence grâce à l'absence de Head-of-Line Blocking
- Un meilleur multiplexage de streams

## Structure des Fichiers de Résultats

### Fichiers générés pendant les tests

```
results_<scenario>_<protocol>_client.json  # Données client (envoi)
results_<scenario>_<protocol>_server.json  # Données serveur (réception)
```

### Graphiques générés

```
gaming_comparison_bon.png       # Comparaison TCP vs QUIC (Réseau Bon)
gaming_comparison_moyen.png     # Comparaison TCP vs QUIC (Réseau Moyen)
gaming_comparison_mauvais.png   # Comparaison TCP vs QUIC (Réseau Mauvais)
gaming_summary_table.png        # Tableau récapitulatif
```

## Nettoyage

Pour supprimer tous les fichiers de résultats :

```bash
rm -f results_*.json video_*.log gaming_*.png
```

## Troubleshooting

### Erreur "controller not found"
✅ Déjà corrigé - le script n'utilise plus de contrôleur OpenFlow

### Pas de résultats générés
Vérifiez que les tests se sont bien exécutés :
```bash
ls -la results_*.json
```

### Graphiques non générés
Vérifiez que matplotlib est installé :
```bash
pip3 install matplotlib numpy
```

## Améliorations Possibles

1. **Durée des tests ajustable** : Modifier `test_duration` dans `gaming_benchmark.py`
2. **Autres résolutions** : Modifier `fps` et `avg_frame_size_kb` dans `video_traffic_gen.py`
3. **Plus de scénarios** : Ajouter des entrées dans le dictionnaire `SCENARIOS`
4. **Vraie implémentation QUIC** : Utiliser msquic pour une comparaison réelle

## Auteurs

Projet réalisé dans le cadre d'un cours de réseaux - NCKU Exchange Program

## Licence

MIT License - Libre d'utilisation pour des fins éducatives
