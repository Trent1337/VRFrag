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
CSV_PATH = os.path.join(BASE_DIR, "data.csv")

FILES_FOLDER = os.path.join(BASE_DIR, "files")
EVENTS_FOLDER = os.path.join(BASE_DIR, "events")
os.makedirs(FILES_FOLDER, exist_ok=True)
os.makedirs(EVENTS_FOLDER, exist_ok=True)

REPO_OWNER = "Trent1337"
REPO_NAME = "VRFrag"
REPO_BRANCH = "main"


# ----------------------------
# GitHub Helpers
# ----------------------------
def _github_headers(token: str):
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github.v3+json",
    }


def save_file_to_github(repo_path: str, content: str, commit_message: str):
    """
    Speichert/aktualisiert eine Datei in GitHub (beliebiger Pfad),
    z.B. 'events/x.txt' oder 'files/merged.csv_players.csv'
    """
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        return {"success": False, "error": "GITHUB_TOKEN nicht konfiguriert"}

    headers = _github_headers(token)
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/{repo_path}"

    content_base64 = base64.b64encode(content.encode("utf-8")).decode("utf-8")

    # existierende SHA holen (für Update)
    existing_sha = None
    try:
        r = requests.get(url, headers=headers, params={"ref": REPO_BRANCH}, timeout=20)
        if r.status_code == 200:
            existing_sha = r.json().get("sha")
    except Exception:
        pass

    data = {
        "message": commit_message,
        "content": content_base64,
        "branch": REPO_BRANCH,
    }
    if existing_sha:
        data["sha"] = existing_sha

    try:
        r = requests.put(url, headers=headers, json=data, timeout=20)
        resp = r.json() if r.content else {}
        if r.status_code in (200, 201):
            return {
                "success": True,
                "repo_path": repo_path,
                "html_url": resp.get("content", {}).get("html_url", ""),
            }
        return {
            "success": False,
            "error": f"GitHub API Fehler: {r.status_code} - {resp.get('message', 'Unbekannter Fehler')}",
        }
    except Exception as e:
        return {"success": False, "error": f"Verbindungsfehler: {str(e)}"}


def download_file_from_github(repo_path: str, local_path: str):
    """
    Lädt eine Datei aus GitHub (contents API, base64 content) in ein lokales File.
    """
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        return False, "GITHUB_TOKEN nicht konfiguriert"

    headers = _github_headers(token)
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/{repo_path}"

    r = requests.get(url, headers=headers, params={"ref": REPO_BRANCH}, timeout=20)
    if r.status_code != 200:
        return False, f"GitHub download Fehler: {r.status_code} - {r.text}"

    payload = r.json()
    content_b64 = payload.get("content", "")
    if not content_b64:
        return False, "Keine content payload von GitHub erhalten"

    content = base64.b64decode(content_b64).decode("utf-8", errors="replace")
    os.makedirs(os.path.dirname(local_path), exist_ok=True)
    with open(local_path, "w", encoding="utf-8") as f:
        f.write(content)

    return True, None


def push_statistics_csvs_to_github(stats_result: dict):
    """
    Pusht die zuletzt generierten CSVs aus ./files nach GitHub unter files/.
    Erwartet, dass generate_statistics() ein dict mit players_file und matches_file liefert.
    """
    pushed = {}

    players_file = stats_result.get("players_file")
    matches_file = stats_result.get("matches_file")

    # Falls generate_statistics nur Basenames liefert, auf absoluten Pfad mappen:
    if players_file and not os.path.isabs(players_file):
        players_file = os.path.join(FILES_FOLDER, os.path.basename(players_file))
    if matches_file and not os.path.isabs(matches_file):
        matches_file = os.path.join(FILES_FOLDER, os.path.basename(matches_file))

    if players_file and os.path.exists(players_file):
        with open(players_file, "r", encoding="utf-8") as f:
            content = f.read()
        repo_path = f"files/{os.path.basename(players_file)}"
        pushed["players_csv"] = save_file_to_github(
            repo_path=repo_path,
            content=content,
            commit_message=f"Update stats: {os.path.basename(players_file)}",
        )

    if matches_file and os.path.exists(matches_file):
        with open(matches_file, "r", encoding="utf-8") as f:
            content = f.read()
        repo_path = f"files/{os.path.basename(matches_file)}"
        pushed["matches_csv"] = save_file_to_github(
            repo_path=repo_path,
            content=content,
            commit_message=f"Update stats: {os.path.basename(matches_file)}",
        )

    return pushed


