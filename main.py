import sys
import csv
import json
import re
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from threading import Lock, Thread
from time import monotonic

import numpy as np
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)
from PySide6.QtCore import QObject, QThread, QTimer, Signal, Slot, Qt
import pyqtgraph as pg
from labjack import ljm

# 导入界面类
from Fins import FinsUdpClient
from mes_sync import MesSyncClient, sync_once
from ni9234_source import Ni9234Source, discover_ni9234_module
from traceability_store import TraceabilityStore
from tray_mapping_api import TrayMappingApiServer
from ui_main import Ui_MainWindow


CONFIG_PATH = Path(__file__).resolve().with_name("config.json")

FEATURE_FREQUENCY_COLUMNS = 9

PC_START_BIT = 0
PC_STOP_BIT = 1
PC_POINT_DONE_BIT = 2
PC_FAULT_BIT = 3

PLC_EMERGENCY_BIT = 0
PLC_POINT_READY_BIT = 1
PLC_ALL_COMPLETE_BIT = 2
PLC_FAULT_BIT = 3

FREQUENCY_BOUNDARY_EPSILON_HZ = 1e-9
EXPORT_FREQUENCY_DECIMALS = 9

DISPLAY_UNIT_SCALES = {
    "m/s^2": 1.0,
    "mm/s^2": 1000.0,
    "um/s^2": 1000000.0,
}

ACQUISITION_SOURCE_LABJACK = "labjack"
ACQUISITION_SOURCE_NI9234 = "ni9234"


def normalize_acquisition_source(value):
    text = str(value or ACQUISITION_SOURCE_LABJACK).strip().lower()
    aliases = {
        "labjack": ACQUISITION_SOURCE_LABJACK,
        "lj": ACQUISITION_SOURCE_LABJACK,
        "频谱": ACQUISITION_SOURCE_LABJACK,
        "ni": ACQUISITION_SOURCE_NI9234,
        "ni9234": ACQUISITION_SOURCE_NI9234,
        "ni-9234": ACQUISITION_SOURCE_NI9234,
        "accelerometer": ACQUISITION_SOURCE_NI9234,
        "加速度": ACQUISITION_SOURCE_NI9234,
    }
    return aliases.get(text, ACQUISITION_SOURCE_LABJACK)


def merge_export_frequencies(base_frequencies, detection_frequencies, max_frequency):
    combined = np.concatenate((
        np.asarray(base_frequencies, dtype=float),
        np.asarray(detection_frequencies, dtype=float),
    ))
    combined = combined[np.isfinite(combined)]
    combined = np.round(combined, EXPORT_FREQUENCY_DECIMALS)
    combined = combined[(combined >= 0.0) & (combined < float(max_frequency))]
    return np.unique(combined)

DEFAULT_BEARING_FREQUENCY = {
    "base_frequency_hz": 300,
    "range_percent": 2,
    "points": [
        {"name": "滚珠公转/保持架", "coefficient": 0.3933333333, "upper_limit_m_s2": 0.3, "judgment_enabled": True},
        {"name": "滚珠自转", "coefficient": 2.2533333333, "upper_limit_m_s2": 0.2, "judgment_enabled": True},
        {"name": "滚珠通过(1)", "coefficient": 3.1533333333, "upper_limit_m_s2": 0.3, "judgment_enabled": True},
        {"name": "滚珠通过(2)", "coefficient": 4.84, "upper_limit_m_s2": 0.3, "judgment_enabled": False},
        {"name": "内轮径向(1)", "coefficient": 3.8466666667, "upper_limit_m_s2": 0.3, "judgment_enabled": False},
        {"name": "内轮径向(2)", "coefficient": 5.8466666667, "upper_limit_m_s2": 0.25, "judgment_enabled": False},
        {"name": "滚珠轴向", "coefficient": 4.51, "upper_limit_m_s2": 0.3, "judgment_enabled": False},
        {"name": "滚珠径向(1)", "coefficient": 4.1166666667, "upper_limit_m_s2": 0.3, "judgment_enabled": False},
        {"name": "滚珠径向(2)", "coefficient": 4.9066666667, "upper_limit_m_s2": 0.45, "judgment_enabled": False},
    ],
}

DEFAULT_FREQUENCY_BAND_GROUPS = [
    {
        "name": "低频段",
        "start_hz": 300,
        "end_hz": 3600,
        "peak_threshold_m_s2": 0.06,
        "peak_count_upper_limit": 50,
        "energy_upper_limit": 15000000,
    },
    {
        "name": "中频段",
        "start_hz": 6000,
        "end_hz": 12000,
        "peak_threshold_m_s2": 0.12,
        "peak_count_upper_limit": 20,
        "energy_upper_limit": 10000000,
    },
    {
        "name": "高频段",
        "start_hz": 15000,
        "end_hz": 18000,
        "peak_threshold_m_s2": 0.3,
        "peak_count_upper_limit": 10,
        "energy_upper_limit": 20000000,
    },
]

DEFAULT_FIXED_FREQUENCY_POINTS = [
    {"name": "300Hz", "frequency_hz": 300, "upper_limit_m_s2": 2.4, "judgment_enabled": True},
    {"name": "600Hz", "frequency_hz": 600, "upper_limit_m_s2": 2.4, "judgment_enabled": True},
    {"name": "900Hz", "frequency_hz": 900, "upper_limit_m_s2": 0.5, "judgment_enabled": True},
    {"name": "1200Hz", "frequency_hz": 1200, "upper_limit_m_s2": 0.6, "judgment_enabled": True},
    {"name": "1500Hz", "frequency_hz": 1500, "upper_limit_m_s2": 0.6, "judgment_enabled": True},
    {"name": "1800Hz", "frequency_hz": 1800, "upper_limit_m_s2": 0.6, "judgment_enabled": True},
    {"name": "2100Hz", "frequency_hz": 2100, "upper_limit_m_s2": 0.3, "judgment_enabled": True},
    {"name": "2400Hz", "frequency_hz": 2400, "upper_limit_m_s2": 0.3, "judgment_enabled": True},
    {"name": "2700Hz", "frequency_hz": 2700, "upper_limit_m_s2": 0.3, "judgment_enabled": True},
    {"name": "3000Hz", "frequency_hz": 3000, "upper_limit_m_s2": 0.3, "judgment_enabled": True},
    {"name": "3300Hz", "frequency_hz": 3300, "upper_limit_m_s2": 0.3, "judgment_enabled": True},
    {"name": "3600Hz", "frequency_hz": 3600, "upper_limit_m_s2": 0.3, "judgment_enabled": True},
]

DEFAULT_PRODUCT_SETTINGS = {
    "bearing_frequency": deepcopy(DEFAULT_BEARING_FREQUENCY),
    "frequency_band_groups": deepcopy(DEFAULT_FREQUENCY_BAND_GROUPS),
    "fixed_frequency_range_percent": 2,
    "fixed_frequency_points": deepcopy(DEFAULT_FIXED_FREQUENCY_POINTS),
    "high_energy_upper_limit": 1350,
    "high_peak_multiple": 3,
    "wave_threshold_m_s2": 0.01,
    "data_source": "Data0",
    "acceleration_sensitivity_m_s2_per_mv": 0.002594,
}

DEFAULT_PRODUCT_MODELS = [
    "C68",
    "46520-24-43000",
    "38230-24-60000",
    "52232-24-430",
    "40S18-24-500-C080",
    "52237-24-500",
    "52237-24-540",
    "压电陶瓷",
]


def make_default_product(model):
    return {
        "model": model,
        "quantity": "0",
        "operator": "",
    }


DEFAULT_CONFIG = {
    "app": {
        "title": "贝丰压电陶瓷频谱分析系统 - 操作端",
        "export_dir": "exports",
        "auto_connect_labjack": True,
    },
    "traceability": {
        "database_path": "data/traceability.db",
        "station_code": "SPECTRUM_01",
        "mapping_api": {
            "enabled": False,
            "bind_host": "0.0.0.0",
            "port": 8765,
            "token": "change-me",
        },
        "mes": {
            "enabled": False,
            "base_url": "http://MES_SERVER_IP:8000",
            "api_token": "",
            "upload_path": "/api/test-records",
            "heartbeat_path": "/api/stations/heartbeat",
            "timeout_seconds": 3,
            "sync_interval_seconds": 10,
            "batch_size": 50,
        },
    },
    "product": {
        "model": "压电陶瓷",
        "quantity": "0",
        "operator": "",
        "default_status": "合格",
    },
    "product_settings": deepcopy(DEFAULT_PRODUCT_SETTINGS),
    "products": [make_default_product(model) for model in DEFAULT_PRODUCT_MODELS],
    "acquisition": {
        "source": "labjack",
        "input_channel": "AIN3",
        "scan_rate": 100000,
        "scans_per_read": 20000,
        "display_time_sec": 1.5,
        "display_refresh_hz": 5,
        "avg_time_sec": 3.0,
        "records_per_motor": 1,
        "record_value_mode": "window_raw",
        "time_remove_mean": True,
        "invalid_input_voltage_abs_max": 10.5,
        "labjack": {
            "device_type": "ANY",
            "connection_type": "USB",
            "identifier": "ANY",
            "stream_receive_timeout_ms": 3000,
            "ain_range_v": 10.0,
            "ain_negative_channel": 199,
            "stream_resolution_index": 0,
            "stream_settling_us": 0,
        },
        "ni9234": {
            "module": "cDAQ1Mod1",
            "channel": "ai0",
            "scan_rate": 51200,
            "scans_per_read": 1500,
            "iepe_current_ma": 2.0,
            "sensitivity_mv_per_g": 10.0,
            "min_g": -500.0,
            "max_g": 500.0,
            "invalid_input_g_abs_max": 500.0,
        },
        "fft_max_freq": 25000,
        "judgment_max_freq_hz": 50000,
        "gravity_m_s2": 9.80665,
        "display_unit": "mm/s^2",
        "fft_display_mode": "amplitude",
        "fft_highpass_hz": 100,
        "fft_lowpass_hz": 25600,
        "fft_remove_mean": True,
        "fft_window_amplitude_correction": True,
        "time_y_limit_m_s2": {
            "min": -4.0,
            "max": 4.0,
            "auto_scale": True,
            "auto_percentile": 99.0,
            "auto_min_range_m_s2": 4.0,
            "auto_margin": 1.25,
            "auto_update_interval_sec": 0.2,
        },
        "fft_y_limit_m_s2": {
            "min": 0.0,
            "max": 0.05,
            "auto_scale": True,
            "auto_min_max": 0.03,
            "auto_margin": 1.3,
        },
        "raw_spectrum_export": {
            "frequency_interval_hz": 2.56,
            "include_detection_points": True,
            "points": 10000,
            "max_freq": 25600,
            "encoding": "gbk",
        },
    },
    "plc": {
        "enabled": False,
        "protocol": "fins_udp",
        "host": "192.168.250.1",
        "port": 9600,
        "poll_interval_ms": 100,
        "heartbeat_interval_ms": 1000,
        "heartbeat_timeout_sec": 3.0,
        "auto_resume_stable_sec": 1.0,
        "checkpoint_enabled": True,
        "checkpoint_dir": "data/automation_checkpoints",
        "positions_per_tray": 10,
        "addresses": {
            "tray_id": {"area": "DM", "address": 3008, "type": "word", "access": "read"},
            "pc_command_word": {"area": "DM", "address": 3500, "type": "word", "access": "write"},
            "plc_status_word": {"area": "DM", "address": 3501, "type": "word", "access": "read"},
            "spectrum_ok_word": {"area": "DM", "address": 3505, "type": "word", "access": "write"},
            "current_position": {"area": "DM", "address": 3508, "type": "word", "access": "read"},
            "pc_heartbeat": {"area": "DM", "address": 3503, "type": "word", "access": "write"},
            "plc_heartbeat": {"area": "DM", "address": 3504, "type": "word", "access": "read"},
        },
    },
}


def deep_merge(defaults, overrides):
    result = deepcopy(defaults)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config():
    if not CONFIG_PATH.exists():
        return deepcopy(DEFAULT_CONFIG), f"未找到配置文件: {CONFIG_PATH}"

    try:
        with CONFIG_PATH.open("r", encoding="utf-8") as file:
            user_config = json.load(file)
    except (OSError, json.JSONDecodeError) as e:
        return deepcopy(DEFAULT_CONFIG), f"配置文件读取失败，已使用默认配置: {e}"

    return deep_merge(DEFAULT_CONFIG, user_config), None


def save_config_file(config):
    with CONFIG_PATH.open("w", encoding="utf-8") as file:
        json.dump(config, file, ensure_ascii=False, indent=2)
        file.write("\n")


def normalize_list(values, length, default_value=0):
    result = list(values) if isinstance(values, list) else []
    result = result[:length]
    while len(result) < length:
        result.append(default_value)
    return result


def safe_filename_component(value):
    text = re.sub(r'[\\/:*?"<>|\s]+', "_", str(value or "").strip())
    return text.strip("._")


def parse_number(value, default_value=0.0):
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r"[-+]?\d+(?:\.\d+)?", str(value))
    return float(match.group(0)) if match else float(default_value)


def normalize_display_unit(value):
    text = str(value or "mm/s^2").strip().lower()
    text = text.replace("²", "^2").replace("μ", "u").replace(" ", "")
    aliases = {
        "m": "m/s^2",
        "m/s2": "m/s^2",
        "m/s^2": "m/s^2",
        "mm": "mm/s^2",
        "mm/s2": "mm/s^2",
        "mm/s^2": "mm/s^2",
        "um": "um/s^2",
        "um/s2": "um/s^2",
        "um/s^2": "um/s^2",
    }
    return aliases.get(text, "mm/s^2")


def display_scale_for_unit(unit):
    return DISPLAY_UNIT_SCALES.get(normalize_display_unit(unit), 1000.0)


def normalize_fft_display_mode(value):
    text = str(value or "amplitude").strip().lower()
    aliases = {
        "amp": "amplitude",
        "amplitude": "amplitude",
        "幅值": "amplitude",
        "asd": "asd",
        "density": "asd",
        "spectral_density": "asd",
        "谱密度": "asd",
    }
    return aliases.get(text, "amplitude")


def parse_sensor_mv_per_g(value, default_value=1890.26):
    return parse_number(value, default_value)


def parse_acceleration_sensitivity_m_s2_per_mv(settings, acquisition_config, gravity_m_s2):
    direct_value = settings.get(
        "acceleration_sensitivity_m_s2_per_mv",
        acquisition_config.get("acceleration_sensitivity_m_s2_per_mv", 0.002594),
    )
    if direct_value not in (None, ""):
        return parse_number(direct_value, 0.002594)

    reciprocal_value = settings.get(
        "acceleration_sensitivity_mv_per_m_s2",
        acquisition_config.get("acceleration_sensitivity_mv_per_m_s2", None),
    )
    if reciprocal_value not in (None, ""):
        mv_per_m_s2 = parse_number(reciprocal_value, 0.0)
        if mv_per_m_s2:
            return 1.0 / mv_per_m_s2

    legacy_scale = settings.get(
        "sensor_scale",
        acquisition_config.get("sensor_sensitivity_mv_per_g", None),
    )
    if legacy_scale not in (None, ""):
        mv_per_g = parse_sensor_mv_per_g(legacy_scale, 0.0)
        if mv_per_g:
            return gravity_m_s2 / mv_per_g

    return 0.002594


def to_float_list(values, length, default_value=0.0):
    result = []
    for value in normalize_list(values, length, default_value):
        try:
            result.append(float(value))
        except (TypeError, ValueError):
            result.append(float(default_value))
    return result


def to_float(value, default_value=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default_value)


def to_bool(value, default_value=False):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "y", "on", "是", "启用"}:
        return True
    if text in {"false", "0", "no", "n", "off", "否", "关闭"}:
        return False
    return bool(default_value)


def is_judgment_enabled(settings):
    if not isinstance(settings, dict):
        return True
    return to_bool(settings.get("judgment_enabled", True), True)


def normalize_bearing_frequency(value, display_scale_from_m_s2=1000.0):
    source = value if isinstance(value, dict) else {}
    normalized = deepcopy(DEFAULT_BEARING_FREQUENCY)
    normalized.update({key: source[key] for key in ("base_frequency_hz", "range_percent") if key in source})

    source_points = source.get("points", [])
    if not isinstance(source_points, list):
        source_points = []

    points = []
    default_points = DEFAULT_BEARING_FREQUENCY["points"]
    for index in range(FEATURE_FREQUENCY_COLUMNS):
        point = deepcopy(default_points[index])
        if index < len(source_points) and isinstance(source_points[index], dict):
            point.update(source_points[index])
        point["name"] = str(point.get("name", f"频率{index + 1}"))
        point["coefficient"] = to_float(point.get("coefficient"), default_points[index]["coefficient"])
        default_upper_m_s2 = to_float(default_points[index].get("upper_limit_m_s2"), 0.0)
        if "upper_limit_m_s2" in point:
            upper_limit_m_s2 = to_float(point.get("upper_limit_m_s2"), default_upper_m_s2)
        else:
            upper_limit_m_s2 = to_float(point.get("upper_limit"), default_upper_m_s2 * display_scale_from_m_s2) / display_scale_from_m_s2
        point["upper_limit_m_s2"] = upper_limit_m_s2
        point["upper_limit"] = upper_limit_m_s2 * display_scale_from_m_s2
        point["judgment_enabled"] = is_judgment_enabled(point)
        points.append(point)

    normalized["base_frequency_hz"] = to_float(normalized.get("base_frequency_hz"), 300)
    normalized["range_percent"] = to_float(normalized.get("range_percent"), 2)
    normalized["points"] = points
    return normalized


def normalize_frequency_band_groups(value, display_scale_from_m_s2=1000.0):
    source_groups = value if isinstance(value, list) else []
    groups = []
    for index, default_group in enumerate(DEFAULT_FREQUENCY_BAND_GROUPS):
        group = deepcopy(default_group)
        if index < len(source_groups) and isinstance(source_groups[index], dict):
            group.update(source_groups[index])
        group["name"] = str(group.get("name", default_group["name"]))
        group["start_hz"] = to_float(group.get("start_hz"), default_group["start_hz"])
        group["end_hz"] = to_float(group.get("end_hz"), default_group["end_hz"])
        if group["start_hz"] > group["end_hz"]:
            group["start_hz"], group["end_hz"] = group["end_hz"], group["start_hz"]
        if "peak_threshold_m_s2" in group:
            threshold_m_s2 = to_float(group.get("peak_threshold_m_s2"), 0.0)
            group["peak_threshold_m_s2"] = threshold_m_s2
            group["peak_threshold"] = threshold_m_s2 * display_scale_from_m_s2
        elif "peak_threshold" in group:
            threshold_m_s2 = to_float(group.get("peak_threshold"), 0.0) / display_scale_from_m_s2
            group["peak_threshold_m_s2"] = threshold_m_s2
            group["peak_threshold"] = threshold_m_s2 * display_scale_from_m_s2
        group["peak_count_upper_limit"] = to_float(group.get("peak_count_upper_limit"), 0.0)
        group["energy_upper_limit"] = to_float(group.get("energy_upper_limit"), 0.0)
        groups.append(group)
    return groups


def normalize_fixed_frequency_points(value, display_scale_from_m_s2=1000.0):
    source_points = value if isinstance(value, list) else DEFAULT_FIXED_FREQUENCY_POINTS
    points = []
    for index, item in enumerate(source_points):
        default_point = (
            deepcopy(DEFAULT_FIXED_FREQUENCY_POINTS[index])
            if index < len(DEFAULT_FIXED_FREQUENCY_POINTS)
            else {}
        )
        if isinstance(item, dict):
            point = deepcopy(default_point)
            point.update(item)
            frequency_hz = to_float(point.get("frequency_hz", point.get("frequency", point.get("hz", 0.0))), 0.0)
            name = str(point.get("name", f"{frequency_hz:g}Hz"))
            search_width_hz = to_float(point.get("search_width_hz"), 0.0)
        else:
            point = deepcopy(default_point)
            frequency_hz = to_float(item, 0.0)
            name = f"{frequency_hz:g}Hz"
            search_width_hz = 0.0

        if frequency_hz <= 0:
            continue

        default_upper_m_s2 = to_float(default_point.get("upper_limit_m_s2"), 0.0)
        if "upper_limit_m_s2" in point:
            upper_limit_m_s2 = to_float(point.get("upper_limit_m_s2"), default_upper_m_s2)
        elif "upper_limit" in point:
            upper_limit_m_s2 = to_float(point.get("upper_limit"), default_upper_m_s2 * display_scale_from_m_s2) / display_scale_from_m_s2
        else:
            upper_limit_m_s2 = default_upper_m_s2

        points.append({
            "name": name or f"固定频率{index + 1}",
            "frequency_hz": frequency_hz,
            "search_width_hz": max(search_width_hz, 0.0),
            "upper_limit_m_s2": upper_limit_m_s2,
            "upper_limit": upper_limit_m_s2 * display_scale_from_m_s2,
            "judgment_enabled": is_judgment_enabled(point),
        })
    return points


def normalize_product_settings(raw_settings=None, default_settings=None, display_scale_from_m_s2=1000.0):
    raw_settings = raw_settings if isinstance(raw_settings, dict) else {}
    settings = deepcopy(default_settings or DEFAULT_PRODUCT_SETTINGS)
    settings = deep_merge(settings, raw_settings)

    if (
        "acceleration_sensitivity_m_s2_per_mv" not in raw_settings
        and "acceleration_sensitivity_mv_per_m_s2" not in raw_settings
        and "sensor_scale" in raw_settings
    ):
        mv_per_g = parse_sensor_mv_per_g(raw_settings.get("sensor_scale"), 0.0)
        if mv_per_g:
            settings["acceleration_sensitivity_m_s2_per_mv"] = 9.80665 / mv_per_g

    if "wave_threshold_m_s2" in settings:
        threshold_m_s2 = to_float(settings.get("wave_threshold_m_s2"), 0.01)
    else:
        threshold_m_s2 = to_float(settings.get("wave_threshold"), 10.0) / display_scale_from_m_s2
    settings["wave_threshold_m_s2"] = threshold_m_s2
    settings["wave_threshold"] = threshold_m_s2 * display_scale_from_m_s2
    settings["high_energy_upper_limit"] = to_float(settings.get("high_energy_upper_limit"), 1350)
    settings["high_peak_multiple"] = to_float(settings.get("high_peak_multiple"), 3)
    settings["data_source"] = str(settings.get("data_source", "Data0"))
    settings["acceleration_sensitivity_m_s2_per_mv"] = parse_acceleration_sensitivity_m_s2_per_mv(
        settings,
        {},
        9.80665,
    )
    settings.pop("display_format", None)
    settings["bearing_frequency"] = normalize_bearing_frequency(
        settings.get("bearing_frequency"),
        display_scale_from_m_s2,
    )
    settings["frequency_band_groups"] = normalize_frequency_band_groups(
        settings.get("frequency_band_groups"),
        display_scale_from_m_s2,
    )
    settings["fixed_frequency_range_percent"] = max(
        to_float(settings.get("fixed_frequency_range_percent"), 2.0),
        0.0,
    )
    settings["fixed_frequency_points"] = normalize_fixed_frequency_points(
        settings.get("fixed_frequency_points"),
        display_scale_from_m_s2,
    )
    return settings


def normalize_product(product, default_settings=None, display_scale_from_m_s2=1000.0):
    normalized = make_default_product(str(product.get("model", "新产品")))
    normalized.update({key: value for key, value in product.items() if key != "settings"})
    normalized["settings"] = normalize_product_settings(
        product.get("settings", {}),
        default_settings,
        display_scale_from_m_s2,
    )
    return normalized


