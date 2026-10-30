"""笔记附件：存储、接口、导出内联、备份。

守四条底线：
1. **文件名来自调用方**——路径穿越、临时文件、越界读写一律挡住，
   而且挡住之后不能有文件落到附件目录外面；
2. **内容去重但同名的不同内容不互相覆盖**——否则「改了一版图回不去」；
3. **附件丢了要在导出里说出来**，不能让导出悄悄少一张图；
4. **备份跳过附件必须留痕**——用户照着「备份成功」去恢复，才发现图没了最糟。

不联网、不读开发机配置：临时存储区 + 手搓的 PNG/PDF 字节。
"""

from __future__ import annotations

import base64
import json
import sys
import tempfile
import zipfile
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# 测试机上可能有开发用的 app.json，里面的模型配置会真的被拿去调外部服务
import os  # noqa: E402
os.environ.setdefault("EMBEDDING_PROVIDER", "none")
os.environ.setdefault("APP_CONFIG", str(ROOT / "tests" / "__no_such_config__.json"))

from src import backup as backup_module  # noqa: E402
from src.backup import create as backup_create  # noqa: E402
from src.backup import restore as backup_restore  # noqa: E402
from src.notes import api as notes_api  # noqa: E402
from src.notes import assets as assets_mod  # noqa: E402
from src.notes import export as export_mod  # noqa: E402
from src.notes import mcp_server as mcp  # noqa: E402
from src.notes.model import NoteError  # noqa: E402
from src.notes.service import NoteService  # noqa: E402
from src.notes.store import NoteNotFound  # noqa: E402

FAILED = 0
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32
PDF = b"%PDF-1.4\n" + b"x" * 32


def check(name: str, ok: bool, detail: str = "") -> None:
    global FAILED
    if ok:
        print(f"  ok   {name}")
    else:
        FAILED += 1
        print(f"  FAIL {name}  {detail}")


def make_service() -> NoteService:
    home = tempfile.mkdtemp(prefix="jiyi-assets-")
    return NoteService(home, digest_mode="rule")


def save_note(service: NoteService, title: str, body: str) -> str:
    result = service.save({"messages": [{"role": "user", "text": body}],
                           "hint": {"title": title, "kind": "reference", "tags": ["附件"]}},
                          commit=True)
    return result["id"]


def test_roundtrip(service: NoteService, note_id: str) -> None:
    print("存 / 列 / 读 / 去重")
    saved = service.save_asset(note_id, "架构图.png", PNG)
    check("文件名带内容哈希前缀", saved["name"].startswith(saved["sha256"][:8] + "-"), saved["name"])
    check("展示名不带哈希", saved["display"] == "架构图.png", saved["display"])
    check("ref 符合存储区契约", saved["ref"] == f"assets/{note_id}/{saved['name']}", saved["ref"])
    check("图片给出可直接粘贴的 markdown",
          saved["markdown"] == f"![架构图.png]({saved['ref']})", saved["markdown"])
    check("认出是图片", saved["image"] is True)

    rows = service.list_assets(note_id)
    check("列表看得到刚传的", len(rows) == 1 and rows[0]["name"] == saved["name"], str(rows))

    data, mime = service.read_asset(note_id, saved["name"])
    check("读回来字节一致", data == PNG, str(len(data)))
    check("mime 按扩展名推断", mime == "image/png", mime)

    again = service.save_asset(note_id, "架构图.png", PNG)
    check("同内容复用同一份", again["name"] == saved["name"], again["name"])
    folder = assets_mod.asset_dir(service.store.home, note_id)
    check("磁盘上仍只有一份", len(list(folder.iterdir())) == 1, str(list(folder.iterdir())))

    other = service.save_asset(note_id, "架构图.png", PNG + b"x")
    check("同名不同内容不互相覆盖", other["name"] != saved["name"], other["name"])
    check("新内容单独占一份", len(list(folder.iterdir())) == 2)


def test_reject(service: NoteService, note_id: str) -> None:
    print("不该收的一律拒")
    for name, why in (("evil.exe", "可执行文件"), ("noext", "无扩展名"), ("", "空名"),
                      ("a.sh", "脚本")):
        try:
            service.save_asset(note_id, name, PNG)
            check(f"拒收{why}", False, "竟然收了")
        except assets_mod.AssetError:
            check(f"拒收{why}", True)
    try:
        service.save_asset(note_id, "big.png", b"x" * (assets_mod.MAX_BYTES + 1))
        check("拒收超大文件", False, "竟然收了")
    except assets_mod.AssetError as exc:
        check("拒收超大文件且状态码是 413", exc.status == 413, str(exc.status))
    try:
        service.save_asset(note_id, "a.png", b"")
        check("拒收空文件", False, "竟然收了")
    except assets_mod.AssetError:
        check("拒收空文件", True)
    try:
        service.save_asset("不存在的笔记", "a.png", PNG)
        check("附件必须挂在存在的笔记上", False, "竟然收了")
    except NoteNotFound:
        check("附件必须挂在存在的笔记上", True)


