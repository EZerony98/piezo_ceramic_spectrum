"""NI-9234 single-channel IEPE accelerometer acquisition.

The hardware settings mirror the NI path used by the dynamic-balancing
application, while keeping nidaqmx an optional Windows-only dependency.
"""

from typing import Iterable, Tuple

import numpy as np


def select_ni9234_module(configured: str, devices: Iterable[Tuple[str, str]]) -> str:
    """Resolve a configured module or automatically select the only NI-9234."""
    inventory = [
        (str(name).strip(), str(product).strip())
        for name, product in devices
        if str(name).strip()
    ]
    by_lower_name = {name.lower(): name for name, _product in inventory}
    requested = str(configured or "").strip()
    if requested and requested.lower() in by_lower_name:
        return by_lower_name[requested.lower()]

    candidates = [
        name
        for name, product in inventory
        if "9234" in product.upper() or "9234" in name.upper()
    ]
    if len(candidates) == 1:
        return candidates[0]

    discovered = "、".join(
        f"{name} ({product or '未知型号'})" for name, product in inventory
    ) or "未发现任何 NI 设备"
    if len(candidates) > 1:
        raise RuntimeError(
            f"发现多个 NI-9234（{'、'.join(candidates)}），请在 config.json 中指定 ni9234.module"
        )
    raise RuntimeError(
        f"找不到配置的 NI-9234 模块 {requested or '<空>'}；NI MAX 当前设备：{discovered}"
    )


def discover_ni9234_module(config: dict) -> str:
    """Read NI MAX inventory without reserving an acquisition channel."""
    try:
        from nidaqmx.system import System
    except Exception as exc:  # pragma: no cover - Windows target dependency
        raise RuntimeError(
            "Python 无法加载 nidaqmx。请安装 NI-DAQmx 驱动，并在当前 Python 环境执行 "
            "pip install nidaqmx"
        ) from exc

    try:
        devices = [
            (device.name, getattr(device, "product_type", ""))
            for device in System.local().devices
        ]
    except Exception as exc:
        raise RuntimeError(
            f"无法读取 NI MAX 设备列表，请确认 NI-DAQmx Runtime 已安装且服务正常：{exc}"
        ) from exc
    return select_ni9234_module(config.get("module", "cDAQ1Mod1"), devices)


class Ni9234Source:
    """Open and stream one IEPE accelerometer channel in acceleration-g units."""

    def __init__(self, config: dict):
        self.config = dict(config or {})
        self.task = None
        self.module_name = ""
        self.scan_rate = float(self.config.get("scan_rate", 51_200.0))
        self.scans_per_read = max(int(self.config.get("scans_per_read", 1500)), 1)

    def open(self) -> dict:
        try:
            import nidaqmx
            from nidaqmx.constants import (
                AccelSensitivityUnits,
                AccelUnits,
                AcquisitionType,
                Coupling,
                ExcitationSource,
            )
        except Exception as exc:  # pragma: no cover - Windows target dependency
            raise RuntimeError(
                "已选择 NI-9234 加速度传感器，但 Python 无法加载 nidaqmx。"
                "请安装 NI-DAQmx 驱动，并在当前 Python 环境执行 pip install nidaqmx"
            ) from exc

        requested_rate = float(self.config.get("scan_rate", 51_200.0))
        if not 1_652 <= requested_rate <= 51_200:
            raise RuntimeError("NI-9234 扫描率必须在 1,652 到 51,200 S/s/ch 之间")

        sensitivity = float(self.config.get("sensitivity_mv_per_g", 10.0))
        if not np.isfinite(sensitivity) or sensitivity <= 0:
            raise RuntimeError("NI 加速度传感器灵敏度必须大于 0 mV/g")

        module = discover_ni9234_module(self.config)
        channel_name = str(self.config.get("channel", "ai0")).strip() or "ai0"
        physical_channel = (
            channel_name if "/" in channel_name else f"{module}/{channel_name}"
        )
        current_a = float(self.config.get("iepe_current_ma", 2.0)) / 1000.0
        min_g = float(self.config.get("min_g", -500.0))
        max_g = float(self.config.get("max_g", 500.0))
        if min_g >= max_g:
            raise RuntimeError("NI 加速度量程 min_g 必须小于 max_g")

        task = nidaqmx.Task()
        try:
            channel = task.ai_channels.add_ai_accel_chan(
                physical_channel,
                name_to_assign_to_channel="acceleration",
                min_val=min_g,
                max_val=max_g,
                units=AccelUnits.G,
                sensitivity=sensitivity,
                sensitivity_units=AccelSensitivityUnits.MILLIVOLTS_PER_G,
                current_excit_source=ExcitationSource.INTERNAL,
                current_excit_val=current_a,
            )
            channel.ai_coupling = Coupling.AC
            task.timing.cfg_samp_clk_timing(
                rate=requested_rate,
                sample_mode=AcquisitionType.CONTINUOUS,
                samps_per_chan=self.scans_per_read * 4,
            )
            self.scan_rate = float(task.timing.samp_clk_rate)
            task.start()
        except Exception as exc:
            task.close()
            raise RuntimeError(
                f"NI-9234 {physical_channel} 启动失败：{exc}。请在 NI MAX 中确认模块自检通过、"
                "通道未被其他程序占用，且 IEPE 激励可用"
            ) from exc

        self.task = task
        self.module_name = module
        return {
            "module": module,
            "channel": physical_channel,
            "scan_rate": self.scan_rate,
            "sensitivity_mv_per_g": sensitivity,
        }

    def read(self) -> np.ndarray:
        if self.task is None:
            raise RuntimeError("NI-9234 尚未启动")
        timeout = max(2.0, self.scans_per_read / self.scan_rate * 4.0)
        raw = self.task.read(
            number_of_samples_per_channel=self.scans_per_read,
            timeout=timeout,
        )
        return np.asarray(raw, dtype=float).reshape(-1)

    def close(self) -> None:
        if self.task is not None:
            try:
                self.task.stop()
            except Exception:
                pass
            try:
                self.task.close()
            except Exception:
                pass
        self.task = None