def normalize_products(config, default_settings=None, display_scale_from_m_s2=1000.0):
    products = config.get("products")
    if not isinstance(products, list) or not products:
        products = [make_default_product(config.get("product", {}).get("model", "46520-24-43000"))]

    normalized_products = []
    seen = set()
    for product in products:
        normalized = normalize_product(product, default_settings, display_scale_from_m_s2)
        model = str(normalized.get("model", "")).strip()
        if not model or model in seen:
            continue
        normalized["model"] = model
        normalized_products.append(normalized)
        seen.add(model)

    if not normalized_products:
        normalized_products.append(normalize_product(make_default_product("46520-24-43000"), default_settings, display_scale_from_m_s2))

    current_model = str(config.get("product", {}).get("model", normalized_products[0]["model"])).strip()
    if current_model not in {product["model"] for product in normalized_products}:
        normalized_products.insert(0, normalize_product(make_default_product(current_model), default_settings, display_scale_from_m_s2))

    config["products"] = normalized_products
    if not config.get("product", {}).get("model"):
        config.setdefault("product", {})["model"] = normalized_products[0]["model"]
    return normalized_products


def settings_to_storage(settings, display_scale_from_m_s2=1000.0):
    normalized = normalize_product_settings(settings, DEFAULT_PRODUCT_SETTINGS, display_scale_from_m_s2)
    bearing = normalized.get("bearing_frequency", {})
    storage_points = []
    for point in bearing.get("points", []):
        storage_points.append({
            "name": point.get("name", ""),
            "coefficient": to_float(point.get("coefficient"), 0.0),
            "upper_limit_m_s2": to_float(point.get("upper_limit_m_s2"), 0.0),
            "judgment_enabled": is_judgment_enabled(point),
        })

    storage_groups = []
    for group in normalized.get("frequency_band_groups", []):
        stored_group = {
            "name": group.get("name", ""),
            "start_hz": to_float(group.get("start_hz"), 0.0),
            "end_hz": to_float(group.get("end_hz"), 0.0),
        }
        if "peak_threshold_m_s2" in group:
            stored_group["peak_threshold_m_s2"] = to_float(group.get("peak_threshold_m_s2"), 0.0)
        if "peak_count_upper_limit" in group:
            stored_group["peak_count_upper_limit"] = to_float(group.get("peak_count_upper_limit"), 0.0)
        if "energy_upper_limit" in group:
            stored_group["energy_upper_limit"] = to_float(group.get("energy_upper_limit"), 0.0)
        storage_groups.append(stored_group)

    fixed_points = []
    for point in normalized.get("fixed_frequency_points", []):
        stored_point = {
            "name": point.get("name", ""),
            "frequency_hz": to_float(point.get("frequency_hz"), 0.0),
            "upper_limit_m_s2": to_float(point.get("upper_limit_m_s2"), 0.0),
            "judgment_enabled": is_judgment_enabled(point),
        }
        if to_float(point.get("search_width_hz"), 0.0) > 0:
            stored_point["search_width_hz"] = to_float(point.get("search_width_hz"), 0.0)
        fixed_points.append(stored_point)

    return {
        "high_energy_upper_limit": to_float(normalized.get("high_energy_upper_limit"), 1350),
        "high_peak_multiple": to_float(normalized.get("high_peak_multiple"), 3),
        "wave_threshold_m_s2": to_float(normalized.get("wave_threshold_m_s2"), 0.01),
        "data_source": str(normalized.get("data_source", "Data0")),
        "acceleration_sensitivity_m_s2_per_mv": to_float(
            normalized.get("acceleration_sensitivity_m_s2_per_mv"),
            0.002594,
        ),
        "bearing_frequency": {
            "base_frequency_hz": to_float(bearing.get("base_frequency_hz"), 300),
            "range_percent": to_float(bearing.get("range_percent"), 2),
            "points": storage_points,
        },
        "frequency_band_groups": storage_groups,
        "fixed_frequency_range_percent": max(
            to_float(normalized.get("fixed_frequency_range_percent"), 2.0),
            0.0,
        ),
        "fixed_frequency_points": fixed_points,
    }


def values_equal(left, right):
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return abs(float(left) - float(right)) < 1e-9
    return left == right


def diff_value(value, default_value):
    if isinstance(value, dict) and isinstance(default_value, dict):
        diff = {}
        for key, sub_value in value.items():
            sub_diff = diff_value(sub_value, default_value.get(key))
            if sub_diff is not None:
                diff[key] = sub_diff
        return diff or None

    if values_equal(value, default_value):
        return None
    return deepcopy(value)


def compact_products_for_save(products, default_settings, display_scale_from_m_s2):
    default_storage = settings_to_storage(default_settings, display_scale_from_m_s2)
    compacted = []
    for product in products:
        normalized = normalize_product(product, default_settings, display_scale_from_m_s2)
        settings_storage = settings_to_storage(normalized.get("settings", {}), display_scale_from_m_s2)
        settings_diff = diff_value(settings_storage, default_storage)
        compacted_product = {
            "model": str(normalized.get("model", "")),
            "quantity": str(normalized.get("quantity", "0")),
            "operator": str(normalized.get("operator", "")),
        }
        if settings_diff:
            compacted_product["settings"] = settings_diff
        compacted.append(compacted_product)
    return compacted