def test_traversal(service: NoteService, note_id: str) -> None:
    print("路径穿越")
    home = Path(service.store.home).resolve()
    for name in ("../evil.png", "..\\evil.png", f"../{note_id}/evil.png", "/etc/passwd"):
        try:
            service.read_asset(note_id, name)
            check(f"拒绝读 {name}", False, "竟然读了")
        except assets_mod.AssetError:
            check(f"拒绝读 {name}", True)

    got = service.save_asset(note_id, "../../evil.png", PNG)
    where = assets_mod.asset_dir(service.store.home, note_id).resolve() / got["name"]
    check("穿越名被按在附件目录里",
          where.parent == assets_mod.asset_dir(service.store.home, note_id).resolve(), str(where))
    check("没有逃出存储区", str(where).startswith(str(home)), str(where))
    check("穿越名里的目录被抹掉了", "/" not in got["name"] and ".." not in got["name"], got["name"])

    try:
        assets_mod.resolve(service.store.home, note_id, got["name"] + ".tmp")
        check("拒读临时文件", False, "竟然读了")
    except assets_mod.AssetError:
        check("拒读临时文件", True)


def test_delete(service: NoteService, note_id: str) -> None:
    print("删除")
    saved = service.save_asset(note_id, "架构图.png", PNG)
    out = service.delete_asset(note_id, saved["name"])
    check("删除成功", out.get("deleted") is True, str(out))
    check("删除会提醒正文引用会失效", "引用" in str(out.get("warning") or ""), str(out))
    folder = assets_mod.asset_dir(service.store.home, note_id)
    check("文件真的没了", not (folder / saved["name"]).exists())


def call_api(service: NoteService, method: str, path: str, query=None, body=None):
    """dispatch 用抛异常表示错误，这里统一折成 (status, payload, headers)。"""
    try:
        return notes_api.dispatch(service, method, path, query or {}, body)
    except notes_api.ApiError as exc:
        return exc.status, exc.payload, dict(exc.headers or {})


def test_api(service: NoteService, note_id: str) -> None:
    print("HTTP 契约层")
    raw = base64.b64encode(PNG).decode("ascii")
    status, payload, _ = call_api(
        service, "POST", f"/api/notes/{note_id}/assets",
        body={"name": "图.png", "data": "data:image/png;base64," + raw})
    check("上传返回 201", status == 201, str(status))
    check("data URL 前缀也能吃", payload["name"].endswith("图.png"), payload["name"])
    name = payload["name"]

    status, payload, _ = call_api(
        service, "POST", f"/api/notes/{note_id}/assets",
        body={"name": "图.png", "data": "!!!not base64!!!"})
    check("坏 base64 返回 400", status == 400 and payload.get("error") == "invalid_argument",
          f"{status} {payload}")

    status, payload, _ = call_api(service, "GET", f"/api/notes/{note_id}/assets")
    check("列表返回 200 且带总量", status == 200 and payload["bytes"] >= len(PNG), str(payload))

    status, payload, extra = call_api(
        service, "GET", f"/api/notes/{note_id}/assets/{name}")
    check("单文件走 __binary__ 通道", payload.get("__binary__") is True, str(list(payload)))
    check("字节原样交出去", payload.get("content") == PNG, str(len(payload.get("content") or b"")))
    check("带 Content-Disposition", "Content-Disposition" in extra, str(extra))
    check("图片是 inline 而不是下载", "inline" in extra.get("Content-Disposition", ""),
          extra.get("Content-Disposition", ""))

    # 中文名在 URL 里必然是百分号编码的。这一条只走 dispatch（不碰 service），
    # 正是为了防止「单元测试直接调 service 绕过了 URL」导致 404 漏网
    status, payload, _ = call_api(service, "GET",
                                  f"/api/notes/{note_id}/assets/{quote(name)}")
    check("中文名经 URL 编码后仍能读到",
          status == 200 and payload.get("content") == PNG, str(status))
    status, _, _ = call_api(service, "GET",
                            f"/api/notes/{note_id}/assets/{quote('../evil.png')}")
    check("编码过的穿越路径同样被拒", status in (400, 404), str(status))

    status, _, _ = call_api(service, "DELETE", f"/api/notes/{note_id}/assets/{name}")
    check("未确认的删除被拒 400", status == 400, str(status))

    status, payload, _ = call_api(service, "DELETE", f"/api/notes/{note_id}/assets/{name}",
                                  query={"confirm": ["1"]})
    check("确认后删除成功", status == 200 and payload.get("deleted"), str(payload))

    status, _, _ = call_api(service, "GET",
                            f"/api/notes/{note_id}/assets/{quote('不存在的文件.png')}")
    check("读不存在的附件是 404", status == 404, str(status))


