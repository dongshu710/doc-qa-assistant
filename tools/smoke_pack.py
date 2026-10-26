#!/usr/bin/env python3
"""解包 dist 里的应用包，起服务，打几个关键页面与接口，用完即删。

为什么单独一个脚本：发布前要确认「用户拿到的是这个 zip、跑起来是这个行为」，
而不是只信开发目录里的源码。临时目录用 tempfile 自动回收，起服务的端口先探再绑。
"""
from __future__ import annotations

import json
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
PY = sys.executable


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def get(url: str, timeout: int = 20):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.status, r.read()


def main() -> int:
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    pack = DIST / f"jiyi-app-{version}.zip"
    if not pack.exists():
        print(f"错误：找不到 {pack}")
        return 1

    tmp = Path(tempfile.mkdtemp(prefix="jiyi-smoke-"))
    try:
        with zipfile.ZipFile(pack) as z:
            z.extractall(tmp)
        root = tmp / f"jiyi-app-{version}" if (tmp / f"jiyi-app-{version}").exists() else tmp
        print(f"解包：{root}")

        home = tmp / "storage"
        port = free_port()
        # 必须继承整份环境：Windows 上少了 SYSTEMROOT 之类的变量，Python 根本起不来
        env = dict(__import__("os").environ)
        env.update({"PYTHONPATH": str(root), "NOTE_HOME": str(home), "SETUP_DONE": "1",
                    "APP_CONFIG": str(tmp / "app.json")})
        proc = subprocess.Popen([PY, "-m", "src.server", "--host", "127.0.0.1", "--port", str(port)],
                                cwd=root, env=env,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        base = f"http://127.0.0.1:{port}"
        ok = True
        try:
            for _ in range(60):
                try:
                    get(base + "/ask")
                    break
                except Exception:
                    time.sleep(0.5)
            else:
                print("错误：服务没起来")
                return 1

            for page in ("/ask", "/kb", "/files"):
                st, body = get(base + page)
                print(f"{'ok  ' if st == 200 and body else 'FAIL'} {page} 200 · {len(body)} B")
                ok = ok and st == 200 and bool(body)

            st, body = get(base + "/api/settings/setup")
            print(f"{'ok  ' if st == 200 else 'FAIL'} /api/settings/setup 200")
            ok = ok and st == 200

            st, body = get(base + "/api/threads")
            print(f"{'ok  ' if st == 200 else 'FAIL'} /api/threads 200 · {json.loads(body).get('count')} 条")
            ok = ok and st == 200

            st, body = get(base + "/tools.json")
            tools = json.loads(body)
            n = len(tools.get("tools", [])) if isinstance(tools, dict) else len(tools)
            print(f"{'ok  ' if n >= 7 else 'FAIL'} /tools.json 接出 {n} 个工具")
            ok = ok and n >= 7
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()

        print("成品包冒烟通过" if ok else "成品包冒烟有失败项")
        return 0 if ok else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