class ProductSelectionDialog(QDialog):
    def __init__(self, products, current_model, parent=None):
        super().__init__(parent)
        self.setWindowTitle("产品选择")
        self.resize(900, 260)
        self.selected_model = None
        self.deleted_model = None
        self.products = products

        layout = QVBoxLayout(self)
        title = QLabel("产品选择")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(14)
        layout.addLayout(grid)

        for index, product in enumerate(products):
            model = str(product.get("model", ""))
            button = QPushButton(model)
            button.setMinimumSize(170, 44)
            if model == current_model:
                button.setText(f"{model}  √")
            button.clicked.connect(lambda checked=False, value=model: self.choose_product(value))
            grid.addWidget(button, index // 5, index % 5)

        delete_layout = QHBoxLayout()
        delete_layout.addWidget(QLabel("删除产品:"))
        self.delete_combo = QComboBox()
        self.delete_combo.addItems([str(product.get("model", "")) for product in products])
        if current_model:
            self.delete_combo.setCurrentText(current_model)
        delete_layout.addWidget(self.delete_combo)

        delete_button = QPushButton("删除选中产品")
        delete_button.clicked.connect(self.request_delete)
        delete_layout.addWidget(delete_button)

        close_button = QPushButton("关闭")
        close_button.clicked.connect(self.reject)
        delete_layout.addWidget(close_button)
        layout.addLayout(delete_layout)

    def choose_product(self, model):
        self.selected_model = model
        self.accept()

    def request_delete(self):
        self.deleted_model = self.delete_combo.currentText()
        self.accept()


class ProductSettingsDialog(QDialog):
    def __init__(self, product, products, default_settings, display_unit, display_scale_from_m_s2, parent=None):
        super().__init__(parent)
        self.setWindowTitle("产品设置")
        self.resize(1280, 620)
        self.original_model = str(product.get("model", ""))
        self.action = None
        self.default_settings = default_settings
        self.display_unit = display_unit
        self.display_scale_from_m_s2 = display_scale_from_m_s2

        layout = QVBoxLayout(self)
        title = QLabel("风机参数测试记录表--设置")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        top_layout = QHBoxLayout()
        self.product_combo = QComboBox()
        self.product_combo.addItems([str(item.get("model", "")) for item in products])
        self.product_combo.setCurrentText(self.original_model)
        top_layout.addWidget(QLabel("当前产品:"))
        top_layout.addWidget(self.product_combo)
        self.product_combo.currentTextChanged.connect(self.change_product)

        self.model_edit = QLineEdit(self.original_model)
        self.qty_edit = QLineEdit(str(product.get("quantity", "0")))
        self.operator_edit = QLineEdit(str(product.get("operator", "")))
        top_layout.addWidget(QLabel("型号:"))
        top_layout.addWidget(self.model_edit)
        top_layout.addWidget(QLabel("数量Qty:"))
        top_layout.addWidget(self.qty_edit)
        top_layout.addWidget(QLabel("操作员Operator:"))
        top_layout.addWidget(self.operator_edit)
        layout.addLayout(top_layout)

        bearing_layout = QHBoxLayout()
        self.bearing_base_edit = QLineEdit()
        self.bearing_range_edit = QLineEdit()
        self.fixed_frequency_range_edit = QLineEdit()
        bearing_layout.addWidget(QLabel("基准频率Hz:"))
        bearing_layout.addWidget(self.bearing_base_edit)
        bearing_layout.addWidget(QLabel("轴承范围%:"))
        bearing_layout.addWidget(self.bearing_range_edit)
        bearing_layout.addWidget(QLabel("固定频点范围%:"))
        bearing_layout.addWidget(self.fixed_frequency_range_edit)
        bearing_layout.addStretch()
        layout.addLayout(bearing_layout)

        self.feature_table = QTableWidget(FEATURE_FREQUENCY_COLUMNS, 3)
        self.feature_table.setHorizontalHeaderLabels(["振动名称", "乘数系数", f"有效值上限({self.display_unit})"])
        self.feature_table.verticalHeader().setVisible(False)
        self.feature_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.feature_table)

        self.band_group_table = QTableWidget(len(DEFAULT_FREQUENCY_BAND_GROUPS), 3)
        self.band_group_table.setHorizontalHeaderLabels(["频段名称", "起始Hz", "结束Hz"])
        self.band_group_table.verticalHeader().setVisible(False)
        self.band_group_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.band_group_table)

        form = QFormLayout()
        self.high_energy_edit = QLineEdit()
        self.high_peak_edit = QLineEdit()
        self.wave_threshold_edit = QLineEdit()
        self.data_source_edit = QLineEdit()
        self.acceleration_sensitivity_edit = QLineEdit()
        form.addRow("高频信号能量上限", self.high_energy_edit)
        form.addRow("高频信号峰值数", self.high_peak_edit)
        form.addRow(f"波峰阈值({self.display_unit})", self.wave_threshold_edit)
        form.addRow("数据源设置", self.data_source_edit)
        form.addRow("加速度灵敏度(m/s²/mV)", self.acceleration_sensitivity_edit)
        layout.addLayout(form)

        button_layout = QHBoxLayout()
        self.save_button = QPushButton("保存设置")
        self.add_button = QPushButton("新增为产品")
        self.delete_button = QPushButton("删除产品")
        self.close_button = QPushButton("退出")
        self.save_button.clicked.connect(self.save_product)
        self.add_button.clicked.connect(self.add_product)
        self.delete_button.clicked.connect(self.delete_product)
        self.close_button.clicked.connect(self.reject)
        button_layout.addStretch()
        button_layout.addWidget(self.save_button)
        button_layout.addWidget(self.add_button)
        button_layout.addWidget(self.delete_button)
        button_layout.addWidget(self.close_button)
        layout.addLayout(button_layout)

        self.products = products
        self.load_product(product)

    def load_product(self, product):
        self.original_model = str(product.get("model", ""))
        settings = normalize_product(product, self.default_settings, self.display_scale_from_m_s2).get("settings", {})
        self.model_edit.setText(self.original_model)
        self.qty_edit.setText(str(product.get("quantity", "0")))
        self.operator_edit.setText(str(product.get("operator", "")))

        bearing = settings.get("bearing_frequency", {})
        self.bearing_base_edit.setText(str(bearing.get("base_frequency_hz", 300)))
        self.bearing_range_edit.setText(str(bearing.get("range_percent", 2)))
        self.fixed_frequency_range_edit.setText(str(settings.get("fixed_frequency_range_percent", 2)))
        self.feature_table.clearContents()
        self.band_group_table.clearContents()

        for row, point in enumerate(bearing.get("points", [])):
            values = [
                point.get("name", f"频率{row + 1}"),
                point.get("coefficient", 0),
                point.get("upper_limit", 0),
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.feature_table.setItem(row, column, item)

        for row, group in enumerate(settings.get("frequency_band_groups", [])):
            values = [
                group.get("name", ""),
                group.get("start_hz", 0),
                group.get("end_hz", 0),
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.band_group_table.setItem(row, column, item)

        self.high_energy_edit.setText(str(settings.get("high_energy_upper_limit", "")))
        self.high_peak_edit.setText(str(settings.get("high_peak_multiple", "")))
        self.wave_threshold_edit.setText(str(settings.get("wave_threshold", "")))
        self.data_source_edit.setText(str(settings.get("data_source", "")))
        self.acceleration_sensitivity_edit.setText(str(settings.get("acceleration_sensitivity_m_s2_per_mv", "")))

    def change_product(self, model):
        for product in self.products:
            if str(product.get("model", "")) == model:
                self.load_product(product)
                return

    def table_text(self, table, row, column, default_value=""):
        item = table.item(row, column)
        text = item.text().strip() if item is not None else ""
        return text if text else default_value

    def table_number(self, table, row, column, default_value=0):
        item = table.item(row, column)
        text = item.text().strip() if item is not None else ""
        if text == "":
            return default_value
        return float(text)

    def product_data(self):
        model = self.model_edit.text().strip()
        feature_points = []
        for row in range(FEATURE_FREQUENCY_COLUMNS):
            feature_points.append({
                "name": self.table_text(self.feature_table, row, 0, f"频率{row + 1}"),
                "coefficient": self.table_number(self.feature_table, row, 1),
                "upper_limit": self.table_number(self.feature_table, row, 2),
            })

        band_groups = []
        for row in range(len(DEFAULT_FREQUENCY_BAND_GROUPS)):
            band_groups.append({
                "name": self.table_text(self.band_group_table, row, 0, f"频段{row + 1}"),
                "start_hz": self.table_number(self.band_group_table, row, 1),
                "end_hz": self.table_number(self.band_group_table, row, 2),
            })

        return {
            "model": model,
            "quantity": self.qty_edit.text().strip(),
            "operator": self.operator_edit.text().strip(),
            "settings": {
                "bearing_frequency": {
                    "base_frequency_hz": to_float(self.bearing_base_edit.text(), 300),
                    "range_percent": to_float(self.bearing_range_edit.text(), 2),
                    "points": feature_points,
                },
                "fixed_frequency_range_percent": max(
                    to_float(self.fixed_frequency_range_edit.text(), 2),
                    0.0,
                ),
                "frequency_band_groups": band_groups,
                "high_energy_upper_limit": self.high_energy_edit.text().strip(),
                "high_peak_multiple": self.high_peak_edit.text().strip(),
                "wave_threshold": self.wave_threshold_edit.text().strip(),
                "data_source": self.data_source_edit.text().strip(),
                "acceleration_sensitivity_m_s2_per_mv": to_float(self.acceleration_sensitivity_edit.text(), 0.002594),
            },
        }

    def save_product(self):
        self.action = "save"
        self.accept()

    def add_product(self):
        self.action = "add"
        self.accept()

    def delete_product(self):
        self.action = "delete"
        self.accept()


class PlcWorker(QObject):
    state_received = Signal(int, int, int, int)
    connection_changed = Signal(bool, str)
    io_event = Signal(str, str)
    finished = Signal()

    def __init__(self, plc_config):
        super().__init__()
        self.plc_config = deepcopy(plc_config)
        self.addresses = self.plc_config.get("addresses", {})
        self.poll_interval_ms = max(int(self.plc_config.get("poll_interval_ms", 100)), 20)
        self.heartbeat_interval_sec = max(
            float(self.plc_config.get("heartbeat_interval_ms", 1000)) / 1000.0,
            0.2,
        )
        self.client = None
        self.timer = None
        self.command_word = 0
        self.command_dirty = True
        self.result_word = None
        self.result_dirty = False
        self.heartbeat = 0
        self.last_heartbeat_write = -self.heartbeat_interval_sec
        self.connected = False
        self.last_connection_message = None
        self.last_logged_status_word = None
        self.last_logged_position = None
        self.last_logged_tray_id = None
        self.last_logged_plc_heartbeat = None
        self.last_console_heartbeat = None

    def address(self, name, default_address):
        config = self.addresses.get(name, {})
        return str(config.get("area", "DM")), int(config.get("address", default_address))

    @staticmethod
    def address_text(area, address):
        return f"{area}{address}"

    @staticmethod
    def command_word_text(value):
        return (
            f"0x{value:04X} "
            f"[开始={bool(value & (1 << PC_START_BIT))}, "
            f"停止={bool(value & (1 << PC_STOP_BIT))}, "
            f"采集完成={bool(value & (1 << PC_POINT_DONE_BIT))}, "
            f"上位机故障={bool(value & (1 << PC_FAULT_BIT))}]"
        )

    @staticmethod
    def status_word_text(value):
        return (
            f"0x{value:04X} "
            f"[急停={bool(value & (1 << PLC_EMERGENCY_BIT))}, "
            f"采集就绪={bool(value & (1 << PLC_POINT_READY_BIT))}, "
            f"全部完成={bool(value & (1 << PLC_ALL_COMPLETE_BIT))}, "
            f"PLC故障={bool(value & (1 << PLC_FAULT_BIT))}]"
        )

    def result_word_text(self, value):
        position_count = min(max(int(self.plc_config.get("positions_per_tray", 10)), 1), 15)
        ok_positions = [
            str(position)
            for position in range(1, position_count + 1)
            if value & (1 << position)
        ]
        return f"0x{value:04X} [OK位置={','.join(ok_positions) if ok_positions else '无'}]"

    @Slot()
    def start(self):
        self.timer = QTimer(self)
        self.timer.setInterval(self.poll_interval_ms)
        self.timer.timeout.connect(self.poll)
        self.timer.start()
        self.poll()

    @Slot(int)
    def set_command_word(self, value):
        value = int(value) & 0xFFFF
        if value != self.command_word:
            self.command_word = value
            self.command_dirty = True

    @Slot(int)
    def set_result_word(self, value):
        value = int(value) & 0xFFFF
        if self.result_word is None or value != self.result_word:
            self.result_word = value
            self.result_dirty = True

    def set_connection_state(self, connected, message):
        message = str(message)
        if connected != self.connected or message != self.last_connection_message:
            self.connected = connected
            self.last_connection_message = message
            self.connection_changed.emit(connected, message)

    def ensure_client(self):
        if self.client is None:
            self.client = FinsUdpClient.from_config(self.plc_config)
            self.client.connect()

    def read_plc_state(self):
        tray_area, tray_address = self.address("tray_id", 3008)
        status_area, status_address = self.address("plc_status_word", 3501)
        position_area, position_address = self.address("current_position", 3508)
        heartbeat_area, heartbeat_address = self.address("plc_heartbeat", 3504)

        # DM3008 与 DM3501～DM3508 相距较远，单独读取避免每次轮询读500个无用DM字。
        tray_id = self.client.read_words(tray_area, tray_address, 1)[0]

        if status_area == position_area == heartbeat_area:
            first_address = min(status_address, position_address, heartbeat_address)
            last_address = max(status_address, position_address, heartbeat_address)
            values = self.client.read_words(status_area, first_address, last_address - first_address + 1)
            return (
                tray_id,
                values[status_address - first_address],
                values[position_address - first_address],
                values[heartbeat_address - first_address],
            )

        status_word = self.client.read_words(status_area, status_address, 1)[0]
        position = self.client.read_words(position_area, position_address, 1)[0]
        heartbeat = self.client.read_words(heartbeat_area, heartbeat_address, 1)[0]
        return tray_id, status_word, position, heartbeat

    @Slot()
    def poll(self):
        try:
            self.ensure_client()
            result_area, result_address = self.address("spectrum_ok_word", 3505)
            if self.result_dirty and self.result_word is not None:
                self.client.write_words(result_area, result_address, [self.result_word])
                self.result_dirty = False
                self.io_event.emit(
                    "PLC-TX",
                    f"{self.address_text(result_area, result_address)} <- "
                    f"{self.result_word_text(self.result_word)}",
                )

            command_area, command_address = self.address("pc_command_word", 3500)
            if self.command_dirty:
                self.client.write_words(command_area, command_address, [self.command_word])
                self.command_dirty = False
                self.io_event.emit(
                    "PLC-TX",
                    f"{self.address_text(command_area, command_address)} <- "
                    f"{self.command_word_text(self.command_word)}",
                )

            now = monotonic()
            if now - self.last_heartbeat_write >= self.heartbeat_interval_sec:
                heartbeat_area, heartbeat_address = self.address("pc_heartbeat", 3503)
                self.heartbeat = (self.heartbeat + 1) & 0xFFFF
                self.client.write_words(heartbeat_area, heartbeat_address, [self.heartbeat])
                self.last_heartbeat_write = now

            tray_id, status_word, position, plc_heartbeat = self.read_plc_state()
            tray_id = int(tray_id) & 0xFFFF
            status_word = int(status_word) & 0xFFFF
            position = int(position)
            plc_heartbeat = int(plc_heartbeat) & 0xFFFF
            if (
                tray_id != self.last_logged_tray_id
                or status_word != self.last_logged_status_word
                or position != self.last_logged_position
            ):
                tray_area, tray_address = self.address("tray_id", 3008)
                status_area, status_address = self.address("plc_status_word", 3501)
                position_area, position_address = self.address("current_position", 3508)
                self.io_event.emit(
                    "PLC-RX",
                    f"{self.address_text(tray_area, tray_address)} -> 托盘 {tray_id} | "
                    f"{self.address_text(status_area, status_address)} -> "
                    f"{self.status_word_text(status_word)} | "
                    f"{self.address_text(position_area, position_address)} -> 位置 {position}",
                )
                self.last_logged_tray_id = tray_id
                self.last_logged_status_word = status_word
                self.last_logged_position = position
            if (
                self.heartbeat != self.last_console_heartbeat
                and (self.heartbeat == 1 or self.heartbeat % 10 == 0)
            ):
                print(
                    f"[PLC-HEARTBEAT] TX DM3503={self.heartbeat} | RX DM3504={plc_heartbeat}",
                    flush=True,
                )
                self.last_console_heartbeat = self.heartbeat
            self.last_logged_plc_heartbeat = plc_heartbeat
            self.set_connection_state(True, "FINS通信正常")
            self.state_received.emit(tray_id, status_word, position, plc_heartbeat)
        except Exception as error:
            if self.client is not None:
                self.client.close()
                self.client = None
            self.command_dirty = True
            if self.result_word is not None:
                self.result_dirty = True
            self.set_connection_state(False, str(error))

    @Slot(int)
    def shutdown(self, final_command_word):
        if self.timer is not None:
            self.timer.stop()
        self.command_word = int(final_command_word) & 0xFFFF
        try:
            self.ensure_client()
            command_area, command_address = self.address("pc_command_word", 3500)
            self.client.write_words(command_area, command_address, [self.command_word])
            self.io_event.emit(
                "PLC-TX",
                f"关闭前写入 {self.address_text(command_area, command_address)} <- "
                f"{self.command_word_text(self.command_word)}",
            )
        except Exception:
            pass
        if self.client is not None:
            self.client.close()
            self.client = None
        self.finished.emit()
        QThread.currentThread().quit()


class AcquisitionWorker(QThread):
    stream_started = Signal(float, int)
    display_ready = Signal()
    record_ready = Signal(object)
    stream_error = Signal(str)

    DUMMY_VALUE = -9999.0

    def __init__(self, handle, config, stop_after_record=False, parent=None):
        super().__init__(parent)
        self.handle = handle
        self.config = deepcopy(config)
        self.stop_after_record = bool(stop_after_record)
        self.source_type = normalize_acquisition_source(self.config.get("source"))
        self.ni_config = deepcopy(self.config.get("ni9234", {}))
        self.input_channel = str(self.config.get("input_channel", "AIN3"))
        if self.source_type == ACQUISITION_SOURCE_NI9234:
            self.requested_scan_rate = max(float(self.ni_config.get("scan_rate", 51200)), 1.0)
            self.scans_per_read = max(int(self.ni_config.get("scans_per_read", 1500)), 1)
            self.source_label = "NI-9234 加速度传感器"
        else:
            self.requested_scan_rate = max(float(self.config.get("scan_rate", 100000)), 1.0)
            self.scans_per_read = max(int(self.config.get("scans_per_read", 20000)), 1)
            self.source_label = "LabJack 频谱输入"
        self.display_time_sec = max(float(self.config.get("display_time_sec", 1.5)), 0.01)
        self.display_refresh_hz = max(float(self.config.get("display_refresh_hz", 5.0)), 0.5)
        self.record_time_sec = max(float(self.config.get("avg_time_sec", 3.0)), 0.001)
        self.record_value_mode = str(self.config.get("record_value_mode", "window_raw")).strip().lower()
        if self.record_value_mode not in {"batch_mean", "window_raw"}:
            self.record_value_mode = "window_raw"
        self.time_remove_mean = to_bool(self.config.get("time_remove_mean", True), True)
        self.invalid_voltage_limit = max(
            to_float(self.config.get("invalid_input_voltage_abs_max"), 10.5),
            0.0,
        )
        self.invalid_acceleration_g_limit = max(
            to_float(self.ni_config.get("invalid_input_g_abs_max"), 500.0),
            0.0,
        )
        self.gravity_m_s2 = max(to_float(self.config.get("gravity_m_s2"), 9.80665), 1e-12)
        sensitivity = to_float(self.config.get("acceleration_sensitivity_m_s2_per_mv"), 0.0)
        display_scale = to_float(self.config.get("display_scale_from_m_s2"), 1.0)
        self.display_scale_from_m_s2 = display_scale
        self.voltage_scale = 1000.0 * sensitivity * display_scale if sensitivity else 1.0
        self.labjack_config = deepcopy(self.config.get("labjack", {}))

        self.actual_scan_rate = self.requested_scan_rate
        self.display_points = max(
            int(round(self.requested_scan_rate * self.display_time_sec)),
            self.scans_per_read,
        )
        self.display_buffer = np.zeros(self.display_points, dtype=float)
        self.display_valid_samples = 0
        self.samples_since_display = 0
        self.total_samples = 0
        self.device_backlog = 0
        self.ljm_backlog = 0
        self.max_device_backlog = 0
        self.max_ljm_backlog = 0
        self.record_target_samples = 1
        self.display_payload_lock = Lock()
        self.latest_display_payload = None
        self.display_signal_pending = False
        self.reset_record_accumulators()

    def configure_device(self):
        ljm.writeLibraryConfigS("LJM_STREAM_AIN_BINARY", 0)
        ljm.writeLibraryConfigS(
            "LJM_STREAM_SCANS_RETURN",
            ljm.constants.STREAM_SCANS_RETURN_ALL,
        )
        ljm.writeLibraryConfigS(
            "LJM_STREAM_RECEIVE_TIMEOUT_MS",
            max(to_float(self.labjack_config.get("stream_receive_timeout_ms"), 3000), 0.0),
        )
        register_values = (
            ("AIN_ALL_RANGE", self.labjack_config.get("ain_range_v", 10.0)),
            ("AIN_ALL_NEGATIVE_CH", self.labjack_config.get("ain_negative_channel", 199)),
            ("STREAM_RESOLUTION_INDEX", self.labjack_config.get("stream_resolution_index", 0)),
            ("STREAM_SETTLING_US", self.labjack_config.get("stream_settling_us", 0)),
        )
        for register, value in register_values:
            ljm.eWriteName(self.handle, register, float(value))

    def reset_record_accumulators(self):
        self.record_sum = 0.0
        self.record_sum_squares = 0.0
        self.record_sample_count = 0
        self.record_min_value = None
        self.record_max_value = None
        self.batch_rms_values = []
        self.batch_vpp_values = []

    def append_display_data(self, data):
        count = int(data.size)
        if count <= 0:
            return
        if count >= self.display_points:
            self.display_buffer[:] = data[-self.display_points:]
            self.display_valid_samples = self.display_points
            return
        self.display_buffer[:-count] = self.display_buffer[count:]
        self.display_buffer[-count:] = data
        self.display_valid_samples = min(self.display_valid_samples + count, self.display_points)

    def display_snapshot(self):
        raw_snapshot = self.display_buffer.copy()
        processed_snapshot = raw_snapshot.copy()
        valid_count = min(self.display_valid_samples, self.display_points)
        if valid_count < self.display_points:
            processed_snapshot[:self.display_points - valid_count] = 0.0
            raw_snapshot[:self.display_points - valid_count] = 0.0
        if self.time_remove_mean and valid_count > 0:
            valid_start = self.display_points - valid_count
            processed_snapshot[valid_start:] -= np.mean(processed_snapshot[valid_start:])
        return processed_snapshot, raw_snapshot

    def accumulate_record_data(self, data):
        if data.size == 0:
            return
        self.record_sum += float(np.sum(data))
        self.record_sum_squares += float(np.sum(data ** 2))
        self.record_sample_count += int(data.size)
        data_min = float(np.min(data))
        data_max = float(np.max(data))
        self.record_min_value = data_min if self.record_min_value is None else min(self.record_min_value, data_min)
        self.record_max_value = data_max if self.record_max_value is None else max(self.record_max_value, data_max)

        batch_data = data - np.mean(data) if self.time_remove_mean else data
        self.batch_rms_values.append(float(np.sqrt(np.mean(batch_data ** 2))))
        self.batch_vpp_values.append(data_max - data_min)

    def calculate_record_values(self):
        if self.record_sample_count <= 0:
            return None
        if self.record_value_mode == "batch_mean":
            return float(np.mean(self.batch_rms_values)), float(np.mean(self.batch_vpp_values))

        mean_square = self.record_sum_squares / self.record_sample_count
        if self.time_remove_mean:
            mean_value = self.record_sum / self.record_sample_count
            mean_square = max(mean_square - mean_value ** 2, 0.0)
        rms_value = float(np.sqrt(mean_square))
        min_value = self.record_min_value if self.record_min_value is not None else 0.0
        max_value = self.record_max_value if self.record_max_value is not None else 0.0
        return rms_value, float(max_value - min_value)

    def make_payload(self, data=None):
        processed_snapshot, raw_snapshot = self.display_snapshot()
        if data is None or data.size == 0:
            realtime_rms = 0.0
            realtime_vpp = 0.0
        else:
            metric_data = data - np.mean(data) if self.time_remove_mean else data
            realtime_rms = float(np.sqrt(np.mean(metric_data ** 2)))
            realtime_vpp = float(np.max(data) - np.min(data))
        return {
            "data": processed_snapshot,
            "raw_data": raw_snapshot,
            "acquisition_source": self.source_type,
            "acquisition_source_label": self.source_label,
            "input_channel": self.input_channel,
            "realtime_rms": realtime_rms,
            "realtime_vpp": realtime_vpp,
            "device_backlog": self.device_backlog,
            "ljm_backlog": self.ljm_backlog,
            "max_device_backlog": self.max_device_backlog,
            "max_ljm_backlog": self.max_ljm_backlog,
            "total_samples": self.total_samples,
            "actual_scan_rate": self.actual_scan_rate,
        }

    def publish_display(self, data):
        should_emit = False
        payload = self.make_payload(data)
        with self.display_payload_lock:
            self.latest_display_payload = payload
            if not self.display_signal_pending:
                self.display_signal_pending = True
                should_emit = True
        if should_emit:
            self.display_ready.emit()

    def take_latest_display_payload(self):
        with self.display_payload_lock:
            payload = self.latest_display_payload
            self.latest_display_payload = None
            self.display_signal_pending = False
        return payload

    def emit_record(self):
        values = self.calculate_record_values()
        if values is None:
            raise RuntimeError("当前窗口没有采集到有效数据")
        payload = self.make_payload()
        payload.update({
            "rms": values[0],
            "vpp": values[1],
            "sample_count": self.record_sample_count,
            "duration_sec": self.record_sample_count / self.actual_scan_rate,
            "mode_label": "整体计算" if self.record_value_mode == "window_raw" else "批次平均",
        })
        self.record_ready.emit(payload)

    def validate_voltage_data(self, voltage_data):
        if voltage_data.size == 0:
            raise RuntimeError("采集卡返回了空数据")
        if not np.all(np.isfinite(voltage_data)):
            raise RuntimeError("采集数据包含 NaN 或无穷大")
        dummy_count = int(np.count_nonzero(voltage_data == self.DUMMY_VALUE))
        if dummy_count:
            raise RuntimeError(f"检测到 {dummy_count} 个丢样占位值(-9999)，当前窗口已作废")
        if self.invalid_voltage_limit > 0:
            max_voltage = float(np.max(np.abs(voltage_data)))
            if max_voltage > self.invalid_voltage_limit:
                raise RuntimeError(
                    f"输入电压超出范围: {max_voltage:.4f} V > {self.invalid_voltage_limit:g} V"
                )

    def validate_acceleration_data(self, acceleration_g):
        if acceleration_g.size == 0:
            raise RuntimeError("NI-9234 返回了空数据")
        if not np.all(np.isfinite(acceleration_g)):
            raise RuntimeError("NI 加速度数据包含 NaN 或无穷大")
        if self.invalid_acceleration_g_limit > 0:
            max_g = float(np.max(np.abs(acceleration_g)))
            if max_g > self.invalid_acceleration_g_limit:
                raise RuntimeError(
                    f"加速度输入超出范围: {max_g:.4f} g > "
                    f"{self.invalid_acceleration_g_limit:g} g"
                )

    def convert_acceleration_g(self, acceleration_g):
        return (
            np.asarray(acceleration_g, dtype=float)
            * self.gravity_m_s2
            * self.display_scale_from_m_s2
        )

    def prepare_stream_geometry(self, actual_scan_rate):
        self.actual_scan_rate = float(actual_scan_rate)
        self.display_points = max(
            int(round(self.actual_scan_rate * self.display_time_sec)),
            self.scans_per_read,
        )
        self.display_buffer = np.zeros(self.display_points, dtype=float)
        self.record_target_samples = max(
            int(round(self.actual_scan_rate * self.record_time_sec)),
            1,
        )
        display_interval_samples = max(
            int(round(self.actual_scan_rate / self.display_refresh_hz)),
            1,
        )
        self.stream_started.emit(self.actual_scan_rate, self.record_target_samples)
        return display_interval_samples

    def consume_converted_data(self, converted_data, display_interval_samples):
        offset = 0
        stop_after_current_record = False
        while offset < converted_data.size and not self.isInterruptionRequested():
            remaining = self.record_target_samples - self.record_sample_count
            segment = converted_data[offset:offset + remaining]
            offset += segment.size
            self.append_display_data(segment)
            self.accumulate_record_data(segment)
            self.total_samples += int(segment.size)
            self.samples_since_display += int(segment.size)

            if self.samples_since_display >= display_interval_samples:
                self.publish_display(segment)
                self.samples_since_display %= display_interval_samples

            if self.record_sample_count >= self.record_target_samples:
                self.emit_record()
                self.reset_record_accumulators()
                if self.stop_after_record:
                    stop_after_current_record = True
                    break
        return stop_after_current_record

    def run_labjack(self):
        stream_started = False
        try:
            if self.handle is None:
                raise RuntimeError("LabJack 尚未连接")
            self.configure_device()
            scan_list = ljm.namesToAddresses(1, [self.input_channel])[0]
            actual_scan_rate = float(
                ljm.eStreamStart(
                    self.handle,
                    self.scans_per_read,
                    1,
                    scan_list,
                    self.requested_scan_rate,
                )
            )
            stream_started = True
            display_interval_samples = self.prepare_stream_geometry(actual_scan_rate)

            stop_after_current_record = False
            while not self.isInterruptionRequested() and not stop_after_current_record:
                result = ljm.eStreamRead(self.handle)
                voltage_data = np.asarray(result[0], dtype=float)
                self.validate_voltage_data(voltage_data)
                self.device_backlog = int(result[1])
                self.ljm_backlog = int(result[2])
                self.max_device_backlog = max(self.max_device_backlog, self.device_backlog)
                self.max_ljm_backlog = max(self.max_ljm_backlog, self.ljm_backlog)
                converted_data = voltage_data * self.voltage_scale
                stop_after_current_record = self.consume_converted_data(
                    converted_data,
                    display_interval_samples,
                )
        finally:
            if stream_started:
                try:
                    ljm.eStreamStop(self.handle)
                except Exception:
                    pass

    def run_ni9234(self):
        source = Ni9234Source(self.ni_config)
        try:
            info = source.open()
            self.input_channel = str(info["channel"])
            self.scans_per_read = source.scans_per_read
            display_interval_samples = self.prepare_stream_geometry(info["scan_rate"])
            stop_after_current_record = False
            while not self.isInterruptionRequested() and not stop_after_current_record:
                acceleration_g = source.read()
                self.validate_acceleration_data(acceleration_g)
                converted_data = self.convert_acceleration_g(acceleration_g)
                stop_after_current_record = self.consume_converted_data(
                    converted_data,
                    display_interval_samples,
                )
        finally:
            source.close()

    def run(self):
        try:
            if self.source_type == ACQUISITION_SOURCE_NI9234:
                self.run_ni9234()
            else:
                self.run_labjack()
        except Exception as error:
            if not self.isInterruptionRequested():
                self.stream_error.emit(
                    f"{self.source_label}: {error} | 缓冲 设备/驱动: "
                    f"{self.device_backlog}/{self.ljm_backlog}, 最大: "
                    f"{self.max_device_backlog}/{self.max_ljm_backlog}"
                )


class VibrationTester(QMainWindow, Ui_MainWindow):
    plc_command_requested = Signal(int)
    plc_result_requested = Signal(int)
    plc_shutdown_requested = Signal(int)
    mes_sync_completed = Signal(dict)

    def __init__(self):
        super().__init__()
        self.setupUi(self)
        self.setup_runtime_console()

        self.config, config_error = load_config()
        self.app_config = self.config.get("app", {})
        self.product_config = self.config.get("product", {})
        self.acquisition_config = self.config.get("acquisition", {})
        self.acquisition_source = normalize_acquisition_source(
            self.acquisition_config.get("source", ACQUISITION_SOURCE_LABJACK)
        )
        self.ni9234_config = deepcopy(self.acquisition_config.get("ni9234", {}))
        self.labjack_input_channel = str(self.acquisition_config.get("input_channel", "AIN3"))
        self.plc_config = self.config.get("plc", {})
        self.traceability_config = self.config.get("traceability", {})
        configured_database_path = Path(
            str(self.traceability_config.get("database_path", "data/traceability.db"))
        )
        if not configured_database_path.is_absolute():
            configured_database_path = Path(__file__).resolve().parent / configured_database_path
        self.traceability_store = TraceabilityStore(configured_database_path)
        self.mes_sync_client = MesSyncClient(self.traceability_config.get("mes", {}))
        self.mes_sync_running = False
        self.mes_sync_timer = None
        self.mes_sync_had_failure = False
        self.mes_sync_ready_logged = False
        self.tray_mapping_api = None
        self.missing_product_mapping_notices = set()
        self.tray_id_manual_override = False
        self.plc_enabled = bool(self.plc_config.get("enabled", False))
        self.positions_per_tray = max(int(self.plc_config.get("positions_per_tray", 10)), 1)
        self.plc_heartbeat_timeout_sec = max(float(self.plc_config.get("heartbeat_timeout_sec", 3.0)), 1.0)
        self.auto_resume_stable_sec = max(
            float(self.plc_config.get("auto_resume_stable_sec", 1.0)),
            0.0,
        )
        self.checkpoint_enabled = to_bool(
            self.plc_config.get("checkpoint_enabled", True),
            True,
        )
        checkpoint_dir = Path(
            str(self.plc_config.get("checkpoint_dir", "data/automation_checkpoints"))
        )
        if not checkpoint_dir.is_absolute():
            checkpoint_dir = Path(__file__).resolve().parent / checkpoint_dir
        self.automatic_checkpoint_dir = checkpoint_dir

        self.lj_handle = None
        self.acquisition_worker = None
        self.acquisition_error_handled = False
        self.actual_scan_rate = 0.0
        self.last_device_backlog = 0
        self.last_ljm_backlog = 0
        self.max_device_backlog = 0
        self.max_ljm_backlog = 0
        self.plc_thread = None
        self.plc_worker = None
        self.plc_connected = False
        self.plc_status_word = 0
        self.plc_current_tray_id = 0
        self.plc_current_position = 0
        self.plc_all_complete = False
        self.last_plc_heartbeat = None
        self.last_plc_heartbeat_change = monotonic()
        self.pc_command_word = 0
        self.spectrum_ok_word = 0
        self.position_pass_results = {}
        self.auto_test_active = False
        self.auto_test_paused = False
        self.auto_pause_reason = ""
        self.auto_resume_ready_since = None
        self.manual_acquisition_active = False
        self.point_record_done = False
        self.current_test_position = 0
        self.current_position_record_count = 0
        self.completed_positions = set()
        self.skipped_positions = set()
        self.cycle_completion_handled = False
        self.last_auto_save_path = None
        self.heartbeat_warning_active = False
        self.checkpoint_restore_failed = False

        # ========================================================
        # 🛠️ 核心参数区：优先从 config.json 读取
        # ========================================================
        self.display_unit = normalize_display_unit(self.acquisition_config.get("display_unit", "mm/s^2"))
        self.display_scale_from_m_s2 = display_scale_for_unit(self.display_unit)
        self.fft_display_mode = normalize_fft_display_mode(self.acquisition_config.get("fft_display_mode", "amplitude"))
        self.fft_unit = self.display_unit if self.fft_display_mode == "amplitude" else f"{self.display_unit}/√Hz"
        self.fft_highpass_hz = float(self.acquisition_config.get("fft_highpass_hz", 100))
        self.fft_lowpass_hz = float(self.acquisition_config.get("fft_lowpass_hz", 25600))
        self.fft_remove_mean = to_bool(self.acquisition_config.get("fft_remove_mean", True), True)
        self.fft_window_amplitude_correction = to_bool(
            self.acquisition_config.get("fft_window_amplitude_correction", True),
            True,
        )
        self.product_settings = normalize_product_settings(
            self.config.get("product_settings", {}),
            DEFAULT_PRODUCT_SETTINGS,
            self.display_scale_from_m_s2,
        )
        self.config["product_settings"] = self.product_settings
        self.products = normalize_products(self.config, self.product_settings, self.display_scale_from_m_s2)
        self.current_product = self.find_product(self.product_config.get("model", ""))

        y_limit_m_s2 = self.acquisition_config.get("time_y_limit_m_s2", {})
        if isinstance(y_limit_m_s2, dict):
            self.y_limit_neg = float(y_limit_m_s2.get("min", -4.0)) * self.display_scale_from_m_s2
            self.y_limit_pos = float(y_limit_m_s2.get("max", 4.0)) * self.display_scale_from_m_s2
            self.time_y_auto_scale = bool(y_limit_m_s2.get("auto_scale", True))
            self.time_y_auto_percentile = min(max(to_float(y_limit_m_s2.get("auto_percentile"), 99.0), 80.0), 100.0)
            self.time_y_auto_min_range = max(
                to_float(y_limit_m_s2.get("auto_min_range_m_s2"), 4.0) * self.display_scale_from_m_s2,
                1e-9,
            )
            self.time_y_auto_margin = max(to_float(y_limit_m_s2.get("auto_margin"), 1.25), 1.0)
            self.time_y_auto_update_interval_sec = max(
                to_float(y_limit_m_s2.get("auto_update_interval_sec"), 0.2),
                0.05,
            )
        else:
            y_limit = self.acquisition_config.get("time_y_limit", {})
            self.y_limit_neg = float(y_limit.get("min", -4000.0))
            self.y_limit_pos = float(y_limit.get("max", 4000.0))
            self.time_y_auto_scale = False
            self.time_y_auto_percentile = 99.0
            self.time_y_auto_min_range = max(self.y_limit_pos - self.y_limit_neg, 1e-9)
            self.time_y_auto_margin = 1.25
            self.time_y_auto_update_interval_sec = 0.2
        self.time_y_current_min = self.y_limit_neg
        self.time_y_current_max = self.y_limit_pos
        self.time_y_last_auto_update = 0.0
        self.display_time_sec = float(self.acquisition_config.get("display_time_sec", 1.5))
        self.display_refresh_hz = max(float(self.acquisition_config.get("display_refresh_hz", 5.0)), 0.5)
        self.avg_time_sec = float(self.acquisition_config.get("avg_time_sec", 3.0))
        self.records_per_motor = max(int(self.acquisition_config.get("records_per_motor", 1)), 1)
        self.record_value_mode = str(self.acquisition_config.get("record_value_mode", "window_raw")).strip().lower()
        if self.record_value_mode not in {"batch_mean", "window_raw"}:
            self.record_value_mode = "window_raw"
        self.time_remove_mean = to_bool(self.acquisition_config.get("time_remove_mean", True), True)
        self.invalid_input_voltage_abs_max = max(
            to_float(self.acquisition_config.get("invalid_input_voltage_abs_max"), 10.5),
            0.0,
        )
        self.labjack_config = deepcopy(self.acquisition_config.get("labjack", {}))
        self.fft_max_freq = int(self.acquisition_config.get("fft_max_freq", 25000))
        self.judgment_max_freq_hz = float(self.acquisition_config.get("judgment_max_freq_hz", 50000))
        self.input_channel = self.labjack_input_channel
        self.default_status = str(self.product_config.get("default_status", "合格"))
        self.gravity_m_s2 = float(self.acquisition_config.get("gravity_m_s2", 9.80665))
        self.acceleration_sensitivity_m_s2_per_mv = float(
            self.acquisition_config.get("acceleration_sensitivity_m_s2_per_mv", 0.002594)
        )
        fft_y_limit_m_s2 = self.acquisition_config.get("fft_y_limit_m_s2", {})
        if isinstance(fft_y_limit_m_s2, dict):
            self.fft_y_limit_min = float(fft_y_limit_m_s2.get("min", 0.0)) * self.display_scale_from_m_s2
            self.fft_y_limit_max = float(fft_y_limit_m_s2.get("max", 0.05)) * self.display_scale_from_m_s2
            self.fft_y_auto_scale = bool(fft_y_limit_m_s2.get("auto_scale", True))
            self.fft_y_auto_min_max = float(fft_y_limit_m_s2.get("auto_min_max", 0.03)) * self.display_scale_from_m_s2
            self.fft_y_auto_margin = float(fft_y_limit_m_s2.get("auto_margin", 1.3))
        else:
            fft_y_limit = self.acquisition_config.get("fft_y_limit", {})
            self.fft_y_limit_min = float(fft_y_limit.get("min", 0.0))
            self.fft_y_limit_max = float(fft_y_limit.get("max", 50.0))
            self.fft_y_auto_scale = bool(fft_y_limit.get("auto_scale", True))
            self.fft_y_auto_min_max = float(fft_y_limit.get("auto_min_max", 30.0))
            self.fft_y_auto_margin = float(fft_y_limit.get("auto_margin", 1.3))
        # ========================================================

        self.update_product_settings()

        self.apply_config_to_ui()
        self.append_process_log(
            "SYSTEM",
            f"配置已加载: {CONFIG_PATH.name} | 产品 {self.product_config.get('model', '')}",
        )
        if config_error:
            self.append_process_log("WARN", config_error)
            QMessageBox.warning(self, "配置提示", config_error)

        # === 1. 时域绘图视觉调优 (原波形图) ===
        self.graph_widget = pg.PlotWidget()
        self.graph_widget.setBackground('w')

        self.graph_widget.setTitle("电机振动实时波形", color='#000', size='12pt')
        self.graph_widget.setLabel('left', f'幅值 ({self.display_unit})', color='#000')
        self.graph_widget.setLabel('bottom', '时间 (s)', color='#000')
        self.graph_widget.showGrid(x=True, y=True)
        self.graph_widget.setYRange(self.y_limit_neg, self.y_limit_pos, padding=0)

        # 开启 autoDownsample，让 PyQtGraph 底层智能处理密集点，而不是我们手动切片
        self.plot_line = self.graph_widget.plot([], [], pen=pg.mkPen(color='b', width=1.0))
        self.plot_line.setDownsampling(auto=True, method='peak')
        self.plot_line.setClipToView(True)

        container_layout = QVBoxLayout(self.widget)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.addWidget(self.graph_widget)

        # === 2. 频域绘图视觉调优 (新增 FFT 频谱图) ===
        self.graph_fft = pg.PlotWidget()
        self.graph_fft.setBackground('w')

        self.graph_fft.setTitle("频域分析 FFT (幅值-频率)", color='#000', size='12pt')
        self.graph_fft.setLabel('left', f'幅值 ({self.fft_unit})', color='#000')
        self.graph_fft.setLabel('bottom', '频率 (Hz)', color='#000')
        self.graph_fft.showGrid(x=True, y=True)
        self.graph_fft.setXRange(0, self.fft_max_freq, padding=0)
        self.graph_fft.setYRange(self.fft_y_limit_min, self.fft_y_limit_max, padding=0)
        self.plot_line_fft = self.graph_fft.plot([], [], pen=pg.mkPen(color='r', width=1.0))
        self.plot_line_fft.setDownsampling(auto=True, method='peak')
        self.plot_line_fft.setClipToView(True)

        container_layout_fft = QVBoxLayout(self.widget_fft)
        container_layout_fft.setContentsMargins(0, 0, 0, 0)
        container_layout_fft.addWidget(self.graph_fft)

        self.lbl_avg_status.setText(f"【{self.avg_time_sec}秒{self.record_mode_label()}】: 待机")

        self.latest_fft_vals = None
        self.latest_top_freqs = []
        self.latest_top_amps = []
        self.latest_global_peak_freq = None
        self.latest_global_peak_amp = None
        self.latest_feature_amps = []
        self.latest_feature_peak_freqs = []
        self.latest_fixed_frequency_amps = []
        self.latest_fixed_frequency_peak_freqs = []
        self.latest_band_summaries = []

        self.setup_acquisition_source_selector()
        self.btn_start.clicked.connect(self.toggle_automatic_test)
        self.btn_manual_start.clicked.connect(self.toggle_manual_acquisition)
        self.btn_save_records.clicked.connect(self.save_records)
        self.btn_export_snapshot.clicked.connect(self.export_current_data)
        self.btn_clear_records.clicked.connect(self.clear_records)
        self.btn_clear_process_log.clicked.connect(self.clear_process_log)
        self.btn_export_raw = QPushButton("导出原始频谱", self.recordGroup)
        self.btn_export_raw.setMinimumSize(120, 30)
        self.recordActionLayout.insertWidget(self.recordActionLayout.count() - 1, self.btn_export_raw)
        self.btn_export_raw.clicked.connect(self.export_raw_spectrum_data)
        self.btn_exit.clicked.connect(self.close)
        self.btn_help.clicked.connect(self.show_help)
        self.btn_select_product.clicked.connect(self.open_product_selection)
        self.btn_set_product.clicked.connect(self.open_product_settings)
        self.btn_settings.clicked.connect(self.show_placeholder)
        self.txt_tray_id.editingFinished.connect(self.handle_tray_id_edited)

        # === 核心流模式参数 ===
        self.scan_rate = int(self.acquisition_config.get("scan_rate", 100000))
        self.scans_per_read = int(self.acquisition_config.get("scans_per_read", 20000))
        self.update_active_source_parameters()
        self.graph_fft.setXRange(
            0,
            min(float(self.fft_max_freq), self.scan_rate / 2.0),
            padding=0,
        )
        self.update_header_info()

        self.display_points = max(int(self.scan_rate * self.display_time_sec), self.scans_per_read)
        self.data_buffer = np.zeros(self.display_points)
        self.raw_data_buffer = np.zeros(self.display_points)
        self.time_axis = np.linspace(-self.display_time_sec, 0, self.display_points)

        self.fft_freqs = np.fft.rfftfreq(self.display_points, d=1.0 / self.scan_rate)
        self.fft_window = np.hanning(self.display_points)
        self.fft_window_coherent_gain = float(np.mean(self.fft_window))

        self.is_running = False

        self.setup_record_table()
        self.init_traceability()
        self.init_mes_sync()
        self.init_acquisition_device()
        self.init_plc()

    def init_traceability(self):
        api_config = self.traceability_config.get("mapping_api", {})
        database_path = self.traceability_store.database_path
        self.append_process_log("DATA", f"本地追溯数据库已就绪: {database_path}")
        if not bool(api_config.get("enabled", False)):
            self.append_process_log("DATA", "托盘映射接收服务未启用，等待配置频谱电脑IP")
            return
        try:
            self.tray_mapping_api = TrayMappingApiServer(
                self.traceability_store,
                host=api_config.get("bind_host", "0.0.0.0"),
                port=api_config.get("port", 8765),
                token=api_config.get("token", ""),
            )
            self.tray_mapping_api.start()
        except Exception as error:
            self.tray_mapping_api = None
            self.append_process_log("ERROR", f"托盘映射接收服务启动失败: {error}")
            return
        self.append_process_log(
            "DATA",
            "托盘映射接收服务已启动: {}:{}".format(
                api_config.get("bind_host", "0.0.0.0"),
                api_config.get("port", 8765),
            ),
        )

    def init_mes_sync(self):
        mes_config = self.traceability_config.get("mes", {})
        self.mes_sync_timer = QTimer(self)
        self.mes_sync_timer.setInterval(
            max(5, int(mes_config.get("sync_interval_seconds", 10))) * 1000
        )
        self.mes_sync_timer.timeout.connect(self.sync_mes_once)
        self.mes_sync_completed.connect(self.handle_mes_sync_completed)
        if not self.mes_sync_client.enabled:
            self.append_process_log(
                "DATA",
                "MES同步未启用；本地SQLite仍会保存，配置MES地址后可自动补传",
            )
            return
        self.mes_sync_timer.start()
        QTimer.singleShot(0, self.sync_mes_once)
        self.append_process_log(
            "DATA",
            f"MES同步已启用: {mes_config.get('base_url')}",
        )

    def sync_mes_once(self):
        if self.mes_sync_running or not self.mes_sync_client.enabled:
            return
        self.mes_sync_running = True
        station_code = str(self.traceability_config.get("station_code", "SPECTRUM_01"))
        status = "running" if self.is_running else "idle"
        connected = self.lj_handle is not None and (not self.plc_enabled or self.plc_connected)
        metadata = {
            "plc_connected": self.plc_connected,
            "labjack_connected": self.lj_handle is not None,
            "database_path": str(self.traceability_store.database_path),
        }

        def run_sync():
            try:
                report = sync_once(
                    self.mes_sync_client,
                    self.traceability_store,
                    station_code,
                    connected,
                    status,
                    metadata,
                )
            except Exception as error:
                report = {"enabled": True, "uploaded": 0, "failed": 1, "last_error": str(error)}
            self.mes_sync_completed.emit(report)

        Thread(target=run_sync, name="spectrum-mes-sync", daemon=True).start()

    def handle_mes_sync_completed(self, report):
        self.mes_sync_running = False
        uploaded = int(report.get("uploaded", 0))
        failed = int(report.get("failed", 0))
        if uploaded:
            self.append_process_log("DATA", f"已向MES补传 {uploaded} 条频谱记录")
        if failed:
            self.mes_sync_had_failure = True
            self.append_process_log("WARN", f"MES同步失败，本地数据保留待重试: {report.get('last_error', '')}")
        elif self.mes_sync_had_failure:
            self.mes_sync_had_failure = False
            self.append_process_log("DATA", "MES同步已恢复正常")
        elif not self.mes_sync_ready_logged:
            self.mes_sync_ready_logged = True
            self.append_process_log("DATA", "MES同步连接正常")

    def persist_spectrum_result(
        self,
        avg_rms,
        avg_vpp,
        status,
        position,
        tray_id,
        product_sn,
        raw_spectrum_path=None,
    ):
        if position is None or not tray_id or not product_sn:
            self.append_process_log("WARN", "本次频谱记录缺少托盘坑位或产品SN，仅保留在界面/导出文件")
            return None
        scale_to_mm_s2 = 1000.0 / max(self.display_scale_from_m_s2, 1e-12)
        passed = status != "不合格"
        measurements = {
            "spectrum_rms_mm_s2": float(avg_rms) * scale_to_mm_s2,
            "spectrum_vpp_mm_s2": float(avg_vpp) * scale_to_mm_s2,
            "spectrum_dominant_frequency_hz": self.latest_global_peak_freq,
            "spectrum_dominant_amplitude": self.latest_global_peak_amp,
            "spectrum_passed": passed,
            "spectrum_result_code": "0" if passed else "SPECTRUM_LIMIT",
            "fft_mode": self.fft_display_mode,
            "amplitude_unit": self.fft_unit,
            "product_model": self.txt_model.text().strip(),
            "acquisition_source": self.acquisition_source,
            "acquisition_source_label": self.active_source_label(),
            "input_channel": self.input_channel,
            "scan_rate_hz": self.actual_scan_rate or self.scan_rate,
            "feature_amplitudes": list(self.latest_feature_amps),
            "feature_peak_frequencies_hz": list(self.latest_feature_peak_freqs),
            "fixed_frequency_amplitudes": list(self.latest_fixed_frequency_amps),
            "band_summaries": list(self.latest_band_summaries),
        }
        if raw_spectrum_path:
            measurements["raw_spectrum_path"] = str(raw_spectrum_path)
        try:
            record = self.traceability_store.save_spectrum_result(
                tray_id,
                int(position),
                str(self.traceability_config.get("station_code", "SPECTRUM_01")),
                measurements,
            )
        except Exception as error:
            self.append_process_log("ERROR", f"频谱结果写入本地数据库失败: {error}")
            return None
        self.append_process_log("DATA", f"频谱结果已写入本地数据库: {record['record_id']}")
        QTimer.singleShot(0, self.sync_mes_once)
        return record

    def current_tray_id(self):
        return self.txt_tray_id.text().strip()

    def apply_plc_tray_id(self, tray_id, force=False):
        tray_id = int(tray_id) & 0xFFFF
        self.plc_current_tray_id = tray_id
        if force:
            self.tray_id_manual_override = False
        if not force:
            if self.manual_acquisition_active or self.txt_tray_id.hasFocus():
                return
            if self.tray_id_manual_override:
                return

        tray_text = str(tray_id) if tray_id > 0 else ""
        if tray_text == self.current_tray_id():
            return
        self.txt_tray_id.setText(tray_text)
        self.handle_tray_id_edited(source="plc")

    def resolve_product_sn(self, tray_id, tray_slot):
        tray_id = str(tray_id or "").strip()
        try:
            tray_slot = int(tray_slot)
        except (TypeError, ValueError):
            return ""
        if not tray_id or not 1 <= tray_slot <= self.positions_per_tray:
            return ""

        notice_key = (tray_id, tray_slot)
        try:
            product = self.traceability_store.resolve_product(tray_id, tray_slot)
        except LookupError:
            if notice_key not in self.missing_product_mapping_notices:
                self.missing_product_mapping_notices.add(notice_key)
                self.append_process_log(
                    "DATA",
                    f"托盘 {tray_id} 的电机位置 {tray_slot} 暂无产品SN，记录中留空",
                )
            return ""
        except Exception as error:
            error_key = (tray_id, tray_slot, type(error).__name__)
            if error_key not in self.missing_product_mapping_notices:
                self.missing_product_mapping_notices.add(error_key)
                self.append_process_log(
                    "WARN",
                    f"查询托盘 {tray_id} 位置 {tray_slot} 的产品SN失败，记录中留空: {error}",
                )
            return ""

        self.missing_product_mapping_notices.discard(notice_key)
        return str(product.get("product_sn", "")).strip()

    def record_identity(self, position=None, tray_id=None, product_sn=None):
        resolved_tray_id = self.current_tray_id() if tray_id is None else str(tray_id).strip()
        if product_sn is None:
            resolved_product_sn = self.resolve_product_sn(resolved_tray_id, position)
        else:
            resolved_product_sn = str(product_sn).strip()
        return resolved_tray_id, resolved_product_sn

    def current_identity_position(self):
        if 1 <= self.current_test_position <= self.positions_per_tray:
            return self.current_test_position
        if 1 <= self.plc_current_position <= self.positions_per_tray:
            return self.plc_current_position
        return None

    def handle_tray_id_edited(self, source="manual"):
        from_plc = source == "plc"
        self.missing_product_mapping_notices.clear()
        tray_id = self.current_tray_id()
        if not from_plc:
            self.tray_id_manual_override = bool(tray_id)
        log_category = "PLC-RX" if from_plc else "COMMAND"
        log_source = "DM3008托盘编号" if from_plc else "当前托盘编号"
        if not tray_id:
            self.lbl_tray_mapping_status.setText("SN 映射：未选择托盘")
            self.lbl_tray_mapping_status.setStyleSheet(
                "color: #627d98; padding-left: 8px;"
            )
            self.lbl_tray_mapping_status.setToolTip("")
            self.append_process_log(log_category, f"{log_source}已清空，产品SN将留空")
            return

        self.append_process_log(log_category, f"{log_source}已设置为: {tray_id}")
        try:
            products = self.traceability_store.resolve_tray_products(tray_id)
        except Exception as error:
            self.lbl_tray_mapping_status.setText("SN 映射：查询失败")
            self.lbl_tray_mapping_status.setStyleSheet(
                "color: #b42334; font-weight: 600; padding-left: 8px;"
            )
            self.lbl_tray_mapping_status.setToolTip(str(error))
            self.append_process_log(
                "WARN", f"托盘 {tray_id} 的 SN 映射查询失败: {error}"
            )
            return

        valid_slots = {int(item["tray_slot"]) for item in products}
        if len(products) == 10 and valid_slots == set(range(1, 11)):
            details = "\n".join(
                "{}号：{}".format(item["tray_slot"], item["product_sn"])
                for item in products
            )
            self.lbl_tray_mapping_status.setText("SN 映射：已匹配 10/10")
            self.lbl_tray_mapping_status.setStyleSheet(
                "color: #137333; font-weight: 600; padding-left: 8px;"
            )
            self.lbl_tray_mapping_status.setToolTip(details)
            self.append_process_log(
                "DATA", f"托盘 {tray_id} 已匹配 10/10 个产品 SN"
            )
            return

        self.lbl_tray_mapping_status.setText(
            f"SN 映射：未找到（{len(products)}/10）"
        )
        self.lbl_tray_mapping_status.setStyleSheet(
            "color: #a15c00; font-weight: 600; padding-left: 8px;"
        )
        self.lbl_tray_mapping_status.setToolTip("")
        self.append_process_log(
            "DATA", f"托盘 {tray_id} 暂无完整 SN 映射（{len(products)}/10）"
        )

    def setup_runtime_console(self):
        self.txt_process_log.document().setMaximumBlockCount(500)
        self.lbl_motor_position = QLabel("电机编号: --", self.statusbar)
        self.lbl_motor_position.setObjectName("lbl_motor_position")
        self.lbl_motor_position.setMinimumWidth(150)
        self.lbl_motor_position.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self.lbl_motor_position.setToolTip("PLC DM3508 当前电机位置")
        self.statusbar.addPermanentWidget(self.lbl_motor_position)
        self.lbl_plc_heartbeat = QLabel(self.statusbar)
        self.lbl_plc_heartbeat.setObjectName("lbl_plc_heartbeat")
        self.lbl_plc_heartbeat.setFixedSize(14, 14)
        self.plc_heartbeat_pulse_timer = QTimer(self)
        self.plc_heartbeat_pulse_timer.setSingleShot(True)
        self.plc_heartbeat_pulse_timer.setInterval(260)
        self.plc_heartbeat_pulse_timer.timeout.connect(
            lambda: self.set_plc_heartbeat_indicator("connected")
        )
        self.set_plc_heartbeat_indicator("disabled")
        self.lbl_plc_state = QLabel("PLC: 未启用", self.statusbar)
        self.lbl_plc_state.setObjectName("lbl_plc_state")
        self.lbl_plc_state.setMinimumWidth(320)
        self.lbl_plc_state.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.lbl_plc_state.setToolTip("PLC FINS 连接状态")
        self.statusbar.addPermanentWidget(self.lbl_plc_state)
        self.statusbar.addPermanentWidget(self.lbl_plc_heartbeat)

    def set_plc_heartbeat_indicator(self, state):
        if getattr(self, "plc_heartbeat_indicator_state", None) == state:
            return
        colors = {
            "disabled": ("#9e9e9e", "PLC未启用"),
            "connecting": ("#f5a623", "PLC正在连接"),
            "connected": ("#237a3b", "PLC已连接，等待下一次心跳"),
            "pulse": ("#20d45a", "已收到PLC心跳更新"),
            "warning": ("#f5a623", "PLC心跳未更新"),
            "error": ("#d9363e", "PLC通信中断或故障"),
        }
        color, text = colors.get(state, colors["disabled"])
        self.plc_heartbeat_indicator_state = state
        self.lbl_plc_heartbeat.setStyleSheet(
            f"background-color: {color}; border: 1px solid #666; border-radius: 7px;"
        )
        self.lbl_plc_heartbeat.setToolTip(text)

    def pulse_plc_heartbeat_indicator(self):
        self.set_plc_heartbeat_indicator("pulse")
        self.plc_heartbeat_pulse_timer.start()

    def append_process_log(self, category, message):
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        text = str(message).replace("\r", " ").replace("\n", " | ")
        self.txt_process_log.appendPlainText(f"[{timestamp}] [{category}] {text}")
        scroll_bar = self.txt_process_log.verticalScrollBar()
        scroll_bar.setValue(scroll_bar.maximum())

    def clear_process_log(self):
        self.txt_process_log.clear()
        self.append_process_log("SYSTEM", "运行日志已清空")

    def apply_config_to_ui(self):
        title = str(self.app_config.get("title", "频谱分析系统 - 操作端"))
        self.setWindowTitle(title)
        product = self.current_product or {}
        self.txt_model.setText(str(self.product_config.get("model", product.get("model", ""))))
        self.txt_qty.setText(str(self.product_config.get("quantity", product.get("quantity", "0"))))
        self.txt_operator.setText(str(self.product_config.get("operator", product.get("operator", ""))))
        plc_state = "启用" if self.plc_config.get("enabled", False) else "未启用"
        self.statusbar.showMessage(
            f"配置已加载: {CONFIG_PATH.name} | PLC {self.plc_config.get('protocol', 'fins_udp')} "
            f"{self.plc_config.get('host', '')}:{self.plc_config.get('port', '')} {plc_state}"
        )

    def find_product(self, model):
        for product in self.products:
            if str(product.get("model", "")) == str(model):
                return product
        return self.products[0] if self.products else None

    def update_product_settings(self):
        product = self.current_product or {}
        settings = normalize_product(product, self.product_settings, self.display_scale_from_m_s2).get("settings", {})
        bearing = settings.get("bearing_frequency", {})
        self.feature_base_frequency_hz = to_float(bearing.get("base_frequency_hz"), 300.0)
        self.feature_range_percent = to_float(bearing.get("range_percent"), 2.0)
        self.feature_points = list(bearing.get("points", []))
        self.feature_limits = [to_float(point.get("upper_limit"), 0.0) for point in self.feature_points]
        self.frequency_band_groups = list(settings.get("frequency_band_groups", []))
        self.fixed_frequency_range_percent = max(
            to_float(settings.get("fixed_frequency_range_percent"), 2.0),
            0.0,
        )
        self.fixed_frequency_points = list(settings.get("fixed_frequency_points", []))
        self.fixed_frequency_limits = [
            to_float(point.get("upper_limit"), 0.0)
            for point in self.fixed_frequency_points
        ]
        self.wave_threshold = to_float(settings.get("wave_threshold"), 10)

        self.acceleration_sensitivity_m_s2_per_mv = parse_acceleration_sensitivity_m_s2_per_mv(
            settings,
            self.acquisition_config,
            self.gravity_m_s2,
        )

    def calculate_fft_values(self, data):
        fft_data = np.asarray(data, dtype=float)
        if self.fft_remove_mean and fft_data.size:
            fft_data = fft_data - np.mean(fft_data)

        if fft_data.size == self.fft_window.size:
            window = self.fft_window
            coherent_gain = self.fft_window_coherent_gain
        else:
            window = np.hanning(fft_data.size)
            coherent_gain = float(np.mean(window)) if window.size else 0.0
        windowed_data = fft_data * window
        fft_vals = np.abs(np.fft.rfft(windowed_data)) / max(fft_data.size, 1) * 2
        if self.fft_window_amplitude_correction:
            if coherent_gain > 0:
                fft_vals = fft_vals / coherent_gain
        if self.fft_display_mode == "asd":
            frequency_resolution = (self.actual_scan_rate or self.scan_rate) / max(fft_data.size, 1)
            if frequency_resolution > 0:
                fft_vals = fft_vals / np.sqrt(frequency_resolution)

        if self.fft_highpass_hz > 0:
            fft_vals = np.where(self.fft_freqs >= self.fft_highpass_hz, fft_vals, 0.0)
        if self.fft_lowpass_hz > 0:
            fft_vals = np.where(self.fft_freqs <= self.fft_lowpass_hz, fft_vals, 0.0)
        return fft_vals

    def record_mode_label(self):
        return "整体计算" if self.record_value_mode == "window_raw" else "批次平均"

    def save_config(self):
        self.config["product_settings"] = settings_to_storage(
            self.product_settings,
            self.display_scale_from_m_s2,
        )
        self.config["products"] = compact_products_for_save(
            self.products,
            self.product_settings,
            self.display_scale_from_m_s2,
        )
        self.config["product"] = self.product_config
        self.acquisition_config["source"] = self.acquisition_source
        self.acquisition_config["input_channel"] = self.labjack_input_channel
        self.acquisition_config["ni9234"] = deepcopy(self.ni9234_config)
        self.acquisition_config["display_unit"] = self.display_unit
        self.acquisition_config["fft_display_mode"] = self.fft_display_mode
        self.acquisition_config.pop("display_scale_from_m_s2", None)
        self.acquisition_config.pop("time_y_limit", None)
        self.acquisition_config.pop("fft_y_limit", None)
        self.config["acquisition"] = self.acquisition_config
        save_config_file(self.config)

    def apply_product(self, model, save=True):
        product = self.find_product(model)
        if product is None:
            return

        self.current_product = product
        self.product_config["model"] = str(product.get("model", ""))
        self.product_config["quantity"] = str(product.get("quantity", "0"))
        self.product_config["operator"] = str(product.get("operator", ""))
        self.txt_model.setText(self.product_config["model"])
        self.txt_qty.setText(self.product_config["quantity"])
        self.txt_operator.setText(self.product_config["operator"])
        self.update_product_settings()
        self.graph_widget.setLabel('left', f'幅值 ({self.display_unit})', color='#000')
        self.graph_fft.setLabel('left', f'幅值 ({self.fft_unit})', color='#000')
        self.setup_record_table()
        self.statusbar.showMessage(f"已选择产品: {self.product_config['model']}")
        if save:
            self.save_config()

    def open_product_selection(self):
        current_model = str(self.product_config.get("model", ""))
        dialog = ProductSelectionDialog(self.products, current_model, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        if dialog.deleted_model:
            self.delete_product(dialog.deleted_model)
            return

        if dialog.selected_model:
            self.apply_product(dialog.selected_model)

    def open_product_settings(self):
        product = self.current_product or self.find_product(self.product_config.get("model", ""))
        if product is None:
            QMessageBox.warning(self, "无产品", "当前没有可设置的产品。")
            return

        dialog = ProductSettingsDialog(
            product,
            self.products,
            self.product_settings,
            self.display_unit,
            self.display_scale_from_m_s2,
            self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        if dialog.action == "delete":
            self.delete_product(dialog.original_model)
            return

        product_data = normalize_product(dialog.product_data(), self.product_settings, self.display_scale_from_m_s2)
        model = product_data["model"]
        if not model:
            QMessageBox.warning(self, "型号为空", "产品型号不能为空。")
            return

        existing = self.find_product(model)
        original = dialog.original_model
        if dialog.action == "add" and existing is not None:
            QMessageBox.warning(self, "型号重复", f"产品 {model} 已存在，不能重复新增。")
            return
        if dialog.action == "save" and existing is not None and model != original:
            QMessageBox.warning(self, "型号重复", f"产品 {model} 已存在，不能重命名为该型号。")
            return

        if dialog.action == "add":
            self.products.append(product_data)
        else:
            for index, item in enumerate(self.products):
                if str(item.get("model", "")) == original:
                    self.products[index] = product_data
                    break
            else:
                self.products.append(product_data)

        self.apply_product(model, save=False)
        self.save_config()
        QMessageBox.information(self, "保存完成", f"产品 {model} 已保存。")

    def delete_product(self, model):
        model = str(model)
        if len(self.products) <= 1:
            QMessageBox.warning(self, "不能删除", "至少需要保留一个产品。")
            return

        reply = QMessageBox.question(
            self,
            "删除产品",
            f"确定要删除产品 {model} 吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self.products = [product for product in self.products if str(product.get("model", "")) != model]
        if not self.products:
            self.products.append(make_default_product("46520-24-43000"))

        if str(self.product_config.get("model", "")) == model:
            self.apply_product(self.products[0]["model"], save=False)
        self.save_config()
        self.statusbar.showMessage(f"已删除产品: {model}")

    def setup_acquisition_source_selector(self):
        self.lbl_acquisition_source = QLabel("采集模式", self.headerFrame)
        self.cmb_acquisition_source = QComboBox(self.headerFrame)
        self.cmb_acquisition_source.setMinimumWidth(190)
        self.cmb_acquisition_source.addItem("LabJack 频谱输入", ACQUISITION_SOURCE_LABJACK)
        self.cmb_acquisition_source.addItem("NI-9234 加速度传感器", ACQUISITION_SOURCE_NI9234)
        selected_index = self.cmb_acquisition_source.findData(self.acquisition_source)
        self.cmb_acquisition_source.setCurrentIndex(max(selected_index, 0))
        self.acquisition_source_layout = QHBoxLayout()
        self.acquisition_source_layout.setSpacing(8)
        self.acquisition_source_layout.addWidget(self.lbl_acquisition_source)
        self.acquisition_source_layout.addWidget(self.cmb_acquisition_source)
        self.acquisition_source_layout.addStretch(1)
        self.headerLayout.addLayout(self.acquisition_source_layout)
        self.cmb_acquisition_source.currentIndexChanged.connect(
            self.handle_acquisition_source_changed
        )

    def active_source_label(self):
        if self.acquisition_source == ACQUISITION_SOURCE_NI9234:
            return "NI-9234 加速度传感器"
        return "LabJack 频谱输入"

    def update_active_source_parameters(self):
        if self.acquisition_source == ACQUISITION_SOURCE_NI9234:
            module = str(self.ni9234_config.get("module", "cDAQ1Mod1")).strip()
            channel = str(self.ni9234_config.get("channel", "ai0")).strip()
            self.input_channel = channel if "/" in channel else f"{module}/{channel}"
            self.scan_rate = max(int(float(self.ni9234_config.get("scan_rate", 51200))), 1)
            self.scans_per_read = max(int(self.ni9234_config.get("scans_per_read", 1500)), 1)
        else:
            self.input_channel = self.labjack_input_channel
            self.scan_rate = max(int(float(self.acquisition_config.get("scan_rate", 100000))), 1)
            self.scans_per_read = max(int(self.acquisition_config.get("scans_per_read", 20000)), 1)
        self.actual_scan_rate = 0.0

    def init_acquisition_device(self):
        if self.acquisition_source == ACQUISITION_SOURCE_NI9234:
            self.probe_selected_acquisition_source(show_message=False)
            return
        self.init_labjack()

    def probe_selected_acquisition_source(self, show_message=True):
        if self.acquisition_source == ACQUISITION_SOURCE_LABJACK:
            if self.lj_handle is not None:
                return True
            if show_message:
                QMessageBox.warning(self, "采集卡未连接", "LabJack 采集卡尚未连接。")
            return False

        try:
            module = discover_ni9234_module(self.ni9234_config)
        except Exception as error:
            self.append_process_log("ERROR", f"NI-9234 检查失败: {error}")
            self.lbl_status.setText(f"NI-9234 未就绪: {error}")
            if show_message:
                QMessageBox.warning(self, "NI-9234 未就绪", str(error))
            return False

        self.append_process_log(
            "DAQ",
            f"NI-9234 已发现: {module}，将在开始采集时启用 IEPE 通道",
        )
        self.lbl_status.setText(f"NI-9234 已就绪 | 模块 {module} | 等待采集")
        return True

    def handle_acquisition_source_changed(self):
        selected = normalize_acquisition_source(self.cmb_acquisition_source.currentData())
        if selected == self.acquisition_source:
            return
        if self.is_running or self.manual_acquisition_active or self.auto_test_active:
            previous_index = self.cmb_acquisition_source.findData(self.acquisition_source)
            self.cmb_acquisition_source.blockSignals(True)
            self.cmb_acquisition_source.setCurrentIndex(previous_index)
            self.cmb_acquisition_source.blockSignals(False)
            QMessageBox.warning(self, "无法切换", "请先停止采集并退出自动化。")
            return

        self.close_labjack()
        self.acquisition_source = selected
        self.acquisition_config["source"] = selected
        self.update_active_source_parameters()
        self.rebuild_signal_geometry(self.scan_rate)
        self.graph_fft.setXRange(
            0,
            min(float(self.fft_max_freq), self.scan_rate / 2.0),
            padding=0,
        )
        self.latest_fft_vals = None
        self.save_config()
        self.append_process_log("COMMAND", f"采集模式已切换为 {self.active_source_label()}")
        self.init_acquisition_device()

    def close_labjack(self):
        if self.lj_handle is None:
            return
        try:
            ljm.close(self.lj_handle)
        except Exception:
            pass
        self.lj_handle = None

    def init_labjack(self):
        if not self.app_config.get("auto_connect_labjack", True):
            self.lbl_status.setText("实时振动值: LabJack 自动连接已关闭")
            self.append_process_log("DAQ", "LabJack 自动连接已关闭")
            return

        try:
            device_type = str(self.labjack_config.get("device_type", "ANY"))
            connection_type = str(self.labjack_config.get("connection_type", "USB"))
            identifier = str(self.labjack_config.get("identifier", "ANY"))
            self.append_process_log(
                "DAQ",
                f"正在连接 LabJack: device={device_type}, connection={connection_type}, identifier={identifier}",
            )
            self.lj_handle = ljm.openS(device_type, connection_type, identifier)
            try:
                ljm.eStreamStop(self.lj_handle)
            except Exception:
                pass
            handle_info = ljm.getHandleInfo(self.lj_handle)
            native_version = ljm.readLibraryConfigS("LJM_LIBRARY_VERSION")
            self.lbl_status.setText(
                f"LabJack已连接 | 序列号 {handle_info[2]} | LJM {native_version:g}"
            )
            self.append_process_log(
                "DAQ",
                f"LabJack 已连接: 序列号 {handle_info[2]}, LJM {native_version:g}",
            )
        except ljm.LJMError as e:
            self.append_process_log("ERROR", f"LabJack 连接失败: {e}")
            QMessageBox.critical(self, "硬件未连接", f"无法连接 LabJack: {e}")

    def init_plc(self):
        if not self.plc_enabled:
            self.lbl_plc_state.setText("PLC: 未启用")
            self.set_plc_heartbeat_indicator("disabled")
            self.append_process_log("PLC", "PLC FINS 通讯未启用")
            return

        self.plc_thread = QThread(self)
        self.plc_worker = PlcWorker(self.plc_config)
        self.plc_worker.moveToThread(self.plc_thread)
        self.plc_thread.started.connect(self.plc_worker.start)
        self.plc_worker.state_received.connect(self.handle_plc_state)
        self.plc_worker.connection_changed.connect(self.handle_plc_connection)
        self.plc_worker.io_event.connect(self.append_process_log)
        self.plc_command_requested.connect(self.plc_worker.set_command_word)
        self.plc_result_requested.connect(self.plc_worker.set_result_word)
        self.plc_shutdown_requested.connect(self.plc_worker.shutdown)
        self.plc_worker.finished.connect(self.plc_thread.quit)
        self.plc_worker.finished.connect(self.plc_worker.deleteLater)
        self.plc_thread.finished.connect(self.plc_thread.deleteLater)
        self.plc_thread.start()
        self.lbl_plc_state.setText("PLC: 正在连接...")
        self.set_plc_heartbeat_indicator("connecting")
        self.append_process_log(
            "PLC",
            f"正在连接 FINS UDP {self.plc_config.get('host', '')}:{self.plc_config.get('port', '')}",
        )

    def set_pc_command_bit(self, bit, enabled):
        mask = 1 << int(bit)
        next_word = self.pc_command_word | mask if enabled else self.pc_command_word & ~mask
        next_word &= 0xFFFF
        if next_word == self.pc_command_word:
            return
        self.pc_command_word = next_word
        if self.plc_worker is not None:
            self.plc_command_requested.emit(self.pc_command_word)

    def set_spectrum_ok_word(self, value, force=False):
        value = int(value) & 0xFFFF
        if value == self.spectrum_ok_word and not force:
            return
        self.spectrum_ok_word = value
        if self.plc_worker is not None:
            self.plc_result_requested.emit(self.spectrum_ok_word)

    def set_position_spectrum_ok(self, position, passed):
        position = int(position)
        if not 1 <= position <= min(self.positions_per_tray, 15):
            self.append_process_log(
                "ERROR",
                f"无法写入频谱结果位: 电机位置 {position} 超出 DM3505.01～DM3505.15",
            )
            return
        mask = 1 << position
        next_word = self.spectrum_ok_word | mask if passed else self.spectrum_ok_word & ~mask
        self.set_spectrum_ok_word(next_word)

    def pause_automatic_test(self, reason):
        if not self.auto_test_active:
            return
        first_pause = not self.auto_test_paused
        self.auto_test_paused = True
        self.auto_pause_reason = str(reason)
        self.auto_resume_ready_since = None
        if self.is_running:
            self.stop_data_stream()
        self.set_pc_command_bit(PC_START_BIT, False)
        self.set_pc_command_bit(PC_STOP_BIT, False)
        if first_pause:
            self.append_process_log(
                "RECOVERY",
                f"自动化已暂停并保留断点: {reason}",
            )
            self.save_automatic_checkpoint()
        self.lbl_status.setText(f"自动化暂停: {reason}，等待PLC恢复")
        self.lbl_avg_status.setText(
            f"{self.automation_progress_text()}，"
            f"当前点位记录 {self.current_position_record_count}/{self.records_per_motor}"
        )
        self.lbl_plc_state.setText(f"PLC: 自动化暂停 | {reason}")
        self.statusbar.showMessage(f"自动化暂停，断点已保留: {reason}")

    def next_incomplete_position(self):
        return next(
            (
                position
                for position in range(1, self.positions_per_tray + 1)
                if position not in self.completed_positions
                and position not in self.skipped_positions
            ),
            self.positions_per_tray + 1,
        )

    def all_positions_accounted_for(self):
        return self.next_incomplete_position() > self.positions_per_tray

    def automation_progress_text(self):
        return (
            f"频谱完成 {len(self.completed_positions)}，"
            f"跑合跳过 {len(self.skipped_positions)}，"
            f"托盘共 {self.positions_per_tray}"
        )

    def mark_skipped_positions(self, positions, reason):
        new_positions = {
            int(position)
            for position in positions
            if 1 <= int(position) <= self.positions_per_tray
            and int(position) not in self.completed_positions
            and int(position) not in self.skipped_positions
        }
        if not new_positions:
            return []

        self.skipped_positions.update(new_positions)
        skipped_mask = sum(1 << position for position in new_positions)
        self.set_spectrum_ok_word(self.spectrum_ok_word & ~skipped_mask)
        position_text = ",".join(str(position) for position in sorted(new_positions))
        self.append_process_log(
            "PROCESS",
            f"位置 {position_text} 未进入频谱测试，已登记为跑合测试跳过 | {reason}",
        )
        return sorted(new_positions)

    def mark_positions_before_as_skipped(self, position, reason):
        position = int(position)
        return self.mark_skipped_positions(range(1, position), reason)

    def automatic_resume_is_ready(self):
        if not self.auto_test_paused or not self.plc_connected:
            return False
        emergency = bool(self.plc_status_word & (1 << PLC_EMERGENCY_BIT))
        plc_fault = bool(self.plc_status_word & (1 << PLC_FAULT_BIT))
        if emergency or plc_fault:
            self.auto_resume_ready_since = None
            return False

        expected_tray = self.current_tray_id()
        actual_tray = str(self.plc_current_tray_id) if self.plc_current_tray_id else ""
        if expected_tray and actual_tray != expected_tray:
            self.auto_resume_ready_since = None
            self.lbl_status.setText(
                f"自动化暂停: 等待原托盘 {expected_tray}，PLC当前托盘 {actual_tray or '空'}"
            )
            return False

        point_ready = bool(self.plc_status_word & (1 << PLC_POINT_READY_BIT))
        if point_ready:
            if self.all_positions_accounted_for():
                accounted_position = (
                    self.plc_current_position in self.completed_positions
                    or self.plc_current_position in self.skipped_positions
                )
                if not accounted_position and not self.plc_all_complete:
                    self.auto_resume_ready_since = None
                    self.lbl_status.setText(
                        "自动化暂停: 全部点位已完成，等待PLC全部完成信号"
                    )
                    return False
            else:
                if self.point_record_done and self.current_test_position:
                    expected_position = self.current_test_position
                elif (
                    self.current_test_position
                    and self.current_test_position not in self.completed_positions
                ):
                    expected_position = self.current_test_position
                else:
                    expected_position = self.next_incomplete_position()
                can_skip_forward = not (
                    self.current_test_position
                    and self.current_test_position not in self.completed_positions
                    and self.current_position_record_count > 0
                )
                position_matches = self.plc_current_position == expected_position
                forward_skip = (
                    can_skip_forward
                    and expected_position <= self.positions_per_tray
                    and self.plc_current_position > expected_position
                    and self.plc_current_position <= self.positions_per_tray
                )
                if not position_matches and not forward_skip:
                    self.auto_resume_ready_since = None
                    self.lbl_status.setText(
                        f"自动化暂停: 等待电机位置 {expected_position}，"
                        f"PLC当前位置 {self.plc_current_position}"
                    )
                    return False

        now = monotonic()
        if self.auto_resume_ready_since is None:
            self.auto_resume_ready_since = now
            return self.auto_resume_stable_sec == 0
        return now - self.auto_resume_ready_since >= self.auto_resume_stable_sec

    def resume_automatic_test(self):
        reason = self.auto_pause_reason
        self.auto_test_paused = False
        self.auto_pause_reason = ""
        self.auto_resume_ready_since = None
        self.set_pc_command_bit(PC_STOP_BIT, False)
        self.set_pc_command_bit(PC_FAULT_BIT, False)
        if self.point_record_done:
            self.set_pc_command_bit(PC_START_BIT, False)
            self.set_pc_command_bit(PC_POINT_DONE_BIT, True)
        self.append_process_log(
            "RECOVERY",
            f"PLC状态已稳定，自动化从断点恢复: {reason}",
        )
        self.lbl_status.setText("自动化已恢复，正在与PLC当前位置对账")
        self.lbl_plc_state.setText("PLC: 已连接 | 自动化已恢复")
        self.save_automatic_checkpoint()

    def handle_plc_connection(self, connected, message):
        was_connected = self.plc_connected
        self.plc_connected = bool(connected)
        if connected:
            if not was_connected:
                self.last_plc_heartbeat = None
                self.last_plc_heartbeat_change = monotonic()
            if self.auto_test_active and self.auto_test_paused:
                mode_text = "自动化暂停，等待状态稳定"
            else:
                mode_text = "自动化待命" if self.auto_test_active else "手动模式"
            self.lbl_plc_state.setText(f"PLC: 已连接 | {mode_text}")
            self.set_plc_heartbeat_indicator("connected")
            self.append_process_log(
                "PLC",
                f"FINS 通讯已连接: {self.plc_config.get('host', '')}:{self.plc_config.get('port', '')}",
            )
            self.statusbar.showMessage(
                f"PLC FINS {self.plc_config.get('host', '')}:{self.plc_config.get('port', '')} 通信正常"
            )
            return

        self.lbl_plc_state.setText("PLC: 通信中断")
        self.plc_heartbeat_pulse_timer.stop()
        self.set_plc_heartbeat_indicator("error")
        self.append_process_log("ERROR", f"PLC 通信中断: {message}")
        self.statusbar.showMessage(f"PLC 通信中断: {message}")
        if self.auto_test_active:
            self.pause_automatic_test(f"PLC 通信中断: {message}")

    def handle_plc_state(self, tray_id, status_word, position, plc_heartbeat):
        self.plc_current_tray_id = int(tray_id) & 0xFFFF
        self.plc_status_word = int(status_word) & 0xFFFF
        self.plc_current_position = int(position)
        position_text = str(self.plc_current_position) if self.plc_current_position else "--"
        self.lbl_motor_position.setText(f"电机编号: {position_text}")

        auto_waiting_for_first_position = (
            self.auto_test_active
            and not self.is_running
            and not self.completed_positions
            and not self.skipped_positions
            and self.current_test_position == 0
            and not self.point_record_done
            and not self.cycle_completion_handled
        )
        if auto_waiting_for_first_position:
            self.apply_plc_tray_id(self.plc_current_tray_id, force=True)
        elif not self.auto_test_active and not self.manual_acquisition_active:
            self.apply_plc_tray_id(self.plc_current_tray_id, force=False)

        now = monotonic()
        if self.last_plc_heartbeat is None:
            self.last_plc_heartbeat = int(plc_heartbeat)
            self.last_plc_heartbeat_change = now
        elif int(plc_heartbeat) != self.last_plc_heartbeat:
            self.last_plc_heartbeat = int(plc_heartbeat)
            self.last_plc_heartbeat_change = now
            if self.heartbeat_warning_active:
                self.heartbeat_warning_active = False
                self.append_process_log("PLC", "PLC心跳已恢复变化")
            self.pulse_plc_heartbeat_indicator()
        elif now - self.last_plc_heartbeat_change > self.plc_heartbeat_timeout_sec:
            self.set_plc_heartbeat_indicator("warning")
            if not self.heartbeat_warning_active:
                self.heartbeat_warning_active = True
                self.append_process_log(
                    "WARN",
                    "PLC心跳长时间未变化，仅告警，不暂停或退出自动化",
                )

        emergency = bool(self.plc_status_word & (1 << PLC_EMERGENCY_BIT))
        point_ready = bool(self.plc_status_word & (1 << PLC_POINT_READY_BIT))
        self.plc_all_complete = bool(self.plc_status_word & (1 << PLC_ALL_COMPLETE_BIT))
        plc_fault = bool(self.plc_status_word & (1 << PLC_FAULT_BIT))

        if emergency:
            if self.auto_test_active:
                self.pause_automatic_test("PLC 急停已触发")
            self.lbl_plc_state.setText("PLC: 急停")
            self.plc_heartbeat_pulse_timer.stop()
            self.set_plc_heartbeat_indicator("error")
            return
        if plc_fault:
            if self.auto_test_active:
                self.pause_automatic_test("PLC 故障")
            self.lbl_plc_state.setText("PLC: 故障")
            self.plc_heartbeat_pulse_timer.stop()
            self.set_plc_heartbeat_indicator("error")
            return

        if (
            self.auto_test_active
            and self.point_record_done
            and point_ready
            and self.current_test_position
            and self.plc_current_position != self.current_test_position
        ):
            if self.plc_current_position > self.current_test_position:
                self.mark_positions_before_as_skipped(
                    self.plc_current_position,
                    f"PLC从已完成位置 {self.current_test_position} 前进到位置 {self.plc_current_position}",
                )
            next_position = self.next_incomplete_position()
            if self.plc_current_position == next_position:
                completed_position = self.current_test_position
                self.point_record_done = False
                self.current_test_position = 0
                self.current_position_record_count = 0
                self.set_pc_command_bit(PC_POINT_DONE_BIT, False)
                self.append_process_log(
                    "RECOVERY",
                    f"PLC已进入点位 {next_position}，确认点位 "
                    f"{completed_position} 的采集完成握手已被接收",
                )
                self.save_automatic_checkpoint()
            else:
                self.pause_automatic_test(
                    f"PLC点位从 {self.current_test_position} 跳到 "
                    f"{self.plc_current_position}，期望 {next_position}"
                )
                return

        if self.auto_test_paused:
            if not self.automatic_resume_is_ready():
                return
            self.resume_automatic_test()

        if self.auto_test_active and self.cycle_completion_handled and not self.plc_all_complete:
            self.reset_automatic_records()
            self.apply_plc_tray_id(self.plc_current_tray_id, force=True)
            self.append_process_log("PROCESS", "PLC全部完成信号已复位，进入下一托自动化待命")
            self.lbl_status.setText("自动化待命，等待下一托电机到位")
            self.lbl_avg_status.setText(self.automation_progress_text())
            self.lbl_plc_state.setText("PLC: 已连接 | 自动化待命")

        if (
            self.auto_test_active
            and self.plc_all_complete
            and not self.is_running
            and not self.cycle_completion_handled
            and self.all_positions_accounted_for()
        ):
            if self.point_record_done:
                completed_position = self.current_test_position
                self.point_record_done = False
                self.set_pc_command_bit(PC_POINT_DONE_BIT, False)
                self.current_test_position = 0
                self.current_position_record_count = 0
                self.append_process_log(
                    "PROCESS",
                    f"PLC已发送全部完成，确认点位 {completed_position} 的采集完成握手已被接收",
                )
                self.save_automatic_checkpoint()
            self.finish_automatic_test()
            return

        if self.point_record_done and not point_ready:
            completed_position = self.current_test_position
            self.point_record_done = False
            self.set_pc_command_bit(PC_POINT_DONE_BIT, False)
            self.current_test_position = 0
            self.current_position_record_count = 0
            self.append_process_log(
                "PROCESS",
                f"PLC已复位点位 {completed_position} 到位信号，上位机清除采集完成位",
            )
            self.save_automatic_checkpoint()

        if (
            self.auto_test_active
            and point_ready
            and not self.plc_all_complete
            and not self.cycle_completion_handled
        ):
            self.lbl_plc_state.setText(
                f"PLC: 已连接 | 点位 {self.plc_current_position}/{self.positions_per_tray} 已到位"
            )
            if not self.is_running and not self.point_record_done:
                self.start_point_acquisition(self.plc_current_position)
        elif (
            self.auto_test_active
            and not self.is_running
            and not self.point_record_done
            and not self.cycle_completion_handled
        ):
            self.lbl_plc_state.setText(
                f"PLC: 已连接 | {self.automation_progress_text()} | 等待到位"
            )

        if (
            self.auto_test_active
            and self.plc_all_complete
            and not self.is_running
            and not self.point_record_done
            and not self.cycle_completion_handled
        ):
            self.finish_automatic_test()

    def abort_automatic_test(self, reason, upper_fault):
        self.append_process_log(
            "ERROR",
            f"自动测试中止: {reason} | 上位机故障位={bool(upper_fault)}",
        )
        if self.is_running:
            self.stop_data_stream()
        self.save_automatic_checkpoint()
        self.auto_test_active = False
        self.auto_test_paused = False
        self.auto_pause_reason = ""
        self.auto_resume_ready_since = None
        self.point_record_done = False
        self.set_pc_command_bit(PC_START_BIT, False)
        self.set_pc_command_bit(PC_STOP_BIT, True)
        self.set_pc_command_bit(PC_POINT_DONE_BIT, False)
        self.set_pc_command_bit(PC_FAULT_BIT, bool(upper_fault))
        self.btn_start.setText("进入自动化")
        self.btn_manual_start.setEnabled(True)
        self.set_test_controls_enabled(True)
        self.txt_tray_id.setEnabled(True)
        self.txt_complete_time.setText(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        self.lbl_status.setText(f"测试已中止: {reason}")
        self.lbl_avg_status.setText(self.automation_progress_text())
        self.statusbar.showMessage(reason)

    def update_header_info(self):
        source_short = "NI-9234" if self.acquisition_source == ACQUISITION_SOURCE_NI9234 else "LabJack"
        self.lbl_channel.setText(f"{source_short} | {self.input_channel}")
        self.lbl_channel.setToolTip(self.active_source_label())
        effective_scan_rate = self.actual_scan_rate or self.scan_rate
        self.lbl_sample_rate.setText(f"采样率 {effective_scan_rate / 1000:g} kHz")
        effective_fft_max = min(float(self.fft_max_freq), effective_scan_rate / 2.0)
        self.lbl_fft_range.setText(f"FFT 0-{effective_fft_max / 1000:g} kHz")
        self.lbl_read_block.setText(f"每次读取 {self.scans_per_read} 点")

    def setup_record_table(self):
        feature_headers = [
            f"{point.get('name', f'频率{index + 1}')}幅值({self.fft_unit})"
            for index, point in enumerate(self.feature_points)
        ]
        fixed_frequency_headers = [
            f"{point.get('name', f'固定频率{index + 1}')}幅值({self.fft_unit})"
            for index, point in enumerate(self.fixed_frequency_points)
        ]
        band_headers = []
        for group in self.frequency_band_groups:
            name = group.get("name", "频段")
            band_headers.extend([
                f"{name}尖峰数",
                f"{name}尖峰频率(Hz)",
                f"{name}尖峰值({self.fft_unit})",
                f"{name}能量和",
            ])
        self.record_headers = (
            [
                "序号",
                "电机位置",
                "托盘编号",
                "产品SN",
                "时间",
                "通道",
                f"RMS({self.display_unit})",
                f"Vpp({self.display_unit})",
                "全频主频(Hz)",
                f"全频主幅值({self.fft_unit})",
                "轴承特征主频(Hz)",
                f"轴承特征主幅值({self.fft_unit})",
            ]
            + feature_headers
            + fixed_frequency_headers
            + band_headers
            + ["状态"]
        )
        self.tbl_records.setColumnCount(len(self.record_headers))
        self.tbl_records.setHorizontalHeaderLabels(self.record_headers)
        self.tbl_records.setRowCount(0)
        self.tbl_records.setAlternatingRowColors(True)
        self.tbl_records.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tbl_records.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tbl_records.verticalHeader().setVisible(False)
        self.tbl_records.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.tbl_records.horizontalHeader().setStretchLastSection(True)
        self.update_record_count()

    def update_record_count(self):
        self.lbl_record_count.setText(f"记录: {self.tbl_records.rowCount()}")

    def show_help(self):
        QMessageBox.information(
            self,
            "帮助",
            "点击“进入自动化”后，上位机进入待命，不会提前发送开始信号。\n"
            "PLC发送当前电机到位和1～10位置号后，上位机置开始位并采集一个完整时间窗口。\n"
            "每台电机按 acquisition.records_per_motor 连续生成记录；勾选“自动保存原始频谱”时同步保存每条频谱。\n"
            "“当前托盘编号”可手动输入；有托盘映射时按1～10电机位置写入真实产品SN，查不到SN时留空且不影响测试。\n"
            "该电机全部记录完成后，上位机清除开始位并保持采集完成位。\n"
            "每台电机全部记录合格时置对应 DM3505.01～DM3505.10 为1；未完成或任一记录不合格保持为0，新托盘开始时清零。\n"
            "PLC可跳过跑合测试不合格的电机；上位机按实际到位位置采集，跳过位置不生成频谱记录且DM3505对应位保持0。\n"
            "10个位置全部完成后，系统自动保存记录，并在PLC复位全部完成信号后等待下一托。\n"
            "顶部“采集模式”可选择原 LabJack 频谱输入或 NI-9234 加速度传感器；切换前必须停止采集并退出自动化。\n"
            "NI 模式使用 cDAQ/NI-9234、ai0、51.2 kS/s 和 2.0 mA IEPE 激励，可覆盖与原频谱模式相同的 0～25 kHz FFT 范围；灵敏度以 config.json 为准。\n"
            "“手动采集”不依赖PLC，直接连续采集，并按 acquisition.avg_time_sec 设置的周期添加一条记录。\n"
            "采集在后台线程持续读取，并按实际采样率凑满采样点；界面卡顿不会改变记录窗口长度。\n"
            "状态中的设备/LJM缓冲应长期接近0，持续增大或出现-9999时当前窗口会作废。\n"
            "PLC通信中断、急停或PLC故障时自动化只会暂停并保存断点；状态恢复稳定后从当前托盘和电机位置继续。\n"
            "PLC心跳超时只显示黄色告警，不会停止采集或退出自动化。程序重启后再次进入自动化，可恢复同型号同托盘断点。\n"
            "需要PLC复位后从头重测时，请先退出自动化再点击“清空记录”；该操作会删除当前托盘断点并复位DM3500命令位和DM3505结果字。\n"
            "窗口底部显示 PLC 连接状态；运行日志保留最近 500 行程序、采集、DM 收发和错误事件。\n"
            "RMS/Vpp 可通过 acquisition.record_value_mode 配置为 batch_mean 批次平均或 window_raw 整体计算。\n"
            "acquisition.judgment_max_freq_hz 只限制合格/不合格判定，不影响频谱显示和数据导出。\n"
            "全频主频是在有效 FFT 范围内幅值最大的频率；轴承特征主频只在 9 个轴承特征窗口中选取最大值。\n"
            "记录表还包含 9 个轴承特征频率幅值，以及低频段/中频段/高频段的尖峰数量、尖峰频率、尖峰值和能量和。\n"
            "尖峰数量按产品设置里的“波峰阈值”统计，低于该阈值的局部峰不会计数。\n"
            "“保存检测记录”可手动另存下方表格，“导出当前波形/频谱”导出当前波形和 FFT 频谱。\n"
            "产品、采集和 PLC 参数请在 config.json 中维护。",
        )

    def show_placeholder(self):
        button = self.sender()
        name = button.text() if button is not None else "该"
        QMessageBox.information(self, "功能预留", f"{name}功能已预留，可后续接入产品配置。")

    def get_export_path(self, prefix):
        configured_dir = Path(str(self.app_config.get("export_dir", "exports")))
        if configured_dir.is_absolute():
            export_dir = configured_dir
        else:
            export_dir = Path(__file__).resolve().parent / configured_dir
        export_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return str(export_dir / f"{prefix}_{timestamp}.csv")

    def get_raw_export_path(self):
        configured_dir = Path(str(self.app_config.get("export_dir", "exports")))
        if configured_dir.is_absolute():
            export_dir = configured_dir
        else:
            export_dir = Path(__file__).resolve().parent / configured_dir

        model = self.txt_model.text().strip() or "unknown_model"
        date_dir = datetime.now().strftime("%y年%m月%d日")
        raw_dir = export_dir / model / date_dir
        raw_dir.mkdir(parents=True, exist_ok=True)

        used_numbers = []
        for path in raw_dir.glob("*.csv"):
            if path.stem.isdigit():
                used_numbers.append(int(path.stem))
        next_number = max(used_numbers, default=0) + 1
        return str(raw_dir / f"{next_number}.csv")

    def get_automatic_record_path(self):
        configured_dir = Path(str(self.app_config.get("export_dir", "exports")))
        if configured_dir.is_absolute():
            export_dir = configured_dir
        else:
            export_dir = Path(__file__).resolve().parent / configured_dir

        model = self.txt_model.text().strip() or "unknown_model"
        date_dir = datetime.now().strftime("%y年%m月%d日")
        record_dir = export_dir / model / date_dir
        record_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return str(record_dir / f"records_{timestamp}.csv")

    def get_automatic_spectrum_path(self, position, record_number, product_sn=""):
        configured_dir = Path(str(self.app_config.get("export_dir", "exports")))
        if configured_dir.is_absolute():
            export_dir = configured_dir
        else:
            export_dir = Path(__file__).resolve().parent / configured_dir

        model = self.txt_model.text().strip() or "unknown_model"
        date_dir = datetime.now().strftime("%y年%m月%d日")
        raw_dir = export_dir / model / date_dir / "spectrum_raw"
        raw_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        safe_product_sn = safe_filename_component(product_sn)
        sn_part = f"_sn{safe_product_sn}" if safe_product_sn else ""
        return str(
            raw_dir
            / f"spectrum_motor{int(position):02d}{sn_part}_record{int(record_number):02d}_{timestamp}.csv"
        )

    def write_records_csv(self, path):
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as file:
                writer = csv.writer(file)
                writer.writerow(
                    [
                        "型号",
                        self.txt_model.text(),
                        "数量Qty",
                        self.txt_qty.text(),
                        "开始时间",
                        self.txt_start_time.text(),
                        "完成时间",
                        self.txt_complete_time.text(),
                        "操作员",
                        self.txt_operator.text(),
                        "托盘编号",
                        self.current_tray_id(),
                    ]
                )
                writer.writerow(["实时状态", self.lbl_status.text(), "平均状态", self.lbl_avg_status.text()])
                writer.writerow(
                    [
                        "频谱实测数量",
                        len(self.completed_positions),
                        "跑合跳过数量",
                        len(self.skipped_positions),
                        "跑合跳过位置",
                        ",".join(str(position) for position in sorted(self.skipped_positions)),
                    ]
                )
                writer.writerow([])
                writer.writerow(self.record_headers)
                for row in range(self.tbl_records.rowCount()):
                    writer.writerow(
                        [
                            self.tbl_records.item(row, column).text()
                            if self.tbl_records.item(row, column)
                            else ""
                            for column in range(self.tbl_records.columnCount())
                        ]
                    )
        except OSError as error:
            return False, str(error)
        return True, ""

    def automatic_checkpoint_paths(self, tray_id=None):
        tray_id = self.current_tray_id() if tray_id is None else str(tray_id).strip()
        if not self.checkpoint_enabled or not tray_id:
            return None, None
        safe_model = safe_filename_component(self.txt_model.text()) or "unknown_model"
        safe_tray = safe_filename_component(tray_id)
        if not safe_tray:
            return None, None
        base_path = self.automatic_checkpoint_dir / f"{safe_model}__tray_{safe_tray}"
        return base_path.with_suffix(".json"), base_path.with_suffix(".partial.csv")

    def record_table_rows(self):
        return [
            [
                self.tbl_records.item(row, column).text()
                if self.tbl_records.item(row, column)
                else ""
                for column in range(self.tbl_records.columnCount())
            ]
            for row in range(self.tbl_records.rowCount())
        ]

    @staticmethod
    def spectrum_ok_word_for_results(position_pass_results, completed_positions):
        result_word = 0
        for position in completed_positions:
            position = int(position)
            if 1 <= position <= 15 and position_pass_results.get(position, False):
                result_word |= 1 << position
        return result_word & 0xFFFF

    def save_automatic_checkpoint(self):
        checkpoint_path, partial_csv_path = self.automatic_checkpoint_paths()
        if checkpoint_path is None:
            return True

        payload = {
            "schema_version": 1,
            "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "model": self.txt_model.text().strip(),
            "tray_id": self.current_tray_id(),
            "positions_per_tray": self.positions_per_tray,
            "records_per_motor": self.records_per_motor,
            "start_time": self.txt_start_time.text(),
            "completed_positions": sorted(self.completed_positions),
            "skipped_positions": sorted(self.skipped_positions),
            "current_test_position": self.current_test_position,
            "current_position_record_count": self.current_position_record_count,
            "point_record_done": self.point_record_done,
            "position_pass_results": {
                str(position): bool(passed)
                for position, passed in sorted(self.position_pass_results.items())
            },
            "spectrum_ok_word": self.spectrum_ok_word,
            "record_headers": list(self.record_headers),
            "rows": self.record_table_rows(),
        }
        try:
            checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
            temporary_path = checkpoint_path.with_suffix(".json.tmp")
            temporary_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            temporary_path.replace(checkpoint_path)
            saved, error = self.write_records_csv(partial_csv_path)
            if not saved:
                raise OSError(error)
        except (OSError, TypeError, ValueError) as error:
            self.append_process_log("ERROR", f"自动化断点保存失败: {error}")
            return False
        return True

    def restore_automatic_checkpoint(self, tray_id):
        self.checkpoint_restore_failed = False
        checkpoint_path, _ = self.automatic_checkpoint_paths(tray_id)
        if checkpoint_path is None or not checkpoint_path.exists():
            return False
        try:
            payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            if int(payload.get("schema_version", 0)) != 1:
                raise ValueError("断点文件版本不受支持")
            if str(payload.get("tray_id", "")).strip() != str(tray_id).strip():
                raise ValueError("托盘编号不一致")
            if str(payload.get("model", "")).strip() != self.txt_model.text().strip():
                raise ValueError("产品型号不一致")
            if int(payload.get("positions_per_tray", 0)) != self.positions_per_tray:
                raise ValueError("托盘位置数量配置已变化")
            if int(payload.get("records_per_motor", 0)) != self.records_per_motor:
                raise ValueError("每台记录数量配置已变化")
            if list(payload.get("record_headers", [])) != list(self.record_headers):
                raise ValueError("记录表结构已变化")

            rows = list(payload.get("rows", []))
            expected_columns = len(self.record_headers)
            if any(not isinstance(row, list) or len(row) != expected_columns for row in rows):
                raise ValueError("断点记录表格式无效")
            if len(rows) > self.positions_per_tray * self.records_per_motor:
                raise ValueError("断点记录数量超过配置上限")

            completed_positions = {
                int(position) for position in payload.get("completed_positions", [])
            }
            if any(
                position < 1 or position > self.positions_per_tray
                for position in completed_positions
            ):
                raise ValueError("断点包含无效电机位置")

            skipped_positions = {
                int(position) for position in payload.get("skipped_positions", [])
            }
            if any(
                position < 1 or position > self.positions_per_tray
                for position in skipped_positions
            ):
                raise ValueError("断点包含无效跑合跳过位置")
            if completed_positions & skipped_positions:
                raise ValueError("断点中的频谱完成位置与跑合跳过位置重复")

            current_position = int(payload.get("current_test_position", 0))
            current_record_count = int(payload.get("current_position_record_count", 0))
            point_record_done = bool(payload.get("point_record_done", False))
            if current_position and not 1 <= current_position <= self.positions_per_tray:
                raise ValueError("断点当前电机位置无效")
            if not 0 <= current_record_count <= self.records_per_motor:
                raise ValueError("断点当前电机记录数量无效")
            if not current_position and current_record_count:
                raise ValueError("断点没有当前电机，但存在当前电机记录")
            if current_position in skipped_positions:
                raise ValueError("断点当前电机不能同时标记为跑合跳过")

            position_column = self.record_headers.index("电机位置")
            row_counts = {
                position: 0 for position in range(1, self.positions_per_tray + 1)
            }
            for row in rows:
                position = int(row[position_column])
                if position not in row_counts:
                    raise ValueError(f"断点记录包含无效电机位置 {position}")
                row_counts[position] += 1

            derived_pass_results = {}
            if "状态" in self.record_headers:
                status_column = self.record_headers.index("状态")
                for position, row_count in row_counts.items():
                    if not row_count:
                        continue
                    position_statuses = [
                        str(row[status_column]).strip()
                        for row in rows
                        if int(row[position_column]) == position
                    ]
                    derived_pass_results[position] = all(
                        status != "不合格" for status in position_statuses
                    )

            raw_pass_results = payload.get("position_pass_results")
            if raw_pass_results is None:
                position_pass_results = derived_pass_results
            else:
                if not isinstance(raw_pass_results, dict):
                    raise ValueError("断点电机判定结果格式无效")
                position_pass_results = {}
                for position_text, passed in raw_pass_results.items():
                    position = int(position_text)
                    if position not in row_counts or not isinstance(passed, bool):
                        raise ValueError("断点电机判定结果包含无效值")
                    if row_counts[position] == 0:
                        raise ValueError(f"断点电机位置 {position} 没有记录但存在判定结果")
                    position_pass_results[position] = passed
                recorded_positions = {
                    position for position, row_count in row_counts.items() if row_count
                }
                if set(position_pass_results) != recorded_positions:
                    raise ValueError("断点电机判定结果与已有记录位置不一致")
                if derived_pass_results and position_pass_results != derived_pass_results:
                    raise ValueError("断点电机判定结果与记录表状态不一致")

            for position, row_count in row_counts.items():
                if position in skipped_positions and row_count:
                    raise ValueError(f"跑合跳过位置 {position} 不应存在频谱记录")
                if position in completed_positions:
                    if row_count != self.records_per_motor:
                        raise ValueError(
                            f"断点电机位置 {position} 已完成，但记录数为 "
                            f"{row_count}/{self.records_per_motor}"
                        )
                elif position == current_position:
                    if row_count != current_record_count:
                        raise ValueError(
                            f"断点电机位置 {position} 的表格记录数 {row_count} "
                            f"与进度 {current_record_count} 不一致"
                        )
                elif row_count:
                    raise ValueError(
                        f"断点电机位置 {position} 未完成，但存在 {row_count} 条记录"
                    )

            if point_record_done:
                if current_position not in completed_positions:
                    raise ValueError("断点采集完成位与当前电机完成状态不一致")
                if current_record_count != self.records_per_motor:
                    raise ValueError("断点采集完成位已置位，但当前电机记录未满")
            elif current_position in completed_positions:
                raise ValueError("断点当前电机已完成，但采集完成位未置位")

            expected_result_word = self.spectrum_ok_word_for_results(
                position_pass_results,
                completed_positions,
            )
            stored_result_word = int(
                payload.get("spectrum_ok_word", expected_result_word)
            ) & 0xFFFF
            if stored_result_word != expected_result_word:
                raise ValueError("断点频谱OK结果字与电机判定状态不一致")
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
            self.checkpoint_restore_failed = True
            self.append_process_log(
                "ERROR",
                f"托盘 {tray_id} 的自动化断点无法恢复，将等待人工处理: {error}",
            )
            return False

        self.tbl_records.setRowCount(0)
        for row_values in rows:
            row_index = self.tbl_records.rowCount()
            self.tbl_records.insertRow(row_index)
            for column, value in enumerate(row_values):
                item = QTableWidgetItem(str(value))
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.tbl_records.setItem(row_index, column, item)

        self.completed_positions = completed_positions
        self.skipped_positions = skipped_positions
        self.current_test_position = current_position
        self.current_position_record_count = current_record_count
        self.point_record_done = point_record_done
        self.position_pass_results = position_pass_results
        self.spectrum_ok_word = expected_result_word
        self.cycle_completion_handled = False
        self.txt_start_time.setText(str(payload.get("start_time", "")))
        self.txt_complete_time.clear()
        self.txt_qty.setText(str(self.positions_per_tray))
        self.update_record_count()
        self.append_process_log(
            "RECOVERY",
            f"已恢复托盘 {tray_id} 的断点: {self.automation_progress_text()}，"
            f"记录 {self.tbl_records.rowCount()} 条",
        )
        return True

    def clear_automatic_checkpoint(self, tray_id=None):
        checkpoint_path, partial_csv_path = self.automatic_checkpoint_paths(tray_id)
        cleared_paths = []
        for path in (checkpoint_path, partial_csv_path):
            if path is None:
                continue
            try:
                existed = path.exists()
                path.unlink(missing_ok=True)
                if existed:
                    cleared_paths.append(path)
            except OSError as error:
                self.append_process_log("WARN", f"清理自动化断点失败: {path} | {error}")
        return cleared_paths

    def discard_automatic_progress(self, tray_id=None):
        tray_id = self.current_tray_id() if tray_id is None else str(tray_id).strip()
        cleared_paths = self.clear_automatic_checkpoint(tray_id)
        self.reset_automatic_records()
        self.checkpoint_restore_failed = False
        for bit in (PC_START_BIT, PC_STOP_BIT, PC_POINT_DONE_BIT, PC_FAULT_BIT):
            self.set_pc_command_bit(bit, False)

        tray_text = tray_id or "未填写托盘"
        self.lbl_status.setText(f"{tray_text} 的未完成进度已清除，等待从首个PLC到位位置重新测试")
        self.lbl_avg_status.setText(self.automation_progress_text())
        if self.plc_connected:
            self.lbl_plc_state.setText("PLC: 已连接 | 自动化进度已清除")
        self.statusbar.showMessage(f"{tray_text} 的自动化断点和检测记录已清除")
        self.append_process_log(
            "COMMAND",
            f"已清除 {tray_text} 的检测记录和自动化断点，DM3500命令位及DM3505结果字已复位"
            f" | 删除断点文件 {len(cleared_paths)} 个",
        )
        return cleared_paths

    def save_records(self):
        if self.tbl_records.rowCount() == 0:
            QMessageBox.warning(self, "无数据", "下方记录表还没有数据，无法保存。")
            return

        path, _ = QFileDialog.getSaveFileName(
            self,
            "保存检测记录",
            self.get_export_path("records"),
            "CSV 文件 (*.csv)",
        )
        if not path:
            return
        if not path.lower().endswith(".csv"):
            path += ".csv"

        saved, error = self.write_records_csv(path)
        if not saved:
            self.append_process_log("ERROR", f"检测记录保存失败: {error}")
            QMessageBox.critical(self, "保存失败", f"无法保存检测记录文件: {error}")
            return

        self.append_process_log("FILE", f"检测记录已保存: {path}")
        QMessageBox.information(self, "保存完成", f"检测记录已保存到:\n{path}")

    def export_current_data(self):
        if self.latest_fft_vals is None:
            self.latest_fft_vals = self.calculate_fft_values(self.data_buffer)

        position = self.current_identity_position()
        tray_id, product_sn = self.record_identity(position)

        path, _ = QFileDialog.getSaveFileName(
            self,
            "导出当前波形/频谱",
            self.get_export_path("snapshot"),
            "CSV 文件 (*.csv)",
        )
        if not path:
            return
        if not path.lower().endswith(".csv"):
            path += ".csv"

        fft_mask = self.fft_freqs <= self.fft_max_freq
        fft_freqs = self.fft_freqs[fft_mask]
        fft_vals = self.latest_fft_vals[fft_mask]
        row_count = max(len(self.time_axis), len(fft_freqs))

        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as file:
                writer = csv.writer(file)
                writer.writerow(["导出时间", datetime.now().strftime("%Y-%m-%d %H:%M:%S")])
                writer.writerow([
                    "采集模式",
                    self.active_source_label(),
                    "通道",
                    self.input_channel,
                    "采样率Hz",
                    self.actual_scan_rate or self.scan_rate,
                    "FFT上限Hz",
                    self.fft_max_freq,
                    "单位",
                    self.fft_unit,
                    "FFT显示模式",
                    self.fft_display_mode,
                    "加速度灵敏度(m/s^2)/mV",
                    self.acceleration_sensitivity_m_s2_per_mv,
                    "托盘编号",
                    tray_id,
                    "电机位置",
                    "" if position is None else position,
                    "产品SN",
                    product_sn,
                ])
                writer.writerow([
                    "时域去平均值",
                    self.time_remove_mean,
                    "最大设备缓冲",
                    self.max_device_backlog,
                    "最大LJM缓冲",
                    self.max_ljm_backlog,
                ])
                writer.writerow([])
                writer.writerow([
                    "time_s",
                    f"value_raw_{self.display_unit}",
                    f"value_analysis_{self.display_unit}",
                    "frequency_hz",
                    f"amplitude_{self.fft_unit}",
                ])
                for index in range(row_count):
                    writer.writerow(
                        [
                            f"{self.time_axis[index]:.8f}" if index < len(self.time_axis) else "",
                            f"{self.raw_data_buffer[index]:.8f}" if index < len(self.raw_data_buffer) else "",
                            f"{self.data_buffer[index]:.8f}" if index < len(self.data_buffer) else "",
                            f"{fft_freqs[index]:.4f}" if index < len(fft_freqs) else "",
                            f"{fft_vals[index]:.10f}" if index < len(fft_vals) else "",
                        ]
                    )
        except OSError as e:
            self.append_process_log("ERROR", f"当前波形/频谱导出失败: {e}")
            QMessageBox.critical(self, "导出失败", f"无法导出当前波形/频谱: {e}")
            return

        self.append_process_log("FILE", f"当前波形/频谱已导出: {path}")
        QMessageBox.information(self, "导出完成", f"当前波形/频谱已导出到:\n{path}")

    def get_raw_spectrum_detection_frequencies(self, max_freq):
        frequencies = []

        frequencies.extend(
            self.feature_base_frequency_hz * to_float(point.get("coefficient"), 0.0)
            for point in self.feature_points
        )
        frequencies.extend(
            to_float(point.get("frequency_hz"), 0.0)
            for point in self.fixed_frequency_points
        )
        frequencies.extend(self.latest_top_freqs)
        frequencies.extend(self.latest_feature_peak_freqs)
        frequencies.extend(self.latest_fixed_frequency_peak_freqs)
        frequencies.extend(
            to_float(summary.get("peak_frequency_hz"), 0.0)
            for summary in self.latest_band_summaries
        )

        return np.asarray([
            frequency
            for frequency in frequencies
            if np.isfinite(frequency) and 0.0 <= frequency < max_freq
        ], dtype=float)

    def write_raw_spectrum_csv(
        self,
        path,
        position=None,
        record_number=None,
        tray_id=None,
        product_sn=None,
    ):
        export_config = self.acquisition_config.get("raw_spectrum_export", {})
        encoding = str(export_config.get("encoding", "gbk"))
        tray_id, product_sn = self.record_identity(position, tray_id, product_sn)
        try:
            max_freq = float(export_config.get("max_freq", 25600))
        except (TypeError, ValueError):
            return False, "原始频谱导出最高频率不是有效数字"
        if max_freq <= 0:
            return False, "原始频谱导出最高频率必须大于 0"

        interval_value = export_config.get("frequency_interval_hz")
        if interval_value is not None:
            try:
                frequency_interval_hz = float(interval_value)
            except (TypeError, ValueError):
                return False, "原始频谱导出频率间隔不是有效数字"
            if frequency_interval_hz <= 0:
                return False, "原始频谱导出频率间隔必须大于 0"
            export_freqs = np.arange(0.0, max_freq, frequency_interval_hz, dtype=float)
        else:
            try:
                point_count = int(export_config.get("points", 10000))
            except (TypeError, ValueError):
                return False, "原始频谱导出点数不是有效整数"
            if point_count <= 0:
                return False, "原始频谱导出点数必须大于 0"
            export_freqs = np.arange(point_count, dtype=float) * max_freq / point_count

        if self.latest_fft_vals is None:
            self.update_fft_analysis(self.data_buffer, update_plot=False)

        if to_bool(export_config.get("include_detection_points", True), True):
            detection_freqs = self.get_raw_spectrum_detection_frequencies(max_freq)
            if detection_freqs.size:
                export_freqs = merge_export_frequencies(
                    export_freqs,
                    detection_freqs,
                    max_freq,
                )

        source_mask = self.fft_freqs <= min(max_freq, self.fft_freqs[-1])
        source_freqs = self.fft_freqs[source_mask]
        source_amps = self.latest_fft_vals[source_mask]
        if source_freqs.size == 0:
            return False, "当前没有可导出的频谱数据"

        export_amps = np.interp(export_freqs, source_freqs, source_amps, left=0.0, right=0.0)

        try:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", newline="", encoding=encoding) as file:
                writer = csv.writer(file)
                writer.writerow([
                    self.txt_model.text(),
                    self.txt_qty.text(),
                    self.txt_start_time.text(),
                    self.txt_complete_time.text(),
                    self.fft_display_mode,
                    self.fft_unit,
                    "" if position is None else int(position),
                    "" if record_number is None else int(record_number),
                    "托盘编号",
                    tray_id,
                    "产品SN",
                    product_sn,
                    "采集模式",
                    self.active_source_label(),
                    "输入通道",
                    self.input_channel,
                ])
                for freq, amp in zip(export_freqs, export_amps):
                    frequency_text = f"{freq:.9f}".rstrip("0").rstrip(".")
                    writer.writerow([frequency_text, f"{amp:.2f}"])
        except (OSError, LookupError, ValueError) as error:
            return False, str(error)
        return True, ""

    def export_raw_spectrum_data(self):
        if self.latest_fft_vals is None:
            self.update_fft_analysis(self.data_buffer, update_plot=False)

        position = self.current_identity_position()
        tray_id, product_sn = self.record_identity(position)

        path, _ = QFileDialog.getSaveFileName(
            self,
            "导出原始频谱",
            self.get_raw_export_path(),
            "CSV 文件 (*.csv)",
        )
        if not path:
            return
        if not path.lower().endswith(".csv"):
            path += ".csv"

        saved, error = self.write_raw_spectrum_csv(
            path,
            position=position,
            tray_id=tray_id,
            product_sn=product_sn,
        )
        if not saved:
            self.append_process_log("ERROR", f"原始频谱导出失败: {error}")
            QMessageBox.critical(self, "导出失败", f"无法导出原始频谱: {error}")
            return

        self.append_process_log("FILE", f"原始频谱已导出: {path}")
        QMessageBox.information(self, "导出完成", f"原始频谱已导出到:\n{path}")

    def clear_records(self):
        if self.auto_test_active or self.manual_acquisition_active or self.is_running:
            QMessageBox.warning(
                self,
                "无法清空",
                "请先退出自动化或停止手动采集，再清空当前托盘记录。",
            )
            return

        tray_id = self.current_tray_id()
        checkpoint_paths = self.automatic_checkpoint_paths(tray_id)
        has_checkpoint = any(
            path is not None and path.exists()
            for path in checkpoint_paths
        )
        has_progress = bool(
            self.tbl_records.rowCount()
            or self.completed_positions
            or self.skipped_positions
            or self.current_position_record_count
            or has_checkpoint
        )
        if not has_progress:
            self.append_process_log("COMMAND", "当前没有可清除的检测记录或自动化断点")
            return

        tray_text = tray_id or "未填写托盘"
        reply = QMessageBox.question(
            self,
            "清空记录并重新开始",
            f"确定清空 {tray_text} 的未完成检测记录和自动化断点吗？\n\n"
            "清除后再次进入自动化将从PLC发送的首个到位位置重新测试，"
            "DM3505频谱结果字也会清零。\n"
            "已经单独导出的原始频谱文件不会删除。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self.discard_automatic_progress(tray_id)

    def get_top_frequencies(self, fft_vals, count=15):
        mask = (self.fft_freqs > 0) & (self.fft_freqs <= self.fft_max_freq)
        freqs = self.fft_freqs[mask]
        amps = fft_vals[mask]
        if amps.size == 0:
            return [], []

        if amps.size > 2:
            local_peak_idx = np.where((amps[1:-1] >= amps[:-2]) & (amps[1:-1] >= amps[2:]))[0] + 1
        else:
            local_peak_idx = np.arange(amps.size)

        source_idx = local_peak_idx if local_peak_idx.size else np.arange(amps.size)
        top_idx = source_idx[np.argsort(amps[source_idx])[-count:]][::-1]
        return freqs[top_idx].tolist(), amps[top_idx].tolist()

    def get_global_frequency_peak(self, fft_vals):
        lower_hz = max(self.fft_highpass_hz, 0.0)
        upper_hz = float(self.fft_max_freq)
        if self.fft_lowpass_hz > 0:
            upper_hz = min(upper_hz, self.fft_lowpass_hz)
        mask = (self.fft_freqs >= lower_hz) & (self.fft_freqs <= upper_hz)
        freqs = self.fft_freqs[mask]
        amps = np.asarray(fft_vals, dtype=float)[mask]
        finite_mask = np.isfinite(amps)
        if not np.any(finite_mask):
            return None, None

        freqs = freqs[finite_mask]
        amps = amps[finite_mask]
        max_index = int(np.argmax(amps))
        return float(freqs[max_index]), float(amps[max_index])

    def update_fft_y_range(self, fft_vals):
        if not self.fft_y_auto_scale:
            return

        mask = (self.fft_freqs >= 0) & (self.fft_freqs <= self.fft_max_freq)
        visible_amps = fft_vals[mask]
        if visible_amps.size == 0:
            return

        max_amp = float(np.nanmax(visible_amps))
        if not np.isfinite(max_amp):
            return

        y_max = max(self.fft_y_auto_min_max, max_amp * self.fft_y_auto_margin)
        if abs(y_max - self.fft_y_limit_max) / max(self.fft_y_limit_max, 1.0) > 0.15:
            self.fft_y_limit_max = y_max
            self.graph_fft.setYRange(self.fft_y_limit_min, self.fft_y_limit_max, padding=0)

    def update_time_y_range(self, display_data):
        if not self.time_y_auto_scale:
            return

        now = monotonic()
        if now - self.time_y_last_auto_update < self.time_y_auto_update_interval_sec:
            return
        self.time_y_last_auto_update = now

        if display_data.size == 0:
            return

        step = max(1, display_data.size // 5000)
        visible_values = display_data[::step]
        visible_values = visible_values[np.isfinite(visible_values)]
        if visible_values.size == 0:
            return

        center = float(np.nanmedian(visible_values))
        deviations = np.abs(visible_values - center)
        half_range = float(np.nanpercentile(deviations, self.time_y_auto_percentile))
        if not np.isfinite(half_range):
            return

        half_range = max(half_range * self.time_y_auto_margin, self.time_y_auto_min_range / 2.0)
        y_min = center - half_range
        y_max = center + half_range

        current_range = max(self.time_y_current_max - self.time_y_current_min, 1.0)
        next_range = max(y_max - y_min, 1.0)
        range_change = abs(next_range - current_range) / current_range
        center_change = abs((y_max + y_min) / 2.0 - (self.time_y_current_max + self.time_y_current_min) / 2.0)

        if range_change > 0.12 or center_change > current_range * 0.08:
            self.time_y_current_min = y_min
            self.time_y_current_max = y_max
            self.graph_widget.setYRange(y_min, y_max, padding=0)

    def get_feature_frequency_amplitudes(self, fft_vals):
        amplitudes = []
        peak_freqs = []
        range_ratio = max(self.feature_range_percent, 0.0) / 100.0
        lower_base = self.feature_base_frequency_hz * (1.0 - range_ratio)
        upper_base = self.feature_base_frequency_hz * (1.0 + range_ratio)

        for point in self.feature_points:
            coefficient = to_float(point.get("coefficient"), 0.0)
            if self.feature_base_frequency_hz <= 0 or coefficient <= 0:
                amplitudes.append(0.0)
                peak_freqs.append(0.0)
                continue

            start_hz = lower_base * coefficient
            end_hz = upper_base * coefficient
            mask = (self.fft_freqs >= start_hz) & (self.fft_freqs <= end_hz)
            if not np.any(mask):
                amplitudes.append(0.0)
                peak_freqs.append(self.feature_base_frequency_hz * coefficient)
                continue

            local_freqs = self.fft_freqs[mask]
            local_amps = fft_vals[mask]
            max_index = int(np.argmax(local_amps))
            amplitudes.append(float(local_amps[max_index]))
            peak_freqs.append(float(local_freqs[max_index]))
        return amplitudes, peak_freqs

    def get_fixed_frequency_amplitudes(self, fft_vals):
        amplitudes = []
        peak_freqs = []
        for point in self.fixed_frequency_points:
            target_hz = to_float(point.get("frequency_hz"), 0.0)
            search_width_hz = to_float(point.get("search_width_hz"), 0.0)
            range_percent = max(to_float(self.fixed_frequency_range_percent, 2.0), 0.0)
            if target_hz <= 0:
                amplitudes.append(0.0)
                peak_freqs.append(0.0)
                continue

            if search_width_hz > 0:
                start_hz = target_hz - search_width_hz
                end_hz = target_hz + search_width_hz
            elif range_percent > 0:
                range_ratio = range_percent / 100.0
                start_hz = target_hz * (1.0 - range_ratio)
                end_hz = target_hz * (1.0 + range_ratio)
            else:
                start_hz = end_hz = None

            if start_hz is not None:
                mask = (self.fft_freqs >= start_hz) & (self.fft_freqs <= end_hz)
                if not np.any(mask):
                    amplitudes.append(0.0)
                    peak_freqs.append(target_hz)
                    continue
                local_freqs = self.fft_freqs[mask]
                local_amps = fft_vals[mask]
                max_index = int(np.argmax(local_amps))
                amplitudes.append(float(local_amps[max_index]))
                peak_freqs.append(float(local_freqs[max_index]))
            else:
                nearest_index = int(np.argmin(np.abs(self.fft_freqs - target_hz)))
                amplitudes.append(float(fft_vals[nearest_index]))
                peak_freqs.append(float(self.fft_freqs[nearest_index]))

        return amplitudes, peak_freqs

    def get_band_group_summaries(self, fft_vals):
        summaries = []
        for group in self.frequency_band_groups:
            start_hz = to_float(group.get("start_hz"), 0.0)
            end_hz = to_float(group.get("end_hz"), 0.0)
            if start_hz > end_hz:
                start_hz, end_hz = end_hz, start_hz
            mask = (
                (self.fft_freqs >= start_hz - FREQUENCY_BOUNDARY_EPSILON_HZ)
                & (self.fft_freqs <= end_hz + FREQUENCY_BOUNDARY_EPSILON_HZ)
            )
            if not np.any(mask):
                summaries.append({
                    "peak_count": 0,
                    "peak_frequency_hz": 0.0,
                    "peak_amplitude": 0.0,
                    "energy_sum": 0.0,
                })
                continue

            local_freqs = self.fft_freqs[mask]
            local_amps = fft_vals[mask]
            if local_amps.size > 2:
                local_peak_idx = np.where((local_amps[1:-1] >= local_amps[:-2]) & (local_amps[1:-1] >= local_amps[2:]))[0] + 1
            else:
                local_peak_idx = np.arange(local_amps.size)

            threshold = to_float(group.get("peak_threshold"), self.wave_threshold)
            counted_peak_idx = local_peak_idx[local_amps[local_peak_idx] >= threshold]
            max_index = int(np.argmax(local_amps))
            summaries.append({
                "peak_count": int(counted_peak_idx.size),
                "peak_frequency_hz": float(local_freqs[max_index]),
                "peak_amplitude": float(local_amps[max_index]),
                "energy_sum": float(np.sum(local_amps ** 2)),
            })
        return summaries

    def add_record_row(self, avg_rms, avg_vpp, position=None, tray_id=None, product_sn=None):
        row = self.tbl_records.rowCount()
        self.tbl_records.insertRow(row)
        tray_id, product_sn = self.record_identity(position, tray_id, product_sn)

        feature_amps = normalize_list(self.latest_feature_amps, len(self.feature_points), 0.0)
        feature_limits = normalize_list(getattr(self, "feature_limits", []), len(self.feature_points), 0.0)
        feature_peak_freqs = normalize_list(self.latest_feature_peak_freqs, len(self.feature_points), 0.0)
        fixed_frequency_amps = normalize_list(self.latest_fixed_frequency_amps, len(self.fixed_frequency_points), 0.0)
        fixed_frequency_limits = normalize_list(
            getattr(self, "fixed_frequency_limits", []),
            len(self.fixed_frequency_points),
            0.0,
        )
        if feature_amps:
            feature_main_index = int(np.argmax(feature_amps))
            feature_main_freq = feature_peak_freqs[feature_main_index]
            feature_main_amp = feature_amps[feature_main_index]
        else:
            feature_main_freq = ""
            feature_main_amp = ""

        global_main_freq = self.latest_global_peak_freq
        global_main_amp = self.latest_global_peak_amp

        feature_center_freqs = [
            self.feature_base_frequency_hz * to_float(point.get("coefficient"), 0.0)
            for point in self.feature_points
        ]
        failed_feature_items = [
            index + 1
            for index, (point, amp, limit, center_freq) in enumerate(
                zip(self.feature_points, feature_amps, feature_limits, feature_center_freqs)
            )
            if (
                is_judgment_enabled(point)
                and limit > 0
                and amp > limit
                and center_freq <= self.judgment_max_freq_hz
            )
        ]
        failed_fixed_frequency_items = [
            index + 1
            for index, (point, amp, limit) in enumerate(
                zip(self.fixed_frequency_points, fixed_frequency_amps, fixed_frequency_limits)
            )
            if (
                is_judgment_enabled(point)
                and limit > 0
                and amp > limit
                and to_float(point.get("frequency_hz"), 0.0) <= self.judgment_max_freq_hz
            )
        ]
        failed_band_items = []
        for index, (group, summary) in enumerate(zip(self.frequency_band_groups, self.latest_band_summaries)):
            if to_float(group.get("start_hz"), 0.0) > self.judgment_max_freq_hz:
                continue
            peak_count_limit = to_float(group.get("peak_count_upper_limit"), 0.0)
            energy_limit = to_float(group.get("energy_upper_limit"), 0.0)
            if peak_count_limit > 0 and to_float(summary.get("peak_count"), 0.0) > peak_count_limit:
                failed_band_items.append((index, "peak_count"))
            if energy_limit > 0 and to_float(summary.get("energy_sum"), 0.0) > energy_limit:
                failed_band_items.append((index, "energy_sum"))

        status = (
            "不合格"
            if failed_feature_items or failed_fixed_frequency_items or failed_band_items
            else self.default_status
        )
        band_values = []
        for summary in self.latest_band_summaries:
            band_values.extend([
                str(summary.get("peak_count", 0)),
                f"{summary.get('peak_frequency_hz', 0.0):.2f}",
                f"{summary.get('peak_amplitude', 0.0):.2f}",
                f"{summary.get('energy_sum', 0.0):.2f}",
            ])
        values = [
            row + 1,
            position if position is not None else "",
            tray_id,
            product_sn,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            self.input_channel,
            f"{avg_rms:.4f}",
            f"{avg_vpp:.4f}",
            f"{global_main_freq:.2f}" if global_main_freq is not None else "",
            f"{global_main_amp:.6f}" if global_main_amp is not None else "",
            f"{feature_main_freq:.2f}" if feature_main_freq != "" else "",
            f"{feature_main_amp:.6f}" if feature_main_amp != "" else "",
            *[f"{amp:.2f}" for amp in feature_amps],
            *[f"{amp:.2f}" for amp in fixed_frequency_amps],
            *band_values,
            status,
        ]

        for column, value in enumerate(values):
            item = QTableWidgetItem(str(value))
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.tbl_records.setItem(row, column, item)

        self.tbl_records.scrollToBottom()
        self.update_record_count()
        return status

    def set_test_controls_enabled(self, enabled):
        for widget in (
            self.btn_select_product,
            self.btn_set_product,
            self.btn_settings,
            self.btn_save_records,
            self.btn_export_snapshot,
            self.btn_export_raw,
            self.chk_auto_export_spectrum,
            self.btn_clear_records,
            self.cmb_acquisition_source,
            self.txt_model,
            self.txt_qty,
            self.txt_operator,
        ):
            widget.setEnabled(bool(enabled))

    def acquisition_worker_config(self):
        config = deepcopy(self.acquisition_config)
        config.update({
            "source": self.acquisition_source,
            "input_channel": self.input_channel,
            "scan_rate": self.scan_rate,
            "scans_per_read": self.scans_per_read,
            "display_time_sec": self.display_time_sec,
            "display_refresh_hz": self.display_refresh_hz,
            "avg_time_sec": self.avg_time_sec,
            "record_value_mode": self.record_value_mode,
            "time_remove_mean": self.time_remove_mean,
            "invalid_input_voltage_abs_max": self.invalid_input_voltage_abs_max,
            "gravity_m_s2": self.gravity_m_s2,
            "acceleration_sensitivity_m_s2_per_mv": self.acceleration_sensitivity_m_s2_per_mv,
            "display_scale_from_m_s2": self.display_scale_from_m_s2,
            "labjack": deepcopy(self.labjack_config),
            "ni9234": deepcopy(self.ni9234_config),
        })
        return config

    def rebuild_signal_geometry(self, actual_scan_rate, display_points=None):
        self.actual_scan_rate = float(actual_scan_rate)
        self.display_points = int(display_points or max(
            round(self.actual_scan_rate * self.display_time_sec),
            self.scans_per_read,
        ))
        self.data_buffer = np.zeros(self.display_points)
        self.raw_data_buffer = np.zeros(self.display_points)
        self.time_axis = np.linspace(-self.display_time_sec, 0, self.display_points)
        self.fft_freqs = np.fft.rfftfreq(self.display_points, d=1.0 / self.actual_scan_rate)
        self.fft_window = np.hanning(self.display_points)
        self.fft_window_coherent_gain = float(np.mean(self.fft_window))
        self.update_header_info()

    def start_acquisition_worker(self, stop_after_record):
        if (
            self.acquisition_source == ACQUISITION_SOURCE_LABJACK
            and self.lj_handle is None
        ):
            return False
        if self.acquisition_worker is not None and self.acquisition_worker.isRunning():
            return False

        self.acquisition_error_handled = False
        worker = AcquisitionWorker(
            self.lj_handle,
            self.acquisition_worker_config(),
            stop_after_record=stop_after_record,
            parent=self,
        )
        worker.stream_started.connect(self.handle_stream_started)
        worker.display_ready.connect(self.handle_display_ready)
        worker.record_ready.connect(self.handle_record_ready)
        worker.stream_error.connect(self.handle_acquisition_error)
        worker.finished.connect(self.handle_acquisition_finished)
        self.acquisition_worker = worker
        self.is_running = True
        worker.start()
        return True

    def handle_stream_started(self, actual_scan_rate, record_target_samples):
        worker = self.sender()
        if worker is not self.acquisition_worker:
            return
        self.input_channel = worker.input_channel
        self.scans_per_read = worker.scans_per_read
        self.rebuild_signal_geometry(actual_scan_rate, worker.display_points)
        self.graph_fft.setXRange(
            0,
            min(float(self.fft_max_freq), float(actual_scan_rate) / 2.0),
            padding=0,
        )
        duration = record_target_samples / actual_scan_rate
        mode = "手动" if self.manual_acquisition_active else f"自动点位{self.current_test_position}"
        self.append_process_log(
            "DAQ",
            f"{mode}采集已启动: {worker.source_label} | 通道 {worker.input_channel} | "
            f"实际采样率 {actual_scan_rate:g} Hz, "
            f"目标 {record_target_samples} 点/{duration:.3g} 秒",
        )
        if self.manual_acquisition_active:
            self.lbl_status.setText(f"手动采集中，实际采样率 {actual_scan_rate:g} Hz")
            self.lbl_avg_status.setText(
                f"【{duration:.3g}秒{self.record_mode_label()}】 按 {record_target_samples} 个采样点周期记录"
            )
        elif self.auto_test_active:
            self.lbl_status.setText(
                f"正在采集第 {self.current_test_position}/{self.positions_per_tray} 个电机，"
                f"实际采样率 {actual_scan_rate:g} Hz"
            )
            self.lbl_avg_status.setText(
                f"【{duration:.3g}秒{self.record_mode_label()}】 采集 {record_target_samples} 点"
            )

    def update_fft_analysis(self, display_data, update_plot=True):
        fft_vals = self.calculate_fft_values(display_data)
        self.latest_fft_vals = fft_vals
        self.latest_top_freqs, self.latest_top_amps = self.get_top_frequencies(fft_vals)
        self.latest_global_peak_freq, self.latest_global_peak_amp = self.get_global_frequency_peak(fft_vals)
        self.latest_feature_amps, self.latest_feature_peak_freqs = self.get_feature_frequency_amplitudes(fft_vals)
        self.latest_fixed_frequency_amps, self.latest_fixed_frequency_peak_freqs = self.get_fixed_frequency_amplitudes(fft_vals)
        self.latest_band_summaries = self.get_band_group_summaries(fft_vals)
        if update_plot:
            self.plot_line_fft.setData(self.fft_freqs, fft_vals)
            self.update_fft_y_range(fft_vals)

    def apply_acquisition_snapshot(self, payload, update_status=True):
        display_data = np.asarray(payload.get("data", []), dtype=float)
        raw_data = np.asarray(payload.get("raw_data", display_data), dtype=float)
        if display_data.size == 0:
            return
        if display_data.size != self.display_points:
            actual_rate = float(payload.get("actual_scan_rate", self.actual_scan_rate or self.scan_rate))
            self.rebuild_signal_geometry(actual_rate, display_data.size)

        self.data_buffer = display_data.copy()
        self.raw_data_buffer = raw_data.copy()
        self.last_device_backlog = int(payload.get("device_backlog", 0))
        self.last_ljm_backlog = int(payload.get("ljm_backlog", 0))
        self.max_device_backlog = max(self.max_device_backlog, int(payload.get("max_device_backlog", 0)))
        self.max_ljm_backlog = max(self.max_ljm_backlog, int(payload.get("max_ljm_backlog", 0)))

        self.plot_line.setData(self.time_axis[::10], self.data_buffer[::10])
        self.update_time_y_range(self.data_buffer)
        self.update_fft_analysis(self.data_buffer)

        if update_status:
            rms_value = float(payload.get("realtime_rms", 0.0))
            vpp_value = float(payload.get("realtime_vpp", 0.0))
            self.lbl_status.setText(
                f"实时振动值: {rms_value:.4f} {self.display_unit} (RMS) | "
                f"峰峰值: {vpp_value:.2f} {self.display_unit} | "
                f"缓冲 设备/LJM: {self.last_device_backlog}/{self.last_ljm_backlog}"
            )

    def handle_display_ready(self):
        if not self.is_running:
            return
        worker = self.sender()
        if worker is not self.acquisition_worker:
            return
        payload = worker.take_latest_display_payload()
        if payload is None:
            return
        self.apply_acquisition_snapshot(payload, update_status=True)

    def handle_record_ready(self, payload):
        if not self.manual_acquisition_active and not self.auto_test_active:
            return
        if self.auto_test_active and self.auto_test_paused:
            self.append_process_log("RECOVERY", "暂停期间到达的未完成采集窗口已丢弃")
            return
        self.apply_acquisition_snapshot(payload, update_status=False)
        avg_rms = float(payload.get("rms", 0.0))
        avg_vpp = float(payload.get("vpp", 0.0))
        duration = float(payload.get("duration_sec", self.avg_time_sec))
        mode_label = str(payload.get("mode_label", self.record_mode_label()))
        sample_count = int(payload.get("sample_count", 0))
        record_target = (
            "手动采集"
            if self.manual_acquisition_active
            else (
                f"电机位置 {self.current_test_position}/{self.positions_per_tray} "
                f"记录 {self.current_position_record_count + 1}/{self.records_per_motor}"
            )
        )
        self.append_process_log(
            "DAQ",
            f"{record_target}窗口完成: {sample_count} 点, RMS={avg_rms:.4f} {self.display_unit}, "
            f"Vpp={avg_vpp:.4f} {self.display_unit}",
        )
        self.lbl_avg_status.setText(
            f"【{duration:.3g}秒{mode_label}】 有效值(RMS): {avg_rms:.4f} {self.display_unit} | "
            f"峰峰值(Vpp): {avg_vpp:.4f} {self.display_unit} | {sample_count} 点"
        )

        if self.manual_acquisition_active:
            manual_position = (
                self.plc_current_position
                if 1 <= self.plc_current_position <= self.positions_per_tray
                else None
            )
            tray_id, product_sn = self.record_identity(manual_position)
            record_status = self.add_record_row(
                avg_rms,
                avg_vpp,
                position=manual_position,
                tray_id=tray_id,
                product_sn=product_sn,
            )
            self.persist_spectrum_result(
                avg_rms,
                avg_vpp,
                record_status,
                manual_position,
                tray_id,
                product_sn,
            )
            self.lbl_status.setText(
                f"手动采集中，已记录 {self.tbl_records.rowCount()} 个完整采样窗口 | "
                f"最大缓冲 设备/LJM: {self.max_device_backlog}/{self.max_ljm_backlog}"
            )
            return

        next_record_number = self.current_position_record_count + 1
        tray_id, product_sn = self.record_identity(self.current_test_position)
        spectrum_path = None
        if self.chk_auto_export_spectrum.isChecked():
            spectrum_path = self.get_automatic_spectrum_path(
                self.current_test_position,
                next_record_number,
                product_sn,
            )
            saved, error = self.write_raw_spectrum_csv(
                spectrum_path,
                position=self.current_test_position,
                record_number=next_record_number,
                tray_id=tray_id,
                product_sn=product_sn,
            )
            if not saved:
                self.abort_automatic_test(f"原始频谱自动保存失败: {error}", upper_fault=True)
                return

        record_status = self.add_record_row(
            avg_rms,
            avg_vpp,
            self.current_test_position,
            tray_id=tray_id,
            product_sn=product_sn,
        )
        previous_passed = self.position_pass_results.get(self.current_test_position, True)
        self.position_pass_results[self.current_test_position] = (
            previous_passed and record_status != "不合格"
        )
        cumulative_status = (
            "合格"
            if self.position_pass_results[self.current_test_position]
            else "不合格"
        )
        self.persist_spectrum_result(
            avg_rms,
            avg_vpp,
            cumulative_status,
            self.current_test_position,
            tray_id,
            product_sn,
            raw_spectrum_path=spectrum_path,
        )
        self.current_position_record_count = next_record_number
        if spectrum_path is not None:
            self.append_process_log(
                "FILE",
                f"电机位置 {self.current_test_position} 第 {next_record_number}/{self.records_per_motor} 条原始频谱已保存: {spectrum_path}",
            )
        if self.current_position_record_count < self.records_per_motor:
            self.save_automatic_checkpoint()
            self.lbl_status.setText(
                f"第 {self.current_test_position}/{self.positions_per_tray} 个电机已记录 "
                f"{self.current_position_record_count}/{self.records_per_motor} 条，继续采集"
            )
            return

        self.stop_data_stream()
        self.completed_positions.add(self.current_test_position)
        position_passed = self.position_pass_results.get(self.current_test_position, False)
        self.set_position_spectrum_ok(self.current_test_position, position_passed)
        self.point_record_done = True
        self.set_pc_command_bit(PC_START_BIT, False)
        self.set_pc_command_bit(PC_POINT_DONE_BIT, True)
        self.append_process_log(
            "PROCESS",
            f"电机位置 {self.current_test_position} 的 {self.records_per_motor} 条记录完成："
            f"频谱结果={'OK' if position_passed else 'NG'}，DM3505.{self.current_test_position:02d}="
            f"{1 if position_passed else 0}，开始位清零，采集完成位置位",
        )
        self.lbl_status.setText(
            f"第 {self.current_test_position}/{self.positions_per_tray} 个电机采集完成，等待PLC进入下一点位"
        )
        self.save_automatic_checkpoint()

    def handle_acquisition_error(self, error):
        if self.acquisition_error_handled:
            return
        self.acquisition_error_handled = True
        reason = f"采集窗口作废: {error}"
        self.append_process_log("ERROR", reason)
        if self.auto_test_active:
            self.abort_automatic_test(reason, upper_fault=True)
        elif self.manual_acquisition_active:
            self.stop_manual_acquisition(reason)
        else:
            self.stop_data_stream()

    def handle_acquisition_finished(self):
        worker = self.sender()
        if worker is self.acquisition_worker:
            self.is_running = False
            self.acquisition_worker = None
        worker.deleteLater()

    def toggle_manual_acquisition(self):
        if self.manual_acquisition_active:
            self.stop_manual_acquisition("操作员停止")
        else:
            self.start_manual_acquisition()

    def start_manual_acquisition(self):
        self.append_process_log("COMMAND", "操作员点击手动采集")
        if self.auto_test_active:
            self.append_process_log("WARN", "手动采集被拒绝: PLC 自动测试正在运行")
            QMessageBox.warning(self, "无法启动", "PLC自动测试正在运行。")
            return
        if not self.probe_selected_acquisition_source(show_message=True):
            self.append_process_log(
                "WARN",
                f"手动采集被拒绝: {self.active_source_label()} 未就绪",
            )
            return

        self.manual_acquisition_active = True
        tray_id = self.current_tray_id()
        tray_text = tray_id or "未填写（产品SN留空）"
        self.append_process_log("PROCESS", f"手动采集启动条件检查通过 | 托盘编号: {tray_text}")
        self.data_buffer.fill(0.0)
        self.raw_data_buffer.fill(0.0)
        self.max_device_backlog = 0
        self.max_ljm_backlog = 0
        self.btn_manual_start.setText("停止采集")
        self.btn_start.setEnabled(False)
        self.set_test_controls_enabled(False)
        self.txt_tray_id.setEnabled(False)
        self.txt_start_time.setText(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        self.txt_complete_time.clear()
        self.lbl_status.setText("手动采集正在启动...")
        self.lbl_avg_status.setText(f"【{self.avg_time_sec}秒{self.record_mode_label()}】 按采样点周期记录")
        if not self.start_acquisition_worker(stop_after_record=False):
            self.manual_acquisition_active = False
            self.btn_manual_start.setText("手动采集")
            self.btn_start.setEnabled(True)
            self.set_test_controls_enabled(True)
            self.txt_tray_id.setEnabled(True)
            QMessageBox.warning(self, "启动失败", "采集线程无法启动。")

    def stop_manual_acquisition(self, reason):
        if self.is_running:
            self.stop_data_stream()
        self.manual_acquisition_active = False
        self.append_process_log("COMMAND", f"手动采集停止: {reason}")
        self.btn_manual_start.setText("手动采集")
        self.btn_start.setEnabled(True)
        self.set_test_controls_enabled(True)
        self.txt_tray_id.setEnabled(True)
        self.txt_complete_time.setText(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        self.lbl_status.setText(f"手动采集已停止: {reason}")
        self.lbl_avg_status.setText(f"【{self.avg_time_sec}秒{self.record_mode_label()}】 已停止")
        self.statusbar.showMessage(reason)

    def reset_automatic_records(self):
        self.tbl_records.setRowCount(0)
        self.update_record_count()
        self.completed_positions.clear()
        self.skipped_positions.clear()
        self.position_pass_results.clear()
        self.set_spectrum_ok_word(0, force=True)
        self.current_test_position = 0
        self.current_position_record_count = 0
        self.point_record_done = False
        self.cycle_completion_handled = False
        self.auto_test_paused = False
        self.auto_pause_reason = ""
        self.auto_resume_ready_since = None
        self.last_auto_save_path = None
        self.txt_qty.setText(str(self.positions_per_tray))
        self.txt_start_time.setText(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        self.txt_complete_time.clear()
        self.data_buffer.fill(0.0)
        self.raw_data_buffer.fill(0.0)
        self.plot_line.setData([], [])
        self.plot_line_fft.setData([], [])
        self.latest_fft_vals = None
        self.max_device_backlog = 0
        self.max_ljm_backlog = 0

    def toggle_automatic_test(self):
        if self.manual_acquisition_active:
            return
        if self.auto_test_active:
            self.stop_automatic_test("操作员退出自动化")
        else:
            self.start_automatic_test()

    def start_automatic_test(self):
        self.append_process_log("COMMAND", "操作员点击进入自动化")
        if not self.plc_enabled:
            self.append_process_log("WARN", "自动测试被拒绝: config.json 中 PLC 未启用")
            QMessageBox.warning(self, "PLC未启用", "请先在 config.json 中将 plc.enabled 设为 true。")
            return
        if not self.plc_connected:
            self.append_process_log("WARN", "自动测试被拒绝: PLC FINS 尚未连接")
            QMessageBox.warning(self, "PLC未连接", "PLC FINS 通信尚未建立。")
            return
        if not self.probe_selected_acquisition_source(show_message=True):
            self.append_process_log(
                "WARN",
                f"自动测试被拒绝: {self.active_source_label()} 未就绪",
            )
            return
        if self.plc_status_word & (1 << PLC_EMERGENCY_BIT):
            self.append_process_log("WARN", "自动测试被拒绝: PLC 急停未复位")
            QMessageBox.warning(self, "无法开始", "PLC 急停尚未复位。")
            return
        if self.plc_status_word & (1 << PLC_FAULT_BIT):
            self.append_process_log("WARN", "自动测试被拒绝: PLC 处于故障状态")
            QMessageBox.warning(self, "无法开始", "PLC 当前处于故障状态。")
            return
        if self.plc_all_complete:
            self.append_process_log("WARN", "自动测试被拒绝: 上一次全部完成信号尚未清除")
            QMessageBox.warning(self, "无法开始", "PLC 上一次“全部测试完成”信号尚未清除。")
            return

        self.apply_plc_tray_id(self.plc_current_tray_id, force=True)
        tray_id = self.current_tray_id()
        restored_checkpoint = self.restore_automatic_checkpoint(tray_id)
        if self.checkpoint_restore_failed:
            QMessageBox.warning(
                self,
                "断点恢复失败",
                f"托盘 {tray_id} 存在无法读取的断点，已阻止从1号重新覆盖。\n"
                "请先查看运行日志并处理断点文件。",
            )
            return
        if not restored_checkpoint:
            self.reset_automatic_records()
        else:
            self.set_spectrum_ok_word(self.spectrum_ok_word, force=True)
        tray_text = tray_id or "未填写（产品SN留空）"
        self.append_process_log(
            "PROCESS",
            f"已进入自动化待命: 每托盘 {self.positions_per_tray} 个电机，"
            f"每台 {self.records_per_motor} 条记录，"
            f"原始频谱自动保存={'开启' if self.chk_auto_export_spectrum.isChecked() else '关闭'}，"
            f"托盘编号: {tray_text}，"
            f"断点={'已恢复' if restored_checkpoint else '新建'}",
        )
        self.auto_test_active = True
        self.auto_test_paused = False
        self.auto_pause_reason = ""
        self.auto_resume_ready_since = None
        self.set_pc_command_bit(PC_FAULT_BIT, False)
        self.set_pc_command_bit(PC_POINT_DONE_BIT, self.point_record_done)
        self.set_pc_command_bit(PC_STOP_BIT, False)
        self.set_pc_command_bit(PC_START_BIT, False)
        self.btn_start.setText("退出自动化")
        self.btn_manual_start.setEnabled(False)
        self.set_test_controls_enabled(False)
        self.txt_tray_id.setEnabled(False)
        self.lbl_status.setText("自动化待命，等待PLC电机到位")
        self.lbl_avg_status.setText(self.automation_progress_text())
        self.lbl_plc_state.setText("PLC: 已连接 | 自动化待命")
        if restored_checkpoint:
            self.lbl_status.setText("已恢复同托盘断点，等待PLC状态对账")
            self.lbl_avg_status.setText(
                f"{self.automation_progress_text()}，"
                f"记录 {self.tbl_records.rowCount()}"
            )
        self.save_automatic_checkpoint()

    def stop_automatic_test(self, reason):
        if self.is_running:
            self.stop_data_stream()
        self.save_automatic_checkpoint()
        self.auto_test_active = False
        self.auto_test_paused = False
        self.auto_pause_reason = ""
        self.auto_resume_ready_since = None
        self.append_process_log("COMMAND", f"自动测试停止: {reason}")
        self.point_record_done = False
        self.set_pc_command_bit(PC_START_BIT, False)
        self.set_pc_command_bit(PC_STOP_BIT, True)
        self.set_pc_command_bit(PC_POINT_DONE_BIT, False)
        self.set_pc_command_bit(PC_FAULT_BIT, False)
        self.btn_start.setText("进入自动化")
        self.btn_manual_start.setEnabled(True)
        self.set_test_controls_enabled(True)
        self.txt_tray_id.setEnabled(True)
        self.txt_complete_time.setText(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        self.lbl_status.setText(f"测试已停止: {reason}")
        self.lbl_avg_status.setText(self.automation_progress_text())
        self.statusbar.showMessage(reason)

    def start_point_acquisition(self, position):
        position = int(position)
        if not 1 <= position <= self.positions_per_tray:
            self.pause_automatic_test(f"PLC 位置号无效: {position}")
            return
        if position in self.completed_positions:
            self.current_test_position = position
            self.point_record_done = True
            self.set_pc_command_bit(PC_START_BIT, False)
            self.set_pc_command_bit(PC_POINT_DONE_BIT, True)
            self.append_process_log(
                "RECOVERY",
                f"PLC仍停在已完成点位 {position}，重新保持采集完成位",
            )
            self.save_automatic_checkpoint()
            return
        if position in self.skipped_positions:
            self.pause_automatic_test(f"PLC 到达此前已登记为跑合跳过的位置 {position}")
            return

        if (
            self.current_test_position
            and self.current_test_position != position
            and self.current_test_position not in self.completed_positions
            and self.current_position_record_count > 0
        ):
            self.pause_automatic_test(
                f"电机位置 {self.current_test_position} 尚有未完成记录，PLC已移动到 {position}"
            )
            return

        expected_position = self.next_incomplete_position()
        if position > expected_position:
            self.mark_positions_before_as_skipped(
                position,
                f"PLC首个/下一个允许采集位置为 {position}",
            )
            expected_position = self.next_incomplete_position()
        if position != expected_position:
            self.pause_automatic_test(
                f"PLC 位置顺序异常，期望 {expected_position}，实际 {position}",
            )
            return

        resume_existing_position = (
            self.current_test_position == position
            and position not in self.completed_positions
        )
        self.current_test_position = position
        if not resume_existing_position:
            self.current_position_record_count = 0
        self.txt_tray_id.setEnabled(False)
        tray_id, product_sn = self.record_identity(position)
        identity_text = f"托盘 {tray_id}" if tray_id else "未填写托盘"
        if product_sn:
            identity_text += f"，产品SN {product_sn}"
        else:
            identity_text += "，产品SN留空"
        acquisition_action = "恢复" if resume_existing_position else "启动"
        self.append_process_log(
            "PROCESS",
            f"PLC 点位 {position}/{self.positions_per_tray} 已到位，"
            f"{acquisition_action}采集，已有 "
            f"{self.current_position_record_count}/{self.records_per_motor} 条记录 | {identity_text}",
        )
        self.set_pc_command_bit(PC_STOP_BIT, False)
        self.set_pc_command_bit(PC_POINT_DONE_BIT, False)
        self.set_pc_command_bit(PC_START_BIT, True)
        self.append_process_log("COMMAND", f"电机位置 {position} 开始采集：开始位置位")
        self.data_buffer.fill(0.0)
        self.raw_data_buffer.fill(0.0)
        self.lbl_status.setText(f"正在启动第 {position}/{self.positions_per_tray} 个电机的采集窗口")
        self.lbl_avg_status.setText(f"【{self.avg_time_sec}秒{self.record_mode_label()}】 按采样点采集")
        if not self.start_acquisition_worker(stop_after_record=False):
            self.abort_automatic_test("采集线程无法启动", upper_fault=True)

    def stop_data_stream(self):
        worker = self.acquisition_worker
        if worker is not None:
            worker.requestInterruption()
            if worker.isRunning():
                worker.wait(5000)
            if self.acquisition_worker is worker:
                self.acquisition_worker = None
        self.is_running = False

    def finish_automatic_test(self):
        self.cycle_completion_handled = True
        if self.current_position_record_count and self.current_test_position not in self.completed_positions:
            self.abort_automatic_test(
                f"PLC已发送全部完成，但电机位置 {self.current_test_position} 仅记录 "
                f"{self.current_position_record_count}/{self.records_per_motor} 条",
                upper_fault=True,
            )
            return

        remaining_positions = (
            set(range(1, self.positions_per_tray + 1))
            - self.completed_positions
            - self.skipped_positions
        )
        self.mark_skipped_positions(
            remaining_positions,
            "PLC发送10个电机全部测试完成信号",
        )
        completed_count = len(self.completed_positions)
        skipped_count = len(self.skipped_positions)
        expected_record_count = completed_count * self.records_per_motor
        actual_record_count = self.tbl_records.rowCount()
        if (
            completed_count + skipped_count != self.positions_per_tray
            or actual_record_count != expected_record_count
        ):
            self.abort_automatic_test(
                f"PLC已发送全部完成，但上位机频谱实测 {completed_count} 个、"
                f"跑合跳过 {skipped_count} 个、"
                f"{actual_record_count}/{expected_record_count} 条记录",
                upper_fault=True,
            )
            return

        self.txt_complete_time.setText(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        self.lbl_status.setText(
            f"整托处理完成：频谱实测 {completed_count} 个，跑合跳过 {skipped_count} 个"
        )
        self.lbl_avg_status.setText(f"{self.automation_progress_text()}，正在保存")
        path = self.get_automatic_record_path()
        saved, error = self.write_records_csv(path)
        if not saved:
            self.abort_automatic_test(f"自动保存失败: {error}", upper_fault=True)
            return

        self.last_auto_save_path = path
        completed_tray_id = self.current_tray_id()
        self.append_process_log(
            "PROCESS",
            f"整托处理完成：频谱实测 {completed_count} 个，跑合跳过 {skipped_count} 个，"
            f"记录已保存: {path}",
        )
        self.set_pc_command_bit(PC_START_BIT, False)
        self.set_pc_command_bit(PC_STOP_BIT, False)
        self.set_pc_command_bit(PC_POINT_DONE_BIT, False)
        self.set_pc_command_bit(PC_FAULT_BIT, False)
        self.btn_start.setText("退出自动化")
        self.btn_manual_start.setEnabled(False)
        self.set_test_controls_enabled(False)
        self.txt_tray_id.setEnabled(False)
        self.lbl_status.setText(
            f"整托处理完成（实测{completed_count}/跳过{skipped_count}），等待PLC复位全部完成信号"
        )
        self.lbl_avg_status.setText(self.automation_progress_text())
        self.lbl_plc_state.setText("PLC: 整托完成 | 等待全部完成信号复位")
        self.statusbar.showMessage(f"自动测试记录已保存: {path}")
        self.clear_automatic_checkpoint(completed_tray_id)

    def closeEvent(self, event):
        if self.mes_sync_timer is not None:
            self.mes_sync_timer.stop()
        if self.is_running:
            self.stop_data_stream()
        if self.auto_test_active:
            self.save_automatic_checkpoint()
        if self.tray_mapping_api is not None:
            self.tray_mapping_api.stop()
        if self.plc_worker is not None and self.plc_thread is not None and self.plc_thread.isRunning():
            self.plc_shutdown_requested.emit(1 << PC_STOP_BIT)
            self.plc_thread.wait(3500)
        self.close_labjack()
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = VibrationTester()
    window.resize(1000, 800)
    window.show()
    sys.exit(app.exec())
