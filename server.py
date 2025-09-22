from flask import Flask, request, send_from_directory
import subprocess
import os

app = Flask(__name__, static_folder='.')

CSV_PATH = os.path.join(os.path.dirname(__file__), 'data.csv')

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

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
