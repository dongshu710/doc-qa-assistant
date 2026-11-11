"""检索调试台：接口返回候选与阈值判定，页面能打开。

为什么这条要单独测：调试台的价值全在「判断准不准」——
`kept` 标错、阈值带不出去，用户会照着错的结论去调切分或调阈值，
比没有这个页面更浪费时间。
"""
import json
import os
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILED = 0
HOST = "127.0.0.1"


def check(name: str, ok: bool, detail: str = "") -> None:
    global FAILED
    if ok:
        print(f"  ok   {name}")
    else:
        FAILED += 1
        print(f"  FAIL {name}  {detail}")


def main() -> None:
    tmp = tempfile.mkdtemp(prefix="dbg_")
    seed = Path(tmp) / "seed"
    seed.mkdir(parents=True)
    (seed / "产品要素.md").write_text(
        "# 稳盈系列产品要素\n\n## 起购\n第1条 稳盈系列产品的起购金额为 1 元。\n\n"
        "## 期限\n第2条 稳盈系列产品期限分为 90 天、180 天、365 天三档。\n",
        encoding="utf-8")
    env = {
        "KB_DIR": os.path.join(tmp, "kb"),
        "KB_SEED_DIR": str(seed),
        "KEYWORD_INDEX": os.path.join(tmp, "kw.json"),
        "RETRIEVAL": "bm25",
        "QUERY_EXPANSION": "off",
        # 阈值故意设得很高：要让「检索到了但被挡掉」这条路径真的出现，
        # 否则 kept 永远是 true，测不到判定逻辑。
        "MIN_SCORE": "0.99",
        "TOP_K": "4",
        "KB_APPROVAL": "off",
    }
    old = {key: os.environ.get(key) for key in env}
    os.environ.update(env)
    for key in ("LLM_API_KEY", "DEEPSEEK_API_KEY", "API_KEYS"):
        os.environ.pop(key, None)

    from src.server import create_server

    httpd, _pipe = create_server(HOST, 0)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}"

    def post(path: str, body: dict):
        req = urllib.request.Request(
            base + path, data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    print("调试接口")
    status, body = post("/api/search/debug", {"query": "稳盈系列产品的起购金额是多少"})
    check("返回 200", status == 200, json.dumps(body, ensure_ascii=False)[:160])
    check("带阈值（面板要显示它）", body.get("min_score") == 0.99, str(body.get("min_score")))
    check("召回条数 = min(top_k×3, 全库块数)",
          body.get("recalled") == min(12, body.get("chunks_total") or 0),
          f"recalled={body.get('recalled')} chunks={body.get('chunks_total')}")
    check("候选带分数、章节、原文",
          all({"score", "section", "text"} <= set(item) for item in body["candidates"]),
          json.dumps(body["candidates"][:1], ensure_ascii=False)[:200])
    # 归一化后 top-1 的分数恒为 1.0，所以阈值 0.99 时它会留下。
    # 要验证的是「有候选被挡掉」这件事真的发生了，而不是强求全挡。
    check("阈值 0.99 时既有保留也有挡掉（这条路径真的走到）",
          0 <= body["kept"] < body["recalled"],
          f"kept={body['kept']} recalled={body['recalled']}")
    check("kept 与 min_score 判定一致",
          all(item["kept"] == (item["score"] >= body["min_score"])
              for item in body["candidates"]))
    check("带全库块数（判断是不是语料太少）", body.get("chunks_total", 0) >= 1,
          str(body.get("chunks_total")))
    check("带耗时", isinstance(body.get("elapsed_ms"), int), str(body.get("elapsed_ms")))

    print("参数校验")
    status, body = post("/api/search/debug", {"query": "   "})
    check("空 query → 400", status == 400, f"{status} {body}")
    status, body = post("/api/search/debug", {"query": "x", "top_k": "abc"})
    check("坏 top_k → 400 而不是 500", status == 400, f"{status} {body}")
    status, body = post("/api/search/debug", {"query": "稳盈", "top_k": 2})
    check("top_k=2 时召回 6 条（语料不足则按全库块数封顶）",
          body.get("recalled") == min(6, body.get("chunks_total") or 0),
          f"recalled={body.get('recalled')} chunks={body.get('chunks_total')}")

    print("页面")
    with urllib.request.urlopen(base + "/debug", timeout=10) as resp:
        html = resp.read().decode("utf-8")
        ctype = resp.headers.get("Content-Type", "")
    check("/debug 返回 HTML", resp.status == 200 and "text/html" in ctype, ctype)
    check("页面标题对得上", "检索调试" in html, html[:120])
    check("页面引了调试脚本", "/api/search/debug" in html, "脚本里应有这个地址")

    httpd.shutdown()
    httpd.server_close()
    for key, value in old.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value

    if FAILED:
        print(f"\nSEARCH DEBUG: {FAILED} FAILED")
        raise SystemExit(1)
    print("\nSEARCH DEBUG OK")


if __name__ == "__main__":
    main()
