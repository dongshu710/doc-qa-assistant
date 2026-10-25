"""设置面板：配置读写、掩码、校验、存储位置生效、页面挂载位置。

跑法：
    python tests/test_settings.py

为什么单独一个文件：配置层是本轮改造里唯一「用户直接改关键项」的通路，
它错了会让界面看起来能点、实际不生效，比页面错位更难发现。
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

failures: list[str] = []
passed = 0


def check(name: str, cond: bool, extra: str = "") -> None:
    global passed
    if cond:
        passed += 1
        print(f"  ok   {name}")
    else:
        failures.append(name)
        print(f"  FAIL {name} {extra}")


def reset(app_file: Path) -> None:
    """切换配置文件后清掉模块缓存，模拟进程重新读取。"""
    os.environ["APP_CONFIG"] = str(app_file)
    from src import appconfig
    appconfig._cache = None
    appconfig._cache_stat = None


# SVG 内部标签会被 HTMLParser 当成未闭合元素，整棵跳过即可
VOID = {"meta", "link", "br", "img", "input", "hr", "source",
        "svg", "path", "circle", "rect", "g", "defs", "use", "line", "polyline"}


class IdStack(HTMLParser):
    """记录每个 id 出现时的祖先链，用来断言「这个面板没被别人包住」。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.found: dict[str, list[str]] = {}

    def handle_starttag(self, tag, attrs):
        ident = dict(attrs).get("id")
        if ident:
            self.found[ident] = list(self.stack)
        if tag not in VOID:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        if tag in self.stack:
            while self.stack and self.stack.pop() != tag:
                pass


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="rag-settings-"))
    app_file = tmp / "app.json"
    reset(app_file)

    from src import appconfig

    print("默认值")
    view = appconfig.view()
    check("未配置时 key 为空", view["llm"]["api_key_set"] is False)
    check("未配置时关闭储存", view["notes"]["store_chat"] is False)
    check("配置文件路径可读", view["config_path"].endswith("app.json"))

    print("写入与掩码")
    view = appconfig.update({
        "llm": {"base_url": "https://api.example.com/v1", "model": "demo-model",
                "api_key": "sk-abcdefghijklmnop"},
        "notes": {"store_chat": True},
    })
    check("地址已生效", view["llm"]["base_url"] == "https://api.example.com/v1")
    check("模型已生效", view["llm"]["model"] == "demo-model")
    check("密钥只回掩码", view["llm"]["api_key_masked"] == "sk-abc******mnop",
          view["llm"]["api_key_masked"])
    check("掩码不含原文", "abcdefghij" not in json.dumps(view, ensure_ascii=False))
    check("储存开关已开", view["notes"]["store_chat"] is True)
    on_disk = json.loads(app_file.read_text(encoding="utf-8"))
    check("落盘结构是嵌套的", on_disk["llm"]["model"] == "demo-model")

    print("校验")
    for name, patch in (
        ("拒绝非 http 地址", {"llm": {"base_url": "api.example.com"}}),
        ("拒绝空模型", {"llm": {"model": "   "}}),
        ("拒绝相对路径", {"notes": {"home": "notes"}}),
    ):
        try:
            appconfig.update(patch)
            check(name, False)
        except ValueError:
            check(name, True)

    print("存储位置")
    custom = tmp / "my-notes"
    view = appconfig.update({"notes": {"home": str(custom)}})
    check("自定义目录已创建", custom.is_dir())
    check("视图回显自定义目录", view["notes"]["home"] == str(custom))
    from src.notes.store import NoteStore
    store = NoteStore()
    check("笔记库采用界面里选的位置", str(store.home) == str(custom.resolve()),
          f"{store.home} vs {custom.resolve()}")
    appconfig.update({"notes": {"home": ""}})
    check("清空后回到默认位置", appconfig.get("notes.home") in (None, ""))

    print("坏文件不致命")
    app_file.write_text("{ 这不是 JSON", encoding="utf-8")
    appconfig._cache = None
    appconfig._cache_stat = None
    view = appconfig.view()
    check("坏文件按未配置处理", view["llm"]["api_key_set"] is False)

    print("配置优先级")
    reset(tmp / "priority.json")
    os.environ["LLM_MODEL"] = "from-env"
    appconfig.update({"llm": {"model": "from-ui"}})
    from src import config as cfg
    cfg._OVERRIDES_AT = -99.0        # 跳过 1 秒缓存，模拟下一次请求
    check("界面配置压过环境变量", cfg.load_settings().model == "from-ui",
          cfg.load_settings().model)
    del os.environ["LLM_MODEL"]

    print("页面挂载")
    from src.theme import SETTINGS_HTML, nav
    from src.web_pages import ASK_HTML, KB_HTML
    check("导航有设置入口", 'id="setBtn"' in nav("ask"))
    for label, html in (("问答页", ASK_HTML), ("知识库页", KB_HTML)):
        parser = IdStack()
        parser.feed(html)
        check(f"{label}含设置面板", "setPanel" in parser.found)
        chain = parser.found.get("setPanel", [])
        check(f"{label}设置面板不在内容容器内", chain and chain[-1] == "body",
              str(chain))
        check(f"{label}含储存开关", 'id="setStoreChat"' in html)
        check(f"{label}含存储位置控件", 'id="setHomeSeg"' in html)
        check(f"{label}含接口控件", 'id="setBase"' in html)
        check(f"{label}设置脚本已注入", "setMcpInstall" in html)

    print(f"\n{passed} 项通过，{len(failures)} 项失败")
    if failures:
        print("失败项：" + "、".join(failures))
        return 1
    print("SETTINGS OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
