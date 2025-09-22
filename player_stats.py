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

        # Build DataFrames - handle the nested list structure
        # Flatten the nested list structure if needed
        if match_results and isinstance(match_results[0], list):
            print("Flattening nested list structure...")
            flat_matches = []
            for sublist in match_results:
                if isinstance(sublist, list):
                    flat_matches.extend(sublist)
                else:
                    flat_matches.append(sublist)
            match_results = flat_matches
        
        print(f"Processing {len(match_results)} matches")
        
        # Build match_stats_df with winner and MVP information
        match_data_for_df = []
        for match in match_results:
            if not isinstance(match, dict):
                continue
                
            # Determine winner
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

        # Build player_stats_df with MVP information
        player_stats = []
        for match in match_results:
            if not isinstance(match, dict):
                continue
                
            match_number = match.get('matchNr', 0)
            mvp_player = match.get('mvp', '')
            
            # Determine winner for player records
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

def merge_events(events_folder=EVENTS_FOLDER):
    """
    Merge all events in folder.
    Returns two DataFrames: merged_players, merged_matches.
    """
    player_dfs = []
    match_dfs = []

    if not os.path.exists(events_folder):
        raise FileNotFoundError(f"Events folder not found: {events_folder}")

    files = sorted(f for f in os.listdir(events_folder) if f.lower().endswith('.txt'))
    if not files:
        raise FileNotFoundError(f"No event files found in folder: {events_folder}")

    print(f"Found {len(files)} event files:")
    for fname in files:
        print(f"  - {fname}")

    successful_files = 0
    for fname in files:
        try:
            print(f"\nProcessing {fname}...")
            filepath = os.path.join(events_folder, fname)
            url, mappings = parse_event_file(filepath)

            players, matches, date, time_range = fetch_stats_dataframe(url)
            
            if players is not None and matches is not None:
                players = normalize_names(players, mappings)
                player_dfs.append(players)

                matches['EventDate'] = date
                matches['EventTimeRange'] = time_range
                match_dfs.append(matches)
                successful_files += 1
                print(f"✓ Successfully processed {fname}")
            else:
                print(f"✗ Failed to process {fname}")
                
        except Exception as e:
            print(f"✗ Error processing {fname}: {e}")
            continue

    if not player_dfs or not match_dfs:
        raise ValueError("No valid data could be processed from any event file.")

    # Concatenate
    merged_players = pd.concat(player_dfs, ignore_index=True)
    merged_matches = pd.concat(match_dfs, ignore_index=True)

    print(f"\n✓ Successfully merged data from {successful_files} event files")
    print(f"  - Total players entries: {len(merged_players)}")
    print(f"  - Total matches entries: {len(merged_matches)}")
    
    return merged_players, merged_matches

def save_to_files_folder(dfs, base_name="vrfrag_stats"):
    """
    Save DataFrame or tuple of DataFrames to CSV file(s) in the files folder.
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    if isinstance(dfs, tuple):
        players_df, matches_df = dfs
        
        players_file = os.path.join(FILES_FOLDER, f"{base_name}_players_{timestamp}.csv")
        matches_file = os.path.join(FILES_FOLDER, f"{base_name}_matches_{timestamp}.csv")
        
        players_df.to_csv(players_file, index=False, encoding='utf-8')
        matches_df.to_csv(matches_file, index=False, encoding='utf-8')
        
        print(f"✓ Saved players data to: {players_file}")
        print(f"✓ Saved matches data to: {matches_file}")
        
        return players_file, matches_file
    else:
        file_path = os.path.join(FILES_FOLDER, f"{base_name}_{timestamp}.csv")
        dfs.to_csv(file_path, index=False, encoding='utf-8')
        print(f"✓ Saved data to: {file_path}")
        return file_path

def generate_statistics():
    """
    Hauptfunktion zum Generieren der Statistiken
    """
    try:
        print("Starting statistics generation...")
        print(f"Events folder: {EVENTS_FOLDER}")
        print(f"Files folder: {FILES_FOLDER}")
        
        # Events mergen
        merged_players, merged_matches = merge_events()
        
        # Statistiken speichern
        players_file, matches_file = save_to_files_folder((merged_players, merged_matches))
        
        # Zusätzliche Statistiken generieren
        generate_advanced_stats(merged_players, merged_matches)
        
        return {
            'success': True,
            'players_file': players_file,
            'matches_file': matches_file,
            'player_count': len(merged_players),
            'match_count': len(merged_matches),
            'unique_players': merged_players['Player'].nunique(),
            'message': f'Successfully generated statistics for {len(merged_players)} player entries and {len(merged_matches)} matches'
        }
        
    except Exception as e:
        error_msg = f"Error generating statistics: {str(e)}"
        print(error_msg)
        return {'success': False, 'error': error_msg}

def generate_advanced_stats(players_df, matches_df):
    """
    Generiert erweiterte Statistiken und speichert sie als CSV
    """
    try:
        # Spieler-Statistiken
        player_stats = players_df.groupby('Player').agg({
            'kills': ['sum', 'mean', 'max'],
            'deaths': ['sum', 'mean', 'min'],
            'assists': 'sum',
            'score': ['sum', 'mean', 'max'],
            'isMVP': 'sum',
            'playerWon': 'mean'
        }).round(2)
        
        player_stats.columns = ['_'.join(col).strip() for col in player_stats.columns.values]
        player_stats = player_stats.reset_index()
        player_stats = player_stats.rename(columns={'playerWon_mean': 'win_rate'})
        
        # Match-Statistiken
        match_stats = matches_df.groupby('EventDate').agg({
            'matchNr': 'count',
            'teamAPoints': 'sum',
            'teamBPoints': 'sum'
        }).reset_index()
        
        # Dateien speichern
        player_stats_file = os.path.join(FILES_FOLDER, f"player_advanced_stats_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")
        match_stats_file = os.path.join(FILES_FOLDER, f"match_advanced_stats_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")
        
        player_stats.to_csv(player_stats_file, index=False, encoding='utf-8')
        match_stats.to_csv(match_stats_file, index=False, encoding='utf-8')
        
        print(f"✓ Advanced player statistics saved to: {player_stats_file}")
        print(f"✓ Advanced match statistics saved to: {match_stats_file}")
        
    except Exception as e:
        print(f"Warning: Could not generate advanced statistics: {e}")

if __name__ == '__main__':
    # Lokale Ausführung
    result = generate_statistics()
    if result['success']:
        print("🎉 Statistics generation completed successfully!")
        print(f"📊 Player entries: {result['player_count']}")
        print(f"📊 Match entries: {result['match_count']}")
        print(f"👥 Unique players: {result['unique_players']}")
    else:
        print("❌ Statistics generation failed!")
        print(f"Error: {result['error']}")
