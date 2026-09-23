# 检尺材积计算服务

单接口 HTTP 服务，使用 Python 3.14 标准库 `http.server` 直接启动，无第三方依赖。

- **接口**：`POST /api/v1/log-volume/calc`
- **请求体**：检尺记录数组（JSON），每条记录：
  - `diameter_cm`（number，必填）：实测检尺径，单位 cm，范围 (0, 500]
  - `length_m`（number，必填）：实测检尺长，单位 m，范围 (0, 60]
  - `count`（integer，必填）：根数，正整数

## 检尺规则

1. **进级**（按厘米计算）
   - 径：以 **2 cm** 为增进单位，**不足舍去**（如 13.9 cm → 12 cm）
   - 长：以 **20 cm** 为增进单位，**不足进位**（如 4.21 m → 4.4 m）
2. **不检判定**：进级后 `d < 6 cm` 或 `l < 1.0 m`，该条跳过。
3. **材积计算**
   - 单根材积：`V = 0.7854 × d² × l × 1e-4`（m³，d 为进级后厘米径，l 为进级后米长）
   - 单根材积先**四舍五入到 0.001 m³**，再乘根数得**条合计**
   - **批总量**为各条合计直接相加，不再舍入
4. 根数非正或尺寸越界的记录返回其下标与原因并跳过，不影响其余记录。

## 启动

需要 Python 3.14+。

```bash
python3.14 server.py
```

默认监听 `0.0.0.0:8000`；也可用环境变量或参数指定端口：

```bash
LOG_VOLUME_PORT=9000 python3.14 server.py   # 或: python3.14 server.py 9000
```

## 示例请求

```bash
curl -s -X POST http://localhost:8000/api/v1/log-volume/calc \
  -H 'Content-Type: application/json' \
  -d '[
    {"diameter_cm": 12.6, "length_m": 4.21, "count": 10},
    {"diameter_cm": 20.0, "length_m": 5.0,  "count": 3},
    {"diameter_cm": 5.0,  "length_m": 2.0,  "count": 2},
    {"diameter_cm": 30.0, "length_m": 0.8,  "count": 1},
    {"diameter_cm": 18.0, "length_m": 3.0,  "count": 0}
  ]'
```

示例响应：

```json
{
  "batch_total_m3": 0.971,
  "results": [
    {"index": 0, "d_cm": 12, "l_m": 4.4, "count": 10, "volume_per_log_m3": 0.05, "line_total_m3": 0.5},
    {"index": 1, "d_cm": 20, "l_m": 5.0, "count": 3, "volume_per_log_m3": 0.157, "line_total_m3": 0.471}
  ],
  "skipped": [
    {"index": 2, "reason": "进级后检尺径 4 cm 小于 6 cm，判为不检"},
    {"index": 3, "reason": "进级后检尺长 0.8 m 小于 1.0 m，判为不检"},
    {"index": 4, "reason": "根数非正（count=0）"}
  ]
}
```

> 说明：`results` 中字段为进级后的 `d_cm`、`l_m`、单根材积 `volume_per_log_m3`、条合计 `line_total_m3`，`skipped` 中为被跳过记录的原始下标 `index` 与原因。

## 错误响应

- `400`：请求体为空 / JSON 非法 / 顶层不是数组
- `404`：路径不存在
- `405`：使用了非 POST 方法
- `413`：请求体超过 10 MiB
