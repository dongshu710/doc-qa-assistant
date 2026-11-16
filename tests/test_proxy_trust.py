"""反代场景下「谁是管理员」：TRUST_PROXY / TRUSTED_PROXIES / ADMIN_ALLOW_REMOTE。

为什么单独测这一条：单机形态「对端是 127.0.0.1 就算管理员」是对的——能连上
回环端口的只有本机进程。一旦前面挂了 nginx，对端永远是 127.0.0.1，于是
**任何能访问代理的人**都成了管理员：`/metrics`、`/api/audit`、知识库审批全开。
这类问题不会报错、不会告警，只会在某天被人发现，所以必须有回归。

三个开关的语义：
- `TRUST_PROXY=on`：才读 `X-Forwarded-For`，且只认 `TRUSTED_PROXIES` 发来的
- `TRUSTED_PROXIES`：默认只有本机（代理与本服务同机部署是最常见形态）
- `ADMIN_ALLOW_REMOTE=1`：才允许「不是直连本机」的地址行使管理员权限

跑法：python tests/test_proxy_trust.py
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

NO_PROXY = urllib.request.build_opener(urllib.request.ProxyHandler({}))
FAILED = 0
FLAGS = ("TRUST_PROXY", "TRUSTED_PROXIES", "ADMIN_ALLOW_REMOTE", "ADMIN_TOKEN", "API_KEYS")


def check(name: str, ok: bool, detail: str = "") -> None:
    global FAILED
    if ok:
        print(f"  ok   {name}")
    else:
        FAILED += 1
        print(f"  FAIL {name}  {detail}")


@contextmanager
def env(**values: str):
    """临时设置环境变量，退出时恢复。"""
    old = {key: os.environ.get(key) for key in values}
    try:
        for key, value in values.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        yield
    finally:
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def test_unit() -> None:
    print("来源解析（纯函数）")
    from src import security

    with env(TRUST_PROXY=None, TRUSTED_PROXIES=None, ADMIN_ALLOW_REMOTE=None):
        check("默认不信代理", not security.trust_proxy())
        check("默认只信本机代理", security.trusted_proxies() == {"127.0.0.1", "::1"},
              str(security.trusted_proxies()))
        check("关着时忽略 X-Forwarded-For",
              security.client_ip("127.0.0.1", "203.0.113.9") == ("127.0.0.1", False))
        check("本机直连是管理员", security.admin_by_ip("127.0.0.1", False))
        check("非回环默认不是管理员", not security.admin_by_ip("203.0.113.9", False))

    with env(TRUST_PROXY="on", TRUSTED_PROXIES=None, ADMIN_ALLOW_REMOTE=None):
        check("打开后取 XFF 的客户端地址",
              security.client_ip("127.0.0.1", "203.0.113.9") == ("203.0.113.9", True))
        check("XFF 里有端口也能解析",
              security.client_ip("127.0.0.1", "203.0.113.9:51234") == ("203.0.113.9", True))
        check("XFF 里是垃圾就退回对端",
              security.client_ip("127.0.0.1", "unknown")[0] == "127.0.0.1")
        check("对端不是可信代理时不信 XFF",
              security.client_ip("10.0.0.9", "203.0.113.9") == ("10.0.0.9", False))
        check("经代理的回环不算管理员",
              not security.admin_by_ip("127.0.0.1", True))
        check("经代理的外部地址不算管理员",
              not security.admin_by_ip("203.0.113.9", True))

    with env(TRUST_PROXY="on", TRUSTED_PROXIES="127.0.0.1,10.0.0.5", ADMIN_ALLOW_REMOTE=None):
        # 从右往左跳过可信代理：最左是客户端自己填的，不能当身份
        check("跳过可信代理链，取最右不可信地址",
              security.client_ip("127.0.0.1", "1.1.1.1, 10.0.0.5") == ("1.1.1.1", True),
              str(security.client_ip("127.0.0.1", "1.1.1.1, 10.0.0.5")))
        check("整条链都可信时标记经过代理",
              security.client_ip("127.0.0.1", "10.0.0.5")[1] is True)

    with env(TRUST_PROXY="on", TRUSTED_PROXIES=None, ADMIN_ALLOW_REMOTE="1"):
        check("显式允许远程后，经代理也可当管理员",
              security.admin_by_ip("203.0.113.9", True))
        check("显式允许远程后，直连外部也可当管理员",
              security.admin_by_ip("203.0.113.9", False))


def prepare_home(tmp: Path) -> Path:
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
    env_vars = dict(os.environ)
    # 三个开关必须先清空：宿主环境里如果开着，测出来的是宿主的行为
    for key in FLAGS:
        env_vars.pop(key, None)
    env_vars.update({
        "PYTHONPATH": str(ROOT),
        "APP_CONFIG": str(work / "data" / "app.json"),
        "KB_DIR": str(work / "data" / "kb"),
        "RAW_DIR": str(work / "data" / "raw"),
        "LOG_DIR": str(work / "logs"),
        "SETUP_DONE": "1",
        "EMBEDDING_PROVIDER": "none",
    })
    env_vars.update(extra)
    return env_vars


def wait_up(port: int, timeout: float = 30.0) -> bool:
    """等 health 不再是 `state=starting`（启动期也占着端口，只判 200 不够）。"""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            with NO_PROXY.open(f"http://127.0.0.1:{port}/api/health", timeout=1) as resp:
                body = resp.read()
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


def call(port: int, path: str, xff: str | None = None, timeout: float = 10.0):
    headers = {}
    if xff is not None:
        headers["X-Forwarded-For"] = xff
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", headers=headers)
    try:
        with NO_PROXY.open(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def run_case(port: int, work: Path, extra: dict[str, str], body) -> None:
    proc = subprocess.Popen(
        [sys.executable, "-m", "src.server", "--host", "127.0.0.1", "--port", str(port)],
        cwd=str(ROOT), env=env_for(work, **extra),
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    try:
        if not wait_up(port):
            out = (proc.stdout.read() or b"").decode("utf-8", "replace")[-1200:]
            check(f"服务能起来（{extra}）", False, out)
            return
        body(port)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


def test_runtime(tmp: Path) -> None:
    print("经由代理的请求")
    work = prepare_home(tmp)
    sentinel = "203.0.113.9"

    def trusted(port: int) -> None:
        status, _ = call(port, "/api/audit", xff=sentinel)
        check("TRUST_PROXY=on：外部来源读审计 → 403", status == 403, str(status))
        status, _ = call(port, "/metrics", xff=sentinel)
        check("TRUST_PROXY=on：外部来源读指标 → 403", status == 403, str(status))
        # 不带 XFF = 直连本机，仍是管理员：单机体验不能被反代开关误伤
        status, _ = call(port, "/api/audit")
        check("TRUST_PROXY=on：本机直连读审计 → 200", status == 200, str(status))

    run_case(8181, work, {"TRUST_PROXY": "on"}, trusted)

    def allowed(port: int) -> None:
        status, _ = call(port, "/api/audit", xff=sentinel)
        check("ADMIN_ALLOW_REMOTE=1：外部来源读审计 → 200", status == 200, str(status))

    run_case(8182, work, {"TRUST_PROXY": "on", "ADMIN_ALLOW_REMOTE": "1"}, allowed)

    def ignored(port: int) -> None:
        # 默认关：XFF 完全不看，行为与改造前一致（本机直连仍是管理员）
        status, _ = call(port, "/api/audit", xff=sentinel)
        check("TRUST_PROXY 默认关：XFF 被忽略，仍是 200", status == 200, str(status))

    run_case(8183, work, {}, ignored)


def main() -> int:
    test_unit()
    print()
    with tempfile.TemporaryDirectory() as tmp:
        test_runtime(Path(tmp))
    print()
    if FAILED:
        print(f"{FAILED} 项失败")
        return 1
    print("PROXY TRUST OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
