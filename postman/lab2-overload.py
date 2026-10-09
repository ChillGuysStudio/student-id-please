#!/usr/bin/env python3
"""Bounded localhost-only Gateway concurrency demonstration for Postman step 28.

Opens 100 incomplete registration bodies (no registrations are committed),
confirms that the 101st request receives 503 TASK_LIMIT_EXCEEDED, then briefly
keeps the slots occupied for the presenter's Postman request. No credentials.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import http.client
import json
import socket
import sys
import time

HOST = '127.0.0.1'
PORT = 18080
CAPACITY = 100
WIRE = (b'POST /api/v1/players HTTP/1.1\r\n'
        b'Host: 127.0.0.1\r\nContent-Type: application/json\r\n'
        b'Content-Length: 2\r\nConnection: close\r\n\r\n{')


def occupy(_):
    connection = socket.create_connection((HOST, PORT), timeout=2)
    connection.settimeout(2)
    connection.sendall(WIRE)
    return connection


def check_overload():
    connection = http.client.HTTPConnection(HOST, PORT, timeout=3)
    try:
        connection.request('GET', '/api/v1/players/me')
        response = connection.getresponse()
        body = json.loads(response.read(2048))
        return response.status == 503 and body.get('code') == 'TASK_LIMIT_EXCEEDED' and response.getheader('Retry-After') == '1'
    except (OSError, ValueError, TypeError):
        return False
    finally:
        connection.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--hold-seconds', type=float, default=6.0,
                        help='Seconds to keep all 100 slots occupied after READY (1–7; default 6)')
    args = parser.parse_args()
    if not 1 <= args.hold_seconds <= 7:
        parser.error('hold-seconds must be between 1 and 7')
    sockets = []
    try:
        started = time.monotonic()
        with ThreadPoolExecutor(max_workers=32) as pool:
            for connection in pool.map(occupy, range(CAPACITY)):
                sockets.append(connection)
        if time.monotonic()-started > 3:
            raise RuntimeError('Could not fill all slots promptly; try again when host is idle')
        # Accepting TCP sockets precedes admission; give Go's HTTP workers a
        # moment to parse all 100 headers before checking the 101st request.
        time.sleep(0.2)
        if not check_overload():
            raise RuntimeError('Capacity rejection not observed; do not claim a successful limit demo')
        print('READY: 100 live task slots occupied; independent request received 503 TASK_LIMIT_EXCEEDED. Click Send on Postman step 28 NOW.', flush=True)
        time.sleep(args.hold_seconds)
        print('DONE: releasing all slots. Send Postman step 29 next.', flush=True)
    finally:
        for connection in sockets:
            connection.close()


if __name__ == '__main__':
    try:
        main()
    except (OSError, RuntimeError) as error:
        print('NOT READY:', str(error), file=sys.stderr)
        raise SystemExit(1)
