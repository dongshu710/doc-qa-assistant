"""契约与实现不许各走各的。

为什么单独一条：`src/notes/contract.py` 里的 OpenAPI 是手写的，与实际路由
（`notes/api.py::dispatch`）之间没有任何编译期联系。上一版就漏登记了
`/export`、`/rebuild`、`/assets` 三个端点——文档看起来完整，实际调不通的
接口反而没人知道。

这里做双向比对：契约里有的必须真能路由，能路由的必须写进契约。
另外每条路由都真跑一次（用真实笔记与真实附件），确保不是「登记了但处理器
一进去就抛」的假通过。
"""

from __future__ import annotations

import base64
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.notes import api as notes_api  # noqa: E402
from src.notes.contract import notes_paths  # noqa: E402
from src.notes.service import NoteService  # noqa: E402

FAILED = 0
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 40

# dispatch 真正认识的路由。加接口时这里必须跟着加，否则下面的双向比对会失败——
# 这正是它存在的意义：漏登记会被拦住，而不是等用户调不通才发现。
ROUTES = {
    ("GET", "/api/notes"),
    ("POST", "/api/notes"),
    ("GET", "/api/notes/export"),
    ("GET", "/api/notes/stats"),
    ("POST", "/api/notes/rebuild"),
    ("GET", "/api/notes/{id}"),
    ("PATCH", "/api/notes/{id}"),
    ("DELETE", "/api/notes/{id}"),
    ("GET", "/api/notes/{id}/assets"),
    ("POST", "/api/notes/{id}/assets"),
    ("GET", "/api/notes/{id}/assets/{name}"),
    ("DELETE", "/api/notes/{id}/assets/{name}"),
}


def check(name: str, ok: bool, detail: str = "") -> None:
    global FAILED
    if ok:
        print(f"  ok   {name}")
    else:
        FAILED += 1
        print(f"  FAIL {name}  {detail}")


def declared() -> set[tuple[str, str]]:
    out: set[tuple[str, str]] = set()
    for path, spec in notes_paths().items():
        for method in spec:
            if method.lower() in ("get", "post", "patch", "delete", "put"):
                out.add((method.upper(), path))
    return out


def test_bidirectional() -> None:
    print("契约与路由双向比对")
    spec = declared()
    missing = sorted(ROUTES - spec)
    extra = sorted(spec - ROUTES)
    check("契约没有遗漏能路由的接口", not missing, str(missing))
    check("契约没有登记不存在的接口", not extra, str(extra))
    check("契约条数与路由条数一致", len(spec) == len(ROUTES),
          f"契约 {len(spec)} / 路由 {len(ROUTES)}")


def test_each_route_runs(service: NoteService) -> None:
    """每条路由真跑一次：登记了但一进去就 500 的，等于没实现。"""
    print("每条路由都真跑一次")
    status, note, _ = notes_api.dispatch(service, "POST", "/api/notes", {}, {
        "messages": [{"role": "user", "text": "灰度分两批，第一批 10%。"}],
        "hint": {"title": "部署方案", "kind": "decision", "tags": ["上线"]},
    })
    note_id = note["id"]
    status, asset, _ = notes_api.dispatch(service, "POST", f"/api/notes/{note_id}/assets", {}, {
        "name": "图.png", "data": base64.b64encode(PNG).decode("ascii")})
    asset_name = asset["name"]

    cases = [
        ("GET", "/api/notes", {}, None, 200),
        ("GET", "/api/notes/export?format=html", {}, None, 200),
        ("GET", "/api/notes/stats", {}, None, 200),
        ("POST", "/api/notes/rebuild", {}, {"semantic": "off"}, 200),
        ("GET", f"/api/notes/{note_id}", {}, None, 200),
        ("PATCH", f"/api/notes/{note_id}", {}, {"title": "部署方案（修订）", "force": True}, 200),
        ("GET", f"/api/notes/{note_id}?section=结论", {}, None, 200),
        ("GET", f"/api/notes/{note_id}/assets", {}, None, 200),
        ("GET", f"/api/notes/{note_id}/assets/{asset_name}", {}, None, 200),
        ("DELETE", f"/api/notes/{note_id}/assets/{asset_name}", {"confirm": ["1"]}, None, 200),
    ]
    for method, path, query, body, want in cases:
        clean = path.split("?")[0]
        query = dict(query)
        if "?" in path:
            key, value = path.split("?", 1)[1].split("=", 1)
            query[key] = [value]
        try:
            status, payload, _ = notes_api.dispatch(service, method, clean, query, body)
        except notes_api.ApiError as exc:
            check(f"{method} {path}", False,
                  f"抛了 {exc.status} {exc.payload.get('error')}")
            continue
        check(f"{method} {path}", status == want, f"{status} != {want}")

    status, payload, _ = notes_api.dispatch(
        service, "DELETE", f"/api/notes/{note_id}", {"confirm": ["1"]}, None)
    check("DELETE /api/notes/{id}", status == 200, str(status))


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        service = NoteService(tmp)
        test_bidirectional()
        test_each_route_runs(service)
    print()
    if FAILED:
        print(f"{FAILED} 项失败")
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
