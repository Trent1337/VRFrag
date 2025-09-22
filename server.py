from flask import Flask, request, send_from_directory, jsonify, send_file
import subprocess
import os
import json
from datetime import datetime
from get_players import get_players_from_url  # Import der neuen Funktion

app = Flask(__name__, static_folder='.')

CSV_PATH = os.path.join(os.path.dirname(__file__), 'data.csv')
EVENTS_FOLDER = os.path.join(os.path.dirname(__file__), 'events')

# Stelle sicher, dass der events Ordner existiert
os.makedirs(EVENTS_FOLDER, exist_ok=True)

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
    API-Route zum Abrufen der Spieler von VRFrag
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

@app.route('/api/save-event-file', methods=['POST'])
def api_save_event_file():
    """
    Neue API-Route zum Speichern der Event-Datei im events Ordner
    """
    try:
        data = request.get_json()
        if not data or 'game_link' not in data or 'mappings' not in data:
            return jsonify({
                'success': False,
                'error': 'Ungültige Daten im Request'
            }), 400
        
        game_link = data['game_link']
        mappings = data['mappings']
        custom_filename = data.get('filename', '')
        
        # Dateinamen generieren
        if custom_filename:
            filename = custom_filename
            if not filename.endswith('.txt'):
                filename += '.txt'
        else:
            # Automatischen Dateinamen basierend auf aktuellem Datum generieren
            today = datetime.now().strftime("%Y_%m_%d")
            
            # Prüfen, ob heute schon Dateien existieren
            existing_files = [f for f in os.listdir(EVENTS_FOLDER) 
                            if f.startswith(today) and f.endswith('.txt')]
            
            if existing_files:
                # Nächste Nummer finden
                numbers = []
                for f in existing_files:
                    try:
                        # Dateiname format: YYYY_MM_DD_XX.txt
                        num = int(f.split('_')[-1].split('.')[0])
                        numbers.append(num)
                    except:
                        continue
                next_num = max(numbers) + 1 if numbers else 1
            else:
                next_num = 1
            
            filename = f"{today}_{next_num:02d}.txt"
        
        filepath = os.path.join(EVENTS_FOLDER, filename)
        
        # Event-Datei im gewünschten Format erstellen
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(game_link + '\n')
            for mapping in mappings:
                f.write(f"{mapping['nickname']}={mapping['realName']}\n")
        
        return jsonify({
            'success': True,
            'filename': filename,
            'filepath': filepath,
            'message': f'Event-Datei erfolgreich gespeichert als {filename}'
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Fehler beim Speichern: {str(e)}'
        }), 500

@app.route('/api/list-events', methods=['GET'])
def api_list_events():
    """
    Liste aller vorhandenen Event-Dateien
    """
    try:
        event_files = []
        for filename in os.listdir(EVENTS_FOLDER):
            if filename.endswith('.txt'):
                filepath = os.path.join(EVENTS_FOLDER, filename)
                with open(filepath, 'r', encoding='utf-8') as f:
                    first_line = f.readline().strip()
                    event_files.append({
                        'filename': filename,
                        'game_link': first_line,
                        'size': os.path.getsize(filepath)
                    })
        
        return jsonify({
            'success': True,
            'events': sorted(event_files, key=lambda x: x['filename'], reverse=True)
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Fehler beim Lesen: {str(e)}'
        }), 500

@app.route('/events/<filename>')
def download_event_file(filename):
    """
    Event-Datei herunterladen
    """
    try:
        return send_from_directory(EVENTS_FOLDER, filename, as_attachment=True)
    except FileNotFoundError:
        return jsonify({'success': False, 'error': 'Datei nicht gefunden'}), 404

# Statische Dateien für CSS/JS
@app.route('/<path:path>')
def static_files(path):
    return send_from_directory('.', path)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
