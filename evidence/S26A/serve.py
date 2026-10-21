"""Local UI evidence server: python serve.py <db> <port>"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from apps.compass.web import create_app
from waitress import serve
serve(create_app(sys.argv[1]), host='127.0.0.1', port=int(sys.argv[2]), threads=4)
