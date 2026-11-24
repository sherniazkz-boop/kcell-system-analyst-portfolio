from contextlib import closing
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from threading import Thread
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from demo.server import APPLICATIONS, SAMPLE_APPLICATION_ID, make_server, prepare_database


class ApplicationDemoTest(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(TemporaryDirectory())
        self.database = Path(directory) / "test.sqlite3"
        self.server = self.enterContext(make_server(self.database, 0))
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"
        self.thread = Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.01})
        self.thread.start()
        self.addCleanup(self.thread.join)
        self.addCleanup(self.server.shutdown)

    def request(self, path, data=None, content_type="application/json"):
        request = Request(self.base_url + path, data=data, headers={"Content-Type": content_type})
        try:
            response = urlopen(request, timeout=5)
        except HTTPError as error:
            response = error
        with response:
            content = response.read().decode()
            if response.headers.get_content_type() == "application/json":
                content = json.loads(content)
            return response.status, response.headers, content

    def post(self, payload):
        return self.request(APPLICATIONS, json.dumps(payload).encode("utf-8"))

    def test_create_and_find_application(self):
        code, headers, created = self.post({"applicant_alias": "  Демо-клиент ", "service_type": "esim"})
        self.assertEqual(code, 201)
        self.assertEqual(headers["Location"], f'{APPLICATIONS}/{created["id"]}')
        self.assertEqual(created["status"], "RECEIVED")
        self.assertEqual(created["service_type"], "esim")
        self.assertTrue(created["created_at"].endswith("Z"))
        with closing(sqlite3.connect(self.database)) as connection:
            stored_alias, = connection.execute(
                "SELECT applicant_alias FROM applications WHERE id = ?", (created["id"],)
            ).fetchone()
        self.assertEqual(stored_alias, "Демо-клиент")
        prepare_database(self.database)
        code, _, loaded = self.request(headers["Location"])
        self.assertEqual(code, 200)
        self.assertEqual(loaded, created)
        self.assertNotIn("applicant_alias", loaded)

    def test_missing_and_invalid_fields_do_not_create_rows(self):
        cases = [
            ({}, {"applicant_alias", "service_type"}),
            ({"applicant_alias": " ", "service_type": "esim"}, {"applicant_alias"}),
            ({"applicant_alias": "x" * 61, "service_type": "esim"}, {"applicant_alias"}),
            ({"applicant_alias": "Демо", "service_type": ["esim"]}, {"service_type"}),
        ]
        for payload, fields in cases:
            with self.subTest(payload=payload):
                code, _, body = self.post(payload)
                self.assertEqual(code, 422)
                self.assertEqual(body["error"]["code"], "VALIDATION_ERROR")
                self.assertEqual(set(body["error"]["fields"]), fields)
        with closing(sqlite3.connect(self.database)) as connection:
            count, = connection.execute("SELECT COUNT(*) FROM applications").fetchone()
        self.assertEqual(count, 2)

    def test_find_sample_and_unknown_application(self):
        code, _, sample = self.request(f"{APPLICATIONS}/{SAMPLE_APPLICATION_ID}")
        self.assertEqual(code, 200)
        self.assertEqual(sample["status"], "IN_REVIEW")
        code, _, body = self.request(f"{APPLICATIONS}/00000000-0000-4000-8000-000000000003")
        self.assertEqual(code, 404)
        self.assertEqual(body["error"]["code"], "APPLICATION_NOT_FOUND")
        code, _, body = self.request(f"{APPLICATIONS}/123")
        self.assertEqual(code, 400)
        self.assertEqual(body["error"]["code"], "INVALID_ID")

    def test_reject_non_json_and_malformed_json(self):
        code, _, body = self.request(APPLICATIONS, b"{")
        self.assertEqual(code, 400)
        self.assertEqual(body["error"]["code"], "INVALID_JSON")
        code, _, body = self.request(APPLICATIONS, b"{}", "text/plain")
        self.assertEqual(code, 415)
        self.assertEqual(body["error"]["code"], "UNSUPPORTED_MEDIA_TYPE")

    def test_status_counts_on_demo_database(self):
        code, _, _ = self.post({"applicant_alias": "Демо", "service_type": "home_internet"})
        self.assertEqual(code, 201)
        query = Path("demo/status_counts.sql").read_text(encoding="utf-8")
        with closing(sqlite3.connect(self.database)) as connection:
            result = dict(connection.execute(query).fetchall())
        self.assertEqual(result, {"CONNECTED": 1, "IN_REVIEW": 1, "RECEIVED": 1})

    def test_frontend_and_assets_are_served(self):
        code, _, page = self.request("/")
        self.assertEqual(code, 200)
        self.assertIn("Заявка на подключение услуги", page)
        for asset in ("/styles.css", "/app.js"):
            with self.subTest(asset=asset):
                code, _, _ = self.request(asset)
                self.assertEqual(code, 200)


if __name__ == "__main__":
    unittest.main()
