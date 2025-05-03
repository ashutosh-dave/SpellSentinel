# app.py - Flask + Socket.IO real-time log viewer

from flask import Flask, render_template
from flask_socketio import SocketIO
import threading
import time
import subprocess

app = Flask(__name__)
socketio = SocketIO(app)

@app.route('/')
def index():
    return render_template('index.html')

def stream_logs():
    with open('crawler.log', 'r') as log_file:
        log_file.seek(0, 2)  # Move to end of file
        while True:
            line = log_file.readline()
            if line:
                socketio.emit('log_update', {'log': line})
            else:
                time.sleep(0.5)

def run_crawler():
    subprocess.call(['python', 'spellcheck_crawler.py'])

if __name__ == '__main__':
    threading.Thread(target=stream_logs, daemon=True).start()
    threading.Thread(target=run_crawler, daemon=True).start()
    socketio.run(app, debug=True, port=5000)
