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
    for command in ('migrate', 'seed-demo', 'seed-accounts', 'status', 'delivery-status'):
        commands.add_parser(command)
    worker = commands.add_parser('worker')
    worker.add_argument('--once', action='store_true')
    for reserve_command in ('reserve-macos','reserve-console'):
        reserve = commands.add_parser(reserve_command)
        reserve.add_argument('--recipient', required=True, help='Doctor ID on this local demo workstation')
        reserve.add_argument('--once', action='store_true')
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
        elif args.command == 'seed-accounts':
            from .access import seed_accounts
            print(json.dumps(seed_accounts(db), ensure_ascii=False, indent=2))
        elif args.command == 'delivery-status':
            from .critical_delivery import status
            print(json.dumps(status(db), ensure_ascii=False, indent=2))
        elif args.command == 'status':
            print(json.dumps(health(db), ensure_ascii=False))
        elif args.command in ('reserve-macos','reserve-console'):
            from .critical_delivery import reserve_one, console_signal
            while True:
                processed = reserve_one(db, args.recipient, sender=console_signal if args.command == 'reserve-console' else None, channel=args.command)
                if args.once:
                    break
                if not processed:
                    time.sleep(1)
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
