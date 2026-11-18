import tempfile
import unittest
import json
import numpy as np
from urllib.request import Request, urlopen
from pathlib import Path
from types import SimpleNamespace

from main import (
    ACQUISITION_SOURCE_LABJACK,
    ACQUISITION_SOURCE_NI9234,
    AcquisitionWorker,
    PC_POINT_DONE_BIT,
    PLC_ALL_COMPLETE_BIT,
    PLC_POINT_READY_BIT,
    PlcWorker,
    VibrationTester,
    merge_export_frequencies,
    normalize_acquisition_source,
)
from ni9234_source import Ni9234Source, select_ni9234_module
from traceability_store import TraceabilityStore
from tray_mapping_api import TrayMappingApiServer


class LabelStub:
    def __init__(self):
        self.text = ""
        self.style = ""
        self.tooltip = ""

    def setText(self, value):
        self.text = value

    def setStyleSheet(self, value):
        self.style = value

    def setToolTip(self, value):
        self.tooltip = value


class AcquisitionSourceTests(unittest.TestCase):
    def test_source_aliases_keep_labjack_as_default(self):
        self.assertEqual(normalize_acquisition_source(None), ACQUISITION_SOURCE_LABJACK)
        self.assertEqual(normalize_acquisition_source("频谱"), ACQUISITION_SOURCE_LABJACK)
        self.assertEqual(normalize_acquisition_source("NI-9234"), ACQUISITION_SOURCE_NI9234)

    def test_ni9234_module_uses_exact_name_or_single_detected_module(self):
        devices = [("My9234", "NI 9234"), ("Dev1", "NI USB-6001")]
        self.assertEqual(select_ni9234_module("my9234", devices), "My9234")
        self.assertEqual(select_ni9234_module("cDAQ1Mod1", devices), "My9234")

    def test_ni_acceleration_is_converted_from_g_to_display_unit(self):
        worker = AcquisitionWorker(None, {
            "source": "ni9234",
            "gravity_m_s2": 9.80665,
            "display_scale_from_m_s2": 1000.0,
            "ni9234": {"scan_rate": 25600, "scans_per_read": 1500},
        })
        converted = worker.convert_acceleration_g(np.array([1.0, -0.5]))
        np.testing.assert_allclose(converted, [9806.65, -4903.325])
        self.assertEqual(worker.requested_scan_rate, 25600)
        self.assertEqual(worker.scans_per_read, 1500)

    def test_ni_defaults_cover_original_25_khz_fft_range(self):
        worker = AcquisitionWorker(None, {
            "source": "ni9234",
            "ni9234": {},
        })
        source = Ni9234Source({})
        self.assertEqual(worker.requested_scan_rate, 51200)
        self.assertEqual(source.scan_rate, 51200)


class TextWidgetStub:
    def __init__(self, value=""):
        self.value = str(value)
        self.enabled = True

    def text(self):
        return self.value

    def setText(self, value):
        self.value = str(value)

    def clear(self):
        self.value = ""

    def setEnabled(self, enabled):
        self.enabled = bool(enabled)


class StatusBarStub:
    def __init__(self):
        self.message = ""

    def showMessage(self, value):
        self.message = str(value)


class TableStub:
    def __init__(self, column_count):
        self.column_count = int(column_count)
        self.rows = []

    def columnCount(self):
        return self.column_count

    def rowCount(self):
        return len(self.rows)

    def setRowCount(self, count):
        if int(count) == 0:
            self.rows = []
        else:
            self.rows = self.rows[:int(count)]

    def insertRow(self, index):
        self.rows.insert(int(index), [None] * self.column_count)

    def setItem(self, row, column, item):
        self.rows[int(row)][int(column)] = item

    def item(self, row, column):
        return self.rows[int(row)][int(column)]


