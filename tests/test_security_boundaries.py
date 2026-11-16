"""四条边界的回归测试：断连、幂等串题、启动期安全校验、设置脱敏。

为什么单独一条脚本：这四条都属于「不测就不知道坏了」——

- 参数解析异常会一路穿出 do_GET，客户端只拿到 RemoteDisconnected（没有状态码、
  没有响应体），而从服务端日志看那是「客户端主动断开」；
- 幂等键只按 header 取值时，同一个键换一个问题会原样返回上一题的答案；
- `--host ""` 与 `API_KEYS=,` 都能让「非回环必须配 Key」的拒启逻辑失效；
- 设置类子路由是 open 级，脱敏只做在主路由上时，子路由会把家目录交出去。

跑法：python tests/test_security_boundaries.py
"""
from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

NO_PROXY = urllib.request.build_opener(urllib.request.ProxyHandler({}))
FAILED = 0
KEY = "secret123"


def check(name: str, ok: bool, detail: str = "") -> None:
    global FAILED
    if ok:
        print(f"  ok   {name}")
    else:
        FAILED += 1
        print(f"  FAIL {name}  {detail}")


def prepare_home(tmp: Path) -> Path:
    """把 data/ 复制到临时目录，并把笔记存储区指过去。

    直接对开发库跑会污染真实数据（用例、评测产物都写在 data 与 tests 下）。
    """
    work = tmp / "work"
    shutil.copytree(ROOT / "data", work / "data")
    cfg = work / "data" / "app.json"
    data = json.loads(cfg.read_text(encoding="utf-8")) if cfg.is_file() else {}
    data.setdefault("notes", {})["home"] = str(work / "notes")
    cfg.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    (work / "notes").mkdir(parents=True, exist_ok=True)
    (work / "logs").mkdir(parents=True, exist_ok=True)
    return work


def env_for(work: Path, **extra: str) -> dict:
    env = dict(os.environ)
    env.update({
        "PYTHONPATH": str(ROOT),
        "APP_CONFIG": str(work / "data" / "app.json"),
        "KB_DIR": str(work / "data" / "kb"),
        "RAW_DIR": str(work / "data" / "raw"),
        "LOG_DIR": str(work / "logs"),
        "SETUP_DONE": "1",
        "EMBEDDING_PROVIDER": "none",
    })
    env.update(extra)
    return env


def _absolute_strings(obj, _path: str = "") -> list[str]:
    """递归找出响应里看起来是绝对路径的**值**。

    只查值不查键：`PYTHONPATH`、`NOTE_HOME` 这些键名本来就该出现，
    泄露的是它们的值。第一版断言把键名也算进去了，于是脱敏正确也报失败。
    """
    found: list[str] = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            found += _absolute_strings(value, f"{_path}/{key}")
    elif isinstance(obj, list):
        for index, value in enumerate(obj):
            found += _absolute_strings(value, f"{_path}[{index}]")
    elif isinstance(obj, str):
        if re.search(r"[A-Za-z]:[\\/]|/Users/|/home/|/root/", obj):
            found.append(f"{_path}={obj[:80]}")
    return found


def wait_up(port: int, timeout: float = 30.0) -> bool:
    """等 /api/health 报「已就绪」；超时说明服务没起来。

    只判 200 不够：v1.42.0 起服务先占端口再建索引，启动期的应答器同样回 200，
    但正文是 `{"state":"starting"}`，此刻发业务请求一律 503。判 state 才叫就绪——
    不判就会偶发地把「正在建索引」当成失败（真踩过：本文件三项断言随机红）。
    """
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            with NO_PROXY.open(f"http://127.0.0.1:{port}/api/health", timeout=1) as r:
                body = r.read()
        except Exception:  # noqa: BLE001 —— 还没起来
            time.sleep(0.2)
            continue
        try:
            if json.loads(body).get("state") != "starting":
                return True
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass
        time.sleep(0.2)
    return False


