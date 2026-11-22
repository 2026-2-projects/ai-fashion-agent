"""Local-only static frontend server and /api/v1 proxy (Python standard library)."""

import argparse
import http.client
import json
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parent
MAX_BODY = 16 * 1024 * 1024
HOP_HEADERS = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailer", "transfer-encoding", "upgrade",
}


class DevHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, api_port=8000, **kwargs):
        self.api_port = api_port
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def log_message(self, *_args):
        # Do not log cookies, tokens, request bodies, or query strings.
        pass

    def json_error(self, status, detail):
        body = json.dumps({"detail": detail}, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def dispatch(self):
        port = self.server.server_port
        allowed_hosts = {f"localhost:{port}", f"127.0.0.1:{port}"}
        hosts = self.headers.get_all("Host", [])
        if len(hosts) != 1 or hosts[0].lower() not in allowed_hosts:
            self.json_error(403, "로컬 개발 서버 주소로 접속해주세요.")
            return
        origin = self.headers.get("Origin")
        if origin and origin not in {f"http://{host}" for host in allowed_hosts}:
            self.json_error(403, "다른 출처의 요청은 허용하지 않습니다.")
            return
        try:
            url = urlsplit(self.path)
        except ValueError:
            self.json_error(400, "잘못된 요청 경로입니다.")
            return
        if url.scheme or url.netloc or not self.path.startswith("/"):
            self.json_error(400, "잘못된 요청 경로입니다.")
            return
        if url.path == "/api/v1" or url.path.startswith("/api/v1/"):
            self.proxy()
            return
        if self.command not in {"GET", "HEAD"}:
            self.json_error(405, "이 경로에서는 조회만 가능합니다.")
            return
        decoded = unquote(url.path)
        parts = decoded.split("/")
        if "\x00" in decoded or "\\" in decoded or any(
            part.startswith(".") or part == "__pycache__" for part in parts if part
        ):
            self.json_error(404, "파일을 찾을 수 없습니다.")
            return
        target = (ROOT / decoded.lstrip("/")).resolve()
        if not target.is_relative_to(ROOT) or target.suffix in {".py", ".pyc"}:
            self.json_error(404, "파일을 찾을 수 없습니다.")
            return
        if self.command == "HEAD":
            super().do_HEAD()
        else:
            super().do_GET()

    def list_directory(self, _path):
        self.json_error(404, "파일을 찾을 수 없습니다.")
        return None

    def proxy(self):
        lengths = self.headers.get_all("Content-Length", [])
        if self.headers.get("Transfer-Encoding") or len(lengths) > 1:
            self.json_error(400, "지원하지 않는 요청 본문 형식입니다.")
            return
        try:
            length = int(lengths[0]) if lengths else 0
        except ValueError:
            self.json_error(400, "잘못된 요청 크기입니다.")
            return
        if length < 0 or length > MAX_BODY:
            self.json_error(413, "요청 크기는 16 MiB 이하여야 합니다.")
            return
        self.connection.settimeout(30)
        try:
            body = self.rfile.read(length) if length else None
        except (OSError, TimeoutError):
            self.json_error(408, "요청 본문을 받는 시간이 초과되었습니다.")
            return
        if body is not None and len(body) != length:
            self.json_error(400, "요청 본문을 모두 받지 못했습니다.")
            return

        nominated = {
            value.strip().lower()
            for value in self.headers.get("Connection", "").split(",")
        }
        excluded = HOP_HEADERS | nominated | {"host", "content-length", "accept-encoding"}
        headers = {key: value for key, value in self.headers.items() if key.lower() not in excluded}
        headers["Accept-Encoding"] = "identity"
        upstream = http.client.HTTPConnection("127.0.0.1", self.api_port, timeout=120)
        try:
            upstream.request(self.command, self.path, body=body, headers=headers)
            response = upstream.getresponse()
            payload = response.read()
            status = response.status
            response_headers = response.getheaders()
        except (OSError, http.client.HTTPException):
            self.json_error(502, "백엔드 서버에 연결할 수 없습니다. 8000번 서버 실행 상태를 확인해주세요.")
            return
        finally:
            upstream.close()

        excluded = HOP_HEADERS | {"content-length", "cache-control"}
        for key, value in response_headers:
            if key.lower() == "connection":
                excluded.update(part.strip().lower() for part in value.split(","))
        self.send_response(status)
        for key, value in response_headers:
            if key.lower() not in excluded:
                # Iterate the list to preserve repeated Set-Cookie headers.
                self.send_header(key, value)
        self.send_header("Cache-Control", "no-store")
        if status not in {204, 304}:
            content_length = str(len(payload))
            if self.command == "HEAD":
                content_length = response.getheader("Content-Length", content_length)
            self.send_header("Content-Length", content_length)
        self.end_headers()
        if self.command != "HEAD" and status not in {204, 304}:
            self.wfile.write(payload)

    do_GET = dispatch
    do_HEAD = dispatch
    do_POST = dispatch
    do_PUT = dispatch
    do_PATCH = dispatch
    do_DELETE = dispatch
    do_OPTIONS = dispatch


def port_number(value):
    port = int(value)
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("포트는 1~65535 범위여야 합니다.")
    return port


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=port_number, default=5500)
    parser.add_argument("--api-port", type=port_number, default=8000)
    args = parser.parse_args()
    if args.port == args.api_port:
        parser.error("프론트엔드와 백엔드 포트는 서로 달라야 합니다.")
    handler = partial(DevHandler, api_port=args.api_port)
    try:
        server = ThreadingHTTPServer(("127.0.0.1", args.port), handler)
    except OSError as error:
        parser.exit(1, f"개발 서버를 시작할 수 없습니다: {error}\n")
    print(f"Frontend: http://localhost:{args.port}", flush=True)
    print(f"API proxy: /api/v1/* -> http://127.0.0.1:{args.api_port}", flush=True)
    print("로컬 개발 전용 서버입니다. 종료: Ctrl+C", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
