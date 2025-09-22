from flask import Flask, request, send_from_directory, jsonify
import subprocess
import os
import requests
import base64
from datetime import datetime
from get_players import get_players_from_url
from player_stats import generate_statistics  # Neue Import

app = Flask(__name__, static_folder='.')

CSV_PATH = os.path.join(os.path.dirname(__file__), 'data.csv')
FILES_FOLDER = os.path.join(os.path.dirname(__file__), 'files')

# Stelle sicher, dass der files Ordner existiert
os.makedirs(FILES_FOLDER, exist_ok=True)

# ... (deine bestehenden Routes bleiben gleich) ...

@app.route('/api/update-statistics', methods=['POST'])
def api_update_statistics():
    """
    Neue API-Route zum Aktualisieren der Statistiken
    """
    try:
        print("Starting statistics update...")
        
        # Statistiken generieren
        result = generate_statistics()
        
        if result['success']:
            return jsonify({
                'success': True,
                'message': result['message'],
                'player_count': result['player_count'],
                'match_count': result['match_count'],
                'unique_players': result['unique_players'],
                'players_file': os.path.basename(result['players_file']),
                'matches_file': os.path.basename(result['matches_file'])
            })
        else:
            return jsonify({
                'success': False,
                'error': result['error']
            }), 500
            
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Statistics generation failed: {str(e)}'
        }), 500

@app.route('/files/<filename>')
def download_file(filename):
    """
    Ermöglicht das Herunterladen von Statistik-Dateien
    """
    try:
        return send_from_directory(FILES_FOLDER, filename, as_attachment=True)
    except FileNotFoundError:
        return jsonify({'success': False, 'error': 'File not found'}), 404

@app.route('/api/list-files', methods=['GET'])
def api_list_files():
    """
    Liste aller verfügbaren Statistik-Dateien
    """
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

# ... (rest deiner server.py) ...
