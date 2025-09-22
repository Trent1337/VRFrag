from flask import Flask, request, send_from_directory, jsonify
import subprocess
import os
from get_players import get_players_from_url  # Import der neuen Funktion

app = Flask(__name__, static_folder='.')

CSV_PATH = os.path.join(os.path.dirname(__file__), 'data.csv')

@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

@app.route('/run', methods=['POST'])
def run_script():
    players = [request.form.get(f'player{i}') for i in range(1, 11)]
    result = subprocess.run(
        ['python3', 'run_script.py', CSV_PATH] + players,
        capture_output=True, text=True
    )
    return result.stdout or "Script ausgeführt"

@app.route('/api/get-players', methods=['POST'])
def api_get_players():
    """
    Neue API-Route zum Abrufen der Spieler von VRFrag
    """
    try:
        data = request.get_json()
        if not data or 'game_link' not in data:
            return jsonify({
                'success': False,
                'error': 'Kein game_link im Request'
            }), 400
        
        game_link = data['game_link']
        
        if not game_link.startswith('https://www.vrfrag.com/stats?'):
            return jsonify({
                'success': False,
                'error': 'Ungültiger VRFrag Link'
            }), 400
        
        players = get_players_from_url(game_link)
        
        if players is not None:
            return jsonify({
                'success': True,
                'players': players,
                'count': len(players)
            })
        else:
            return jsonify({
                'success': False,
                'error': 'Konnte Spielerdaten nicht abrufen'
            }), 500
            
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Server Fehler: {str(e)}'
        }), 500

# Statische Dateien für CSS/JS
@app.route('/<path:path>')
def static_files(path):
    return send_from_directory('.', path)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
