from flask import Flask, request, send_from_directory, jsonify, render_template
import subprocess
import os
import requests
import base64
import difflib
import pandas as pd
from datetime import datetime

from get_players import get_players_from_url
from player_stats import generate_statistics
from aliases import (
    suggest_real_name, upsert_alias, load_aliases
)

app = Flask(__name__)

BASE_DIR = os.path.dirname(__file__)
CSV_PATH = os.path.join(BASE_DIR, 'data.csv')

FILES_FOLDER = os.path.join(BASE_DIR, "files")
EVENTS_FOLDER = os.path.join(BASE_DIR, "events")
os.makedirs(FILES_FOLDER, exist_ok=True)
os.makedirs(EVENTS_FOLDER, exist_ok=True)

# ---- CSV-Dateien (werden nach Stats-Generierung vorhanden sein) ----
def get_players_csv_path():
    for p in [
        os.path.join(FILES_FOLDER, "vrfrag_players.csv"),
        os.path.join(FILES_FOLDER, "merged.csv_players.csv"),
    ]:
        if os.path.exists(p):
            return p
    return None

def get_matches_csv_path():
    for p in [
        os.path.join(FILES_FOLDER, "vrfrag_matches.csv"),
        os.path.join(FILES_FOLDER, "merged.csv_matches.csv"),
    ]:
        if os.path.exists(p):
            return p
    return None

def ensure_players_csv():
    path = get_players_csv_path()
    if not path:
        return None, jsonify({
            "success": False,
            "error": "Spieler-Daten nicht gefunden (vrfrag_players.csv / merged.csv_players.csv). Bitte zuerst Statistiken generieren."
        }), 400
    return path, None, None

def ensure_matches_csv():
    path = get_matches_csv_path()
    if not path:
        return None, jsonify({
            "success": False,
            "error": "Match-Datei nicht gefunden (vrfrag_matches.csv / merged.csv_matches.csv). Bitte zuerst Statistiken generieren."
        }), 400
    return path, None, None


# ---- Team-Generator: Fuzzy-Mapping ----
def get_player_universe():
    players_file, err_resp, code = ensure_players_csv()
    if err_resp:
        return None, err_resp, code

    df = pd.read_csv(players_file)
    if "Player" not in df.columns:
        return None, jsonify({"success": False, "error": "Spalte 'Player' fehlt in der CSV."}), 500

    all_players = (
        df["Player"]
        .dropna()
        .astype(str)
        .str.strip()
        .unique()
        .tolist()
    )
    all_players = sorted([p for p in all_players if p])
    return all_players, None, None

def resolve_player_name(input_name: str, all_players: list[str], cutoff: float = 0.78):
    raw = (input_name or "").strip()
    if not raw:
        return raw, 0.0

    lower_map = {p.lower(): p for p in all_players}
    if raw.lower() in lower_map:
        return lower_map[raw.lower()], 1.0

    candidates = difflib.get_close_matches(raw, all_players, n=1, cutoff=cutoff)
    if candidates:
        best = candidates[0]
        conf = difflib.SequenceMatcher(a=raw.lower(), b=best.lower()).ratio()
        return best, conf

    return raw, 0.0


# ---- GitHub Save ----
def _github_headers(token: str):
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github.v3+json",
    }

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

    content_base64 = base64.b64encode(content.encode('utf-8')).decode('utf-8')
    headers = _github_headers(token)

    url = f"https://api.github.com/repos/{repo_owner}/{repo_name}/contents/events/{filename}"

    existing_sha = None
    try:
        response = requests.get(url, headers=headers, params={"ref": branch}, timeout=20)
        if response.status_code == 200:
            existing_sha = response.json().get("sha")
    except Exception:
        pass

    data = {
        "message": f"Add event file: {filename}",
        "content": content_base64,
        "branch": branch
    }
    if existing_sha:
        data["sha"] = existing_sha

    try:
        response = requests.put(url, headers=headers, json=data, timeout=20)
        response_data = response.json() if response.content else {}

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


def save_event_locally(filename: str, content: str):
    local_path = os.path.join(EVENTS_FOLDER, filename)
    with open(local_path, "w", encoding="utf-8") as f:
        f.write(content)
    return local_path


