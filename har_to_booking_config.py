import argparse
import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any

KEYWORD_PATTERN = re.compile(r"(book|booking|reserve|court|场地|预约|order)", re.IGNORECASE)


def load_har(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def parse_json_text(value: str) -> Any:
    text = value.strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {}


def headers_to_dict(headers: list[dict[str, str]]) -> dict[str, str]:
    out: dict[str, str] = {}
    for h in headers:
        name = h.get("name", "").strip()
        if not name:
            continue
        out[name] = h.get("value", "")
    return out


def replace_placeholders(payload: Any) -> Any:
    if isinstance(payload, dict):
        out: dict[str, Any] = {}
        for key, value in payload.items():
            low = key.lower()
            if low in {"date", "bookdate", "booking_date", "reserve_date"} and isinstance(value, str):
                out[key] = "{date}"
            elif low in {"court", "courtno", "court_no", "venue", "field", "site"}:
                out[key] = "{court}"
            elif low in {"timeslot", "time_slot", "slot", "period", "time_range"} and isinstance(value, str):
                out[key] = "{time_slot}"
            elif low in {"start", "starttime", "start_time"} and isinstance(value, str):
                out[key] = "{slot_start}"
            elif low in {"end", "endtime", "end_time"} and isinstance(value, str):
                out[key] = "{slot_end}"
            else:
                out[key] = replace_placeholders(value)
        return out
    if isinstance(payload, list):
        return [replace_placeholders(v) for v in payload]
    return payload


def score_entry(url: str, method: str, body: Any) -> int:
    score = 0
    if method.upper() == "POST":
        score += 2
    if KEYWORD_PATTERN.search(url):
        score += 3
    if isinstance(body, dict):
        keys = {k.lower() for k in body}
        if {"date", "bookdate", "booking_date", "reserve_date"} & keys:
            score += 2
        if {"court", "courtno", "venue", "field", "site"} & keys:
            score += 2
    return score


def candidate_entries(har: dict[str, Any], host_keyword: str | None) -> list[dict[str, Any]]:
    entries = har.get("log", {}).get("entries", [])
    candidates: list[dict[str, Any]] = []

    for idx, entry in enumerate(entries):
        req = entry.get("request", {})
        url = req.get("url", "")
        if host_keyword and host_keyword not in url:
            continue

        method = req.get("method", "GET")
        post_data = req.get("postData", {}).get("text", "")
        body = parse_json_text(post_data)
        headers = headers_to_dict(req.get("headers", []))

        item = {
            "index": idx,
            "url": url,
            "method": method,
            "headers": headers,
            "body": body,
            "score": score_entry(url, method, body),
        }
        candidates.append(item)

    candidates.sort(key=lambda x: x["score"], reverse=True)
    return candidates


def create_config(candidate: dict[str, Any], attempts: int, interval_ms: int) -> dict[str, Any]:
    headers = deepcopy(candidate["headers"])
    for drop_key in ["Content-Length", "Host", ":authority", ":method", ":path", ":scheme"]:
        headers.pop(drop_key, None)

    payload = replace_placeholders(candidate["body"])

    return {
        "api_url": candidate["url"],
        "method": candidate["method"].upper(),
        "headers_text": json.dumps(headers, ensure_ascii=False, indent=2),
        "payload_text": json.dumps(payload, ensure_ascii=False, indent=2),
        "court": "1",
        "time_slot": "15:00-16:00",
        "execute_time": "23:00:00",
        "attempts": attempts,
        "interval_ms": interval_ms,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="从 HAR 抓包文件中提取候选预约请求并生成 booking_config.json")
    parser.add_argument("--har", required=True, help="HAR 文件路径")
    parser.add_argument("--host-keyword", default="xcx-api.zuduijun.com", help="URL 过滤关键词")
    parser.add_argument("--pick", type=int, default=0, help="选择第几个候选(默认0，即评分最高)")
    parser.add_argument("--attempts", type=int, default=30, help="默认重试次数")
    parser.add_argument("--interval-ms", type=int, default=120, help="默认重试间隔")
    parser.add_argument("--output", default="booking_config.json", help="输出配置文件路径")
    args = parser.parse_args()

    har = load_har(Path(args.har))
    candidates = candidate_entries(har, args.host_keyword)
    if not candidates:
        raise SystemExit("未找到候选请求，请检查 host-keyword 或 HAR 文件是否正确")

    print("候选请求(前10条):")
    for i, item in enumerate(candidates[:10]):
        body_keys = list(item["body"].keys()) if isinstance(item["body"], dict) else []
        print(f"[{i}] score={item['score']} {item['method']} {item['url']} keys={body_keys}")

    pick = args.pick
    if pick < 0 or pick >= len(candidates):
        raise SystemExit(f"pick 超出范围: {pick}")

    selected = candidates[pick]
    config = create_config(selected, args.attempts, args.interval_ms)
    out_path = Path(args.output)
    out_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n已生成配置: {out_path}")
    print("请打开 GUI 复核 headers/payload，特别是 token/signature 等动态字段。")


if __name__ == "__main__":
    main()
