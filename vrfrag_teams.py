import pandas as pd
import numpy as np
import random
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
import warnings
warnings.filterwarnings('ignore')

_MODEL_CACHE = {}

def _filter_by_map(df: pd.DataFrame, map_name: str | None) -> pd.DataFrame:
    if not map_name or "maptitle" not in df.columns:
        return df
    out = df[df["maptitle"].astype(str) == str(map_name)].copy()
    return out if not out.empty else df

def _to_num(s: pd.Series, default: float = 0.0) -> pd.Series:
    return pd.to_numeric(s, errors="coerce").fillna(default)

def calculate_team_win_probability_simple(team_a_players, team_b_players, player_stats_df, map_name=None):
    """
    Einfache Gewinnwahrscheinlichkeit basierend auf Durchschnitts-Scores
    """
    if len(team_a_players) == 0 or len(team_b_players) == 0:
        return 0.5  # 50/50 bei unbekannten Spielern
    
    # Historische Performance der Spieler filtern
    player_stats_df = _filter_by_map(player_stats_df, map_name)
    if "score" not in player_stats_df.columns or "Player" not in player_stats_df.columns:
        return 0.5
    
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

def _train_team_diff_model(player_stats_df: pd.DataFrame, map_name=None):
    """
    Trainiert ein Modell auf Match-level Team-Differenzen:
    Features: (avg_score_A - avg_score_B), (kd_A - kd_B)
    Label: 1 wenn Team A gewinnt, 0 wenn Team B gewinnt
    """
    df = _filter_by_map(player_stats_df, map_name)

    required = {"matchNr", "team", "matchWinner", "score", "kills", "deaths", "EventDate", "EventTimeRange"}
    if not required.issubset(set(df.columns)):
        return None, None

    tmp = df[list(required)].copy()
    tmp["score"] = _to_num(tmp["score"], 0.0)
    tmp["kills"] = _to_num(tmp["kills"], 0.0)
    tmp["deaths"] = _to_num(tmp["deaths"], 0.0)

    tmp = tmp[tmp["matchWinner"].isin(["A", "B"])].copy()
    if tmp.empty:
        return None, None

    tmp["matchKey"] = (
        tmp["matchNr"].astype(str)
        + "|"
        + tmp["EventDate"].astype(str)
        + "|"
        + tmp["EventTimeRange"].astype(str)
    )

    winners = tmp.groupby("matchKey", dropna=True)["matchWinner"].first()

    agg = (
        tmp.groupby(["matchKey", "team"], dropna=True)
        .agg(score_mean=("score", "mean"), kills_sum=("kills", "sum"), deaths_sum=("deaths", "sum"))
        .reset_index()
    )
    if agg.empty:
        return None, None

    agg["kd"] = agg["kills_sum"] / agg["deaths_sum"].replace(0, np.nan)
    agg["kd"] = agg["kd"].fillna(agg["kills_sum"])

    a = agg[agg["team"] == "A"].set_index("matchKey")
    b = agg[agg["team"] == "B"].set_index("matchKey")
    common = a.join(b, how="inner", lsuffix="_A", rsuffix="_B")
    if common.empty:
        return None, None

    y = winners.reindex(common.index)
    mask = y.isin(["A", "B"])
    common = common[mask]
    y = y[mask].map({"A": 1, "B": 0}).astype(int)
    if len(common) < 20:
        return None, None

    X = np.column_stack([
        (common["score_mean_A"] - common["score_mean_B"]).to_numpy(),
        (common["kd_A"] - common["kd_B"]).to_numpy(),
    ])

    scaler = StandardScaler()
    Xs = scaler.fit_transform(X)

    model = LogisticRegression(random_state=42, max_iter=200)
    model.fit(Xs, y.to_numpy())

    return model, scaler

def _get_cached_model(player_stats_df: pd.DataFrame, map_name=None):
    df = _filter_by_map(player_stats_df, map_name)

    # very cheap "signature" to avoid re-training every request
    try:
        max_match = int(_to_num(df.get("matchNr", pd.Series([], dtype=object)), 0).max() or 0)
    except Exception:
        max_match = 0
    event_n = int(df["EventId"].nunique()) if "EventId" in df.columns else 0
    sig = (str(map_name or ""), int(df.shape[0]), max_match, event_n)

    hit = _MODEL_CACHE.get(sig)
    if hit:
        return hit

    model, scaler = _train_team_diff_model(df, map_name=None)  # df already map-filtered
    _MODEL_CACHE[sig] = (model, scaler)
    return model, scaler

