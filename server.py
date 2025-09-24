from flask import Flask, request, send_from_directory, jsonify, render_template
import subprocess
import os
import requests
import base64
from datetime import datetime
from get_players import get_players_from_url
from player_stats import generate_statistics

app = Flask(__name__)

CSV_PATH = os.path.join(os.path.dirname(__file__), 'data.csv')
FILES_FOLDER = os.path.join(os.path.dirname(__file__), 'files')

# Stelle sicher, dass der files Ordner existiert
os.makedirs(FILES_FOLDER, exist_ok=True)

# ... deine bestehenden Funktionen (save_to_github, generate_filename, etc.) ...

@app.route('/')
def index():
    return render_template('index.html')

# ... deine bestehenden Routes (/run, /api/get-players, etc.) ...

@app.route('/api/generate-teams', methods=['POST'])
def api_generate_teams():
    """
    Neue API-Route für Team-Generator
    """
    try:
        data = request.get_json()
        if not data or 'players' not in data:
            return jsonify({'success': False, 'error': 'Keine Spieler-Daten'}), 400
        
        selected_players = data['players']
        selected_map = data.get('map', None)
        
        # Lade Spieler-Daten
        players_file = os.path.join(FILES_FOLDER, 'vrfrag_players.csv')
        if not os.path.exists(players_file):
            return jsonify({'success': False, 'error': 'Spieler-Daten nicht gefunden. Bitte zuerst Statistiken generieren.'}), 400
        
        players_df = pd.read_csv(players_file)
        
        # Team-Generator Funktion importieren
        from vrfrag_teams import generate_fair_teams
        result = generate_fair_teams(selected_players, players_df, selected_map)
        
        if 'error' in result:
            return jsonify({'success': False, 'error': result['error']}), 400
        
        return jsonify({
            'success': True,
            'teams': result
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': f'Team-Generator Fehler: {str(e)}'}), 500

@app.route('/api/get-all-players', methods=['GET'])
def api_get_all_players():
    """
    Gibt alle verfügbaren Spieler aus der Datenbank zurück
    """
    try:
        players_file = os.path.join(FILES_FOLDER, 'vrfrag_players.csv')
        if not os.path.exists(players_file):
            return jsonify({'success': False, 'error': 'Spieler-Daten nicht gefunden'}), 400
        
        players_df = pd.read_csv(players_file)
        all_players = sorted(players_df['Player'].unique())
        
        # Zusätzliche Statistiken für jeden Spieler
        players_with_stats = []
        for player in all_players:
            player_data = players_df[players_df['Player'] == player]
            avg_score = player_data['score'].mean()
            games_played = len(player_data)
            players_with_stats.append({
                'name': player,
                'avg_score': round(avg_score, 1),
                'games_played': games_played
            })
        
        return jsonify({
            'success': True,
            'players': players_with_stats,
            'total_players': len(all_players)
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/get-available-maps', methods=['GET'])
def api_get_available_maps():
    """
    Gibt alle verfügbaren Maps aus der Datenbank zurück
    """
    try:
        players_file = os.path.join(FILES_FOLDER, 'vrfrag_players.csv')
        if not os.path.exists(players_file):
            return jsonify({'success': False, 'error': 'Spieler-Daten nicht gefunden'}), 400
        
        players_df = pd.read_csv(players_file)
        maps = sorted(players_df['maptitle'].dropna().unique())
        
        return jsonify({
            'success': True,
            'maps': maps,
            'total_maps': len(maps)
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/teams')
def teams_page():
    """
    Team-Generator Webseite
    """
    return render_template('teams.html')

# ... deine bestehenden Routes bleiben unverändert ...

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