def test_export(service: NoteService, note_id: str) -> None:
    print("导出内联")
    saved = service.save_asset(note_id, "架构图.png", PNG)
    service.patch(note_id, {"sections": {"要点": "看这张图：\n" + saved["markdown"]}}, force=True)
    html = export_mod.render_html([service.get(note_id)], home=service.store.home)
    check("图片内联成 data URI", "data:image/png;base64," in html)
    check("导出里没有外链附件路径", f"/api/notes/{note_id}/assets/" not in html)

    service.delete_asset(note_id, saved["name"])
    html = export_mod.render_html([service.get(note_id)], home=service.store.home)
    check("附件丢了要原位标注", "附件已丢失" in html)

    doc = service.save_asset(note_id, "合同.pdf", PDF)
    html = export_mod.render_html([service.get(note_id)], home=service.store.home)
    check("正文没提到的附件单独列出来", "附件</h3>" in html and "合同.pdf" in html,
          str(len(html)))
    check("非图片附件内联成链接", "data:application/pdf;base64," in html)

    plain = export_mod.render_html([service.get(note_id)])
    check("不给 home 就完全不碰附件", "data:image/png" not in plain and "data:application/pdf" not in plain)
    check("不给 home 时老行为不变", "附件</h3>" not in plain)

    service.delete_asset(note_id, doc["name"])


def test_backup(service: NoteService, note_id: str) -> None:
    print("备份覆盖附件")
    saved = service.save_asset(note_id, "架构图.png", PNG)
    result = backup_create(service.store.home)
    with zipfile.ZipFile(result["path"]) as zf:
        names = zf.namelist()
    check("备份包含附件", any(n.startswith("assets/") for n in names), str(names))
    check("没超限就没有警告", not result["warnings"], str(result["warnings"]))

    old = backup_module.ASSET_MAX_TOTAL_BYTES
    backup_module.ASSET_MAX_TOTAL_BYTES = 16
    try:
        capped = backup_create(service.store.home)
    finally:
        backup_module.ASSET_MAX_TOTAL_BYTES = old
    check("超限附件被跳过而不是让备份失败", capped["skipped"] >= 1, str(capped))
    check("跳过要说出来", bool(capped["warnings"]) and "附件" in capped["warnings"][0],
          str(capped["warnings"]))

    service.delete_asset(note_id, saved["name"])
    backup_restore(service.store.home, result["name"], force=True)
    check("恢复后附件回来了",
          (assets_mod.asset_dir(service.store.home, note_id) / saved["name"]).exists())


def test_mcp(service: NoteService, note_id: str) -> None:
    print("MCP 工具与资源")
    names = [item["name"] for item in mcp.tools()]
    check("工具清单含附件两件套",
          "save_attachment" in names and "list_attachments" in names, str(names))

    raw = base64.b64encode(PNG).decode("ascii")
    got = json.loads(mcp.call_tool(service, "save_attachment",
                                   {"id": note_id, "name": "图.png", "data": raw}))
    check("MCP 存附件返回可粘贴片段", got["markdown"].startswith("!["), got["markdown"])
    check("MCP 存附件返回大小", got["size"] == len(PNG), str(got["size"]))

    try:
        mcp.call_tool(service, "save_attachment",
                      {"id": note_id, "name": "a.png", "data": "!!!not base64!!!"})
        check("坏 base64 被拒", False, "竟然收了")
    except NoteError:
        check("坏 base64 被拒", True)

    listed = json.loads(mcp.call_tool(service, "list_attachments", {"id": note_id}))
    check("MCP 能列出附件", listed["count"] >= 1, str(listed["count"]))
    name = listed["items"][0]["name"]

    res = mcp.read_resource(service, f"notes://asset/{note_id}/{name}")
    check("图片资源走 blob", "blob" in res["contents"][0], str(list(res["contents"][0])))
    check("blob 就是那段 base64", res["contents"][0]["blob"] == raw)

    res = mcp.read_resource(service, f"notes://asset/{note_id}/{name}")
    check("资源 mime 正确", res["contents"][0]["mimeType"] == "image/png",
          res["contents"][0]["mimeType"])

    txt = service.save_asset(note_id, "记录.csv", b"a,b\n1,2\n")
    res = mcp.read_resource(service, f"notes://asset/{note_id}/{txt['name']}")
    check("文本附件走 text 而不是 blob", "text" in res["contents"][0], str(res["contents"][0]))

    try:
        mcp.read_resource(service, f"notes://asset/{note_id}/")
        check("资源名缺失被拒", False, "竟然通过了")
    except mcp.RpcError:
        check("资源名缺失被拒", True)


def main() -> int:
    service = make_service()
    note_id = save_note(service, "带附件的笔记", "这是一篇用来挂附件的笔记。")
    test_roundtrip(service, note_id)
    test_reject(service, note_id)
    test_traversal(service, note_id)
    test_delete(service, note_id)
    test_api(service, note_id)
    test_export(service, note_id)
    test_backup(service, note_id)
    test_mcp(service, note_id)
    if FAILED:
        print(f"\n附件测试失败 {FAILED} 项")
        return 1
    print("\nNOTES ASSETS OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
