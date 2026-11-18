# 压电陶瓷频谱分析系统

基于 PySide6、NumPy 和 pyqtgraph 的频谱检测上位机，支持两种可切换的采集模式：

- LabJack 模拟输入频谱采集
- NI-9234 IEPE 加速度传感器采集

程序共用同一套实时波形、FFT、频率点判定、自动化、追溯和导出流程。NI 模式参考动平衡设备配置，默认使用 `cDAQ1Mod1/ai0`、25.6 kS/s、2.0 mA IEPE 激励和 10 mV/g 灵敏度。

## 运行

```bash
python -m pip install -r requirements.txt
cp config.example.json config.json
python main.py
```

Windows 使用 NI 模式前，需要安装 NI-DAQmx，并在 NI MAX 中确认 NI-9234 自检通过。LabJack 模式需要安装 LabJack LJM 驱动。

## 配置

界面顶部可以选择“LabJack 频谱输入”或“NI-9234 加速度传感器”。切换前必须停止采集并退出自动化。

现场 `config.json`、数据库、检测结果和导出文件不会提交到 Git。首次使用时复制 `config.example.json`，再填写现场 PLC、MES、传感器灵敏度及产品阈值。详细说明见 `config参数说明.txt`。

两种传感器的幅值响应不同，正式使用 NI 模式前应使用确认过的 OK/NG 产品重新标定判定阈值。

## 测试

```bash
python -m unittest discover -s tests
python -m py_compile main.py ni9234_source.py
```