def generate_filename(custom_name=None):
    """
    Generiert einen Dateinamen im Format YYYY_MM_DD_NN.txt
    """
    if custom_name:
        return custom_name if custom_name.endswith('.txt') else custom_name + '.txt'

    today = datetime.now().strftime("%Y_%m_%d")

    next_num = 1
    try:
        token = os.environ.get('GITHUB_TOKEN')
        if token:
            headers = _github_headers(token)
            url = "https://api.github.com/repos/Trent1337/VRFrag/contents/events"
            response = requests.get(url, headers=headers, timeout=20)
            if response.status_code == 200 and isinstance(response.json(), list):
                files = response.json()
                today_files = [f for f in files if f.get('name', '').startswith(today)]
                next_num = len(today_files) + 1
    except Exception:
        next_num = 1

    return f"{today}_{next_num:02d}.txt"


# ---- Pages ----
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/teams')
def teams_page():
    return render_template('teams.html')


# ---- Misc old route ----
@app.route('/run', methods=['POST'])
def run_script():
    players = [request.form.get(f'player{i}') for i in range(1, 11)]
    result = subprocess.run(
        ['python3', 'run_script.py', CSV_PATH] + players,
        capture_output=True, text=True
    )
    return result.stdout or "Script ausgeführt"


# ---- Aliases / Suggestions ----
@app.get("/api/name-suggestions")
def api_name_suggestions():
    username = (request.args.get("username") or "").strip()
    if not username:
        return jsonify({"success": False, "error": "username fehlt"}), 400
    best, others = suggest_real_name(username)
    return jsonify({"success": True, "username": username, "best": best, "others": others})

@app.post("/api/aliases")
def api_aliases_upsert():
    data = request.get_json(force=True) or {}
    username = (data.get("username") or "").strip()
    real_name = (data.get("real_name") or "").strip()
    if not username or not real_name:
        return jsonify({"success": False, "error": "username und real_name erforderlich"}), 400
    upsert_alias(username, real_name, source="manual", confidence=0.95)
    return jsonify({"success": True})


# ---- VRFrag players from link ----
@app.route('/api/get-players', methods=['POST'])
def api_get_players():
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


# ---- Save event (Option A: GitHub + local + generate stats) ----
@app.route('/api/save-to-github', methods=['POST'])
def api_save_to_github():
    """
    Speichert Event-Datei in GitHub UND lokal in ./events,
    damit generate_statistics() auf Render sofort damit arbeiten kann.
    """
    try:
        data = request.get_json()
        if not data or 'game_link' not in data or 'mappings' not in data:
            return jsonify({'success': False, 'error': 'Ungültige Daten'}), 400

        game_link = data['game_link']
        mappings = data['mappings']
        custom_filename = data.get('filename', '')

        # Dateiinhalt generieren
        content_lines = [game_link.strip()]
        for mapping in mappings:
            nick = (mapping.get('nickname') or "").strip()
            real = (mapping.get('realName') or mapping.get('real_name') or "").strip()
            if nick and real:
                content_lines.append(f"{nick}={real}")
        content = "\n".join(content_lines) + "\n"

        filename = generate_filename(custom_filename)

        # 1) Zu GitHub pushen
        result = save_to_github(filename, content)
        if not result.get("success"):
            return jsonify(result)

        # 2) Lokal speichern (Option A)
        try:
            local_path = save_event_locally(filename, content)
            result["local_saved"] = True
            result["local_path"] = local_path
        except Exception as e:
            result["local_saved"] = False
            result["local_error"] = str(e)

        # 3) Statistiken neu generieren (arbeitet auf ./events)
        try:
            stats = generate_statistics()
            # generate_statistics liefert bei dir anscheinend ein dict mit success/message/...
            result["statistics_updated"] = bool(stats.get("success", True))
            result["statistics_result"] = stats
        except Exception as e:
            result["statistics_updated"] = False
            result["statistics_error"] = str(e)

        return jsonify(result)

    except Exception as e:
        return jsonify({'success': False, 'error': f'Fehler: {str(e)}'}), 500


# ---- List events on GitHub ----
@app.route('/api/list-events', methods=['GET'])
def api_list_events():
    try:
        token = os.environ.get('GITHUB_TOKEN')
        headers = {'Accept': 'application/vnd.github.v3+json'}
        if token:
            headers = _github_headers(token)

        url = "https://api.github.com/repos/Trent1337/VRFrag/contents/events"
        response = requests.get(url, headers=headers, timeout=20)

        if response.status_code == 200:
            files = response.json()
            event_files = []
            for file in files:
                if file.get('name', '').endswith('.txt'):
                    event_files.append({
                        'filename': file.get('name'),
                        'download_url': file.get('download_url'),
                        'html_url': file.get('html_url'),
                        'size': file.get('size', 0)
                    })

            return jsonify({
                'success': True,
                'events': sorted(event_files, key=lambda x: x['filename'], reverse=True)
            })
        else:
            return jsonify({
                'success': False,
                'error': f'GitHub Fehler: {response.status_code} - {response.text}'
            }), 500

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ---- Update stats manually ----
@app.route('/api/update-statistics', methods=['POST'])
def api_update_statistics():
    try:
        print("Starting statistics update...")
        result = generate_statistics()

        if result.get('success'):
            return jsonify({
                'success': True,
                'message': result.get('message'),
                'player_count': result.get('player_count'),
                'match_count': result.get('match_count'),
                'unique_players': result.get('unique_players'),
                'players_file': os.path.basename(result.get('players_file', '')),
                'matches_file': os.path.basename(result.get('matches_file', ''))
            })
        else:
            return jsonify({
                'success': False,
                'error': result.get('error', 'Unbekannter Fehler')
            }), 500

    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Statistics generation failed: {str(e)}'
        }), 500


