from flask import Flask, request, jsonify, render_template
import requests
from bs4 import BeautifulSoup
import json
import re

app = Flask(__name__)

def get_players_from_url(game_link):
    """Extrahiert Spieler-Nicknames aus VRFrag Link"""
    try:
        response = requests.get(game_link)
        if response.status_code != 200:
            return {"success": False, "error": f"Fehler beim Abrufen: {response.status_code}"}
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Finde das Script mit globalAllMatchesResults
        script_tags = soup.find_all('script')
        target_script = None
        
        for script in script_tags:
            if script.string and 'globalAllMatchesResults' in script.string:
                target_script = script.string
                break
        
        if not target_script:
            return {"success": False, "error": "Keine Spielerdaten gefunden"}
        
        # Extrahiere JSON
        match = re.search(r'const\s+globalAllMatchesResults\s*=\s*(\[.*?\])\s*;', target_script, re.DOTALL)
        if not match:
            return {"success": False, "error": "Konnte Spielerdaten nicht extrahieren"}
        
        match_results_data = match.group(1)
        match_results_data = re.sub(r'//.*?$', '', match_results_data, flags=re.MULTILINE)
        
        match_results = json.loads(match_results_data)
        
        # Flatten die Struktur
        if match_results and isinstance(match_results[0], list):
            flat_matches = []
            for sublist in match_results:
                if isinstance(sublist, list):
                    flat_matches.extend(sublist)
                else:
                    flat_matches.append(sublist)
            match_results = flat_matches
        
        # Sammle Spieler
        players = set()
        for match in match_results:
            if not isinstance(match, dict):
                continue
            
            for player in match.get('playerTeamA', []):
                if isinstance(player, dict) and 'nickname' in player:
                    players.add(player['nickname'])
            
            for player in match.get('playerTeamB', []):
                if isinstance(player, dict) and 'nickname' in player:
                    players.add(player['nickname'])
        
        players_list = sorted(list(players))
        return {"success": True, "players": players_list, "count": len(players_list)}
        
    except Exception as e:
        return {"success": False, "error": f"Fehler: {str(e)}"}

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/get-players', methods=['POST'])
def api_get_players():
    data = request.get_json()
    game_link = data.get('game_link', '')
    
    if not game_link:
        return jsonify({"success": False, "error": "Kein Link angegeben"})
    
    result = get_players_from_url(game_link)
    return jsonify(result)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
