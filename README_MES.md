# 频谱上位机本地数据库与 MES 同步

频谱测试结果除 CSV 导出外，会自动保存到本机
`data/traceability.db` 的 `spectrum_results` 表，并写入 `upload_outbox`。
托盘号、坑位和产品 SN 来自跑合电脑同步的托盘映射；每个坑位重复测试时会
更新该坑位当前结果并重新进入待上传状态。

在 `config.json` 的 `traceability.mes` 中配置 MES：

```json
{
  "enabled": true,
  "base_url": "http://192.168.250.2:8000",
  "upload_path": "/api/test-records",
  "heartbeat_path": "/api/stations/heartbeat",
  "sync_interval_seconds": 10
}
```

MES 断网时测试照常进行，记录保持 `pending`；网络恢复后后台自动补传，成功后
`spectrum_results.upload_status` 变为 `uploaded`。MES 电脑需要监听
`0.0.0.0:8000`，并允许局域网设备访问 TCP 8000。
