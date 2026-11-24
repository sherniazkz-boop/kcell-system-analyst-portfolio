"""Local service request demo with a JSON API and SQLite storage."""

import argparse
from contextlib import closing
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sqlite3
from urllib.parse import urlsplit
from uuid import UUID, uuid4


ROOT = Path(__file__).resolve().parent
APPLICATIONS = "/api/applications"
SERVICE_TYPES = {"home_internet", "esim"}
MAX_ALIAS_LENGTH = 60
MAX_BODY_BYTES = 8192
SAMPLE_APPLICATION_ID = "00000000-0000-4000-8000-000000000001"

ASSETS = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/styles.css": ("styles.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
}


def prepare_database(database):
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS applications (
                id TEXT PRIMARY KEY,
                applicant_alias TEXT NOT NULL,
                service_type TEXT NOT NULL,
                status TEXT NOT NULL CHECK (status IN ('RECEIVED', 'IN_REVIEW', 'CONNECTED')),
                created_at TEXT NOT NULL
            )
        """)
        connection.executemany("""
            INSERT INTO applications (id, applicant_alias, service_type, status, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(id) DO NOTHING
        """, [
            (SAMPLE_APPLICATION_ID, "Тестовый клиент", "home_internet", "IN_REVIEW", "2026-01-01T09:00:00Z"),
            ("00000000-0000-4000-8000-000000000002", "Демо eSIM", "esim", "CONNECTED", "2026-01-01T09:05:00Z"),
        ])


class DemoHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = urlsplit(self.path).path
        if path in ASSETS:
            filename, content_type = ASSETS[path]
            self.send_content(HTTPStatus.OK, (ROOT / "ui" / filename).read_bytes(), content_type)
            return

        if not path.startswith(APPLICATIONS + "/"):
            self.send_error_json(HTTPStatus.NOT_FOUND, "NOT_FOUND", "Страница не найдена.")
            return

        application_id = path.removeprefix(APPLICATIONS + "/")
        try:
            application_id = str(UUID(application_id))
        except ValueError:
            self.send_error_json(HTTPStatus.BAD_REQUEST, "INVALID_ID", "Проверьте формат номера заявки.")
            return

        with closing(sqlite3.connect(self.server.database)) as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute("""
                SELECT id, service_type, status, created_at
                FROM applications
                WHERE id = ?
            """, (application_id,)).fetchone()

        if row is None:
            self.send_error_json(HTTPStatus.NOT_FOUND, "APPLICATION_NOT_FOUND", "Заявка с таким номером не найдена.")
            return
        self.send_json(HTTPStatus.OK, dict(row))

    def do_POST(self):
        if urlsplit(self.path).path != APPLICATIONS:
            self.send_error_json(HTTPStatus.NOT_FOUND, "NOT_FOUND", "Маршрут не найден.")
            return
        if self.headers.get_content_type() != "application/json":
            self.send_error_json(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "UNSUPPORTED_MEDIA_TYPE", "Ожидается JSON.")
            return
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            content_length = 0
        if content_length > MAX_BODY_BYTES:
            self.send_error_json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "BODY_TOO_LARGE", "Запрос слишком большой.")
            return
        try:
            if content_length < 1:
                raise ValueError
            data = json.loads(self.rfile.read(content_length).decode("utf-8"))
            if not isinstance(data, dict):
                raise ValueError
        except ValueError:
            self.send_error_json(HTTPStatus.BAD_REQUEST, "INVALID_JSON", "Ожидается JSON-объект.")
            return

        fields = {}
        alias = data.get("applicant_alias")
        service_type = data.get("service_type")
        alias = alias.strip() if isinstance(alias, str) else ""
        if not 1 <= len(alias) <= MAX_ALIAS_LENGTH or not alias.isprintable():
            fields["applicant_alias"] = f"Укажите псевдоним длиной от 1 до {MAX_ALIAS_LENGTH} символов."
        if not isinstance(service_type, str) or service_type not in SERVICE_TYPES:
            fields["service_type"] = "Выберите одну из доступных услуг."
        if fields:
            self.send_error_json(HTTPStatus.UNPROCESSABLE_ENTITY, "VALIDATION_ERROR", "Проверьте поля заявки.", fields)
            return

        application = {
            "id": str(uuid4()),
            "service_type": service_type,
            "status": "RECEIVED",
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        }
        with closing(sqlite3.connect(self.server.database)) as connection, connection:
            connection.execute("""
                INSERT INTO applications (id, applicant_alias, service_type, status, created_at)
                VALUES (?, ?, ?, ?, ?)
            """, (application["id"], alias, service_type, application["status"], application["created_at"]))
        self.send_json(HTTPStatus.CREATED, application, location=f'{APPLICATIONS}/{application["id"]}')

    def send_error_json(self, status, code, message, fields=None):
        error = {"code": code, "message": message}
        if fields:
            error["fields"] = fields
        self.send_json(status, {"error": error})

    def send_json(self, status, value, location=None):
        content = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_content(status, content, "application/json; charset=utf-8", location)

    def send_content(self, status, content, content_type, location=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        if location:
            self.send_header("Location", location)
        self.end_headers()
        self.wfile.write(content)


def make_server(database, port):
    prepare_database(database)
    server = ThreadingHTTPServer(("127.0.0.1", port), DemoHandler)
    server.database = database
    return server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--database", type=Path, default=ROOT / "applications.sqlite3")
    args = parser.parse_args()
    with make_server(args.database, args.port) as server:
        print(f"Демо открыто на http://127.0.0.1:{server.server_port}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