class CheckpointHarness:
    automatic_checkpoint_paths = VibrationTester.automatic_checkpoint_paths
    record_table_rows = VibrationTester.record_table_rows
    spectrum_ok_word_for_results = staticmethod(VibrationTester.spectrum_ok_word_for_results)
    save_automatic_checkpoint = VibrationTester.save_automatic_checkpoint
    restore_automatic_checkpoint = VibrationTester.restore_automatic_checkpoint
    clear_automatic_checkpoint = VibrationTester.clear_automatic_checkpoint
    automation_progress_text = VibrationTester.automation_progress_text

    def __init__(self, directory, records_per_motor=2):
        self.checkpoint_enabled = True
        self.automatic_checkpoint_dir = Path(directory)
        self.txt_model = TextWidgetStub("C68")
        self.txt_start_time = TextWidgetStub("2026-08-14 10:00:00")
        self.txt_complete_time = TextWidgetStub()
        self.txt_qty = TextWidgetStub()
        self.lbl_record_count = LabelStub()
        self.tray_id = "7001"
        self.positions_per_tray = 10
        self.records_per_motor = int(records_per_motor)
        self.record_headers = ["序号", "电机位置", "状态"]
        self.tbl_records = TableStub(len(self.record_headers))
        self.completed_positions = set()
        self.skipped_positions = set()
        self.position_pass_results = {}
        self.spectrum_ok_word = 0
        self.current_test_position = 0
        self.current_position_record_count = 0
        self.point_record_done = False
        self.cycle_completion_handled = False
        self.checkpoint_restore_failed = False
        self.messages = []

    def current_tray_id(self):
        return self.tray_id

    def append_process_log(self, category, message):
        self.messages.append((category, message))

    def update_record_count(self):
        self.lbl_record_count.setText(f"记录: {self.tbl_records.rowCount()}")

    def write_records_csv(self, path):
        Path(path).write_text("partial", encoding="utf-8")
        return True, ""

    def append_row(self, sequence, position, status="合格"):
        row = self.tbl_records.rowCount()
        self.tbl_records.insertRow(row)
        self.tbl_records.setItem(row, 0, TextWidgetStub(sequence))
        self.tbl_records.setItem(row, 1, TextWidgetStub(position))
        self.tbl_records.setItem(row, 2, TextWidgetStub(status))


class TraceabilityStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.store = TraceabilityStore(
            Path(self.temporary_directory.name) / "traceability.db"
        )

    def tearDown(self):
        self.temporary_directory.cleanup()

    def mapping_payload(self):
        return {
            "schema_version": "1.0",
            "tray_cycle_id": "cycle-001",
            "tray_id": "7001",
            "loaded_at": "2026-08-11T10:00:00+08:00",
            "items": [
                {
                    "tray_slot": slot,
                    "product_sn": "SN{:02d}".format(slot),
                    "scanned_at": "2026-08-11T10:00:00+08:00",
                }
                for slot in range(1, 11)
            ],
        }

    def test_mapping_is_saved_and_resolved(self):
        self.store.save_mapping_batch(self.mapping_payload())

        product = self.store.resolve_product("7001", 7)
        self.assertEqual(product["product_sn"], "SN07")
        products = self.store.resolve_tray_products("7001")
        self.assertEqual(len(products), 10)
        self.assertEqual(products[0]["tray_slot"], 1)
        self.assertEqual(products[-1]["product_sn"], "SN10")

    def test_plc_reads_tray_id_without_large_dm_range(self):
        calls = []

        class FakeClient:
            def read_words(self, area, address, count):
                calls.append((area, address, count))
                if address == 3008:
                    return [42]
                if address == 3501 and count == 8:
                    return [2, 0, 0, 10, 0, 0, 0, 4]
                raise AssertionError((area, address, count))

        worker = PlcWorker({
            "addresses": {
                "tray_id": {"area": "DM", "address": 3008},
                "plc_status_word": {"area": "DM", "address": 3501},
                "plc_heartbeat": {"area": "DM", "address": 3504},
                "current_position": {"area": "DM", "address": 3508},
            }
        })
        worker.client = FakeClient()

        self.assertEqual(worker.read_plc_state(), (42, 2, 4, 10))
        self.assertEqual(calls, [("DM", 3008, 1), ("DM", 3501, 8)])

    def test_plc_worker_writes_spectrum_ok_word_to_dm3505(self):
        writes = []

        class FakeClient:
            def write_words(self, area, address, values):
                writes.append((area, address, list(values)))

            def read_words(self, _area, address, count):
                if address == 3008:
                    return [42]
                if address == 3501 and count == 8:
                    return [0, 0, 0, 1, 0, 0, 0, 1]
                raise AssertionError((address, count))

        worker = PlcWorker({
            "positions_per_tray": 10,
            "addresses": {
                "tray_id": {"area": "DM", "address": 3008},
                "pc_command_word": {"area": "DM", "address": 3500},
                "plc_status_word": {"area": "DM", "address": 3501},
                "pc_heartbeat": {"area": "DM", "address": 3503},
                "plc_heartbeat": {"area": "DM", "address": 3504},
                "spectrum_ok_word": {"area": "DM", "address": 3505},
                "current_position": {"area": "DM", "address": 3508},
            },
        })
        worker.client = FakeClient()
        worker.set_result_word((1 << 1) | (1 << 10))

        worker.poll()

        self.assertEqual(writes[0], ("DM", 3505, [(1 << 1) | (1 << 10)]))

    def test_unknown_tray_has_no_products(self):
        self.assertEqual(self.store.resolve_tray_products("UNKNOWN"), [])

    def test_main_window_sn_lookup_is_optional(self):
        self.store.save_mapping_batch(self.mapping_payload())
        messages = []
        window = SimpleNamespace(
            positions_per_tray=10,
            traceability_store=self.store,
            missing_product_mapping_notices=set(),
            append_process_log=lambda category, message: messages.append(
                (category, message)
            ),
        )

        self.assertEqual(
            VibrationTester.resolve_product_sn(window, "7001", 3),
            "SN03",
        )
        self.assertEqual(
            VibrationTester.resolve_product_sn(window, "missing", 3),
            "",
        )
        self.assertEqual(
            VibrationTester.resolve_product_sn(window, "missing", 3),
            "",
        )
        self.assertEqual(len(messages), 1)

    def test_entering_tray_id_shows_complete_mapping_status(self):
        self.store.save_mapping_batch(self.mapping_payload())
        messages = []
        status_label = LabelStub()
        window = SimpleNamespace(
            current_tray_id=lambda: "7001",
            traceability_store=self.store,
            missing_product_mapping_notices=set(),
            lbl_tray_mapping_status=status_label,
            append_process_log=lambda category, message: messages.append(
                (category, message)
            ),
        )

        VibrationTester.handle_tray_id_edited(window)

        self.assertEqual(status_label.text, "SN 映射：已匹配 10/10")
        self.assertIn("1号：SN01", status_label.tooltip)
        self.assertIn("10号：SN10", status_label.tooltip)

    def test_spectrum_result_uses_mapping_product_sn(self):
        self.store.save_mapping_batch(self.mapping_payload())

        record = self.store.save_spectrum_result(
            "7001",
            4,
            "SPECTRUM_01",
            {
                "spectrum_rms_mm_s2": 1200.3,
                "spectrum_vpp_mm_s2": 10468.5,
                "spectrum_dominant_frequency_hz": 1801.33,
                "spectrum_dominant_amplitude": 126.5,
                "spectrum_passed": True,
                "spectrum_result_code": "OK",
                "fft_mode": "asd",
                "amplitude_unit": "mm/s^2/√Hz",
            },
        )

        self.assertEqual(record["product_sn"], "SN04")
        self.assertEqual(record["tray_slot"], 4)
        self.assertEqual(
            self.store.pending_uploads()[0]["entity_type"], "spectrum_result"
        )

    def test_mapping_api_accepts_authenticated_batch(self):
        server = TrayMappingApiServer(
            self.store, host="127.0.0.1", port=0, token="test-token"
        )
        server.start()
        try:
            port = server.server.server_address[1]
            request = Request(
                "http://127.0.0.1:{}/api/v1/tray-mappings".format(port),
                data=json.dumps(self.mapping_payload()).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "X-Line-Token": "test-token",
                },
                method="POST",
            )
            with urlopen(request, timeout=2) as response:
                payload = json.loads(response.read().decode("utf-8"))
        finally:
            server.stop()

        self.assertEqual(payload["status"], "saved")
        self.assertEqual(self.store.resolve_product("7001", 10)["product_sn"], "SN10")


class AutomaticRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_checkpoint_restores_completed_and_partial_position(self):
        source = CheckpointHarness(self.temporary_directory.name)
        source.append_row(1, 1)
        source.append_row(2, 1)
        source.append_row(3, 2)
        source.completed_positions = {1}
        source.skipped_positions = {3}
        source.position_pass_results = {1: True, 2: True}
        source.spectrum_ok_word = 1 << 1
        source.current_test_position = 2
        source.current_position_record_count = 1

        self.assertTrue(source.save_automatic_checkpoint())

        restored = CheckpointHarness(self.temporary_directory.name)
        self.assertTrue(restored.restore_automatic_checkpoint("7001"))
        self.assertEqual(restored.completed_positions, {1})
        self.assertEqual(restored.skipped_positions, {3})
        self.assertEqual(restored.current_test_position, 2)
        self.assertEqual(restored.current_position_record_count, 1)
        self.assertEqual(restored.tbl_records.rowCount(), 3)
        self.assertEqual(restored.position_pass_results, {1: True, 2: True})
        self.assertEqual(restored.spectrum_ok_word, 1 << 1)

    def test_checkpoint_rejects_inconsistent_completed_position(self):
        source = CheckpointHarness(self.temporary_directory.name)
        source.append_row(1, 1)
        source.append_row(2, 1)
        source.append_row(3, 2)
        source.completed_positions = {1}
        source.position_pass_results = {1: True, 2: True}
        source.spectrum_ok_word = 1 << 1
        source.current_test_position = 2
        source.current_position_record_count = 1
        self.assertTrue(source.save_automatic_checkpoint())

        checkpoint_path, _ = source.automatic_checkpoint_paths()
        payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        payload["completed_positions"] = [1, 2]
        checkpoint_path.write_text(
            json.dumps(payload, ensure_ascii=False),
            encoding="utf-8",
        )

        restored = CheckpointHarness(self.temporary_directory.name)
        self.assertFalse(restored.restore_automatic_checkpoint("7001"))
        self.assertTrue(restored.checkpoint_restore_failed)

    def test_checkpoint_without_result_fields_derives_dm3505_word(self):
        source = CheckpointHarness(self.temporary_directory.name)
        source.append_row(1, 1)
        source.append_row(2, 1)
        source.completed_positions = {1}
        source.position_pass_results = {1: True}
        source.spectrum_ok_word = 1 << 1
        source.current_test_position = 1
        source.current_position_record_count = 2
        source.point_record_done = True
        self.assertTrue(source.save_automatic_checkpoint())

        checkpoint_path, _ = source.automatic_checkpoint_paths()
        payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        payload.pop("position_pass_results")
        payload.pop("spectrum_ok_word")
        checkpoint_path.write_text(
            json.dumps(payload, ensure_ascii=False),
            encoding="utf-8",
        )

        restored = CheckpointHarness(self.temporary_directory.name)
        self.assertTrue(restored.restore_automatic_checkpoint("7001"))
        self.assertEqual(restored.position_pass_results, {1: True})
        self.assertEqual(restored.spectrum_ok_word, 1 << 1)

    def test_clear_checkpoint_removes_json_and_partial_csv(self):
        source = CheckpointHarness(self.temporary_directory.name)
        source.append_row(1, 1)
        source.current_test_position = 1
        source.current_position_record_count = 1
        source.position_pass_results = {1: True}
        self.assertTrue(source.save_automatic_checkpoint())

        checkpoint_path, partial_csv_path = source.automatic_checkpoint_paths()
        self.assertTrue(checkpoint_path.exists())
        self.assertTrue(partial_csv_path.exists())

        cleared_paths = source.clear_automatic_checkpoint("7001")

        self.assertEqual(set(cleared_paths), {checkpoint_path, partial_csv_path})
        self.assertFalse(checkpoint_path.exists())
        self.assertFalse(partial_csv_path.exists())

    def test_discard_progress_resets_plc_words_and_prevents_restore(self):
        class DiscardHarness:
            discard_automatic_progress = VibrationTester.discard_automatic_progress
            automation_progress_text = VibrationTester.automation_progress_text

            def __init__(self):
                self.completed_positions = {1, 2}
                self.skipped_positions = {3}
                self.positions_per_tray = 10
                self.checkpoint_restore_failed = True
                self.plc_connected = True
                self.lbl_status = LabelStub()
                self.lbl_avg_status = LabelStub()
                self.lbl_plc_state = LabelStub()
                self.statusbar = StatusBarStub()
                self.messages = []
                self.command_bits = {}
                self.cleared_tray = None
                self.reset_called = False

            def current_tray_id(self):
                return "7001"

            def clear_automatic_checkpoint(self, tray_id):
                self.cleared_tray = tray_id
                return [Path("checkpoint.json"), Path("partial.csv")]

            def reset_automatic_records(self):
                self.reset_called = True
                self.completed_positions.clear()
                self.skipped_positions.clear()

            def set_pc_command_bit(self, bit, enabled):
                self.command_bits[int(bit)] = bool(enabled)

            def append_process_log(self, category, message):
                self.messages.append((category, message))

        window = DiscardHarness()
        cleared_paths = window.discard_automatic_progress()

        self.assertTrue(window.reset_called)
        self.assertEqual(window.cleared_tray, "7001")
        self.assertEqual(len(cleared_paths), 2)
        self.assertFalse(window.checkpoint_restore_failed)
        self.assertEqual(window.command_bits, {0: False, 1: False, 2: False, 3: False})
        self.assertEqual(window.lbl_plc_state.text, "PLC: 已连接 | 自动化进度已清除")

    def test_spectrum_ok_result_uses_dm3505_bits_1_through_10(self):
        class ResultHarness:
            set_spectrum_ok_word = VibrationTester.set_spectrum_ok_word
            set_position_spectrum_ok = VibrationTester.set_position_spectrum_ok

            def __init__(self):
                self.positions_per_tray = 10
                self.spectrum_ok_word = 0
                self.plc_worker = None
                self.messages = []

            def append_process_log(self, category, message):
                self.messages.append((category, message))

        window = ResultHarness()
        window.set_position_spectrum_ok(1, True)
        window.set_position_spectrum_ok(10, True)
        self.assertEqual(window.spectrum_ok_word, (1 << 1) | (1 << 10))

        window.set_position_spectrum_ok(1, False)
        self.assertEqual(window.spectrum_ok_word, 1 << 10)

    def test_forward_plc_position_marks_intermediate_positions_as_runin_skipped(self):
        class SkipHarness:
            next_incomplete_position = VibrationTester.next_incomplete_position
            mark_skipped_positions = VibrationTester.mark_skipped_positions
            mark_positions_before_as_skipped = VibrationTester.mark_positions_before_as_skipped
            set_spectrum_ok_word = VibrationTester.set_spectrum_ok_word

            def __init__(self):
                self.positions_per_tray = 10
                self.completed_positions = {1}
                self.skipped_positions = set()
                self.spectrum_ok_word = (1 << 1) | (1 << 2) | (1 << 3)
                self.plc_worker = None
                self.messages = []

            def append_process_log(self, category, message):
                self.messages.append((category, message))

        window = SkipHarness()
        skipped = window.mark_positions_before_as_skipped(4, "PLC直接到达4号")

        self.assertEqual(skipped, [2, 3])
        self.assertEqual(window.skipped_positions, {2, 3})
        self.assertEqual(window.next_incomplete_position(), 4)
        self.assertEqual(window.spectrum_ok_word, 1 << 1)

    def test_first_ready_position_can_skip_runin_ng_motors(self):
        class StartHarness:
            start_point_acquisition = VibrationTester.start_point_acquisition
            next_incomplete_position = VibrationTester.next_incomplete_position
            mark_skipped_positions = VibrationTester.mark_skipped_positions
            mark_positions_before_as_skipped = VibrationTester.mark_positions_before_as_skipped
            set_spectrum_ok_word = VibrationTester.set_spectrum_ok_word

            def __init__(self):
                self.positions_per_tray = 10
                self.completed_positions = set()
                self.skipped_positions = set()
                self.current_test_position = 0
                self.current_position_record_count = 0
                self.records_per_motor = 1
                self.spectrum_ok_word = 0
                self.plc_worker = None
                self.txt_tray_id = TextWidgetStub("7001")
                self.data_buffer = np.zeros(4)
                self.raw_data_buffer = np.zeros(4)
                self.lbl_status = LabelStub()
                self.lbl_avg_status = LabelStub()
                self.avg_time_sec = 3
                self.messages = []
                self.command_bits = {}
                self.started = False
                self.pause_reason = ""

            def append_process_log(self, category, message):
                self.messages.append((category, message))

            def set_pc_command_bit(self, bit, enabled):
                self.command_bits[int(bit)] = bool(enabled)

            def pause_automatic_test(self, reason):
                self.pause_reason = str(reason)

            def save_automatic_checkpoint(self):
                return True

            def record_identity(self, position):
                return "7001", f"SN{int(position):02d}"

            def record_mode_label(self):
                return "整体计算"

            def start_acquisition_worker(self, stop_after_record=False):
                self.started = not stop_after_record
                return True

            def abort_automatic_test(self, reason, upper_fault):
                raise AssertionError((reason, upper_fault))

        window = StartHarness()
        window.start_point_acquisition(3)

        self.assertEqual(window.skipped_positions, {1, 2})
        self.assertEqual(window.current_test_position, 3)
        self.assertTrue(window.started)
        self.assertEqual(window.pause_reason, "")

    def test_all_complete_accepts_only_the_positions_sent_by_plc(self):
        class FinishHarness:
            finish_automatic_test = VibrationTester.finish_automatic_test
            automation_progress_text = VibrationTester.automation_progress_text
            mark_skipped_positions = VibrationTester.mark_skipped_positions
            set_spectrum_ok_word = VibrationTester.set_spectrum_ok_word

            def __init__(self, directory):
                self.positions_per_tray = 10
                self.records_per_motor = 1
                self.completed_positions = {1, 3}
                self.skipped_positions = {2}
                self.current_test_position = 0
                self.current_position_record_count = 0
                self.position_pass_results = {1: True, 3: True}
                self.spectrum_ok_word = (1 << 1) | (1 << 3)
                self.plc_worker = None
                self.tbl_records = TableStub(1)
                self.tbl_records.insertRow(0)
                self.tbl_records.insertRow(1)
                self.txt_complete_time = TextWidgetStub()
                self.txt_tray_id = TextWidgetStub("7001")
                self.lbl_status = LabelStub()
                self.lbl_avg_status = LabelStub()
                self.lbl_plc_state = LabelStub()
                self.statusbar = StatusBarStub()
                self.btn_start = TextWidgetStub()
                self.btn_manual_start = TextWidgetStub()
                self.last_auto_save_path = None
                self.cycle_completion_handled = False
                self.messages = []
                self.output_path = str(Path(directory) / "records.csv")
                self.cleared_checkpoint = False

            def append_process_log(self, category, message):
                self.messages.append((category, message))

            def set_pc_command_bit(self, _bit, _enabled):
                pass

            def set_test_controls_enabled(self, _enabled):
                pass

            def get_automatic_record_path(self):
                return self.output_path

            def write_records_csv(self, path):
                Path(path).write_text("saved", encoding="utf-8")
                return True, ""

            def current_tray_id(self):
                return self.txt_tray_id.text()

            def clear_automatic_checkpoint(self, _tray_id):
                self.cleared_checkpoint = True

            def abort_automatic_test(self, reason, upper_fault):
                raise AssertionError((reason, upper_fault))

        window = FinishHarness(self.temporary_directory.name)
        window.finish_automatic_test()

        self.assertEqual(window.completed_positions, {1, 3})
        self.assertEqual(window.skipped_positions, {2, 4, 5, 6, 7, 8, 9, 10})
        self.assertTrue(window.cleared_checkpoint)
        self.assertTrue(Path(window.output_path).exists())

    def test_pause_keeps_automation_active_and_saves_once(self):
        class PauseHarness:
            pause_automatic_test = VibrationTester.pause_automatic_test
            automation_progress_text = VibrationTester.automation_progress_text

            def __init__(self):
                self.auto_test_active = True
                self.auto_test_paused = False
                self.auto_pause_reason = ""
                self.auto_resume_ready_since = None
                self.is_running = True
                self.completed_positions = {1, 2}
                self.skipped_positions = set()
                self.positions_per_tray = 10
                self.current_position_record_count = 1
                self.records_per_motor = 3
                self.lbl_status = LabelStub()
                self.lbl_avg_status = LabelStub()
                self.lbl_plc_state = LabelStub()
                self.statusbar = StatusBarStub()
                self.stop_observed_paused = False
                self.checkpoint_save_count = 0

            def stop_data_stream(self):
                self.stop_observed_paused = self.auto_test_paused
                self.is_running = False

            def set_pc_command_bit(self, _bit, _enabled):
                pass

            def append_process_log(self, _category, _message):
                pass

            def save_automatic_checkpoint(self):
                self.checkpoint_save_count += 1

        window = PauseHarness()
        window.pause_automatic_test("PLC通信中断")
        window.pause_automatic_test("PLC通信中断")

        self.assertTrue(window.auto_test_active)
        self.assertTrue(window.auto_test_paused)
        self.assertTrue(window.stop_observed_paused)
        self.assertEqual(window.checkpoint_save_count, 1)

    def test_resume_accepts_completed_position_waiting_for_plc_ack(self):
        class ResumeHarness:
            automatic_resume_is_ready = VibrationTester.automatic_resume_is_ready
            next_incomplete_position = VibrationTester.next_incomplete_position
            all_positions_accounted_for = VibrationTester.all_positions_accounted_for

        window = ResumeHarness()
        window.auto_test_paused = True
        window.plc_connected = True
        window.plc_status_word = 1 << PLC_POINT_READY_BIT
        window.current_tray_id = lambda: "7001"
        window.plc_current_tray_id = 7001
        window.plc_current_position = 4
        window.current_test_position = 4
        window.completed_positions = {1, 2, 3, 4}
        window.skipped_positions = set()
        window.positions_per_tray = 10
        window.point_record_done = True
        window.auto_resume_ready_since = None
        window.auto_resume_stable_sec = 0
        window.lbl_status = LabelStub()

        self.assertTrue(window.automatic_resume_is_ready())

    def test_resume_accepts_last_completed_position_before_all_complete(self):
        class ResumeHarness:
            automatic_resume_is_ready = VibrationTester.automatic_resume_is_ready
            next_incomplete_position = VibrationTester.next_incomplete_position
            all_positions_accounted_for = VibrationTester.all_positions_accounted_for

        window = ResumeHarness()
        window.auto_test_paused = True
        window.plc_connected = True
        window.plc_status_word = 1 << PLC_POINT_READY_BIT
        window.current_tray_id = lambda: "7001"
        window.plc_current_tray_id = 7001
        window.plc_current_position = 10
        window.current_test_position = 0
        window.current_position_record_count = 0
        window.completed_positions = set(range(1, 11))
        window.skipped_positions = set()
        window.positions_per_tray = 10
        window.point_record_done = False
        window.plc_all_complete = False
        window.auto_resume_ready_since = None
        window.auto_resume_stable_sec = 0
        window.lbl_status = LabelStub()

        self.assertTrue(window.automatic_resume_is_ready())

    def test_all_complete_finishes_when_last_point_ack_is_still_held(self):
        class CompleteHarness:
            handle_plc_state = VibrationTester.handle_plc_state
            next_incomplete_position = VibrationTester.next_incomplete_position
            all_positions_accounted_for = VibrationTester.all_positions_accounted_for

            def __init__(self):
                self.auto_test_active = True
                self.auto_test_paused = False
                self.is_running = False
                self.completed_positions = set(range(1, 11))
                self.skipped_positions = set()
                self.positions_per_tray = 10
                self.current_test_position = 10
                self.current_position_record_count = 1
                self.point_record_done = True
                self.cycle_completion_handled = False
                self.last_plc_heartbeat = 1
                self.last_plc_heartbeat_change = 0
                self.plc_heartbeat_timeout_sec = 999999
                self.heartbeat_warning_active = False
                self.lbl_motor_position = LabelStub()
                self.lbl_status = LabelStub()
                self.lbl_avg_status = LabelStub()
                self.lbl_plc_state = LabelStub()
                self.statusbar = StatusBarStub()
                self.command_bits = {}
                self.messages = []
                self.checkpoint_saved = False
                self.finished = False

            def append_process_log(self, category, message):
                self.messages.append((category, message))

            def set_pc_command_bit(self, bit, enabled):
                self.command_bits[int(bit)] = bool(enabled)

            def save_automatic_checkpoint(self):
                self.checkpoint_saved = True
                return True

            def finish_automatic_test(self):
                self.finished = True

        window = CompleteHarness()
        status_word = (1 << PLC_POINT_READY_BIT) | (1 << PLC_ALL_COMPLETE_BIT)

        window.handle_plc_state(7001, status_word, 10, 1)

        self.assertTrue(window.finished)
        self.assertFalse(window.point_record_done)
        self.assertEqual(window.current_test_position, 0)
        self.assertEqual(window.current_position_record_count, 0)
        self.assertFalse(window.command_bits[PC_POINT_DONE_BIT])
        self.assertTrue(window.checkpoint_saved)


class SpectrumFrequencyTests(unittest.TestCase):
    def test_export_frequency_merge_removes_values_that_serialize_identically(self):
        frequencies = merge_export_frequencies(
            np.array([299.0, 300.0, 301.0]),
            np.array([299.99999999999994, 300.0, 300.6666666666666]),
            1000.0,
        )

        self.assertEqual(np.count_nonzero(frequencies == 300.0), 1)
        self.assertIn(300.666666667, frequencies)

    def test_band_start_includes_fft_bin_with_float_rounding_error(self):
        window = SimpleNamespace(
            frequency_band_groups=[{
                "name": "低频段",
                "start_hz": 300.0,
                "end_hz": 3600.0,
            }],
            fft_freqs=np.array([
                299.33333333333326,
                299.99999999999994,
                300.6666666666666,
                301.33333333333326,
            ]),
            wave_threshold=0.0,
        )
        fft_values = np.array([1.0, 1083.85, 836.41, 2.0])

        summary = VibrationTester.get_band_group_summaries(window, fft_values)[0]

        self.assertAlmostEqual(summary["peak_frequency_hz"], 300.0, places=9)
        self.assertEqual(summary["peak_amplitude"], 1083.85)


if __name__ == "__main__":
    unittest.main()