# ----------------------------
# Local Helpers
# ----------------------------
def save_event_locally(filename: str, content: str):
    local_path = os.path.join(EVENTS_FOLDER, filename)
    with open(local_path, "w", encoding="utf-8") as f:
        f.write(content)
    return local_path


# ----------------------------
# CSV Resolution (local first, fallback to GitHub)
# ----------------------------
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
    if path and os.path.exists(path):
        return path, None, None

    # Fallback: aus GitHub holen
    candidates = ["merged.csv_players.csv", "vrfrag_players.csv"]
    for name in candidates:
        repo_path = f"files/{name}"
        local_path = os.path.join(FILES_FOLDER, name)
        ok, _err = download_file_from_github(repo_path, local_path)
        if ok and os.path.exists(local_path):
            return local_path, None, None

    return None, jsonify({
        "success": False,
        "error": "Spieler-Daten nicht gefunden (lokal & GitHub). Bitte zuerst Statistiken generieren."
    }), 400


def ensure_matches_csv():
    path = get_matches_csv_path()
    if path and os.path.exists(path):
        return path, None, None

    # Fallback: aus GitHub holen
    candidates = ["merged.csv_matches.csv", "vrfrag_matches.csv"]
    for name in candidates:
        repo_path = f"files/{name}"
        local_path = os.path.join(FILES_FOLDER, name)
        ok, _err = download_file_from_github(repo_path, local_path)
        if ok and os.path.exists(local_path):
            return local_path, None, None

    return None, jsonify({
        "success": False,
        "error": "Match-Datei nicht gefunden (lokal & GitHub). Bitte zuerst Statistiken generieren."
    }), 400


# ----------------------------
# Team-Generator: Fuzzy-Mapping
# ----------------------------
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


# ----------------------------
# Filename Generation
# ----------------------------
def generate_filename(custom_name=None):
    """
    Generiert einen Dateinamen im Format YYYY_MM_DD_NN.txt
    """
    if custom_name:
        return custom_name if custom_name.endswith(".txt") else custom_name + ".txt"

    today = datetime.now().strftime("%Y_%m_%d")
    next_num = 1

    # Optional: schaut in GitHub wie viele Events es heute schon gibt
    try:
        token = os.environ.get("GITHUB_TOKEN")
        if token:
            headers = _github_headers(token)
            url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/events"
            response = requests.get(url, headers=headers, timeout=20)
            if response.status_code == 200 and isinstance(response.json(), list):
                files = response.json()
                today_files = [f for f in files if f.get("name", "").startswith(today)]
                next_num = len(today_files) + 1
    except Exception:
        next_num = 1

    return f"{today}_{next_num:02d}.txt"


# ----------------------------
# Pages
# ----------------------------
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/teams")
def teams_page():
    return render_template("teams.html")
    
@app.route("/dashboard")
def dashboard_page():
    return render_template("dashboard.html")


# ----------------------------
# Misc old route
# ----------------------------
@app.route("/run", methods=["POST"])
def run_script():
    players = [request.form.get(f"player{i}") for i in range(1, 11)]
    result = subprocess.run(
        ["python3", "run_script.py", CSV_PATH] + players,
        capture_output=True,
        text=True,
    )
    return result.stdout or "Script ausgeführt"


# ----------------------------
# Aliases / Suggestions
# ----------------------------
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


# ----------------------------
# VRFrag players from link
# ----------------------------
@app.route("/api/get-players", methods=["POST"])
def api_get_players():
    try:
        data = request.get_json()
        if not data or "game_link" not in data:
            return jsonify({"success": False, "error": "Kein game_link"}), 400

        game_link = data["game_link"]
        if not game_link.startswith("https://www.vrfrag.com/stats?"):
            return jsonify({"success": False, "error": "Ungültiger Link"}), 400

        players = get_players_from_url(game_link)
        if players is not None:
            return jsonify({"success": True, "players": players, "count": len(players)})
        return jsonify({"success": False, "error": "Konnte Spielerdaten nicht abrufen"}), 500

    except Exception as e:
        return jsonify({"success": False, "error": f"Server Fehler: {str(e)}"}), 500


