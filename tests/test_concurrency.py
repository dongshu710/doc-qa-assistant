"""并发写：乐观锁到底有没有生效，只能靠线程同时打进来验证。

为什么单测不够：顺序执行的用例里「读 rev → 比较 → 落盘」永远是对的，
只有在同一条 `base_rev` 上同时发起多个写请求，才能看出锁是不是真的存在。
"""
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.client_api import Client, ClientError  # noqa: E402

FAILED = 0
WORKERS = 8


def check(name: str, ok: bool, detail: str = "") -> None:
    global FAILED
    if ok:
        print(f"  ok   {name}")
    else:
        FAILED += 1
        print(f"  FAIL {name}  {detail}")


def start(tmp: Path):
    import os
    import socket

    (tmp / "kb").mkdir()
    (tmp / "kb" / "seed.md").write_text("# 产品\n\n稳盈系列起购金额为 1 元。\n", encoding="utf-8")
    (tmp / "home").mkdir()
    os.environ.update({
        "APP_CONFIG": str(tmp / "app.json"), "NOTE_HOME": str(tmp / "home"),
        "SETUP_DONE": "1", "KB_STORE": "off", "KB_DIR": str(tmp / "kb"),
        "RETRIEVAL": "vector", "EMBEDDING_PROVIDER": "none", "API_KEYS": "", "DEBUG": "off",
    })
    from src.server import create_server
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    httpd, _pipe = create_server("127.0.0.1", port, str(tmp / "kb"))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, port


def race(fn, workers: int = WORKERS) -> list:
    """让 N 个线程尽量同时出发，否则先到的线程写完后，后面的只会撞 409 而不是撞竞态。"""
    barrier = threading.Barrier(workers)
    results: list = [None] * workers

    def run(index: int) -> None:
        barrier.wait()
        try:
            results[index] = ("ok", fn(index))
        except ClientError as exc:
            results[index] = ("err", exc)
        except Exception as exc:  # noqa: BLE001 —— 测试里要看见真实异常
            results[index] = ("boom", exc)

    threads = [threading.Thread(target=run, args=(i,)) for i in range(workers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return results


def main() -> int:
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        httpd, port = start(tmp)
        client = Client(f"http://127.0.0.1:{port}")
        try:
            print("同一 base_rev 并发覆盖")
            created = client.create_note_file("notes/race.md", "初始内容\n")
            base_rev = created["rev"]
            results = race(lambda i: client.write_file("notes/race.md", f"线程 {i} 写入\n", base_rev))
            wins = [r for r in results if r[0] == "ok"]
            conflicts = [r for r in results if r[0] == "err" and r[1].status == 409]
            others = [r for r in results if r not in wins and r not in conflicts]
            check("只有一个写成功", len(wins) == 1, f"成功 {len(wins)} 个")
            check("其余全部 409", len(conflicts) == WORKERS - 1, f"409 {len(conflicts)} 个")
            check("没有意外异常", not others, str(others[:1]))
            final = client.read_file("notes/race.md")
            check("落盘的是成功那一个", wins[0][1]["rev"] == final["rev"], f"rev={final['rev']}")

            print("相同内容并发存笔记")
            body = {
                "from": "api",
                "messages": [
                    {"role": "user", "text": "并发保存同一段对话"},
                    {"role": "assistant", "text": "只应该产生一篇笔记。"},
                ],
            }
            results = race(lambda i: client._request("POST", "/api/notes", body=body))
            ids = {str((r[1] or {}).get("id") or (r[1] or {}).get("note", {}).get("id"))
                   for r in results if r[0] == "ok"}
            committed = [r for r in results if r[0] == "ok" and (r[1] or {}).get("committed")]
            check("同一个 id", len(ids) == 1, str(ids))
            check("只有一次真正落盘", len(committed) == 1, f"committed {len(committed)}")
            # 排除上面那个并发写测试留下的 notes/race.md，只看笔记目录新产生的文件
            files = [f for f in (tmp / "home" / "notes").rglob("*.md") if f.name != "race.md"]
            check("磁盘上只有一篇", len(files) == 1, str([f.name for f in files]))

            print("同一会话并发写")
            results = race(lambda i: client._request(
                "PUT", "/api/threads/race-thread",
                body={"title": f"标题 {i}", "messages": [{"role": "user", "text": f"第 {i} 次"}]}))
            bad = [r for r in results if r[0] != "ok"]
            check("写入没有报错", not bad, str(bad[:1]))
            got = client.thread("race-thread")
            check("文件仍是合法 JSON", isinstance(got, dict) and isinstance(got.get("turns"), list),
                  str(got)[:80])
        finally:
            httpd.shutdown()
            httpd.server_close()
    print()
    print("全部通过" if not FAILED else f"{FAILED} 项失败")
    return 0 if not FAILED else 1


if __name__ == "__main__":
    raise SystemExit(main())
