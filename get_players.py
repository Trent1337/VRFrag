#!/usr/bin/env python3
import cgi
import cgitb
import json
import sys
import os
from bs4 import BeautifulSoup
import requests
import re

# Fehler anzeigen für Debugging
cgitb.enable()

print("Content-Type: application/json\n")

def get_players_from_url(game_link):
    """
    Extrahiert alle Spieler-Nicknames aus einem VRFrag Spiel-Link
    """
    try:
        response = requests.get(game_link)
        if response.status_code != 200:
            return {"success": False, "error": f"Fehler beim Abrufen der Seite: {response.status_code}"}
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Finde das Script mit globalAllMatchesResults
        script_tags = soup.find_all('script')
        target_script = None
        
        for script in script_tags:
            if script.string and 'globalAllMatchesResults' in script.string:
                target_script = script.string
                break
        
        if not target_script:
            return {"success": False, "error": "Keine Spielerdaten auf der Seite gefunden"}
        
        # Extrahiere das JSON
        match = re.search(r'const\s+globalAllMatchesResults\s*=\s*(\[.*?\])\s*;', target_script, re.DOTALL)
        if not match:
            return {"success": False, "error": "Konnte Spielerdaten nicht extrahieren"}
        
        match_results_data = match.group(1)
        match_results_data = re.sub(r'//.*?$', '', match_results_data, flags=re.MULTILINE)
        
        match_results = json.loads(match_results_data)
        
        # Flatten die Datenstruktur falls nötig
        if match_results and isinstance(match_results[0], list):
            flat_matches = []
            for sublist in match_results:
                if isinstance(sublist, list):
                    flat_matches.extend(sublist)
                else:
                    flat_matches.append(sublist)
            match_results = flat_matches
        
        # Sammle alle eindeutigen Spieler-Nicknames
        players = set()
        
        for match in match_results:
            if not isinstance(match, dict):
                continue
            
            # Spieler aus Team A
            for player in match.get('playerTeamA', []):
                if isinstance(player, dict) and 'nickname' in player:
                    players.add(player['nickname'])
            
            # Spieler aus Team B
            for player in match.get('playerTeamB', []):
                if isinstance(player, dict) and 'nickname' in player:
                    players.add(player['nickname'])
        
        players_list = sorted(list(players))
        
        return {"success": True, "players": players_list, "count": len(players_list)}
        
    except Exception as e:
        return {"success": False, "error": f"Fehler beim Verarbeiten: {str(e)}"}

def main():
    # JSON Daten vom POST Request lesen
    if os.environ.get('CONTENT_TYPE') == 'application/json':
        try:
            content_length = int(os.environ.get('CONTENT_LENGTH', 0))
            if content_length > 0:
                post_data = sys.stdin.read(content_length)
                data = json.loads(post_data)
                game_link = data.get('game_link', '')
            else:
                game_link = ''
        except:
            game_link = ''
    else:
        # Fallback für GET Parameter
        form = cgi.FieldStorage()
        game_link = form.getvalue('game_link', '')
    
    if not game_link:
        print(json.dumps({"success": False, "error": "Kein Spiel-Link angegeben"}))
        return
    
    result = get_players_from_url(game_link)
    print(json.dumps(result))

if __name__ == '__main__':
    main()
