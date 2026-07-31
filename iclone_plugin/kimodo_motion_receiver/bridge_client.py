"""Command-line diagnostics client for Kimodo Motion Receiver."""

import argparse
import datetime
import json
import os
import socket
import uuid


TOKEN_FILE = os.path.join(
    os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
    "Kimodo Blender Bridge",
    "bridge-token.txt",
)


def _send(operation, arguments=None, mode="query", dry_run=False, session=None):
    with open(TOKEN_FILE, "r", encoding="ascii") as stream:
        token = stream.read().strip()
    deadline = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=160)
    payload = {
        "schema_version": 1,
        "request_id": str(uuid.uuid4()),
        "deadline_utc": deadline.isoformat().replace("+00:00", "Z"),
        "mode": mode,
        "operation": operation,
        "arguments": arguments or {},
        "dry_run": bool(dry_run),
        "token": token,
    }
    if session is not None:
        payload["session"] = session
    with socket.create_connection(("127.0.0.1", 18732), timeout=5.0) as connection:
        connection.sendall((json.dumps(payload) + "\n").encode("utf-8"))
        connection.settimeout(175.0)
        chunks = []
        while True:
            chunk = connection.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)
            if b"\n" in chunk:
                break
    return json.loads(b"".join(chunks).split(b"\n", 1)[0].decode("utf-8"))


def call(operation, arguments=None, mode="query", dry_run=False):
    session = None
    if mode != "query":
        handshake = _send("session.describe")
        if not handshake.get("ok"):
            return handshake
        live = handshake.get("result") or {}
        session = {
            "product": live.get("product"),
            "process_id": live.get("process_id"),
            "project_fingerprint": live.get("project_fingerprint"),
        }
    return _send(operation, arguments, mode, dry_run, session)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("operation")
    parser.add_argument("--mode", default="query", choices=("query", "mutate"))
    parser.add_argument("--arguments", default="{}", help="JSON object")
    parser.add_argument("--arguments-file", help="Path to a UTF-8 JSON object file")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.arguments_file:
        with open(args.arguments_file, "r", encoding="utf-8") as stream:
            arguments = json.load(stream)
    else:
        arguments = json.loads(args.arguments)
    if not isinstance(arguments, dict):
        parser.error("arguments must decode to a JSON object")
    response = call(args.operation, arguments, args.mode, args.dry_run)
    print(json.dumps(response, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
