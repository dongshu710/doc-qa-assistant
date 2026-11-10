"""设置改完必须立刻生效，不需要重启。

为什么单独一条：`RAGPipeline.settings` 是构造时的快照。设置面板保存后
如果不重载，面板显示「已保存／已生效」，判域却仍按启动时的阈值走。
这是最典型的「静默不生效」——用户会反复改、反复觉得没反应。

这里同时守两件事：
1. `reload_settings()` 之后 `pipe.settings` 换成新值；
2. 走 HTTP 保存设置时，服务端会自动调用它（而不是只写文件）。
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILED = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global FAILED
    if ok:
        print(f"  ok   {name}")
    else:
        FAILED += 1
        print(f"  FAIL {name}  {detail}")


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="settings_reload_")
    seed = Path(tmp) / "seed"
    seed.mkdir(parents=True)
    (seed / "a.md").write_text("# A\n\n## 一、条款\n\n内容。\n", encoding="utf-8")

    env = {
        # 必须指向不存在的配置文件：否则会读到开发机真实配置，
        # 界面配置优先级又高于环境变量，MIN_SCORE 改了也没反应。
        "APP_CONFIG": str(Path(tmp) / "none.json"),
        "KB_DIR": str(Path(tmp) / "kb"),
        "KB_SEED_DIR": str(seed),
        "KEYWORD_INDEX": str(Path(tmp) / "kw.json"),
        "RETRIEVAL": "bm25",
        "QUERY_EXPANSION": "off",
        "MIN_SCORE": "0.11",
        "KB_APPROVAL": "off",
    }
    old = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    for key in ("LLM_API_KEY", "DEEPSEEK_API_KEY"):
        os.environ.pop(key, None)

    try:
        from src.pipeline import RAGPipeline

        # pipeline 直接读知识库目录，不跑 kbstore 的 bootstrap，
        # 所以这里先把语料摆进目标目录。
        kb_dir = Path(tmp) / "kb"
        kb_dir.mkdir(parents=True, exist_ok=True)
        for item in seed.iterdir():
            (kb_dir / item.name).write_bytes(item.read_bytes())

        pipe = RAGPipeline(os.path.join(tmp, "kb"))
        check("初始阈值来自环境变量", abs(pipe.settings.min_score - 0.11) < 1e-9,
              str(pipe.settings.min_score))

        # 1) 直接调 reload_settings
        os.environ["MIN_SCORE"] = "0.22"
        pipe.reload_settings()
        check("reload_settings 后阈值更新",
              abs(pipe.settings.min_score - 0.22) < 1e-9,
              str(pipe.settings.min_score))

        # 2) 走 HTTP 保存设置：服务端必须自己调重载。
        #    这里用 llm.model，因为它是设置面板真正管得到的字段
        #    （SCHEMA 只有模型/路径/保留版本数几项，min_score 不在面板里）。
        from src.server import create_server

        httpd, http_pipe = create_server("127.0.0.1", 0)
        port = httpd.server_address[1]
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        try:
            check("初始模型", http_pipe.settings.model == "deepseek-chat",
                  http_pipe.settings.model)
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/settings",
                data=json.dumps({"llm": {"base_url": "https://api.deepseek.com/v1",
                                         "model": "deepseek-reasoner"}}).encode("utf-8"),
                headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=20) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            check("保存设置返回 200", bool(body.get("ok")),
                  json.dumps(body, ensure_ascii=False)[:160])
            check("保存后 pipeline 立即换模型",
                  http_pipe.settings.model == "deepseek-reasoner",
                  http_pipe.settings.model)
            check("响应里没有重载失败标记", not body.get("reload_error"),
                  str(body.get("reload_error")))
        finally:
            httpd.shutdown()
            httpd.server_close()
    finally:
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    print()
    if FAILED:
        print(f"{FAILED} 项失败")
        return 1
    print("SETTINGS RELOAD OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