def calculate_team_win_probability_advanced(team_a_players, team_b_players, player_stats_df, map_name=None):
    """
    Erweiterte Gewinnwahrscheinlichkeit mit scikit-learn Machine Learning
    """
    try:
        df = _filter_by_map(player_stats_df, map_name)
        if "Player" not in df.columns or "score" not in df.columns:
            return calculate_team_win_probability_simple(team_a_players, team_b_players, player_stats_df, map_name)

        model, scaler = _get_cached_model(df, map_name=None)  # df already map-filtered
        if model is None or scaler is None:
            return calculate_team_win_probability_simple(team_a_players, team_b_players, df, map_name=None)

        team_a_data = df[df["Player"].isin(team_a_players)]
        team_b_data = df[df["Player"].isin(team_b_players)]

        team_a_score = float(_to_num(team_a_data.get("score", pd.Series([], dtype=object)), 0.0).mean() or 0.0)
        team_b_score = float(_to_num(team_b_data.get("score", pd.Series([], dtype=object)), 0.0).mean() or 0.0)

        team_a_kills = float(_to_num(team_a_data.get("kills", pd.Series([], dtype=object)), 0.0).sum() or 0.0)
        team_a_deaths = float(_to_num(team_a_data.get("deaths", pd.Series([], dtype=object)), 0.0).sum() or 0.0)
        team_a_kd = (team_a_kills / team_a_deaths) if team_a_deaths > 0 else team_a_kills

        team_b_kills = float(_to_num(team_b_data.get("kills", pd.Series([], dtype=object)), 0.0).sum() or 0.0)
        team_b_deaths = float(_to_num(team_b_data.get("deaths", pd.Series([], dtype=object)), 0.0).sum() or 0.0)
        team_b_kd = (team_b_kills / team_b_deaths) if team_b_deaths > 0 else team_b_kills

        x = np.array([[team_a_score - team_b_score, team_a_kd - team_b_kd]])
        p = model.predict_proba(scaler.transform(x))[0][1]  # P(team A wins)
        return round(float(p), 3)
            
    except Exception as e:
        print(f"ML Fehler, verwende einfache Berechnung: {e}")
        # Fallback zur einfachen Berechnung
        return calculate_team_win_probability_simple(team_a_players, team_b_players, player_stats_df, map_name)

