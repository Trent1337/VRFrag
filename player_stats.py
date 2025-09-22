import os
import re
import pandas as pd
import requests
from bs4 import BeautifulSoup
import json
from datetime import datetime

# Ordner definieren
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FILES_FOLDER = os.path.join(BASE_DIR, 'files')
EVENTS_FOLDER = os.path.join(BASE_DIR, 'events')

# Ordner erstellen falls nicht vorhanden
os.makedirs(FILES_FOLDER, exist_ok=True)
os.makedirs(EVENTS_FOLDER, exist_ok=True)

# Feste Dateinamen
PLAYERS_FILE = os.path.join(FILES_FOLDER, 'vrfrag_players.csv')
MATCHES_FILE = os.path.join(FILES_FOLDER, 'vrfrag_matches.csv')

def parse_event_file(filepath):
    """
    Read an event .txt file.
    Expected format:
      - First line: URL to statistics
      - Remaining lines: nickname=full name mappings
    Returns URL string and mapping dict.
    """
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = [line.strip() for line in f if line.strip()]

    url = lines[0]
    mappings = {}
    for mapping_line in lines[1:]:
        try:
            nick, real = mapping_line.split('=', 1)
            mappings[nick.strip()] = real.strip()
        except ValueError:
            continue
    return url, mappings

def fetch_stats_dataframe(url):
    """
    HTTP-request to grab player- and match-stats from the embedded JS variable
    `globalAllMatchesResults`, plus extract bookingDate and bookingStartEnd.
    """
    try:
        response = requests.get(url, timeout=30)
        if response.status_code != 200:
            print(f"Error fetching page: {response.status_code}")
            return None, None, None, None

        soup = BeautifulSoup(response.text, 'html.parser')

        # Find the script containing globalAllMatchesResults
        script_tags = soup.find_all('script')
        target_script = None
        
        for script in script_tags:
            if script.string and 'globalAllMatchesResults' in script.string:
                target_script = script.string
                break
        
        if not target_script:
            print("No globalMatchResults script found.")
            return None, None, None, None

        # Improved regex to extract the array
        match = re.search(r'const\s+globalAllMatchesResults\s*=\s*(\[.*?\])\s*;', target_script, re.DOTALL)
        if not match:
            print("Could not extract globalAllMatchesResults array")
            return None, None, None, None

        try:
            match_results_data = match.group(1)
            # Clean the data
            match_results_data = re.sub(r'//.*?$', '', match_results_data, flags=re.MULTILINE)
            
            match_results = json.loads(match_results_data)
            
        except json.JSONDecodeError as e:
            print(f"Error decoding globalMatchResults JSON: {e}")
            return None, None, None, None

        # Extract bookingDate
        date_match = re.search(r"const\s+globalBookingDateSpelledOut\s*=\s*['\"](.*?)['\"]", target_script)
        booking_date = date_match.group(1) if date_match else "Unknown Date"

        # Extract bookingStartEnd
        range_match = re.search(r"const\s+globalBookingStartEndTime\s*=\s*['\"](.*?)['\"]", target_script)
        booking_time_range = range_match.group(1) if range_match else "Unknown Time"

        # Build DataFrames
        if match_results and isinstance(match_results[0], list):
            flat_matches = []
            for sublist in match_results:
                if isinstance(sublist, list):
                    flat_matches.extend(sublist)
                else:
                    flat_matches.append(sublist)
            match_results = flat_matches
        
        print(f"Processing {len(match_results)} matches")
        
        # Build match_stats_df
        match_data_for_df = []
        for match in match_results:
            if not isinstance(match, dict):
                continue
                
            team_a_points = match.get('teamAPoints', 0)
            team_b_points = match.get('teamBPoints', 0)
            
            if team_a_points > team_b_points:
                winner = 'A'
            elif team_b_points > team_a_points:
                winner = 'B'
            else:
                winner = 'Draw'
                
            match_data_for_df.append({
                'courtsMask': match.get('courtsMask', 0),
                'matchNr': match.get('matchNr', 0),
                'maptitle': match.get('maptitle', ''),
                'teamA': match.get('teamA', ''),
                'teamB': match.get('teamB', ''),
                'teamAPoints': team_a_points,
                'teamBPoints': team_b_points,
                'teamAPointsHalfTime': match.get('teamAPointsHalfTime', 0),
                'teamBPointsHalfTime': match.get('teamBPointsHalfTime', 0),
                'matchCompleted': match.get('matchCompleted', 0),
                'mvp': match.get('mvp', ''),
                'winner': winner,
                'EventDate': booking_date,
                'EventTimeRange': booking_time_range
            })
        
        match_stats_df = pd.DataFrame(match_data_for_df)

        # Build player_stats_df
        player_stats = []
        for match in match_results:
            if not isinstance(match, dict):
                continue
                
            match_number = match.get('matchNr', 0)
            mvp_player = match.get('mvp', '')
            
            team_a_points = match.get('teamAPoints', 0)
            team_b_points = match.get('teamBPoints', 0)
            winner = 'A' if team_a_points > team_b_points else 'B' if team_b_points > team_a_points else 'Draw'
            
            # Process team A players
            team_a_players = match.get('playerTeamA', [])
            if not isinstance(team_a_players, list):
                team_a_players = []
                
            for player in team_a_players:
                if isinstance(player, dict):
                    is_mvp = player.get('nickname', '') == mvp_player
                    player_stats.append({
                        'matchNr': match_number,
                        'nickname': player.get('nickname', ''),
                        'kills': player.get('kills', 0),
                        'assists': player.get('assists', 0),
                        'deaths': player.get('deaths', 0),
                        'score': player.get('score', 0),
                        'team': 'A',
                        'isMVP': is_mvp,
                        'matchWinner': winner,
                        'playerWon': winner == 'A',
                        'EventDate': booking_date,
                        'EventTimeRange': booking_time_range,
                        'mvpPlayer': mvp_player
                    })
            
            # Process team B players
            team_b_players = match.get('playerTeamB', [])
            if not isinstance(team_b_players, list):
                team_b_players = []
                
            for player in team_b_players:
                if isinstance(player, dict):
                    is_mvp = player.get('nickname', '') == mvp_player
                    player_stats.append({
                        'matchNr': match_number,
                        'nickname': player.get('nickname', ''),
                        'kills': player.get('kills', 0),
                        'assists': player.get('assists', 0),
                        'deaths': player.get('deaths', 0),
                        'score': player.get('score', 0),
                        'team': 'B',
                        'isMVP': is_mvp,
                        'matchWinner': winner,
                        'playerWon': winner == 'B',
                        'EventDate': booking_date,
                        'EventTimeRange': booking_time_range,
                        'mvpPlayer': mvp_player
                    })

        player_stats_df = pd.DataFrame(player_stats)
        
        print(f"Successfully processed {len(player_stats)} player entries from {len(match_results)} matches")
        
        return player_stats_df, match_stats_df, booking_date, booking_time_range
        
    except Exception as e:
        print(f"Error in fetch_stats_dataframe: {e}")
        import traceback
        traceback.print_exc()
        return None, None, None, None

