import argparse
import json
import os
import time

from .db import connect, health, migrate
from .events import process_one
from .repository import seed_demo


def main():
    parser = argparse.ArgumentParser(description='Clinical Compass synthetic demo')
    parser.add_argument('--db', default=os.environ.get('COMPASS_DB', 'var/compass.sqlite3'))
    commands = parser.add_subparsers(dest='command', required=True)
    for command in ('migrate', 'seed-demo', 'status'):
        commands.add_parser(command)
    worker = commands.add_parser('worker')
    worker.add_argument('--once', action='store_true')
    serve = commands.add_parser('serve')
    serve.add_argument('--host', choices=['127.0.0.1', '0.0.0.0'], default='127.0.0.1')
    serve.add_argument('--port', type=int, default=8000)
    args = parser.parse_args()
    if args.command == 'serve':
        from waitress import serve as run_server
        from .web import create_app
        run_server(create_app(args.db), host=args.host, port=args.port, threads=4)
        return
    db = connect(args.db)
    try:
        migrate(db)
        if args.command == 'seed-demo':
            seed_demo(db)
        elif args.command == 'status':
            print(json.dumps(health(db), ensure_ascii=False))
        elif args.command == 'worker':
            while True:
                processed = process_one(db)
                if args.once and not processed:
                    break
                if not processed:
                    time.sleep(1)
    finally:
        db.close()


if __name__ == '__main__':
    main()
