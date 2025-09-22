import requests
from bs4 import BeautifulSoup
import json
import re

def get_players_from_url(game_link):
    """
    Extrahiert alle Spieler-Nicknames aus einem VRFrag Spiel-Link
    Gibt eine Liste von Spielern zurück oder None bei Fehler
    """
    try:
        print(f"Versuche Spielerdaten von {game_link} abzurufen...")
        
        response = requests.get(game_link, timeout=10)
        if response.status_code != 200:
            print(f"Fehler: HTTP Status {response.status_code}")
            return None
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Finde das Script mit globalAllMatchesResults
        script_tags = soup.find_all('script')
        target_script = None
        
        for script in script_tags:
            if script.string and 'globalAllMatchesResults' in script.string:
                target_script = script.string
                break
        
        if not target_script:
            print("Kein Script mit globalAllMatchesResults gefunden")
            return None
        
        # Extrahiere das JSON
        match = re.search(r'const\s+globalAllMatchesResults\s*=\s*(\[.*?\])\s*;', target_script, re.DOTALL)
        if not match:
            print("Konnte JSON Daten nicht extrahieren")
            return None
        
        match_results_data = match.group(1)
        # Kommentare entfernen
        match_results_data = re.sub(r'//.*?$', '', match_results_data, flags=re.MULTILINE)
        
        print("JSON erfolgreich extrahiert, versuche zu parsen...")
        
        match_results = json.loads(match_results_data)
        
        # Debug: Struktur analysieren
        print(f"Parsed data type: {type(match_results)}")
        if match_results:
            print(f"First element type: {type(match_results[0])}")
        
        # Flatten die Datenstruktur falls nötig
        if match_results and isinstance(match_results[0], list):
            print("Flattening nested list structure...")
            flat_matches = []
            for sublist in match_results:
                if isinstance(sublist, list):
                    flat_matches.extend(sublist)
                else:
                    flat_matches.append(sublist)
            match_results = flat_matches
        
        print(f"Verarbeite {len(match_results)} Matches")
        
        # Sammle alle eindeutigen Spieler-Nicknames
        players = set()
        
        for match in match_results:
            if not isinstance(match, dict):
                print("Skipping non-dict match element")
                continue
            
            # Spieler aus Team A
            team_a_players = match.get('playerTeamA', [])
            if not isinstance(team_a_players, list):
                team_a_players = []
                
            for player in team_a_players:
                if isinstance(player, dict) and 'nickname' in player:
                    players.add(player['nickname'])
            
            # Spieler aus Team B
            team_b_players = match.get('playerTeamB', [])
            if not isinstance(team_b_players, list):
                team_b_players = []
                
            for player in team_b_players:
                if isinstance(player, dict) and 'nickname' in player:
                    players.add(player['nickname'])
        
        players_list = sorted(list(players))
        print(f"Gefundene Spieler: {players_list}")
        
        return players_list
        
    except requests.exceptions.RequestException as e:
        print(f"Netzwerkfehler: {e}")
        return None
    except json.JSONDecodeError as e:
        print(f"JSON Parse Fehler: {e}")
        return None
    except Exception as e:
        print(f"Unerwarteter Fehler: {e}")
        return None

# Für direkte Tests
if __name__ == '__main__':
    # Test URL
    test_url = "https://www.vrfrag.com/stats?8IfcFJU"
    players = get_players_from_url(test_url)
    
    if players:
        print(f"\n🎯 Gefundene Spieler ({len(players)}):")
        for i, player in enumerate(players, 1):
            print(f"{i}. {player}")
    else:
        print("❌ Keine Spieler gefunden oder Fehler aufgetreten")
