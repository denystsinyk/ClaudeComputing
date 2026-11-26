"""Loopback-only HTTP adapter for local API development."""

import json
import os
import secrets
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from backend.api import MAX_REQUEST_BYTES, Api, Response, TokenAuth
from backend.execution import JobLifecycle, LocalDispatcher
from backend.jobs import JobStore, LocalDockerExecutor
from backend.submissions import LocalSubmissionStore


def create_server(api: Api, port: int = 8080) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def _respond(self, response: Response) -> None:
            data = json.dumps(response.payload).encode("utf-8")
            self.send_response(response.status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:
            path = urlsplit(self.path).path
            self._respond(api.handle("GET", path, self.headers.get("Authorization")))

        def do_POST(self) -> None:
            path = urlsplit(self.path).path
            authorization = self.headers.get("Authorization")
            if api.auth.user_id(authorization) is None:
                self.close_connection = True
                self._respond(Response(401, {"error": {"code": "unauthorized"}}))
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                length = -1
            if length < 0 or length > MAX_REQUEST_BYTES:
                self.close_connection = True
                self._respond(Response(400, {"error": {"code": "request_too_large"}}))
                return
            body = self.rfile.read(length)
            self._respond(api.handle("POST", path, authorization, body))

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def main() -> None:
    token = os.environ.get("SUDOSOLVER_LOCAL_TOKEN") or secrets.token_urlsafe(32)
    port = int(os.environ.get("SUDOSOLVER_PORT", "8080"))
    examples = Path(__file__).resolve().parents[1] / "examples"
    database = Path(
        os.environ.get(
            "SUDOSOLVER_LOCAL_DB", str(Path(__file__).parent / ".local/submissions.sqlite3")
        )
    )
    with ThreadPoolExecutor(max_workers=2) as scheduler:
        lifecycle = JobLifecycle(JobStore(), LocalSubmissionStore(database))
        api = Api(
            examples,
            TokenAuth({token: "local-dev"}),
            lifecycle,
            LocalDispatcher(LocalDockerExecutor(), scheduler, lifecycle),
        )
        server = create_server(api, port)
        print(f"Local API: http://127.0.0.1:{server.server_port}", flush=True)
        print(f"Local bearer token: {token}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()


if __name__ == "__main__":
    main()