def normalize_names(df, mappings):
    """
    Map 'Nickname' to 'Player' using provided mappings.
    """
    df = df.copy()
    df['Player'] = df['nickname'].replace(mappings)
    return df

def load_existing_data():
    """
    Lädt vorhandene Daten aus den CSV-Dateien
    """
    players_df = pd.DataFrame()
    matches_df = pd.DataFrame()
    
    if os.path.exists(PLAYERS_FILE):
        players_df = pd.read_csv(PLAYERS_FILE)
        print(f"Loaded existing players data: {len(players_df)} entries")
    
    if os.path.exists(MATCHES_FILE):
        matches_df = pd.read_csv(MATCHES_FILE)
        print(f"Loaded existing matches data: {len(matches_df)} entries")
    
    return players_df, matches_df

def save_combined_data(players_df, matches_df):
    """
    Speichert die kombinierten Daten in die festen Dateien
    """
    try:
        players_df.to_csv(PLAYERS_FILE, index=False, encoding='utf-8')
        matches_df.to_csv(MATCHES_FILE, index=False, encoding='utf-8')
        
        print(f"✓ Saved players data to: {PLAYERS_FILE} ({len(players_df)} entries)")
        print(f"✓ Saved matches data to: {MATCHES_FILE} ({len(matches_df)} entries)")
        
        return True
    except Exception as e:
        print(f"Error saving data: {e}")
        return False

