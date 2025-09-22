from flask import Flask, request, send_from_directory, jsonify
import subprocess
import os
import requests
import base64
from datetime import datetime
from get_players import get_players_from_url

app = Flask(__name__, static_folder='.')

CSV_PATH = os.path.join(os.path.dirname(__file__), 'data.csv')

def save_to_github(filename, content):
    """
    Speichert eine Datei direkt im GitHub Repo über die API
    """
    token = os.environ.get('GITHUB_TOKEN')
    if not token:
        return {"success": False, "error": "GITHUB_TOKEN nicht konfiguriert"}
    
    repo_owner = "Trent1337"
    repo_name = "VRFrag"
    branch = "main"
    
    # Datei encoden
    content_base64 = base64.b64encode(content.encode('utf-8')).decode('utf-8')
    
    headers = {
        'Authorization': f'token {token}',
        'Accept': 'application/vnd.github.v3+json'
    }
    
    # GitHub API URL
    url = f"https://api.github.com/repos/{repo_owner}/{repo_name}/contents/events/{filename}"
    
    # Prüfen ob Datei bereits existiert (für SHA)
    existing_sha = None
    try:
        response = requests.get(url, headers=headers, params={"ref": branch})
        if response.status_code == 200:
            existing_sha = response.json().get("sha")
    except:
        pass  # Datei existiert nicht
    
    data = {
        "message": f"Add event file: {filename}",
        "content": content_base64,
        "branch": branch
    }
    
    if existing_sha:
        data["sha"] = existing_sha  # Für Updates benötigt
    
    try:
        response = requests.put(url, headers=headers, json=data)
        response_data = response.json()
        
        if response.status_code in [200, 201]:
            return {
                "success": True,
                "filename": filename,
                "html_url": response_data.get("content", {}).get("html_url", ""),
                "message": "Datei erfolgreich zu GitHub gepusht"
            }
        else:
            return {
                "success": False,
                "error": f"GitHub API Fehler: {response.status_code} - {response_data.get('message', 'Unbekannter Fehler')}"
            }
            
    except Exception as e:
        return {"success": False, "error": f"Verbindungsfehler: {str(e)}"}

def generate_filename(custom_name=None):
    """
    Generiert einen Dateinamen im Format YYYY_MM_DD_NN.txt
    """
    if custom_name:
        return custom_name if custom_name.endswith('.txt') else custom_name + '.txt'
    
    today = datetime.now().strftime("%Y_%m_%d")
    
    # Versuche nächste Nummer zu finden (optional - kann übersprungen werden)
    try:
        token = os.environ.get('GITHUB_TOKEN')
        if token:
            headers = {'Authorization': f'token {token}'}
            url = f"https://api.github.com/repos/Trent1337/VRFrag/contents/events"
            response = requests.get(url, headers=headers)
            
            if response.status_code == 200:
                files = response.json()
                today_files = [f for f in files if f['name'].startswith(today)]
                next_num = len(today_files) + 1
            else:
                next_num = 1
        else:
            next_num = 1
    except:
        next_num = 1
    
    return f"{today}_{next_num:02d}.txt"

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
    """Spieler von VRFrag abrufen"""
    try:
        data = request.get_json()
        if not data or 'game_link' not in data:
            return jsonify({'success': False, 'error': 'Kein game_link'}), 400
        
        game_link = data['game_link']
        
        if not game_link.startswith('https://www.vrfrag.com/stats?'):
            return jsonify({'success': False, 'error': 'Ungültiger Link'}), 400
        
        players = get_players_from_url(game_link)
        
        if players is not None:
            return jsonify({'success': True, 'players': players, 'count': len(players)})
        else:
            return jsonify({'success': False, 'error': 'Konnte Spielerdaten nicht abrufen'}), 500
            
    except Exception as e:
        return jsonify({'success': False, 'error': f'Server Fehler: {str(e)}'}), 500

@app.route('/api/save-to-github', methods=['POST'])
def api_save_to_github():
    """
    Speichert Event-Datei direkt in GitHub Repo
    """
    try:
        data = request.get_json()
        if not data or 'game_link' not in data or 'mappings' not in data:
            return jsonify({'success': False, 'error': 'Ungültige Daten'}), 400
        
        game_link = data['game_link']
        mappings = data['mappings']
        custom_filename = data.get('filename', '')
        
        # Dateiinhalt generieren
        content = game_link + '\n'
        for mapping in mappings:
            content += f"{mapping['nickname']}={mapping['realName']}\n"
        
        # Dateinamen generieren
        filename = generate_filename(custom_filename)
        
        # Zu GitHub pushen
        result = save_to_github(filename, content)
        
        return jsonify(result)
        
    except Exception as e:
        return jsonify({'success': False, 'error': f'Fehler: {str(e)}'}), 500

@app.route('/api/list-events', methods=['GET'])
def api_list_events():
    """
    Liste aller Event-Dateien von GitHub
    """
    try:
        token = os.environ.get('GITHUB_TOKEN')
        headers = {'Accept': 'application/vnd.github.v3+json'}
        
        if token:
            headers['Authorization'] = f'token {token}'
        
        url = "https://api.github.com/repos/Trent1337/VRFrag/contents/events"
        response = requests.get(url, headers=headers)
        
        if response.status_code == 200:
            files = response.json()
            event_files = []
            
            for file in files:
                if file['name'].endswith('.txt'):
                    event_files.append({
                        'filename': file['name'],
                        'download_url': file['download_url'],
                        'html_url': file['html_url'],
                        'size': file['size']
                    })
            
            return jsonify({
                'success': True,
                'events': sorted(event_files, key=lambda x: x['filename'], reverse=True)
            })
        else:
            return jsonify({
                'success': False,
                'error': f'GitHub Fehler: {response.status_code}'
            }), 500
            
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# Statische Dateien
@app.route('/<path:path>')
def static_files(path):
    return send_from_directory('.', path)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