def http(port: int, path: str, *, method: str = "GET", body=None,
         headers: dict | None = None, timeout: float = 15.0):
    """返回 (状态码 | None, body)。状态码 None 表示连接被断开。"""
    hdrs = dict(headers or {})
    payload = None
    if body is not None:
        payload = json.dumps(body).encode()
        hdrs["Content-Type"] = "application/json"
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=payload,
                                 headers=hdrs, method=method)
    try:
        with NO_PROXY.open(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")
    except Exception as exc:  # noqa: BLE001 —— 连接被重置
        return None, f"{type(exc).__name__}: {exc}"


def test_runtime(work: Path) -> None:
    port = 8171
    proc = subprocess.Popen(
        [sys.executable, "-m", "src.server", "--host", "127.0.0.1", "--port", str(port)],
        cwd=str(ROOT), env=env_for(work, API_KEYS=KEY),
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    auth = {"Authorization": f"Bearer {KEY}"}
    try:
        if not wait_up(port):
            out = (proc.stdout.read() or b"").decode("utf-8", "replace")[-1500:]
            check("服务能起来", False, out)
            return
        check("服务能起来", True)

        # 1) 坏整数参数必须回一个正常响应，而不是断连
        status, text = http(port, "/api/threads?limit=abc", headers=auth)
        ok = status == 200 and text.startswith("{")
        check("?limit=abc 返回 200 JSON（不是无状态码断连）", ok, f"{status} {text[:120]}")
        status, _ = http(port, "/api/threads?limit=999999", headers=auth)
        check("?limit=999999 被夹到上限仍 200", status == 200, str(status))

        # 2) 幂等键必须绑定问题内容
        first = "稳盈系列起购金额是多少"
        second = "大额存单的期限是多久"
        idem = {**auth, "Idempotency-Key": "same-key-1"}
        s1, b1 = http(port, "/api/ask", method="POST", body={"query": first},
                      headers=idem, timeout=40)
        s2, b2 = http(port, "/api/ask", method="POST", body={"query": second},
                      headers=idem, timeout=40)
        try:
            j1, j2 = json.loads(b1), json.loads(b2)
        except json.JSONDecodeError:
            check("幂等：两个请求都返回 JSON", False, f"{b1[:120]} / {b2[:120]}")
        else:
            check("幂等：第二次返回的是第二题的答案",
                  s1 == 200 and s2 == 200 and j2.get("query") == second,
                  f"第二次 query={j2.get('query')!r}")
            check("幂等：两题答案不相同", j1.get("answer") != j2.get("answer"),
                  "两题拿到了同一个答案——幂等键没绑定问题内容")

        # 3) 设置子路由：没带 Key 时不能交出绝对路径
        status, text = http(port, "/api/settings/mcp")
        check("无 Key 读 /api/settings/mcp 仍 200", status == 200, str(status))
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            payload = {}
        check("无 Key 读 /api/settings/mcp 走了脱敏分支",
              payload.get("redacted") is True, str(payload)[:140])
        check("无 Key 读 /api/settings/mcp 不泄露绝对路径",
              not _absolute_strings(payload), str(_absolute_strings(payload))[:200])
        status, text = http(port, "/api/settings/setup")
        # 用户名会出现在绝对路径里；脱敏后只剩「…/末级」。
        user_seg = Path.home().name
        check("无 Key 读 /api/settings/setup 不泄露家目录",
              status == 200 and user_seg not in text,
              f"{status} {text[:140]}")

        # 4) 空闲连接不该占工作槽：64 条只连不发的连接开着时，健康检查仍要是 200
        socks = []
        for _ in range(64):
            try:
                socks.append(socket.create_connection(("127.0.0.1", port), timeout=2))
            except OSError:
                break
        time.sleep(0.4)
        status, text = http(port, "/api/health", timeout=4)
        check("64 条空闲连接下 /api/health 仍是 200", status == 200,
              f"空闲={len(socks)} status={status} {text[:100]}")
        for sock in socks:
            try:
                sock.close()
            except OSError:
                pass
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


def test_refuse_boot(work: Path) -> None:
    """这两个写法必须被拒启：否则局域网能读完整库，而启动日志不会有任何提示。"""
    cases = [
        ("--host 空串", ["--host", "", "--port", "8172"], {}),
        ("--host 0.0.0.0 + API_KEYS=,", ["--host", "0.0.0.0", "--port", "8173"],
         {"API_KEYS": ","}),
    ]
    for label, args, extra in cases:
        proc = subprocess.Popen([sys.executable, "-m", "src.server"] + args,
                                cwd=str(ROOT), env=env_for(work, **extra),
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        code = None
        for _ in range(30):
            time.sleep(0.3)
            if proc.poll() is not None:
                code = proc.returncode
                break
        out = ""
        if code is not None:
            out = (proc.stdout.read() or b"").decode("utf-8", "replace")
        else:
            proc.terminate()
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()
        check(f"拒绝启动：{label}", code == 1 and "拒绝启动" in out,
              f"exit={code} 输出={out[-160:]}")


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        work = prepare_home(Path(tmp))
        print("请求边界与安全问题：")
        print(" 回连与鉴权：")
        test_runtime(work)
        print(" 启动校验：")
        test_refuse_boot(work)
    print()
    if FAILED:
        print(f"{FAILED} 项失败")
        return 1
    print("SECURITY BOUNDARIES OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
