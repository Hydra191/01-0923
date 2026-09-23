#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""原木检尺材积计算服务。

仅依赖 Python 标准库（http.server），提供单一接口：
    POST /api/v1/log-volume/calc

规则：
  - 检尺径进级：以 2 cm 为增进单位，不足 2 cm 舍去。
  - 检尺长进级：以 20 cm（0.2 m）为增进单位，不足 20 cm 进位。
  - 进级后 d < 6 cm 或 l < 1.0 m 判为不检尺，该条跳过。
  - 单根材积 V = 0.7854 * d^2 * l * 1e-4（m³），四舍五入到 0.001 m³
    后再乘根数得到条合计；批总量为各条合计之和，不再舍入。
"""

import json
import math
import os
import sys
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROUTE = "/api/v1/log-volume/calc"
MAX_BODY_BYTES = 10 * 1024 * 1024

VOLUME_FACTOR = Decimal("0.7854")
SCALE = Decimal("1E-4")
VOLUME_QUANTUM = Decimal("0.001")
MIN_D = 6            # cm
MIN_L = Decimal("1.0")  # m


def _is_finite_number(value):
    """JSON 数字（bool 不算）且有限。"""
    if isinstance(value, bool):
        return False
    if not isinstance(value, (int, float)):
        return False
    return math.isfinite(value)


def _grade_diameter(raw):
    """径进级：2 cm 增进，不足舍去，返回进级后径级 d（整数 cm）。"""
    steps = (Decimal(str(raw)) / 2).to_integral_value(rounding=ROUND_FLOOR)
    return int(steps) * 2


def _grade_length(raw):
    """长进级：20 cm 增进，不足进位，返回进级后检尺长 l（Decimal，单位 m）。"""
    steps = (Decimal(str(raw)) * 100 / 20).to_integral_value(
        rounding=ROUND_CEILING
    )
    return Decimal(int(steps) * 20) / 100


def calculate(records):
    """对检尺记录数组逐条计算。

    返回 (results, errors, batch_total)：
      results: 成功记录的计算结果；
      errors:  被跳过记录的下标与原因；
      batch_total: Decimal 形式的批总量。
    """
    results = []
    errors = []
    batch_total = Decimal("0")

    for index, record in enumerate(records):
        if not isinstance(record, dict):
            errors.append({"index": index, "reason": "记录必须是 JSON 对象"})
            continue

        diameter = record.get("diameter_cm")
        length = record.get("length_m")
        count = record.get("count")

        if not _is_finite_number(diameter):
            errors.append(
                {"index": index, "reason": "diameter_cm 缺失或不是有限数值"}
            )
            continue
        if not _is_finite_number(length):
            errors.append(
                {"index": index, "reason": "length_m 缺失或不是有限数值"}
            )
            continue
        if not _is_finite_number(count):
            errors.append(
                {"index": index, "reason": "count 缺失或不是有限数值"}
            )
            continue

        if count <= 0:
            errors.append(
                {
                    "index": index,
                    "reason": "根数非正：count 必须大于 0（实际 %s）" % count,
                }
            )
            continue
        if int(count) != count:
            errors.append(
                {
                    "index": index,
                    "reason": "根数不是正整数：count 必须为整数（实际 %s）" % count,
                }
            )
            continue
        count = int(count)

        if diameter <= 0:
            errors.append(
                {
                    "index": index,
                    "reason": "尺寸越界：diameter_cm 必须大于 0（实际 %s）"
                    % diameter,
                }
            )
            continue
        if length <= 0:
            errors.append(
                {
                    "index": index,
                    "reason": "尺寸越界：length_m 必须大于 0（实际 %s）" % length,
                }
            )
            continue

        d = _grade_diameter(diameter)
        l = _grade_length(length)

        if d < MIN_D or l < MIN_L:
            reasons = []
            if d < MIN_D:
                reasons.append("进级后 d=%d cm 小于 6 cm" % d)
            if l < MIN_L:
                reasons.append("进级后 l=%s m 小于 1.0 m" % l)
            errors.append(
                {"index": index, "reason": "判为不检尺：" + "；".join(reasons)}
            )
            continue

        volume = VOLUME_FACTOR * d * d * l * SCALE
        volume_rounded = volume.quantize(VOLUME_QUANTUM, rounding=ROUND_HALF_UP)
        line_total = volume_rounded * count
        batch_total += line_total

        results.append(
            {
                "index": index,
                "d_cm": d,
                "l_m": float(l),
                "volume_per_piece_m3": float(volume_rounded),
                "line_total_m3": float(line_total),
            }
        )

    return results, errors, batch_total


class LogVolumeHandler(BaseHTTPRequestHandler):
    server_version = "LogVolumeHTTP/1.0"

    def _send_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _path_only(self):
        return self.path.split("?", 1)[0]

    def do_POST(self):
        if self._path_only() != ROUTE:
            self._send_json(404, {"error": "接口不存在", "path": self._path_only()})
            return

        length_header = self.headers.get("Content-Length")
        try:
            content_length = int(length_header)
        except (TypeError, ValueError):
            self._send_json(400, {"error": "缺少或非法的 Content-Length 请求头"})
            return
        if content_length < 0:
            self._send_json(400, {"error": "非法的 Content-Length 请求头"})
            return
        if content_length > MAX_BODY_BYTES:
            self._send_json(413, {"error": "请求体超过 10 MiB 上限"})
            return

        raw = self.rfile.read(content_length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            self._send_json(400, {"error": "请求体不是合法 JSON：%s" % exc})
            return

        if isinstance(data, list):
            records = data
        elif isinstance(data, dict) and isinstance(data.get("records"), list):
            records = data["records"]
        else:
            self._send_json(
                400,
                {"error": "请求体必须是检尺记录数组，或含 records 数组的对象"},
            )
            return

        results, errors, batch_total = calculate(records)
        self._send_json(
            200,
            {
                "results": results,
                "errors": errors,
                "batch_total_m3": float(batch_total),
            },
        )

    def do_GET(self):
        if self._path_only() == ROUTE:
            self._send_json(
                405, {"error": "方法不允许，该接口仅支持 POST"}
            )
        else:
            self._send_json(404, {"error": "接口不存在", "path": self._path_only()})

    def log_message(self, fmt, *args):
        sys.stderr.write(
            "[%s] %s\n" % (self.log_date_time_string(), fmt % args)
        )


def main():
    host = os.environ.get("HOST", "0.0.0.0")
    if len(sys.argv) > 1:
        port = int(sys.argv[1])
    else:
        port = int(os.environ.get("PORT", "8000"))

    server = ThreadingHTTPServer((host, port), LogVolumeHandler)
    server.daemon_threads = True
    print(
        "log-volume server listening on http://%s:%d%s" % (host, port, ROUTE),
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nshutting down ...", flush=True)
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
