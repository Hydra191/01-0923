# 原木检尺材积计算服务（log-volume）

单接口 HTTP 服务，仅使用 Python 3.14 标准库 `http.server`，无任何第三方依赖。

## 接口

`POST /api/v1/log-volume/calc`

请求体为检尺记录数组（也支持 `{"records": [...]}` 包裹），每条记录：

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `diameter_cm` | number | 实测检尺径（cm） |
| `length_m` | number | 实测检尺长（m） |
| `count` | 正整数 | 根数 |

### 计算规则

1. **径进级**：以 2 cm 为增进单位，不足 2 cm 的部分**舍去**。
   例：13.9 cm → d = 12 cm；14.0 cm → d = 14 cm。
2. **长进级**：以 20 cm（0.2 m）为增进单位，不足 20 cm 的部分**进位**。
   例：2.01 m → l = 2.2 m；2.20 m → l = 2.2 m。
3. 进级后 **d < 6 cm 或 l < 1.0 m** 判为不检尺，该条跳过。
4. 单根材积：`V = 0.7854 × d² × l × 1e-4`（m³），先**四舍五入到 0.001 m³**
   （ROUND_HALF_UP，0.0005 进为 0.001），再乘根数得到条合计。
5. 批总量 = 各条合计直接相加，**不再舍入**。
6. 根数非正、根数非整数或尺寸非正（越界）的记录返回其下标与原因并跳过，
   不影响其余记录。

### 响应

```json
{
  "results": [
    {
      "index": 0,
      "d_cm": 12,
      "l_m": 2.2,
      "volume_per_piece_m3": 0.025,
      "line_total_m3": 0.075
    }
  ],
  "errors": [
    { "index": 3, "reason": "根数非正：count 必须大于 0（实际 0）" }
  ],
  "batch_total_m3": 0.075
}
```

- `results[].index`：记录在请求数组中的原始下标。
- `errors`：被跳过记录的下标与原因（不检尺 / 根数非正 / 尺寸越界 / 字段非法）。

## 启动

单条命令（Python 3.14，默认监听 `0.0.0.0:8000`）：

```bash
python3.14 server.py
```

自定义端口（如 8080）：

```bash
python3.14 server.py 8080
```

也可用环境变量 `HOST` / `PORT` 指定监听地址与端口。

## 示例请求

```bash
curl -s -X POST http://localhost:8000/api/v1/log-volume/calc \
  -H 'Content-Type: application/json' \
  -d '[
    {"diameter_cm": 13.5, "length_m": 2.1,  "count": 3},
    {"diameter_cm": 10,   "length_m": 1.0,  "count": 2},
    {"diameter_cm": 5,    "length_m": 2.0,  "count": 1},
    {"diameter_cm": 12,   "length_m": 2.0,  "count": 0},
    {"diameter_cm": 7,    "length_m": 0.9,  "count": 1}
  ]'
```

示例响应：

```json
{
  "results": [
    {"index": 0, "d_cm": 12, "l_m": 2.2, "volume_per_piece_m3": 0.025, "line_total_m3": 0.075},
    {"index": 1, "d_cm": 10, "l_m": 1.0, "volume_per_piece_m3": 0.008, "line_total_m3": 0.016},
    {"index": 4, "d_cm": 6,  "l_m": 1.0, "volume_per_piece_m3": 0.003, "line_total_m3": 0.003}
  ],
  "errors": [
    {"index": 2, "reason": "判为不检尺：进级后 d=4 cm 小于 6 cm"},
    {"index": 3, "reason": "根数非正：count 必须大于 0（实际 0）"}
  ],
  "batch_total_m3": 0.094
}
```
