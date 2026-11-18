"""MES heartbeat and reliable outbox upload over the factory LAN."""

import json
import os
import socket
import hashlib
from pathlib import Path
from typing import Any, Dict
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


class MesSyncClient:
    def __init__(self, config: Dict[str, Any]) -> None:
        self.config = dict(config or {})

    @property
    def enabled(self) -> bool:
        base_url = str(self.config.get("base_url", "")).strip()
        return bool(self.config.get("enabled", False) and base_url)

    def _post(self, path_key: str, default_path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        base_url = str(self.config.get("base_url", "")).rstrip("/")
        path = str(self.config.get(path_key, default_path)).lstrip("/")
        headers = {"Content-Type": "application/json; charset=utf-8"}
        api_token = os.getenv(
            "MES_API_TOKEN", str(self.config.get("api_token", ""))
        ).strip()
        if api_token:
            headers["Authorization"] = f"Bearer {api_token}"
        request = Request(
            f"{base_url}/{path}",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urlopen(request, timeout=float(self.config.get("timeout_seconds", 3))) as response:
                body = response.read().decode("utf-8")
                return json.loads(body) if body else {}
        except HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"MES HTTP {error.code}: {detail}") from error
        except (URLError, TimeoutError, OSError) as error:
            raise RuntimeError(f"MES 无法连接: {error}") from error

    def heartbeat(self, station_code: str, connected: bool, status: str, metadata: Dict[str, Any]) -> Dict[str, Any]:
        return self._post(
            "heartbeat_path",
            "/api/stations/heartbeat",
            {
                "station_code": station_code,
                "connected": connected,
                "status": status,
                "source_app": "贝丰频谱分析系统",
                "host_name": socket.gethostname(),
                "metadata": metadata,
            },
        )

    def upload_outbox_item(self, item: Dict[str, Any], station_code: str) -> Dict[str, Any]:
        payload = dict(item.get("payload") or {})
        measurements = dict(payload.get("measurements") or {})
        raw_spectrum_path = str(measurements.pop("raw_spectrum_path", "") or "").strip()
        if measurements:
            payload["measurements"] = measurements
        response = self._post(
            "upload_path",
            "/api/test-records",
            {
                "outbox_id": item.get("outbox_id"),
                "entity_type": item.get("entity_type"),
                "entity_id": item.get("entity_id"),
                "station_code": station_code,
                "source_app": "贝丰频谱分析系统",
                "actor": "spectrum-upper-computer",
                "payload": payload,
            },
        )
        if raw_spectrum_path:
            self.upload_raw_spectrum(int(response["id"]), raw_spectrum_path)
        return response

    def upload_raw_spectrum(self, record_id: int, file_path: str) -> Dict[str, Any]:
        path = self._resolve_raw_spectrum_path(file_path)
        if not path.is_file():
            raise RuntimeError(f"原始频谱文件不存在: {path}")
        content = path.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        base_url = str(self.config.get("base_url", "")).rstrip("/")
        path_template = str(
            self.config.get(
                "raw_spectrum_upload_path",
                "/api/test-records/{record_id}/raw-spectrum",
            )
        )
        upload_path = path_template.format(record_id=int(record_id)).lstrip("/")
        api_token = os.getenv(
            "MES_API_TOKEN", str(self.config.get("api_token", ""))
        ).strip()
        headers = {
            "Content-Type": "text/csv",
            "X-Content-SHA256": digest,
        }
        if api_token:
            headers["Authorization"] = f"Bearer {api_token}"
        request = Request(
            f"{base_url}/{upload_path}?filename={quote(path.name)}",
            data=content,
            headers=headers,
            method="POST",
        )
        try:
            timeout = float(self.config.get("raw_upload_timeout_seconds", 30))
            with urlopen(request, timeout=timeout) as response:
                body = response.read().decode("utf-8")
                return json.loads(body) if body else {}
        except HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"MES原始频谱上传 HTTP {error.code}: {detail}") from error
        except (URLError, TimeoutError, OSError) as error:
            raise RuntimeError(f"MES原始频谱上传失败: {error}") from error

    def _resolve_raw_spectrum_path(self, file_path: str) -> Path:
        path = Path(file_path)
        if path.is_file():
            return path

        search_root = None
        for parent in path.parents:
            if parent.name == "exports":
                search_root = parent
                break
        if search_root is None or not search_root.exists():
            return path

        matches = [candidate for candidate in search_root.rglob(path.name) if candidate.is_file()]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise RuntimeError(f"原始频谱文件名重复，无法确定上传哪一个: {path.name}")
        return path


def sync_once(client: MesSyncClient, store: Any, station_code: str, connected: bool, status: str, metadata: Dict[str, Any]) -> Dict[str, Any]:
    """Send one heartbeat and drain a bounded batch from the local outbox."""
    if not client.enabled:
        return {"enabled": False, "uploaded": 0, "failed": 0}

    client.heartbeat(station_code, connected, status, metadata)
    uploaded = 0
    failed = 0
    last_error = ""
    for item in store.pending_uploads(limit=int(client.config.get("batch_size", 50))):
        try:
            response = client.upload_outbox_item(item, station_code)
            store.mark_upload_succeeded(
                item["outbox_id"],
                response.get("server_received_at"),
            )
            uploaded += 1
        except Exception as error:
            failed += 1
            last_error = str(error)
            store.mark_upload_failed(item["outbox_id"], last_error)
    return {"enabled": True, "uploaded": uploaded, "failed": failed, "last_error": last_error}
