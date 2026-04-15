import json
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import requests
import tkinter as tk
from tkinter import ttk, messagebox


CONFIG_FILE = Path("booking_config.json")
TIME_SLOTS = [
    "15:00-16:00",
    "16:00-17:00",
    "17:00-18:00",
    "18:00-19:00",
    "19:00-20:00",
    "20:00-21:00",
]


@dataclass
class BookingConfig:
    api_url: str
    method: str
    headers_text: str
    payload_text: str
    court: str
    time_slot: str
    execute_time: str
    attempts: int
    interval_ms: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "api_url": self.api_url,
            "method": self.method,
            "headers_text": self.headers_text,
            "payload_text": self.payload_text,
            "court": self.court,
            "time_slot": self.time_slot,
            "execute_time": self.execute_time,
            "attempts": self.attempts,
            "interval_ms": self.interval_ms,
        }


class BookingBotGUI:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("羽毛球抢场脚本（本地）")
        self.root.geometry("980x760")

        self.scheduler_thread: threading.Thread | None = None
        self.stop_flag = threading.Event()

        self.api_url_var = tk.StringVar()
        self.method_var = tk.StringVar(value="POST")
        self.court_var = tk.StringVar(value="1")
        self.slot_var = tk.StringVar(value=TIME_SLOTS[0])
        self.execute_time_var = tk.StringVar(value="23:00:00")
        self.attempts_var = tk.StringVar(value="30")
        self.interval_var = tk.StringVar(value="120")
        self.target_date_var = tk.StringVar(value=self._booking_date_str())

        self._build_ui()
        self._load_config_if_exists()

    def _build_ui(self) -> None:
        frm = ttk.Frame(self.root, padding=12)
        frm.pack(fill="both", expand=True)

        row = 0
        ttk.Label(frm, text="预约接口 URL").grid(column=0, row=row, sticky="w")
        ttk.Entry(frm, textvariable=self.api_url_var, width=95).grid(column=1, row=row, sticky="we", padx=8)

        row += 1
        ttk.Label(frm, text="请求方式").grid(column=0, row=row, sticky="w")
        ttk.Combobox(frm, values=["POST", "GET"], textvariable=self.method_var, width=12, state="readonly").grid(
            column=1, row=row, sticky="w", padx=8
        )

        row += 1
        ttk.Label(frm, text="目标日期（自动=后天）").grid(column=0, row=row, sticky="w")
        ttk.Entry(frm, textvariable=self.target_date_var, width=20).grid(column=1, row=row, sticky="w", padx=8)

        row += 1
        ttk.Label(frm, text="场地编号").grid(column=0, row=row, sticky="w")
        ttk.Combobox(
            frm,
            values=["1", "2", "3", "4", "5", "6"],
            textvariable=self.court_var,
            width=12,
            state="readonly",
        ).grid(column=1, row=row, sticky="w", padx=8)

        row += 1
        ttk.Label(frm, text="时间段").grid(column=0, row=row, sticky="w")
        ttk.Combobox(frm, values=TIME_SLOTS, textvariable=self.slot_var, width=20, state="readonly").grid(
            column=1, row=row, sticky="w", padx=8
        )

        row += 1
        ttk.Label(frm, text="执行时间（24h）").grid(column=0, row=row, sticky="w")
        ttk.Entry(frm, textvariable=self.execute_time_var, width=20).grid(column=1, row=row, sticky="w", padx=8)

        row += 1
        ttk.Label(frm, text="重试次数").grid(column=0, row=row, sticky="w")
        ttk.Entry(frm, textvariable=self.attempts_var, width=20).grid(column=1, row=row, sticky="w", padx=8)

        row += 1
        ttk.Label(frm, text="重试间隔（毫秒）").grid(column=0, row=row, sticky="w")
        ttk.Entry(frm, textvariable=self.interval_var, width=20).grid(column=1, row=row, sticky="w", padx=8)

        row += 1
        ttk.Label(frm, text="Headers(JSON)").grid(column=0, row=row, sticky="nw")
        self.headers_text = tk.Text(frm, width=70, height=8)
        self.headers_text.grid(column=1, row=row, sticky="we", padx=8)
        self.headers_text.insert("1.0", '{\n  "Content-Type": "application/json"\n}')

        row += 1
        ttk.Label(frm, text="Body模板(JSON，可用占位符)").grid(column=0, row=row, sticky="nw")
        self.payload_text = tk.Text(frm, width=70, height=12)
        self.payload_text.grid(column=1, row=row, sticky="we", padx=8)
        self.payload_text.insert(
            "1.0",
            '{\n  "date": "{date}",\n  "court": "{court}",\n  "time_slot": "{time_slot}",\n  "start": "{slot_start}",\n  "end": "{slot_end}"\n}',
        )

        row += 1
        btn_frm = ttk.Frame(frm)
        btn_frm.grid(column=1, row=row, sticky="w", padx=8, pady=8)
        ttk.Button(btn_frm, text="保存配置", command=self.save_config).pack(side="left", padx=6)
        ttk.Button(btn_frm, text="开始定时", command=self.start_schedule).pack(side="left", padx=6)
        ttk.Button(btn_frm, text="立即测试发送1次", command=self.send_once_for_test).pack(side="left", padx=6)
        ttk.Button(btn_frm, text="停止任务", command=self.stop_schedule).pack(side="left", padx=6)

        row += 1
        ttk.Label(frm, text="日志").grid(column=0, row=row, sticky="nw")
        self.log_text = tk.Text(frm, width=90, height=14)
        self.log_text.grid(column=1, row=row, sticky="nsew", padx=8)

        frm.columnconfigure(1, weight=1)
        frm.rowconfigure(row, weight=1)

    def _booking_date_str(self) -> str:
        return (datetime.now() + timedelta(days=2)).strftime("%Y-%m-%d")

    def _log(self, msg: str) -> None:
        now = datetime.now().strftime("%H:%M:%S")
        self.log_text.insert("end", f"[{now}] {msg}\n")
        self.log_text.see("end")

    def _build_config(self) -> BookingConfig:
        return BookingConfig(
            api_url=self.api_url_var.get().strip(),
            method=self.method_var.get().strip().upper(),
            headers_text=self.headers_text.get("1.0", "end").strip(),
            payload_text=self.payload_text.get("1.0", "end").strip(),
            court=self.court_var.get().strip(),
            time_slot=self.slot_var.get().strip(),
            execute_time=self.execute_time_var.get().strip(),
            attempts=int(self.attempts_var.get().strip()),
            interval_ms=int(self.interval_var.get().strip()),
        )

    def _load_config_if_exists(self) -> None:
        if not CONFIG_FILE.exists():
            return

        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        self.api_url_var.set(data.get("api_url", ""))
        self.method_var.set(data.get("method", "POST"))
        self.court_var.set(data.get("court", "1"))
        self.slot_var.set(data.get("time_slot", TIME_SLOTS[0]))
        self.execute_time_var.set(data.get("execute_time", "23:00:00"))
        self.attempts_var.set(str(data.get("attempts", 30)))
        self.interval_var.set(str(data.get("interval_ms", 120)))
        self.headers_text.delete("1.0", "end")
        self.headers_text.insert("1.0", data.get("headers_text", "{}"))
        self.payload_text.delete("1.0", "end")
        self.payload_text.insert("1.0", data.get("payload_text", "{}"))

    def save_config(self) -> None:
        config = self._build_config()
        CONFIG_FILE.write_text(json.dumps(config.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        self._log(f"配置已保存到 {CONFIG_FILE}")

    def _template_payload(self, payload_text: str) -> dict[str, Any]:
        slot_start, slot_end = self.slot_var.get().split("-")
        templated = payload_text.format(
            date=self.target_date_var.get().strip(),
            court=self.court_var.get().strip(),
            time_slot=self.slot_var.get().strip(),
            slot_start=slot_start,
            slot_end=slot_end,
        )
        return json.loads(templated)

    def send_once_for_test(self) -> None:
        try:
            config = self._build_config()
            self._send_request(config, 1)
        except Exception as exc:
            messagebox.showerror("测试失败", f"请求失败: {exc}")
            self._log(f"测试失败: {exc}")

    def _send_request(self, config: BookingConfig, idx: int) -> None:
        headers = json.loads(config.headers_text) if config.headers_text else {}
        payload = self._template_payload(config.payload_text)

        start = time.perf_counter()
        if config.method == "POST":
            resp = requests.post(config.api_url, json=payload, headers=headers, timeout=3)
        else:
            resp = requests.get(config.api_url, params=payload, headers=headers, timeout=3)

        duration_ms = int((time.perf_counter() - start) * 1000)
        body_preview = resp.text[:160].replace("\n", " ")
        self._log(f"第{idx}次 => HTTP {resp.status_code}, {duration_ms}ms, 响应: {body_preview}")

    def _next_run_datetime(self, execute_time: str) -> datetime:
        target_time = datetime.strptime(execute_time, "%H:%M:%S").time()
        now = datetime.now()
        run_dt = datetime.combine(now.date(), target_time)
        if run_dt <= now:
            run_dt += timedelta(days=1)
        return run_dt

    def start_schedule(self) -> None:
        if self.scheduler_thread and self.scheduler_thread.is_alive():
            messagebox.showinfo("提示", "已有任务在运行")
            return

        config = self._build_config()
        if not config.api_url:
            messagebox.showwarning("提示", "请先填写预约接口 URL")
            return

        self.stop_flag.clear()
        self.scheduler_thread = threading.Thread(target=self._schedule_worker, daemon=True)
        self.scheduler_thread.start()
        self._log("已启动定时任务")

    def stop_schedule(self) -> None:
        self.stop_flag.set()
        self._log("已请求停止任务")

    def _schedule_worker(self) -> None:
        try:
            config = self._build_config()
            run_dt = self._next_run_datetime(config.execute_time)
            self._log(f"计划执行时间: {run_dt.strftime('%Y-%m-%d %H:%M:%S')}")

            while not self.stop_flag.is_set():
                now = datetime.now()
                if now >= run_dt:
                    break
                remain = int((run_dt - now).total_seconds())
                if remain % 60 == 0 or remain <= 10:
                    self._log(f"倒计时 {remain} 秒")
                time.sleep(1)

            if self.stop_flag.is_set():
                self._log("任务已停止，不再发送请求")
                return

            self._log("开始抢场请求...")
            for idx in range(1, config.attempts + 1):
                if self.stop_flag.is_set():
                    self._log("发送中止")
                    return
                try:
                    self._send_request(config, idx)
                except Exception as exc:
                    self._log(f"第{idx}次异常: {exc}")
                time.sleep(config.interval_ms / 1000)

            self._log("请求发送完成")
        except Exception as exc:
            self._log(f"定时任务异常: {exc}")


if __name__ == "__main__":
    root = tk.Tk()
    app = BookingBotGUI(root)
    root.mainloop()