# ---- Download/list stats files ----
@app.route('/files/<filename>')
def download_file(filename):
    try:
        return send_from_directory(FILES_FOLDER, filename, as_attachment=True)
    except FileNotFoundError:
        return jsonify({'success': False, 'error': 'File not found'}), 404

@app.route('/api/list-files', methods=['GET'])
def api_list_files():
    try:
        files = []
        for filename in os.listdir(FILES_FOLDER):
            if filename.endswith('.csv'):
                filepath = os.path.join(FILES_FOLDER, filename)
                files.append({
                    'filename': filename,
                    'size': os.path.getsize(filepath),
                    'modified': datetime.fromtimestamp(os.path.getmtime(filepath)).isoformat()
                })

        return jsonify({
            'success': True,
            'files': sorted(files, key=lambda x: x['modified'], reverse=True)
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Error listing files: {str(e)}'
        }), 500


# ---- Team Generator API ----
@app.route('/api/generate-teams', methods=['POST'])
def api_generate_teams():
    try:
        data = request.get_json()
        if not data or 'players' not in data:
            return jsonify({'success': False, 'error': 'Keine Spieler-Daten'}), 400

        selected_players = data['players']
        selected_map = data.get('map', None)

        # A) Fuzzy-Mapping
        all_players, err_resp, code = get_player_universe()
        if err_resp:
            return err_resp, code

        resolved_players = []
        unresolved = []

        for name in selected_players:
            best, conf = resolve_player_name(name, all_players, cutoff=0.78)
            resolved_players.append(best)
            if conf < 0.78:
                unresolved.append({
                    "input": name,
                    "best_guess": best,
                    "confidence": round(conf, 3)
                })

        selected_players = resolved_players

        # Load player data
        players_file, err_resp, code = ensure_players_csv()
        if err_resp:
            return err_resp, code

        players_df = pd.read_csv(players_file)

        from vrfrag_teams import generate_fair_teams
        result = generate_fair_teams(selected_players, players_df, selected_map)

        if isinstance(result, dict) and 'error' in result:
            return jsonify({'success': False, 'error': result['error']}), 400

        return jsonify({
            'success': True,
            'teams': result,
            'resolved_players': selected_players,
            'unresolved': unresolved
        })

    except Exception as e:
        return jsonify({'success': False, 'error': f'Team-Generator Fehler: {str(e)}'}), 500


# ---- Get all players for datalist ----
@app.get("/api/get-all-players")
def get_all_players():
    path, err_resp, code = ensure_players_csv()
    if err_resp:
        return err_resp, code

    df = pd.read_csv(path)
    if "Player" not in df.columns:
        return jsonify({"success": False, "error": "Spalte 'Player' fehlt in der CSV."}), 500

    aliases = load_aliases()[["norm_username", "real_name"]]
    df["norm_username"] = df["Player"].astype(str).str.strip().str.lower()
    out = df.merge(aliases, how="left", on="norm_username")
    out["display_name"] = out["real_name"].where(out["real_name"].astype(bool), out["Player"])

    rows = out[["Player", "display_name"]].dropna().drop_duplicates()
    players = [{"value": r["Player"], "label": r["display_name"]} for _, r in rows.iterrows()]
    players = sorted(players, key=lambda x: (x["label"] or x["value"]).lower())

    return jsonify({"players": players})


@app.route('/api/get-available-maps', methods=['GET'])
def api_get_available_maps():
    try:
        matches_file, err_resp, code = ensure_matches_csv()
        if err_resp:
            return err_resp, code

        df = pd.read_csv(matches_file)
        if "maptitle" not in df.columns:
            return jsonify({"success": False, "error": "Spalte 'maptitle' fehlt in der Match-CSV."}), 500

        maps = sorted(df["maptitle"].dropna().unique().tolist())
        return jsonify({"success": True, "maps": maps})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