def merge_events(events_folder=EVENTS_FOLDER):
    """
    Merge all events in folder and combine with existing data.
    """
    # Vorhandene Daten laden
    existing_players, existing_matches = load_existing_data()
    
    if not os.path.exists(events_folder):
        raise FileNotFoundError(f"Events folder not found: {events_folder}")

    files = sorted(f for f in os.listdir(events_folder) if f.lower().endswith('.txt'))
    if not files:
        raise FileNotFoundError(f"No event files found in folder: {events_folder}")

    print(f"Found {len(files)} event files:")
    for fname in files:
        print(f"  - {fname}")

    player_dfs = [existing_players] if not existing_players.empty else []
    match_dfs = [existing_matches] if not existing_matches.empty else []

    successful_files = 0
    processed_events = set()
    
    # Bereits verarbeitete Events aus vorhandenen Daten identifizieren
    if not existing_players.empty:
        processed_events = set(existing_players['EventDate'].unique())
        print(f"Already processed events: {len(processed_events)}")

    for fname in files:
        try:
            print(f"\nProcessing {fname}...")
            filepath = os.path.join(events_folder, fname)
            url, mappings = parse_event_file(filepath)

            # Prüfen ob dieses Event bereits verarbeitet wurde
            with open(filepath, 'r', encoding='utf-8') as f:
                first_line = f.readline().strip()
            
            # Event-Datum aus der URL oder Dateinamen extrahieren
            event_date = extract_event_date(fname, first_line)
            if event_date in processed_events:
                print(f"✓ Event already processed, skipping: {fname}")
                continue

            players, matches, date, time_range = fetch_stats_dataframe(url)
            
            if players is not None and matches is not None:
                players = normalize_names(players, mappings)
                player_dfs.append(players)

                matches['EventDate'] = date
                matches['EventTimeRange'] = time_range
                match_dfs.append(matches)
                
                processed_events.add(date)
                successful_files += 1
                print(f"✓ Successfully processed {fname}")
            else:
                print(f"✗ Failed to process {fname}")
                
        except Exception as e:
            print(f"✗ Error processing {fname}: {e}")
            continue

    if not player_dfs or (len(player_dfs) == 1 and player_dfs[0].empty):
        return existing_players, existing_matches, 0

    # Concatenate
    merged_players = pd.concat(player_dfs, ignore_index=True).drop_duplicates()
    merged_matches = pd.concat(match_dfs, ignore_index=True).drop_duplicates()

    print(f"\n✓ Successfully merged data from {successful_files} new event files")
    print(f"  - Total players entries: {len(merged_players)}")
    print(f"  - Total matches entries: {len(merged_matches)}")
    print(f"  - New entries added: {successful_files}")
    
    return merged_players, merged_matches, successful_files

def extract_event_date(filename, first_line):
    """
    Extrahiert Event-Datum aus Dateinamen oder URL
    """
    # Versuche Datum aus Dateinamen zu extrahieren (YYYY_MM_DD)
    date_match = re.search(r'(\d{4}_\d{2}_\d{2})', filename)
    if date_match:
        return date_match.group(1)
    
    # Fallback: Verwende ersten Teil der URL
    return filename.split('_')[0] if '_' in filename else filename

def generate_statistics():
    """
    Hauptfunktion zum Generieren der Statistiken
    """
    try:
        print("Starting statistics generation...")
        print(f"Events folder: {EVENTS_FOLDER}")
        print(f"Files folder: {FILES_FOLDER}")
        
        # Events mergen (kombiniert mit vorhandenen Daten)
        merged_players, merged_matches, new_files = merge_events()
        
        if new_files == 0 and not merged_players.empty:
            print("✓ No new events to process, using existing data")
        
        # Daten speichern (überschreibt vorhandene Dateien)
        save_success = save_combined_data(merged_players, merged_matches)
        
        if not save_success:
            return {'success': False, 'error': 'Failed to save data files'}
        
        return {
            'success': True,
            'players_file': os.path.basename(PLAYERS_FILE),
            'matches_file': os.path.basename(MATCHES_FILE),
            'player_count': len(merged_players),
            'match_count': len(merged_matches),
            'unique_players': merged_players['Player'].nunique(),
            'new_files_processed': new_files,
            'message': f'Successfully updated statistics. Total: {len(merged_players)} players, {len(merged_matches)} matches. New events: {new_files}'
        }
        
    except Exception as e:
        error_msg = f"Error generating statistics: {str(e)}"
        print(error_msg)
        return {'success': False, 'error': error_msg}

if __name__ == '__main__':
    # Lokale Ausführung
    result = generate_statistics()
    if result['success']:
        print("🎉 Statistics generation completed successfully!")
        print(f"📊 Player entries: {result['player_count']}")
        print(f"📊 Match entries: {result['match_count']}")
        print(f"👥 Unique players: {result['unique_players']}")
        print(f"🆕 New events processed: {result['new_files_processed']}")
    else:
        print("❌ Statistics generation failed!")
        print(f"Error: {result['error']}")
