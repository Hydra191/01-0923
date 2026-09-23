#!/usr/bin/env python3
"""检尺材积计算服务（Python 3.14，仅标准库 http.server）。

接口: POST /api/v1/log-volume/calc
请求体: 检尺记录数组，每条含 diameter_cm / length_m / count。
"""

import json
import math
import os
import sys
from decimal import Decimal, ROUND_HALF_UP
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

API_PATH = "/api/v1/log-volume/calc"
MAX_BODY_BYTES = 10 * 1024 * 1024

# 原始尺寸合法域（进级前的越界判定）
DIAMETER_MAX_CM = 500.0
LENGTH_MAX_M = 60.0

# 进级后“不检”门槛
MIN_D_CM = 6
MIN_L_CM = 100  # 1.0 m

_EPS = 1e-9  # 抵消浮点表示误差（如 0.29*100 = 28.99999...）
_FACTOR = Decimal("0.7854")
_MILLI = Decimal("0.001")
_ONE_MILLION = Decimal("1000000")


def _is_finite_number(value) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _grade_diameter(diameter_cm: float) -> int:
    """径以 2 cm 为增进单位，不足舍去（向下取整到偶数厘米）。"""
    return int(math.floor(diameter_cm / 2.0 + _EPS)) * 2


def _grade_length_cm(length_m: float) -> int:
    """长以 20 cm 为增进单位，不足进位（向上取整到 20 cm 的整数倍）。"""
    raw_cm = length_m * 100.0
    steps = math.ceil(raw_cm / 20.0 - _EPS)
    return steps * 20


def calc_log_volumes(records: list) -> dict:
    """对检尺记录数组逐条进级、判不检并计算材积。

    非法/不检记录只进入 skipped（附下标与原因），不影响其余记录与批总量。
    """
    results = []
    skipped = []
    batch_total = Decimal("0")

    for index, record in enumerate(records):
        if not isinstance(record, dict):
            skipped.append({"index": index, "reason": "记录必须为对象"})
            continue

        diameter_cm = record.get("diameter_cm")
        length_m = record.get("length_m")
        count = record.get("count")

        if not _is_finite_number(diameter_cm):
            skipped.append({"index": index, "reason": "diameter_cm 必须为有限数值"})
            continue
        if not 0.0 < diameter_cm <= DIAMETER_MAX_CM:
            skipped.append({
                "index": index,
                "reason": f"diameter_cm={diameter_cm} 尺寸越界，允许范围 (0, 500] cm",
            })
            continue

        if not _is_finite_number(length_m):
            skipped.append({"index": index, "reason": "length_m 必须为有限数值"})
            continue
        if not 0.0 < length_m <= LENGTH_MAX_M:
            skipped.append({
                "index": index,
                "reason": f"length_m={length_m} 尺寸越界，允许范围 (0, 60] m",
            })
            continue

        # 根数：正整数（2.0 这类整数值浮点接受）
        if isinstance(count, bool) or not isinstance(count, (int, float)):
            skipped.append({"index": index, "reason": "count 必须为正整数"})
            continue
        if isinstance(count, float) and not math.isfinite(count):
            skipped.append({"index": index, "reason": "count 必须为正整数"})
            continue
        if count <= 0:
            skipped.append({"index": index, "reason": f"根数非正（count={count}）"})
            continue
        if float(count) != int(count):
            skipped.append({"index": index, "reason": f"根数须为正整数（count={count}）"})
            continue
        count_int = int(count)

        # 进级
        d_cm = _grade_diameter(diameter_cm)
        l_cm = _grade_length_cm(length_m)

        # 进级后判不检
        not_graded = []
        if d_cm < MIN_D_CM:
            not_graded.append(f"进级后检尺径 {d_cm} cm 小于 {MIN_D_CM} cm")
        if l_cm < MIN_L_CM:
            l_text = format(Decimal(l_cm) / Decimal(100), "f")
            not_graded.append(f"进级后检尺长 {l_text} m 小于 1.0 m")
        if not_graded:
            skipped.append({
                "index": index,
                "reason": "；".join(not_graded) + "，判为不检",
            })
            continue

        # V = 0.7854 d^2 l * 1e-4；l 以厘米计为 l_cm/100，故系数合计 1e-6
        volume = _FACTOR * d_cm * d_cm * l_cm / _ONE_MILLION
        volume_round = volume.quantize(_MILLI, rounding=ROUND_HALF_UP)
        line_total = volume_round * count_int  # 条合计：先舍入再乘根数
        batch_total += line_total             # 批总量：各条合计相加，不再舍入

        results.append({
            "index": index,
            "d_cm": d_cm,
            "l_m": float(Decimal(l_cm) / Decimal(100)),
            "count": count_int,
            "volume_per_log_m3": float(volume_round),
            "line_total_m3": float(line_total),
        })

    return {
        "batch_total_m3": float(batch_total),
        "results": results,
        "skipped": skipped,
    }


class LogVolumeHandler(BaseHTTPRequestHandler):
    server_version = "LogVolume/1.0"

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _method_not_allowed(self) -> None:
        self.send_response(405)
        self.send_header("Allow", "POST")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        self._method_not_allowed()

    def do_PUT(self):
        self._method_not_allowed()

    def do_DELETE(self):
        self._method_not_allowed()

    def do_PATCH(self):
        self._method_not_allowed()

    def do_POST(self) -> None:
        if urlsplit(self.path).path != API_PATH:
            self._send_json(404, {"error": f"未找到路径: {self.path}"})
            return

        try:
            content_length = int(self.headers.get("Content-Length", 0))
        except (TypeError, ValueError):
            self._send_json(400, {"error": "Content-Length 头无效"})
            return

        if content_length <= 0:
            self._send_json(400, {"error": "请求体为空，应为检尺记录数组"})
            return
        if content_length > MAX_BODY_BYTES:
            self._send_json(413, {"error": "请求体超过 10 MiB 上限"})
            return

        raw = self.rfile.read(content_length)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            self._send_json(400, {"error": f"JSON 解析失败: {exc}"})
            return

        if not isinstance(payload, list):
            self._send_json(400, {"error": "请求体必须为检尺记录数组"})
            return

        self._send_json(200, calc_log_volumes(payload))


def main() -> None:
    if len(sys.argv) > 1:
        port = int(sys.argv[1])
    else:
        port = int(os.environ.get("LOG_VOLUME_PORT", "8000"))
    server = ThreadingHTTPServer(("0.0.0.0", port), LogVolumeHandler)
    print(f"log-volume service listening on http://0.0.0.0:{port}{API_PATH}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
