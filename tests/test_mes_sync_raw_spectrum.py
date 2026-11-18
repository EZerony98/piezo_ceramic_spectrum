import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mes_sync import MesSyncClient


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class MesRawSpectrumUploadTests(unittest.TestCase):
    def test_record_upload_is_followed_by_raw_file_upload(self):
        with tempfile.TemporaryDirectory() as directory:
            raw_path = Path(directory) / "spectrum_motor01.csv"
            raw_path.write_bytes(b"frequency_hz,amplitude\n100,0.125\n")
            item = {
                "outbox_id": "outbox-1",
                "entity_type": "spectrum_result",
                "entity_id": "record-1",
                "payload": {
                    "record_id": "record-1",
                    "measurements": {
                        "spectrum_rms_mm_s2": 1.25,
                        "raw_spectrum_path": str(raw_path),
                    },
                },
            }
            requests = []

            def fake_urlopen(request, timeout):
                requests.append(request)
                if len(requests) == 1:
                    return FakeResponse({"id": 42, "server_received_at": "2026-09-01T00:00:00Z"})
                return FakeResponse({"station_record_id": 42})

            client = MesSyncClient({"enabled": True, "base_url": "http://mes.local:8000"})
            with patch("mes_sync.urlopen", side_effect=fake_urlopen):
                response = client.upload_outbox_item(item, "SPECTRUM_01")

            self.assertEqual(response["id"], 42)
            self.assertEqual(len(requests), 2)
            posted_record = json.loads(requests[0].data.decode("utf-8"))
            self.assertNotIn("raw_spectrum_path", posted_record["payload"]["measurements"])
            self.assertIn("/api/test-records/42/raw-spectrum", requests[1].full_url)
            self.assertEqual(requests[1].data, raw_path.read_bytes())

    def test_raw_file_upload_falls_back_to_matching_export_filename(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            expected_path = root / "exports" / "C68" / "26年09月11日" / "spectrum_raw" / "spectrum_motor01.csv"
            actual_path = root / "exports" / "C68" / "26年09月10日" / "spectrum_raw" / "spectrum_motor01.csv"
            actual_path.parent.mkdir(parents=True)
            actual_path.write_bytes(b"frequency_hz,amplitude\n100,0.25\n")
            requests = []

            def fake_urlopen(request, timeout):
                requests.append(request)
                return FakeResponse({"station_record_id": 42})

            client = MesSyncClient({"enabled": True, "base_url": "http://mes.local:8000"})
            with patch("mes_sync.urlopen", side_effect=fake_urlopen):
                client.upload_raw_spectrum(42, str(expected_path))

            self.assertEqual(len(requests), 1)
            self.assertIn("filename=spectrum_motor01.csv", requests[0].full_url)
            self.assertEqual(requests[0].data, actual_path.read_bytes())


if __name__ == "__main__":
    unittest.main()