# ----------------------------
# Save event: GitHub + local + generate stats + push CSVs to GitHub
# ----------------------------
@app.route("/api/save-to-github", methods=["POST"])
def api_save_to_github():
    """
    Speichert Event-Datei in GitHub UND lokal in ./events,
    führt generate_statistics lokal aus und pushed anschließend die CSVs nach GitHub (/files).
    """
    try:
        data = request.get_json()
        if not data or "game_link" not in data or "mappings" not in data:
            return jsonify({"success": False, "error": "Ungültige Daten"}), 400

        game_link = data["game_link"]
        mappings = data["mappings"]
        custom_filename = data.get("filename", "")

        # Dateiinhalt generieren
        content_lines = [game_link.strip()]
        for mapping in mappings:
            nick = (mapping.get("nickname") or "").strip()
            real = (mapping.get("realName") or mapping.get("real_name") or "").strip()
            if nick and real:
                content_lines.append(f"{nick}={real}")
        content = "\n".join(content_lines) + "\n"

        filename = generate_filename(custom_filename)

        # 1) Event nach GitHub pushen
        event_repo_path = f"events/{filename}"
        result = save_file_to_github(
            repo_path=event_repo_path,
            content=content,
            commit_message=f"Add event file: {filename}",
        )
        if not result.get("success"):
            return jsonify(result)

        # 2) Lokal speichern (damit generate_statistics sofort was sieht)
        try:
            local_path = save_event_locally(filename, content)
            result["local_saved"] = True
            result["local_path"] = local_path
        except Exception as e:
            result["local_saved"] = False
            result["local_error"] = str(e)

        # 3) Statistiken neu generieren (arbeitet auf ./events) + CSVs nach GitHub pushen
        try:
            stats = generate_statistics()
            result["statistics_result"] = stats
            result["statistics_updated"] = bool(stats.get("success", True))

            if isinstance(stats, dict) and stats.get("success"):
                pushed = push_statistics_csvs_to_github(stats)
                result["pushed_csvs"] = pushed

        except Exception as e:
            result["statistics_updated"] = False
            result["statistics_error"] = str(e)

        return jsonify(result)

    except Exception as e:
        return jsonify({"success": False, "error": f"Fehler: {str(e)}"}), 500


# ----------------------------
# List events on GitHub
# ----------------------------
@app.route("/api/list-events", methods=["GET"])
def api_list_events():
    try:
        token = os.environ.get("GITHUB_TOKEN")
        headers = {"Accept": "application/vnd.github.v3+json"}
        if token:
            headers = _github_headers(token)

        url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/events"
        response = requests.get(url, headers=headers, timeout=20)

        if response.status_code == 200:
            files = response.json()
            event_files = []
            for file in files:
                if file.get("name", "").endswith(".txt"):
                    event_files.append({
                        "filename": file.get("name"),
                        "download_url": file.get("download_url"),
                        "html_url": file.get("html_url"),
                        "size": file.get("size", 0),
                    })

            return jsonify({
                "success": True,
                "events": sorted(event_files, key=lambda x: x["filename"], reverse=True),
            })

        return jsonify({
            "success": False,
            "error": f"GitHub Fehler: {response.status_code} - {response.text}",
        }), 500

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ----------------------------
# Update stats manually: generate + push CSVs to GitHub
# ----------------------------
@app.route("/api/update-statistics", methods=["POST"])
def api_update_statistics():
    try:
        print("Starting statistics update...")
        result = generate_statistics()

        pushed = {}
        if isinstance(result, dict) and result.get("success"):
            pushed = push_statistics_csvs_to_github(result)

        if result.get("success"):
            return jsonify({
                "success": True,
                "message": result.get("message"),
                "player_count": result.get("player_count"),
                "match_count": result.get("match_count"),
                "unique_players": result.get("unique_players"),
                "players_file": os.path.basename(result.get("players_file", "")),
                "matches_file": os.path.basename(result.get("matches_file", "")),
                "pushed_csvs": pushed,
            })

        return jsonify({
            "success": False,
            "error": result.get("error", "Unbekannter Fehler"),
            "pushed_csvs": pushed,
        }), 500

    except Exception as e:
        return jsonify({
            "success": False,
            "error": f"Statistics generation failed: {str(e)}",
        }), 500


# ----------------------------
# Download/list stats files (local)
# ----------------------------
@app.route("/files/<filename>")
def download_file(filename):
    try:
        return send_from_directory(FILES_FOLDER, filename, as_attachment=True)
    except FileNotFoundError:
        return jsonify({"success": False, "error": "File not found"}), 404


@app.route("/api/list-files", methods=["GET"])
def api_list_files():
    try:
        files = []
        for filename in os.listdir(FILES_FOLDER):
            if filename.endswith(".csv"):
                filepath = os.path.join(FILES_FOLDER, filename)
                files.append({
                    "filename": filename,
                    "size": os.path.getsize(filepath),
                    "modified": datetime.fromtimestamp(os.path.getmtime(filepath)).isoformat(),
                })

        return jsonify({
            "success": True,
            "files": sorted(files, key=lambda x: x["modified"], reverse=True),
        })

    except Exception as e:
        return jsonify({"success": False, "error": f"Error listing files: {str(e)}"}), 500


