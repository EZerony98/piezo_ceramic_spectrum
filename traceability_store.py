"""频谱电脑的托盘映射副本与频谱结果本地存储。"""

import json
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path


class ProductMappingNotFoundError(LookupError):
    pass


def local_timestamp():
    return datetime.now().astimezone().isoformat(timespec="seconds")


class TraceabilityStore:
    def __init__(self, database_path):
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize_schema()

    def _connect(self):
        connection = sqlite3.connect(str(self.database_path), timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def _initialize_schema(self):
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS tray_cycles (
                    tray_cycle_id TEXT PRIMARY KEY,
                    tray_id TEXT NOT NULL,
                    loaded_at TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    received_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_tray_cycles_active
                ON tray_cycles(tray_id, status, loaded_at);

                CREATE TABLE IF NOT EXISTS tray_products (
                    tray_cycle_id TEXT NOT NULL,
                    tray_id TEXT NOT NULL,
                    tray_slot INTEGER NOT NULL CHECK(tray_slot BETWEEN 1 AND 10),
                    product_sn TEXT NOT NULL,
                    scanned_at TEXT NOT NULL,
                    PRIMARY KEY (tray_cycle_id, tray_slot),
                    UNIQUE (tray_cycle_id, product_sn),
                    FOREIGN KEY (tray_cycle_id)
                        REFERENCES tray_cycles(tray_cycle_id)
                        ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_tray_products_lookup
                ON tray_products(tray_id, tray_slot, scanned_at);

                CREATE TABLE IF NOT EXISTS spectrum_results (
                    record_id TEXT PRIMARY KEY,
                    tray_cycle_id TEXT NOT NULL,
                    tray_id TEXT NOT NULL,
                    tray_slot INTEGER NOT NULL CHECK(tray_slot BETWEEN 1 AND 10),
                    product_sn TEXT NOT NULL,
                    station_code TEXT NOT NULL,
                    spectrum_rms_mm_s2 REAL,
                    spectrum_vpp_mm_s2 REAL,
                    spectrum_dominant_frequency_hz REAL,
                    spectrum_dominant_amplitude REAL,
                    spectrum_passed INTEGER,
                    spectrum_result_code TEXT,
                    spectrum_tested_at TEXT NOT NULL,
                    fft_mode TEXT,
                    amplitude_unit TEXT,
                    measurements_json TEXT NOT NULL,
                    upload_status TEXT NOT NULL DEFAULT 'pending',
                    server_received_at TEXT,
                    UNIQUE (tray_cycle_id, tray_slot),
                    FOREIGN KEY (tray_cycle_id)
                        REFERENCES tray_cycles(tray_cycle_id)
                );

                CREATE TABLE IF NOT EXISTS upload_outbox (
                    outbox_id TEXT PRIMARY KEY,
                    entity_type TEXT NOT NULL,
                    entity_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    next_retry_at TEXT,
                    last_error TEXT,
                    created_at TEXT NOT NULL,
                    uploaded_at TEXT,
                    UNIQUE (entity_type, entity_id)
                );
                """
            )

    def save_mapping_batch(self, payload):
        tray_cycle_id = str(payload.get("tray_cycle_id", "")).strip()
        tray_id = str(payload.get("tray_id", "")).strip()
        loaded_at = str(payload.get("loaded_at", "")).strip()
        items = list(payload.get("items") or [])
        if not tray_cycle_id or not tray_id or not loaded_at:
            raise ValueError("托盘映射缺少 tray_cycle_id、tray_id 或 loaded_at")
        if len(items) != 10:
            raise ValueError("托盘映射必须包含 10 个坑位")

        normalized_items = []
        for item in items:
            tray_slot = int(item.get("tray_slot", 0))
            product_sn = str(item.get("product_sn", "")).strip()
            scanned_at = str(item.get("scanned_at") or loaded_at)
            if not 1 <= tray_slot <= 10 or not product_sn:
                raise ValueError("托盘映射包含无效坑位或空产品 SN")
            normalized_items.append((tray_slot, product_sn, scanned_at))
        if sorted(item[0] for item in normalized_items) != list(range(1, 11)):
            raise ValueError("托盘坑位必须完整覆盖 1 到 10")
        if len({item[1] for item in normalized_items}) != 10:
            raise ValueError("同一托盘批次不能包含重复产品 SN")

        with self._connect() as connection:
            connection.execute(
                """
                UPDATE tray_cycles
                SET status = 'superseded'
                WHERE tray_id = ? AND status = 'active' AND tray_cycle_id != ?
                """,
                (tray_id, tray_cycle_id),
            )
            connection.execute(
                """
                INSERT INTO tray_cycles(
                    tray_cycle_id, tray_id, loaded_at, status, received_at
                ) VALUES (?, ?, ?, 'active', ?)
                ON CONFLICT(tray_cycle_id) DO UPDATE SET
                    tray_id = excluded.tray_id,
                    loaded_at = excluded.loaded_at,
                    status = 'active',
                    received_at = excluded.received_at
                """,
                (tray_cycle_id, tray_id, loaded_at, local_timestamp()),
            )
            connection.execute(
                "DELETE FROM tray_products WHERE tray_cycle_id = ?",
                (tray_cycle_id,),
            )
            connection.executemany(
                """
                INSERT INTO tray_products(
                    tray_cycle_id, tray_id, tray_slot, product_sn, scanned_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (tray_cycle_id, tray_id, tray_slot, product_sn, scanned_at)
                    for tray_slot, product_sn, scanned_at in normalized_items
                ],
            )
        return self.get_mapping_batch(tray_cycle_id)

    def get_mapping_batch(self, tray_cycle_id):
        with self._connect() as connection:
            cycle = connection.execute(
                "SELECT * FROM tray_cycles WHERE tray_cycle_id = ?",
                (str(tray_cycle_id),),
            ).fetchone()
            if cycle is None:
                raise LookupError("找不到托盘批次：" + str(tray_cycle_id))
            items = connection.execute(
                """
                SELECT tray_slot, product_sn, scanned_at
                FROM tray_products
                WHERE tray_cycle_id = ?
                ORDER BY tray_slot
                """,
                (str(tray_cycle_id),),
            ).fetchall()
        return {
            "schema_version": "1.0",
            "tray_cycle_id": cycle["tray_cycle_id"],
            "tray_id": cycle["tray_id"],
            "loaded_at": cycle["loaded_at"],
            "status": cycle["status"],
            "items": [dict(row) for row in items],
        }

    def resolve_product(self, tray_id, tray_slot):
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT p.tray_cycle_id, p.tray_id, p.tray_slot, p.product_sn,
                       p.scanned_at
                FROM tray_products AS p
                JOIN tray_cycles AS c ON c.tray_cycle_id = p.tray_cycle_id
                WHERE p.tray_id = ? AND p.tray_slot = ? AND c.status = 'active'
                ORDER BY c.loaded_at DESC
                LIMIT 1
                """,
                (str(tray_id).strip(), int(tray_slot)),
            ).fetchone()
        if row is None:
            raise ProductMappingNotFoundError(
                "找不到托盘 {} 坑位 {} 对应的产品 SN".format(
                    tray_id, tray_slot
                )
            )
        return dict(row)

    def resolve_tray_products(self, tray_id):
        """返回托盘当前有效批次的 1～10 号坑位与产品 SN。"""
        normalized_tray_id = str(tray_id or "").strip()
        if not normalized_tray_id:
            return []
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT p.tray_cycle_id, p.tray_id, p.tray_slot, p.product_sn,
                       p.scanned_at
                FROM tray_products AS p
                JOIN tray_cycles AS c ON c.tray_cycle_id = p.tray_cycle_id
                WHERE p.tray_id = ? AND c.status = 'active'
                ORDER BY p.tray_slot
                """,
                (normalized_tray_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def pending_uploads(self, limit=100):
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM upload_outbox
                WHERE status = 'pending'
                ORDER BY created_at
                LIMIT ?
                """,
                (max(1, int(limit)),),
            ).fetchall()
        records = []
        for row in rows:
            record = dict(row)
            record["payload"] = json.loads(record.pop("payload_json"))
            records.append(record)
        return records

    def mark_upload_succeeded(self, outbox_id, server_received_at=None):
        with self._connect() as connection:
            outbox = connection.execute(
                "SELECT entity_type, entity_id FROM upload_outbox WHERE outbox_id = ?",
                (str(outbox_id),),
            ).fetchone()
            uploaded_at = server_received_at or local_timestamp()
            connection.execute(
                """
                UPDATE upload_outbox
                SET status = 'uploaded', uploaded_at = ?, last_error = NULL
                WHERE outbox_id = ?
                """,
                (uploaded_at, str(outbox_id)),
            )
            if outbox is not None and outbox["entity_type"] == "spectrum_result":
                connection.execute(
                    """
                    UPDATE spectrum_results
                    SET upload_status = 'uploaded', server_received_at = ?
                    WHERE record_id = ?
                    """,
                    (uploaded_at, str(outbox["entity_id"])),
                )

    def mark_upload_failed(self, outbox_id, message):
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE upload_outbox
                SET status = 'pending', retry_count = retry_count + 1,
                    last_error = ?
                WHERE outbox_id = ?
                """,
                (str(message), str(outbox_id)),
            )

    def save_spectrum_result(
        self,
        tray_id,
        tray_slot,
        station_code,
        measurements,
        tested_at=None,
    ):
        product = self.resolve_product(tray_id, tray_slot)
        record_id = str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                "spectrum:{}:{}".format(
                    product["tray_cycle_id"], product["tray_slot"]
                ),
            )
        )
        tested_at = tested_at or local_timestamp()
        record = {
            "record_id": record_id,
            "tray_cycle_id": product["tray_cycle_id"],
            "tray_id": product["tray_id"],
            "tray_slot": product["tray_slot"],
            "product_sn": product["product_sn"],
            "station_code": str(station_code),
            "spectrum_rms_mm_s2": measurements.get("spectrum_rms_mm_s2"),
            "spectrum_vpp_mm_s2": measurements.get("spectrum_vpp_mm_s2"),
            "spectrum_dominant_frequency_hz": measurements.get(
                "spectrum_dominant_frequency_hz"
            ),
            "spectrum_dominant_amplitude": measurements.get(
                "spectrum_dominant_amplitude"
            ),
            "spectrum_passed": measurements.get("spectrum_passed"),
            "spectrum_result_code": measurements.get("spectrum_result_code"),
            "spectrum_tested_at": tested_at,
            "fft_mode": measurements.get("fft_mode"),
            "amplitude_unit": measurements.get("amplitude_unit"),
            "measurements": dict(measurements),
        }
        payload_json = json.dumps(record, ensure_ascii=False)
        measurements_json = json.dumps(measurements, ensure_ascii=False)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO spectrum_results(
                    record_id, tray_cycle_id, tray_id, tray_slot, product_sn,
                    station_code, spectrum_rms_mm_s2, spectrum_vpp_mm_s2,
                    spectrum_dominant_frequency_hz,
                    spectrum_dominant_amplitude, spectrum_passed,
                    spectrum_result_code, spectrum_tested_at, fft_mode,
                    amplitude_unit, measurements_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(tray_cycle_id, tray_slot) DO UPDATE SET
                    station_code = excluded.station_code,
                    spectrum_rms_mm_s2 = excluded.spectrum_rms_mm_s2,
                    spectrum_vpp_mm_s2 = excluded.spectrum_vpp_mm_s2,
                    spectrum_dominant_frequency_hz = excluded.spectrum_dominant_frequency_hz,
                    spectrum_dominant_amplitude = excluded.spectrum_dominant_amplitude,
                    spectrum_passed = excluded.spectrum_passed,
                    spectrum_result_code = excluded.spectrum_result_code,
                    spectrum_tested_at = excluded.spectrum_tested_at,
                    fft_mode = excluded.fft_mode,
                    amplitude_unit = excluded.amplitude_unit,
                    measurements_json = excluded.measurements_json,
                    upload_status = 'pending',
                    server_received_at = NULL
                """,
                (
                    record_id, product["tray_cycle_id"], product["tray_id"],
                    product["tray_slot"], product["product_sn"],
                    str(station_code), record["spectrum_rms_mm_s2"],
                    record["spectrum_vpp_mm_s2"],
                    record["spectrum_dominant_frequency_hz"],
                    record["spectrum_dominant_amplitude"],
                    None if record["spectrum_passed"] is None else int(bool(record["spectrum_passed"])),
                    record["spectrum_result_code"], tested_at,
                    record["fft_mode"], record["amplitude_unit"],
                    measurements_json,
                ),
            )
            connection.execute(
                """
                INSERT INTO upload_outbox(
                    outbox_id, entity_type, entity_id, payload_json, created_at
                ) VALUES (?, 'spectrum_result', ?, ?, ?)
                ON CONFLICT(entity_type, entity_id) DO UPDATE SET
                    payload_json = excluded.payload_json,
                    status = 'pending',
                    last_error = NULL
                """,
                (str(uuid.uuid4()), record_id, payload_json, local_timestamp()),
            )
        return record
