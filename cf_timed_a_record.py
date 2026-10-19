#!/usr/bin/env python3
"""按中国时间为每条配置记录独立创建、删除 Cloudflare DNS 记录。"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, time as clock_time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import config

API_ROOT = "https://api.cloudflare.com/client/v4"
CHINA_TIME = ZoneInfo("Asia/Shanghai")
SUPPORTED_TYPES = {"A", "CNAME"}


def parse_clock(value: str, label: str) -> clock_time:
    for format_string in ("%H:%M", "%H:%M:%S"):
        try:
            return datetime.strptime(value, format_string).time()
        except ValueError:
            pass
    raise RuntimeError(f"{label} 必须为 HH:MM 或 HH:MM:SS，例如 20:00。")


def qualified_name(value: str) -> str:
    name, zone = value.strip().rstrip("."), config.ZONE_NAME.strip().rstrip(".")
    if name == "@":
        return zone
    return name if name.endswith(f".{zone}") else f"{name}.{zone}"


def fingerprint(record: dict[str, Any]) -> str:
    return json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def plan_records() -> list[dict[str, Any]]:
    raw_records = getattr(config, "RECORDS", None)
    if not isinstance(raw_records, list) or not raw_records:
        raise RuntimeError("config.py 中的 RECORDS 必须是至少包含一条记录的列表。")
    result: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_records, start=1):
        if not isinstance(raw, dict):
            raise RuntimeError(f"RECORDS 第 {index} 项必须是字典。")
        record_type = str(raw.get("type", "")).upper()
        if record_type not in SUPPORTED_TYPES:
            raise RuntimeError(f"RECORDS 第 {index} 项 type 只能是 A 或 CNAME。")
        if not str(raw.get("name", "")).strip() or not str(raw.get("content", "")).strip():
            raise RuntimeError(f"RECORDS 第 {index} 项缺少 name 或 content。")
        ttl, proxied = raw.get("ttl", 1), raw.get("proxied", False)
        if not isinstance(ttl, int) or (ttl != 1 and ttl < 60):
            raise RuntimeError(f"RECORDS 第 {index} 项 ttl 必须是 1 或至少 60。")
        if not isinstance(proxied, bool):
            raise RuntimeError(f"RECORDS 第 {index} 项 proxied 必须是 True 或 False。")
        start_clock = parse_clock(str(raw.get("start_time", "")), f"RECORDS 第 {index} 项 start_time")
        end_clock = parse_clock(str(raw.get("end_time", "")), f"RECORDS 第 {index} 项 end_time")
        result.append({
            "type": record_type, "name": qualified_name(str(raw["name"])), "content": str(raw["content"]).strip(),
            "ttl": ttl, "proxied": proxied, "start_time": start_clock.strftime("%H:%M:%S"), "end_time": end_clock.strftime("%H:%M:%S"),
        })
    keys = [fingerprint(item) for item in result]
    if len(keys) != len(set(keys)):
        raise RuntimeError("RECORDS 不能包含完全相同的重复项。")
    return result


def validate_config() -> list[dict[str, Any]]:
    for field in ("CF_EMAIL", "CF_GLOBAL_API_KEY", "ZONE_NAME"):
        value = str(getattr(config, field, "")).strip()
        if not value or "your-" in value or "paste-" in value or value == "example.com":
            raise RuntimeError(f"请先在 config.py 填写 {field}。")
    if "@" not in config.CF_EMAIL:
        raise RuntimeError("CF_EMAIL 必须是 Cloudflare 登录邮箱。")
    return plan_records()


def api(method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
    headers = {"X-Auth-Email": config.CF_EMAIL, "X-Auth-Key": config.CF_GLOBAL_API_KEY, "Content-Type": "application/json"}
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(f"{API_ROOT}{path}", data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.load(response)
    except urllib.error.HTTPError as error:
        try:
            message = "; ".join(item.get("message", "未知错误") for item in json.load(error).get("errors", []))
        except Exception:
            message = str(error.reason)
        raise RuntimeError(f"Cloudflare API 返回 HTTP {error.code}: {message}") from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"无法连接 Cloudflare API: {error.reason}") from error
    if not data.get("success"):
        message = "; ".join(item.get("message", "未知错误") for item in data.get("errors", []))
        raise RuntimeError(f"Cloudflare API 请求失败: {message}")
    return data["result"]


def zone_id() -> str:
    query = urllib.parse.urlencode({"name": config.ZONE_NAME, "status": "active"})
    matches = [zone for zone in api("GET", f"/zones?{query}") if zone.get("name", "").lower() == config.ZONE_NAME.lower()]
    if len(matches) != 1:
        raise RuntimeError(f"未找到唯一的活动 Zone：{config.ZONE_NAME}。")
    return matches[0]["id"]


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": 2, "active": []}
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"无法读取状态文件 {path}: {error}") from error
    if state.get("version") != 2 or not isinstance(state.get("active"), list):
        raise RuntimeError(f"状态文件 {path} 属于旧版脚本；为避免误删，请先确认并清理旧任务后再继续。")
    return state


def save_state(path: Path, state: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def daily_window(now: datetime, start_clock: clock_time, end_clock: clock_time) -> tuple[datetime, datetime]:
    """Return the current daily window if active; otherwise the next one."""
    today_start = datetime.combine(now.date(), start_clock, CHINA_TIME)
    today_end = datetime.combine(now.date(), end_clock, CHINA_TIME)
    if end_clock <= start_clock:
        today_end += timedelta(days=1)
        previous_start, previous_end = today_start - timedelta(days=1), today_end - timedelta(days=1)
        if previous_start <= now < previous_end:
            return previous_start, previous_end
    if now < today_start:
        return today_start, today_end
    if now < today_end:
        return today_start, today_end
    tomorrow = now.date() + timedelta(days=1)
    next_start = datetime.combine(tomorrow, start_clock, CHINA_TIME)
    next_end = datetime.combine(tomorrow, end_clock, CHINA_TIME)
    if end_clock <= start_clock:
        next_end += timedelta(days=1)
    return next_start, next_end


def delete_expired(state: dict[str, Any], now: datetime) -> bool:
    changed = False
    remaining = []
    for item in state["active"]:
        end_at = datetime.fromisoformat(item["end_at"]).astimezone(CHINA_TIME)
        if now < end_at:
            remaining.append(item)
            continue
        try:
            api("DELETE", f"/zones/{item['zone_id']}/dns_records/{item['record_id']}")
            print(f"已删除 {item['type']} {item['name']} 的本次 record_id={item['record_id']}。")
        except RuntimeError as error:
            if "HTTP 404" in str(error):
                print(f"record_id={item['record_id']} 已不存在（404），按删除完成处理。")
            else:
                print(f"删除 record_id={item['record_id']} 失败，将在下次循环重试：{error}", file=sys.stderr)
                remaining.append(item)
                continue
        changed = True
    if len(remaining) != len(state["active"]):
        state["active"] = remaining
        changed = True
    return changed


def create_due_records(state: dict[str, Any], state_path: Path, plans: list[dict[str, Any]], now: datetime, current_zone_id: str | None) -> str | None:
    active_keys = {item["plan_key"] for item in state["active"]}
    for plan in plans:
        start_clock = parse_clock(plan["start_time"], "start_time")
        end_clock = parse_clock(plan["end_time"], "end_time")
        start_at, end_at = daily_window(now, start_clock, end_clock)
        plan_key = fingerprint(plan)
        if now < start_at or plan_key in active_keys:
            continue
        if current_zone_id is None:
            current_zone_id = zone_id()
        payload = {field: plan[field] for field in ("type", "name", "content", "ttl", "proxied")}
        result = api("POST", f"/zones/{current_zone_id}/dns_records", payload)
        state["active"].append({
            "plan_key": plan_key, "record_id": result["id"], "zone_id": current_zone_id,
            "type": plan["type"], "name": plan["name"], "end_at": end_at.isoformat(),
        })
        save_state(state_path, state)  # 每创建一条立即持久化；后续创建失败也能精确清理已创建项。
        active_keys.add(plan_key)
        print(f"已创建 {plan['type']} {plan['name']}，record_id={result['id']}；将在中国时间 {end_at:%F %T} 删除。")
    return current_zone_id


def main() -> int:
    plans = validate_config()
    state_path = Path(config.STATE_FILE)
    print(f"常驻任务启动：共 {len(plans)} 条记录，各自按中国时间独立执行。")
    for plan in plans:
        print(f"  - {plan['type']} {plan['name']} -> {plan['content']}：{plan['start_time']} 至 {plan['end_time']}")
    if not config.CONFIRM_CHANGES:
        print("当前为预演模式：请确认 config.py 后将 CONFIRM_CHANGES 改为 True。")
        return 0

    while True:
        state = load_state(state_path)
        now = datetime.now(CHINA_TIME)
        changed = delete_expired(state, now)
        before = len(state["active"])
        create_due_records(state, state_path, plans, now, None)
        changed = changed or len(state["active"]) != before
        if changed:
            save_state(state_path, state)
        time.sleep(15)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\n收到停止指令，状态文件会保留；下次启动仍会只删除其中保存的 record_id。")
        raise SystemExit(130)
    except RuntimeError as error:
        print(f"错误：{error}", file=sys.stderr)
        raise SystemExit(1)