# ----------------------------
# Team Generator API
# ----------------------------
@app.route("/api/generate-teams", methods=["POST"])
def api_generate_teams():
    try:
        data = request.get_json()
        if not data or "players" not in data:
            return jsonify({"success": False, "error": "Keine Spieler-Daten"}), 400

        selected_players = data["players"]
        selected_map = data.get("map", None)

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
                    "confidence": round(conf, 3),
                })

        selected_players = resolved_players

        # Load player data
        players_file, err_resp, code = ensure_players_csv()
        if err_resp:
            return err_resp, code

        players_df = pd.read_csv(players_file)

        from vrfrag_teams import generate_fair_teams
        result = generate_fair_teams(selected_players, players_df, selected_map)

        if isinstance(result, dict) and "error" in result:
            return jsonify({"success": False, "error": result["error"]}), 400

        return jsonify({
            "success": True,
            "teams": result,
            "resolved_players": selected_players,
            "unresolved": unresolved,
        })

    except Exception as e:
        return jsonify({"success": False, "error": f"Team-Generator Fehler: {str(e)}"}), 500


# ----------------------------
# Get all players for datalist
# ----------------------------
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


# ----------------------------
# Maps
# ----------------------------
@app.route("/api/get-available-maps", methods=["GET"])
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

# ----------------------------
# Dashboard helpers (PBIX-like)
# ----------------------------
GERMAN_MONTHS = {
    "januar": "01", "februar": "02", "märz": "03", "maerz": "03",
    "april": "04", "mai": "05", "juni": "06", "juli": "07",
    "august": "08", "september": "09", "oktober": "10",
    "november": "11", "dezember": "12",
}

def _parse_event_date(s: str):
    """
    Erwartet Strings wie: 'Freitag, 18. Juli 2025'
    Gibt datetime.date oder None zurück.
    """
    if not s:
        return None
    try:
        txt = str(s).strip()
        if "," in txt:
            txt = txt.split(",", 1)[1].strip()  # '18. Juli 2025'
        parts = txt.replace("  ", " ").split(" ")
        # ['18.', 'Juli', '2025']
        if len(parts) < 3:
            return None
        day = parts[0].replace(".", "").zfill(2)
        month_name = parts[1].strip().lower()
        month = GERMAN_MONTHS.get(month_name)
        year = parts[2].strip()
        if not month:
            return None
        return pd.to_datetime(f"{year}-{month}-{day}", errors="coerce").date()
    except Exception:
        return None

def _load_players_matches_merged():
    players_path, err, code = ensure_players_csv()
    if err:
        return None, None, err, code
    matches_path, err, code = ensure_matches_csv()
    if err:
        return None, None, err, code

    p = pd.read_csv(players_path)
    m = pd.read_csv(matches_path)

    # merge: matchNr + EventDate + EventTimeRange
    # (in deinen CSVs sind EventDate und EventTimeRange in beiden Files vorhanden)
    for col in ["EventDate", "EventTimeRange"]:
        if col not in p.columns:
            p[col] = None
        if col not in m.columns:
            m[col] = None

    merged = p.merge(
        m[["matchNr", "EventDate", "EventTimeRange", "maptitle"]],
        how="left",
        on=["matchNr", "EventDate", "EventTimeRange"],
    )

    merged["EventDateParsed"] = merged["EventDate"].apply(_parse_event_date)

    # robust types
    for c in ["kills", "assists", "deaths", "score"]:
        if c in merged.columns:
            merged[c] = pd.to_numeric(merged[c], errors="coerce").fillna(0)

    # KD pro Match (wie PowerBI Durchschnitt KD)
    merged["kd_match"] = merged.apply(
        lambda r: (r["kills"] / r["deaths"]) if r.get("deaths", 0) not in (0, None) else float(r.get("kills", 0)),
        axis=1
    )

    # MVP count
    if "isMVP" in merged.columns:
        merged["isMVP"] = merged["isMVP"].astype(str).str.lower().isin(["true", "1", "yes"])
    else:
        merged["isMVP"] = False

    # Winrate
    if "playerWon" in merged.columns:
        merged["playerWon"] = merged["playerWon"].astype(str).str.lower().isin(["true", "1", "yes"])
    else:
        merged["playerWon"] = False

    # Player column must exist
    if "Player" not in merged.columns:
        return None, None, jsonify({"success": False, "error": "Spalte 'Player' fehlt in Players-CSV."}), 500

    return merged, m, None, None


