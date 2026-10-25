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

    # 协议头大小写不敏感：HTTPS:// 是合法地址，不该被拒
    upper = appconfig.update({"llm": {"base_url": "HTTPS://api.example.com/v1"}})
    check("大写协议头被规范化", upper["llm"]["base_url"] == "https://api.example.com/v1",
          upper["llm"]["base_url"])

    print("存储位置")
    custom = tmp / "my-notes"
    view = appconfig.update({"notes": {"home": str(custom)}})
    check("自定义目录已创建", custom.is_dir())
    check("视图回显自定义目录", view["notes"]["home"] == str(custom))

    print("路径清洗")
    check("去掉成对双引号", appconfig.clean_path('"D:\\notes"') == "D:\\notes")
    check("去掉成对单引号", appconfig.clean_path("'D:\\notes'") == "D:\\notes")
    check("中文引号也处理", appconfig.clean_path("“D:\\notes”") == "D:\\notes")
    check("首尾空白清掉", appconfig.clean_path("  D:\\notes  ") == "D:\\notes")
    check("带引号也能通过校验", appconfig._check_home(f'"{custom}"') == str(custom))
    check("空串原样返回", appconfig.clean_path("   ") == "")
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
    check("坏文件说明坏在哪一行", "第 1 行" in view["config_error"], view["config_error"])
    broken = app_file.read_text(encoding="utf-8")
    appconfig.update({"llm": {"model": "after-broken"}})
    view = appconfig.view()
    check("覆盖前自动备份坏文件", bool(view["config_backup"]), view["config_backup"])
    backup = Path(view["config_backup"]) if view["config_backup"] else None
    check("备份内容与原文一致", bool(backup and backup.exists()
                                and backup.read_text(encoding="utf-8") == broken))
    check("覆盖后错误标记清掉", view["config_error"] == "", view["config_error"])

    print("开关取值")
    app_file.write_text('{"notes": {"store_chat": "false"}}', encoding="utf-8")
    appconfig._cache = None
    appconfig._cache_stat = None
    check("手写字符串 false 就是关", appconfig.store_chat() is False)
    check("映射成环境变量也是 off", appconfig.as_env().get("STORE_CHAT") == "off")
    check("接口传字符串 false 存成布尔假",
          appconfig.update({"notes": {"store_chat": "false"}})["notes"]["store_chat"] is False)
    try:
        appconfig.update({"notes": {"store_chat": "maybe"}})
        check("无法识别的开关值被拒绝", False)
    except ValueError:
        check("无法识别的开关值被拒绝", True)

    print("配置写权限探测")
    probe_dir = tmp / "probe-dir"
    probe_dir.mkdir()
    keep = probe_dir / ".write-test"
    keep.write_text("用户自己的文件", encoding="utf-8")
    appconfig._check_home(str(probe_dir))
    check("探测写权限不删同名文件", keep.exists()
          and keep.read_text(encoding="utf-8") == "用户自己的文件")

    print("手改时间戳")
    reset(tmp / "hand.json")
    app_file = tmp / "hand.json"
    app_file.write_text('{"notes": {"last_export_at": "2026-10-01T10:00:00"}}',
                        encoding="utf-8")
    appconfig._cache = None
    appconfig._cache_stat = None
    try:
        state = appconfig.backup_state(3)
        check("无时区时间戳不抛异常", True)
        check("无时区时间戳按本机时区算", state["days"] is not None and state["days"] > 20,
              str(state))
    except TypeError as exc:
        check("无时区时间戳不抛异常", False, str(exc))

    print("配置优先级")
    reset(tmp / "priority.json")
    os.environ["LLM_MODEL"] = "from-env"
    appconfig.update({"llm": {"model": "from-ui"}})
    from src import config as cfg
    cfg._OVERRIDES_AT = -99.0        # 跳过 1 秒缓存，模拟下一次请求
    check("界面配置压过环境变量", cfg.load_settings().model == "from-ui",
          cfg.load_settings().model)
    del os.environ["LLM_MODEL"]

    print("保存即生效")
    reset(tmp / "instant.json")
    cfg._OVERRIDES_AT = 0.0
    cfg.load_settings()              # 先让 1 秒缓存装上一次旧值
    appconfig.update({"llm": {"model": "just-saved"}})
    check("同秒内保存立刻生效（不吃旧缓存）", cfg.load_settings().model == "just-saved",
          cfg.load_settings().model)

    print("备份提醒")
    reset(tmp / "backup.json")
    never = appconfig.backup_state(5)
    check("从未备份且有笔记要提醒", never["due"] is True and never["text"] == "还没备份过",
          str(never))
    check("空库不提醒", appconfig.backup_state(0)["due"] is False)
    appconfig.mark_exported()
    fresh = appconfig.backup_state(5)
    check("导出后不再提醒", fresh["due"] is False, str(fresh))
    check("文案显示今天", fresh["text"] == "今天备份过", fresh["text"])
    check("上次导出时间已落盘", bool(appconfig.last_export_at()))

    print("环境变量兜底")
    reset(tmp / "envonly.json")
    os.environ["STORE_CHAT"] = "on"
    check("配置没写时认 STORE_CHAT", appconfig.store_chat() is True)
    check("视图回显的也是生效值", appconfig.view()["notes"]["store_chat"] is True)
    appconfig.update({"notes": {"store_chat": False}})
    check("配置写过就以配置为准", appconfig.store_chat() is False)
    os.environ.pop("STORE_CHAT", None)

    print("编码容错")
    gbk = tmp / "gbk.json"
    gbk.write_bytes('{"llm": {"model": "深度求索"}}'.encode("gbk"))
    reset(gbk)
    check("GBK 配置能读出来", appconfig.view()["llm"]["model"] == "深度求索",
          appconfig.view()["llm"]["model"])
    appconfig.update({"llm": {"model": "deepseek-chat"}})
    try:
        gbk.read_bytes().decode("utf-8")
        check("保存后统一写回 UTF-8", True)
    except UnicodeDecodeError:
        check("保存后统一写回 UTF-8", False)
    binary = tmp / "binary.json"
    binary.write_bytes(b"\xff\xfe\x00\x01")
    reset(binary)
    try:
        view = appconfig.view()
        check("编码无法识别不抛异常", True)
        check("编码无法识别有提示", "编码" in view["config_error"], view["config_error"])
    except UnicodeDecodeError as exc:
        check("编码无法识别不抛异常", False, str(exc))

    print("页面挂载")
    from src.theme import FILES_HTML, SETTINGS_HTML, nav
    from src.web_pages import ASK_HTML, KB_HTML
    check("导航有设置入口", 'id="setBtn"' in nav("ask"))
    check("导航有文件入口", 'id="filesBtn"' in nav("ask") and 'id="filesCount"' in nav("ask"))
    check("已存不再重复出现在设置里", 'data-tab="save"' not in SETTINGS_HTML)
    check("文件抽屉结构独立", 'id="filesPanel"' in FILES_HTML and 'id="filesList"' in FILES_HTML)
    for label, html in (("问答页", ASK_HTML), ("知识库页", KB_HTML)):
        parser = IdStack()
        parser.feed(html)
        check(f"{label}含设置面板", "setPanel" in parser.found)
        check(f"{label}含文件抽屉", "filesPanel" in parser.found)
        for panel_id in ("setPanel", "filesPanel"):
            chain = parser.found.get(panel_id, [])
            check(f"{label}{panel_id} 挂在 body 下", chain and chain[-1] == "body", str(chain))
        check(f"{label}含储存开关", 'id="setStoreChat"' in html)
        check(f"{label}含存储位置控件", 'id="setHomeSeg"' in html)
        check(f"{label}含接口控件", 'id="setBase"' in html)
        check(f"{label}设置脚本已注入", "setMcpInstall" in html)
        check(f"{label}文件脚本已注入", "filesExport" in html)

    print(f"\n{passed} 项通过，{len(failures)} 项失败")
    if failures:
        print("失败项：" + "、".join(failures))
        return 1
    print("SETTINGS OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
