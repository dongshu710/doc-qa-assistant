"""桌面客户端的接口层：不启动界面也要能证明它调得通。

界面（Tkinter）没法在无显示环境里跑，但「客户端调用的每个接口」都能在这里覆盖：
问答、存笔记、读改文件（含 428 冲突）、会话、备份恢复、服务未启动时的错误提示。

起真服务的理由和 test_security 一样：只测函数无法证明 HTTP 契约没变。
"""
import json
import socket
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.client_api import Client, ClientError  # noqa: E402

FAILED = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global FAILED
    if ok:
        print(f"  ok   {name}")
    else:
        FAILED += 1
        print(f"  FAIL {name}  {detail}")


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def start(tmp: Path):
    (tmp / "kb").mkdir()
    (tmp / "kb" / "seed.md").write_text("# 产品\n\n稳盈系列起购金额为 1 元，期限 90 天。\n",
                                       encoding="utf-8")
    (tmp / "home").mkdir()
    import os
    os.environ.update({
        "APP_CONFIG": str(tmp / "app.json"), "NOTE_HOME": str(tmp / "home"),
        "SETUP_DONE": "1", "KB_STORE": "off", "KB_DIR": str(tmp / "kb"),
        "RETRIEVAL": "vector", "EMBEDDING_PROVIDER": "none", "API_KEYS": "",
    })
    from src.server import create_server
    port = free_port()
    httpd, _pipe = create_server("127.0.0.1", port, str(tmp / "kb"))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, port


def main() -> int:
    with tempfile.TemporaryDirectory() as tmpdir:
        httpd, port = start(Path(tmpdir))
        client = Client(f"http://127.0.0.1:{port}")
        try:
            print("连接与状态")
            health = client.health()
            check("health 可用", health.get("status") == "ok", str(health)[:80])
            check("health 标明单实例", (health.get("runtime") or {}).get("mode") == "single-instance",
                  str(health.get("runtime")))
            settings = client.settings()
            check("settings 拿到存储区", bool((settings.get("notes") or {}).get("home_effective")))

            print("问答")
            result = client.ask("稳盈系列的起购金额是多少")
            answer = str(result.get("answer") or "")
            check("回答了内容", "1 元" in answer or "起购" in answer, answer[:60])
            check("带引用", isinstance(result.get("citations"), list))
            check("带引用支持率", "citation_support_rate" in result)

            print("存为笔记")
            try:
                client.save_note("稳盈系列的起购金额是多少", answer)
                check("开关关闭时保存被拒（403）", False, "居然存进去了")
            except ClientError as exc:
                check("开关关闭时保存被拒（403）", exc.status == 403 and exc.code == "store_chat_off",
                      f"status={exc.status} code={exc.code}")
            client.update_settings({"notes": {"store_chat": True}})
            saved = client.save_note("稳盈系列的起购金额是多少", answer)
            check("存成功", bool(saved.get("id")), str(saved)[:120])
            items = client.notes()
            check("列表能看到", any(item["id"] == saved["id"] for item in items), str(len(items)))
            note = client.note(saved["id"])
            check("单篇带 path", bool(note.get("path")), str(note)[:80])

            print("读改文件")
            raw = client.read_file(note["path"])
            check("读到 rev", len(raw.get("rev") or "") == 16, str(raw.get("rev")))
            updated = client.write_file(note["path"], raw["content"] + "\n补充一行\n", raw["rev"])
            check("带 rev 写入成功", updated.get("rev") != raw["rev"], str(updated))
            try:
                client.write_file(note["path"], "无 rev 覆盖")
                check("无 rev 覆盖被拒（428）", False, "居然成功了")
            except ClientError as exc:
                check("无 rev 覆盖被拒（428）", exc.status == 428, f"status={exc.status}")
            try:
                client.create_note_file(note["path"], "再建一次")
                check("create 撞已有文件报 409", False)
            except ClientError as exc:
                check("create 撞已有文件报 409", exc.status == 409, f"status={exc.status}")
            check("新建文件可用", bool(client.create_note_file("notes/new.md", "# 新文件\n").get("rev")))

            print("会话")
            client._request("PUT", "/api/threads/t_000001", body={
                "title": "桌面端会话", "turns": [{"q": "问题", "ts": "", "d": {"answer": "回答"}}]})
            threads = client.threads()
            check("会话列表有 1 条", len(threads) == 1, str(threads))
            thread = client.thread("t_000001")
            check("会话正文正确", thread.get("turns") and thread["turns"][0]["q"] == "问题", str(thread)[:80])

            print("备份与恢复")
            pack = client.backup("客户端测试")
            check("备份产出包", pack.get("name", "").endswith(".zip"), str(pack)[:100])
            check("备份含文件", int(pack.get("files") or 0) >= 2, str(pack.get("files")))
            check("备份列表有 1 个", len(client.backups()) == 1)
            target = note["path"]
            client.write_file(target, "被改坏\n", client.read_file(target)["rev"])
            restored = client.restore(pack["name"], force=True)
            check("恢复成功", int(restored.get("restored") or 0) >= 2, str(restored))
            check("内容回到备份时", "补充一行" in client.read_file(target)["content"])

            print("终端客户端（python -m src.client）")
            import subprocess
            base = ["-m", "src.client", "--base", f"http://127.0.0.1:{port}"]
            env = dict(__import__("os").environ)
            env["PYTHONPATH"] = str(ROOT)
            status = subprocess.run([sys.executable, *base, "status"], cwd=str(ROOT), env=env,
                                    capture_output=True, text=True, timeout=60)
            check("status 退出码 0", status.returncode == 0, status.stderr[-200:])
            check("status 打印存储区", "存储区" in status.stdout, status.stdout[:80])
            asked = subprocess.run([sys.executable, *base, "ask", "稳盈系列的起购金额是多少"],
                                   cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=120)
            check("ask 有回答", asked.returncode == 0 and "起购" in asked.stdout,
                  (asked.stdout + asked.stderr)[:120])
            listed = subprocess.run([sys.executable, *base, "notes"], cwd=str(ROOT), env=env,
                                    capture_output=True, text=True, timeout=60)
            check("notes 列出笔记", listed.returncode == 0 and "共" in listed.stdout,
                  listed.stdout[:80])
        finally:
            httpd.shutdown()
            httpd.server_close()

        print("服务没启动时")
        offline = Client(f"http://127.0.0.1:{free_port()}")
        try:
            offline.health()
            check("连不上时抛 ClientError", False)
        except ClientError as exc:
            check("连不上时抛 ClientError", exc.is_offline, f"status={exc.status}")
            check("错误信息给出启动命令", "src.server" in str(exc), str(exc)[:80])

    print(f"\n{'全部通过' if FAILED == 0 else f'{FAILED} 项失败'}")
    return 0 if FAILED == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