# ----------------------------
# Dashboard API
# ----------------------------
@app.get("/api/dashboard/filters")
def api_dashboard_filters():
    merged, _m, err, code = _load_players_matches_merged()
    if err:
        return err, code

    players = sorted([x for x in merged["Player"].dropna().astype(str).str.strip().unique().tolist() if x])
    maps = sorted([x for x in merged["maptitle"].dropna().astype(str).str.strip().unique().tolist() if x])

    return jsonify({"success": True, "players": players, "maps": maps})


@app.get("/api/dashboard/leaderboard")
def api_dashboard_leaderboard():
    """
    metric:
      - avg_kills
      - avg_score
      - total_kills
      - mvp_count
    """
    merged, _m, err, code = _load_players_matches_merged()
    if err:
        return err, code

    metric = (request.args.get("metric") or "").strip()
    limit = int(request.args.get("limit") or 20)

    g = merged.groupby("Player", dropna=True)

    if metric == "avg_kills":
        s = g["kills"].mean()
    elif metric == "avg_score":
        s = g["score"].mean()
    elif metric == "total_kills":
        s = g["kills"].sum()
    elif metric == "mvp_count":
        s = g["isMVP"].sum()
    else:
        return jsonify({"success": False, "error": "Unbekannte metric"}), 400

    s = s.sort_values(ascending=False).head(limit)

    rows = [{"player": idx, "value": float(val) if pd.notna(val) else 0.0} for idx, val in s.items()]
    return jsonify({"success": True, "metric": metric, "rows": rows})


@app.get("/api/dashboard/player-summary")
def api_dashboard_player_summary():
    merged, _m, err, code = _load_players_matches_merged()
    if err:
        return err, code

    player = (request.args.get("player") or "").strip()
    if not player:
        return jsonify({"success": False, "error": "player fehlt"}), 400

    mapname = (request.args.get("map") or "").strip()
    df = merged[merged["Player"].astype(str).str.strip() == player].copy()
    if mapname:
        df = df[df["maptitle"].astype(str).str.strip() == mapname]

    if df.empty:
        return jsonify({
            "avg_kills": 0, "avg_deaths": 0, "avg_assists": 0, "avg_kd": 0, "avg_score": 0,
            "total_games": 0, "winrate": 0, "mvp_count": 0,
            "sum_kills": 0, "sum_deaths": 0, "sum_assists": 0
        })

    # TotalGames = Anzahl unique Matches (matchNr + EventDate + EventTimeRange)
    df["matchKey"] = df["matchNr"].astype(str) + "|" + df["EventDate"].astype(str) + "|" + df["EventTimeRange"].astype(str)
    total_games = int(df["matchKey"].nunique())

    out = {
        "avg_kills": float(df["kills"].mean()),
        "avg_deaths": float(df["deaths"].mean()),
        "avg_assists": float(df["assists"].mean()),
        "avg_kd": float(df["kd_match"].mean()),
        "avg_score": float(df["score"].mean()),
        "total_games": total_games,
        "winrate": float(df["playerWon"].mean() * 100.0),
        "mvp_count": int(df["isMVP"].sum()),
        "sum_kills": int(df["kills"].sum()),
        "sum_deaths": int(df["deaths"].sum()),
        "sum_assists": int(df["assists"].sum()),
    }
    return jsonify(out)


@app.get("/api/dashboard/player-series")
def api_dashboard_player_series():
    merged, _m, err, code = _load_players_matches_merged()
    if err:
        return err, code

    player = (request.args.get("player") or "").strip()
    metric = (request.args.get("metric") or "").strip()
    mapname = (request.args.get("map") or "").strip()

    if not player:
        return jsonify({"success": False, "error": "player fehlt"}), 400
    if metric not in {"avg_kills", "avg_deaths", "avg_assists", "avg_kd", "avg_score"}:
        return jsonify({"success": False, "error": "metric ungültig"}), 400

    df = merged[merged["Player"].astype(str).str.strip() == player].copy()
    if mapname:
        df = df[df["maptitle"].astype(str).str.strip() == mapname]

    df = df[df["EventDateParsed"].notna()]
    if df.empty:
        return jsonify({"labels": [], "values": []})

    metric_col = {
        "avg_kills": "kills",
        "avg_deaths": "deaths",
        "avg_assists": "assists",
        "avg_kd": "kd_match",
        "avg_score": "score",
    }[metric]

    s = df.groupby("EventDateParsed")[metric_col].mean().sort_index()
    labels = [d.isoformat() for d in s.index.tolist()]
    values = [float(v) for v in s.values.tolist()]
    return jsonify({"labels": labels, "values": values})



if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