def generate_fair_teams(player_names, player_stats_df, map_name=None, max_iterations=1000, target_fairness=0.05, use_advanced_probability=True):
    """
    Generiert faire Teams basierend auf historischer Performance
    
    Args:
        player_names: Liste der Spieler-Namen
        player_stats_df: DataFrame mit Spieler-Statistiken
        map_name: Optionaler Map-Name für map-spezifische Statistiken
        max_iterations: Maximale Anzahl an Versuchen
        target_fairness: Ziel-Fairness (0.05 = 5% Unterschied max)
        use_advanced_probability: Verwende ML-basierte Wahrscheinlichkeit
    
    Returns:
        Dictionary mit Team-Zusammenstellung und Wahrscheinlichkeiten
    """
    
    if len(player_names) < 4:
        return {"error": "Mindestens 4 Spieler benötigt"}
    
    if len(player_names) % 2 != 0:
        return {"error": "Gerade Anzahl an Spielern benötigt"}
    
    team_size = len(player_names) // 2
    
    # Historische Daten der Spieler sammeln
    df_use = _filter_by_map(player_stats_df, map_name)
    if "Player" not in df_use.columns or "score" not in df_use.columns:
        return {"error": "Players-CSV hat nicht die erwarteten Spalten (mind. Player, score)."}

    df_use = df_use.copy()
    for c in ["score", "kills", "deaths"]:
        if c in df_use.columns:
            df_use[c] = _to_num(df_use[c], 0.0)

    grouped = (
        df_use.groupby("Player", dropna=True)
        .agg(
            avg_score=("score", "mean"),
            avg_kills=("kills", "mean"),
            avg_deaths=("deaths", "mean"),
            total_games=("score", "size"),
        )
    )
    overall_avg_score = float(df_use["score"].mean() or 0.0)
    overall_avg_kills = float(df_use["kills"].mean() if "kills" in df_use.columns else 0.0)
    overall_avg_deaths = float(df_use["deaths"].mean() if "deaths" in df_use.columns else 0.0)

    player_scores = {}
    player_stats = {}
    used_fallback_for = []

    for player in player_names:
        if player in grouped.index:
            row = grouped.loc[player]
            player_scores[player] = float(row["avg_score"])
            player_stats[player] = {
                "avg_score": float(row["avg_score"]),
                "avg_kills": float(row["avg_kills"]) if "avg_kills" in row else overall_avg_kills,
                "avg_deaths": float(row["avg_deaths"]) if "avg_deaths" in row else overall_avg_deaths,
                "total_games": int(row["total_games"]),
            }
        else:
            used_fallback_for.append(player)
            player_scores[player] = overall_avg_score
            player_stats[player] = {
                "avg_score": overall_avg_score,
                "avg_kills": overall_avg_kills,
                "avg_deaths": overall_avg_deaths,
                "total_games": 0,
            }
    

    top_candidates = []  # Liste von (fairness, team_a, team_b, team_a_score, team_b_score)
    best_fairness = float('inf')
    iterations_used = 0

    TOP_K = 10          # wie viele gute Kandidaten wir sammeln
    EPS = 0.05          # wie nah an best_fairness noch akzeptiert (1.5% vom Gesamtscore)

    
    # Mehrere zufällige Kombinationen testen
    for iteration in range(max_iterations):
        iterations_used = iteration + 1

        shuffled_players = random.sample(player_names, len(player_names))
        team_a = shuffled_players[:team_size]
        team_b = shuffled_players[team_size:]

        team_a_score = sum(player_scores.get(player, 0) for player in team_a)
        team_b_score = sum(player_scores.get(player, 0) for player in team_b)

        total_score = team_a_score + team_b_score
        fairness = abs(team_a_score - team_b_score) / total_score if total_score > 0 else 1.0

        if fairness < best_fairness:
            best_fairness = fairness

        if fairness <= target_fairness or fairness <= (best_fairness + EPS):
            top_candidates.append((fairness, team_a, team_b, team_a_score, team_b_score))
            top_candidates.sort(key=lambda x: x[0])
            top_candidates = top_candidates[:TOP_K]

    
    if not top_candidates:
        return {"error": "Keine gültige Team-Kombination gefunden"}

    # Randomisiert auswählen – aber nur aus sehr guten Kandidaten
    choice = random.choice(top_candidates)
    best_fairness, team_a, team_b, team_a_score, team_b_score = choice
        
    # Detaillierte Team-Statistiken berechnen
    team_a_stats = calculate_team_stats(team_a, player_stats)
    team_b_stats = calculate_team_stats(team_b, player_stats)
    
    # Gewinnwahrscheinlichkeit berechnen
    if use_advanced_probability:
        win_probability = calculate_team_win_probability_advanced(team_a, team_b, df_use, map_name=None)
    else:
        win_probability = calculate_team_win_probability_simple(team_a, team_b, df_use, map_name=None)
    
    return {
        "team_a": {
            "players": team_a,
            "average_score": round(team_a_score / len(team_a), 2),
            "total_score": round(team_a_score, 2),
            "stats": team_a_stats
        },
        "team_b": {
            "players": team_b,
            "average_score": round(team_b_score / len(team_b), 2),
            "total_score": round(team_b_score, 2),
            "stats": team_b_stats
        },
        "win_probability": {
            "team_a": win_probability,
            "team_b": round(1 - win_probability, 3)
        },
        "fairness": round(best_fairness, 3),
        "iterations_used": iterations_used,
        "map_used": map_name if map_name else "Alle Maps",
        "calculation_method": "ML-basiert" if use_advanced_probability else "Einfache Berechnung",
        "used_fallback_for": used_fallback_for,
        "player_avg_scores": {k: round(float(v), 3) for k, v in player_scores.items()}
    }

def calculate_team_stats(team_players, player_stats):
    """
    Berechnet detaillierte Statistiken für ein Team
    """
    total_games = 0
    total_kills = 0
    total_deaths = 0
    
    for player in team_players:
        stats = player_stats.get(player, {})
        total_games += stats.get('total_games', 0)
        g = stats.get("total_games", 0) or 0
        total_kills += stats.get('avg_kills', 0) * g
        total_deaths += stats.get('avg_deaths', 0) * g
    
    avg_kills = total_kills / max(total_games, 1)
    avg_deaths = total_deaths / max(total_games, 1)
    kd_ratio = avg_kills / avg_deaths if avg_deaths > 0 else avg_kills
    
    return {
        "total_games": total_games,
        "avg_kills": round(avg_kills, 2),
        "avg_deaths": round(avg_deaths, 2),
        "kd_ratio": round(kd_ratio, 2)
    }

