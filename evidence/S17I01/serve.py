"""Local UI evidence server with optional baseline template override."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from apps.compass.web import create_app
from jinja2 import ChoiceLoader,FileSystemLoader
from waitress import serve
app=create_app(sys.argv[1])
if len(sys.argv)>3:app.jinja_loader=ChoiceLoader([FileSystemLoader(sys.argv[3]),app.jinja_loader])
serve(app,host='127.0.0.1',port=int(sys.argv[2]),threads=4)
