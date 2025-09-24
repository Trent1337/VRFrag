import pandas as pd
import numpy as np
import random
import os

def calculate_team_win_probability(team_a_players, team_b_players, player_stats_df, map_name=None):
    """
    Berechnet die Gewinnwahrscheinlichkeit zwischen zwei Teams basierend auf historischen Daten
    """
    if len(team_a_players) == 0 or len(team_b_players) == 0:
        return 0.5  # 50/50 bei unbekannten Spielern
    
    # Historische Performance der Spieler filtern
    if map_name:
        map_stats = player_stats_df[player_stats_df['maptitle'] == map_name]
        if len(map_stats) > 0:
            player_stats_df = map_stats
    
    # Durchschnittliche Scores berechnen
    team_a_avg_score = player_stats_df[player_stats_df['Player'].isin(team_a_players)]['score'].mean()
    team_b_avg_score = player_stats_df[player_stats_df['Player'].isin(team_b_players)]['score'].mean()
    
    # Falls keine Daten vorhanden, verwende Fallback
    if pd.isna(team_a_avg_score):
        team_a_avg_score = player_stats_df['score'].mean()
    if pd.isna(team_b_avg_score):
        team_b_avg_score = player_stats_df['score'].mean()
    
    # Einfache Wahrscheinlichkeitsberechnung basierend auf Score-Verhältnis
    total_score = team_a_avg_score + team_b_avg_score
    if total_score > 0:
        team_a_win_prob = team_a_avg_score / total_score
    else:
        team_a_win_prob = 0.5
    
    return round(team_a_win_prob, 3)

def generate_fair_teams(player_names, player_stats_df, map_name=None, max_iterations=1000, target_fairness=0.05):
    """
    Generiert faire Teams basierend auf historischer Performance
    """
    if len(player_names) < 4:
        return {"error": "Mindestens 4 Spieler benötigt"}
    
    if len(player_names) % 2 != 0:
        return {"error": "Gerade Anzahl an Spielern benötigt"}
    
    team_size = len(player_names) // 2
    
    # Historische Daten der Spieler sammeln
    player_scores = {}
    for player in player_names:
        player_data = player_stats_df[player_stats_df['Player'] == player]
        if len(player_data) > 0:
            if map_name:
                map_data = player_data[player_data['maptitle'] == map_name]
                if len(map_data) > 0:
                    player_scores[player] = map_data['score'].mean()
                else:
                    player_scores[player] = player_data['score'].mean()
            else:
                player_scores[player] = player_data['score'].mean()
        else:
            # Fallback für unbekannte Spieler
            player_scores[player] = player_stats_df['score'].mean()
    
    best_teams = None
    best_fairness = float('inf')
    
    # Mehrere zufällige Kombinationen testen
    for iteration in range(max_iterations):
        # Spieler zufällig mischen
        shuffled_players = random.sample(player_names, len(player_names))
        team_a = shuffled_players[:team_size]
        team_b = shuffled_players[team_size:]
        
        # Team-Scores berechnen
        team_a_score = sum(player_scores.get(player, 0) for player in team_a)
        team_b_score = sum(player_scores.get(player, 0) for player in team_b)
        
        # Fairness berechnen (prozentualer Unterschied)
        total_score = team_a_score + team_b_score
        if total_score > 0:
            fairness = abs(team_a_score - team_b_score) / total_score
        else:
            fairness = 1.0
        
        # Bessere Kombination gefunden?
        if fairness < best_fairness:
            best_fairness = fairness
            best_teams = (team_a, team_b, team_a_score, team_b_score)
            
            # Frühzeitig beenden wenn ausreichend fair
            if fairness <= target_fairness:
                break
    
    if best_teams is None:
        return {"error": "Keine gültige Team-Kombination gefunden"}
    
    team_a, team_b, team_a_score, team_b_score = best_teams
    
    # Gewinnwahrscheinlichkeit berechnen
    win_probability = calculate_team_win_probability(team_a, team_b, player_stats_df, map_name)
    
    return {
        "team_a": {
            "players": team_a,
            "average_score": round(team_a_score / len(team_a), 2),
            "total_score": round(team_a_score, 2)
        },
        "team_b": {
            "players": team_b,
            "average_score": round(team_b_score / len(team_b), 2),
            "total_score": round(team_b_score, 2)
        },
        "win_probability": {
            "team_a": win_probability,
            "team_b": round(1 - win_probability, 3)
        },
        "fairness": round(best_fairness, 3),
        "map_used": map_name if map_name else "Alle Maps"
    }

if __name__ == '__main__':
    # Test-Funktion für direkte Ausführung
    try:
        FILES_FOLDER = os.path.join(os.path.dirname(__file__), 'files')
        players_file = os.path.join(FILES_FOLDER, 'vrfrag_players.csv')
        
        if os.path.exists(players_file):
            players_df = pd.read_csv(players_file)
            print(f"✅ Spieler-Daten geladen: {len(players_df)} Einträge")
            
            # Beispiel-Test
            test_players = players_df['Player'].unique()[:8]  # Erste 8 Spieler
            if len(test_players) >= 4:
                result = generate_fair_teams(list(test_players), players_df)
                print("Test-Ergebnis:", result)
            else:
                print("❌ Nicht genug Spieler für Test")
        else:
            print("❌ Spieler-Daten nicht gefunden")
    except Exception as e:
        print(f"❌ Fehler: {e}")