def get_player_recommendations(player_stats_df, num_players=10):
    """
    Gibt empfohlene Spieler für Team-Generierung zurück
    """
    try:
        # Spieler nach durchschnittlicher Performance sortieren
        player_stats = player_stats_df.groupby('Player').agg({
            'score': ['mean', 'count'],
            'kills': 'mean',
            'deaths': 'mean'
        }).round(2)
        
        player_stats.columns = ['avg_score', 'games_played', 'avg_kills', 'avg_deaths']
        player_stats = player_stats.reset_index()
        
        # KD-Ratio berechnen
        player_stats['kd_ratio'] = (player_stats['avg_kills'] / player_stats['avg_deaths']).round(2)
        
        # Nach Score und Spielanzahl sortieren
        player_stats = player_stats.sort_values(['avg_score', 'games_played'], ascending=[False, False])
        
        return player_stats.head(num_players).to_dict('records')
        
    except Exception as e:
        print(f"Fehler bei Spieler-Empfehlungen: {e}")
        return []

# Hilfsfunktion für die Web-Oberfläche
def get_available_players(player_stats_df):
    """
    Gibt alle verfügbaren Spieler mit Basis-Statistiken zurück
    """
    try:
        players = player_stats_df['Player'].unique()
        players_with_stats = []
        
        for player in players:
            player_data = player_stats_df[player_stats_df['Player'] == player]
            avg_score = player_data['score'].mean()
            games_played = len(player_data)
            avg_kills = player_data['kills'].mean()
            avg_deaths = player_data['deaths'].mean()
            kd_ratio = avg_kills / avg_deaths if avg_deaths > 0 else avg_kills
            
            players_with_stats.append({
                'name': player,
                'avg_score': round(avg_score, 1),
                'games_played': games_played,
                'avg_kills': round(avg_kills, 1),
                'avg_deaths': round(avg_deaths, 1),
                'kd_ratio': round(kd_ratio, 2)
            })
        
        return sorted(players_with_stats, key=lambda x: x['avg_score'], reverse=True)
        
    except Exception as e:
        print(f"Fehler beim Laden der Spieler-Statistiken: {e}")
        return []

if __name__ == '__main__':
    # Test-Funktion für direkte Ausführung
    try:
        FILES_FOLDER = os.path.join(os.path.dirname(__file__), 'files')
        players_file = os.path.join(FILES_FOLDER, 'vrfrag_players.csv')
        
        if os.path.exists(players_file):
            players_df = pd.read_csv(players_file)
            print(f"✅ Spieler-Daten geladen: {len(players_df)} Einträge, {players_df['Player'].nunique()} Spieler")
            
            # Verfügbare Spieler anzeigen
            available_players = get_available_players(players_df)
            print(f"\n🏆 Top 10 Spieler:")
            for i, player in enumerate(available_players[:10], 1):
                print(f"{i:2d}. {player['name']:20} ⭐ {player['avg_score']:5.1f} 📊 {player['games_played']:3d} Spiele")
            
            # Test mit zufälligen Spielern
            if len(available_players) >= 4:
                test_players = [p['name'] for p in available_players[:8]]  # Erste 8 Spieler
                print(f"\n🎯 Teste Team-Generierung mit {len(test_players)} Spielern...")
                
                result = generate_fair_teams(test_players, players_df)
                
                if 'error' not in result:
                    print("\n✅ Team-Generierung erfolgreich!")
                    print(f"⚖️  Fairness: {result['fairness']*100}% Unterschied")
                    print(f"🔄 Iterationen: {result['iterations_used']}")
                    print(f"📊 Methode: {result['calculation_method']}")
                    
                    print(f"\n🏆 Team A ({result['win_probability']['team_a']*100:.1f}% Gewinnchance):")
                    for player in result['team_a']['players']:
                        player_data = next((p for p in available_players if p['name'] == player), {})
                        print(f"   👤 {player} ⭐ {player_data.get('avg_score', 'N/A')}")
                    
                    print(f"\n🏆 Team B ({result['win_probability']['team_b']*100:.1f}% Gewinnchance):")
                    for player in result['team_b']['players']:
                        player_data = next((p for p in available_players if p['name'] == player), {})
                        print(f"   👤 {player} ⭐ {player_data.get('avg_score', 'N/A')}")
                else:
                    print(f"❌ Fehler: {result['error']}")
            else:
                print("❌ Nicht genug Spieler für Test")
        else:
            print("❌ Spieler-Daten nicht gefunden")
            
    except Exception as e:
        print(f"❌ Fehler: {e}")
        import traceback
        traceback.print_exc()
