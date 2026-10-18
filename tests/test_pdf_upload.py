"""PDF 上传端到端冒烟：解析 → 入库 → 能答 → 能删。

用运行时 python（没有 pypdf）跑，确保验证的是**内置解析器**，
而不是 .venv 里那份 pypdf——上传能力必须在零第三方依赖下成立。

  python tests/test_pdf_upload.py
"""
import base64
import json
import os
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.server import create_server  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"
HOST = "127.0.0.1"


_KEY_ENVS = ("LLM_API_KEY", "DEEPSEEK_API_KEY")


def _force_offline():
    """临时清掉密钥，确保测的是「无 Key 也能跑」的确定性链路（退出时还原）。"""
    saved = {k: os.environ.pop(k, None) for k in _KEY_ENVS}
    return saved


def _restore_env(saved):
    for k, v in saved.items():
        if v is not None:
            os.environ[k] = v


def _start():
    httpd, _pipe = create_server(HOST, 0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, httpd.server_address[1]


def _post(port: int, path: str, payload: dict):
    req = urllib.request.Request(
        f"http://{HOST}:{port}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "ignore")
        try:
            return exc.code, json.loads(body)
        except json.JSONDecodeError:
            return exc.code, {"raw": body[:200]}


def _b64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("ascii")


def main() -> int:
    if not (FIXTURES / "sample_text.pdf").exists():
        print("缺少测试样本，先跑：.venv/Scripts/python.exe tests/fixtures/build_fixtures.py")
        return 1

    saved = _force_offline()
    httpd, port = _start()
    kb_dir = ROOT / "data" / "knowledge"
    raw_dir = ROOT / "data" / "raw"
    created_md: list[str] = []
    created_raw: list[str] = []
    upload_name = "云杉计划经费管理办法.pdf"   # 用可读名字，便于在看板上辨认

    try:
        # 1) 扫描件（无文本层）→ 422 + OCR 提示，不能静默入库
        code, body = _post(port, "/api/knowledge/upload_pdf", {
            "name": "扫描件样本.pdf",
            "data_b64": _b64(FIXTURES / "sample_scanned.pdf"),
        })
        assert code == 422, f"扫描件应被拒，实际 {code} {body}"
        assert "OCR" in (body.get("error") or ""), body
        print(f"[1] 扫描件被拒（{code}）：{(body.get('error') or '')[:46]}…")

        # 2) 正常 PDF → 解析入库
        code, body = _post(port, "/api/knowledge/upload_pdf", {
            "name": upload_name,
            "data_b64": _b64(FIXTURES / "sample_text.pdf"),
        })
        assert code == 200 and body.get("ok"), f"上传失败 {code} {body}"
        assert body["pages"] == 1 and body["chars"] > 100, body
        assert body["added_chunks"] > 0, body
        created_md.append(body["md"])
        created_raw.append(upload_name)
        print(f"[2] 上传成功：{body['md']}｜{body['pages']} 页 / {body['chars']} 字 / "
              f"引擎 {body['engine']} / 新增 {body['added_chunks']} 块")

        # 3) 立刻能答（数字只在刚上传的文档里出现过）
        code, ans = _post(port, "/api/ask", {"query": "云杉计划的年度差旅报销上限是多少"})
        assert code == 200 and ans.get("behavior") == "answer", f"应能回答：{ans.get('behavior')}"
        assert "8.7" in ans["answer"].replace(" ", ""), f"答案没带上关键数字：{ans['answer'][:80]}"
        print(f"[3] 问答命中：{ans['answer'][:60]}…（mode={ans['mode']}, 引用 {len(ans.get('citations') or [])} 条）")

        # 4) 删除 → 索引回落
        code, body2 = _post(port, "/api/knowledge/delete", {"name": body["md"]})
        assert code == 200 and body2.get("ok"), body2
        created_md.clear()
        print(f"[4] 删除成功，剩余 {body2['chunks']} 块")

        # 5) 文件名与内容校验
        cases = [
            ("../evil.pdf", _b64(FIXTURES / "sample_text.pdf"), 400),
            ("a.txt", _b64(FIXTURES / "sample_text.pdf"), 400),
            ("fake.pdf", base64.b64encode(b"not a pdf at all").decode(), 400),
        ]
        for name, blob, want in cases:
            code, body3 = _post(port, "/api/knowledge/upload_pdf", {"name": name, "data_b64": blob})
            assert code == want, f"{name} 应返回 {want}，实际 {code} {body3}"
        print("[5] 非法文件名 / 非 PDF 均被拒（400）")

        assert not list(kb_dir.glob("evil*")), "目录穿越留下了文件"
        print("PDF 上传冒烟通过")
        return 0
    finally:
        for md in created_md:  # 异常退出也要清理，避免污染知识库
            target = kb_dir / md
            if target.exists():
                target.unlink()
        for raw in created_raw:  # 原始 PDF 也清掉，否则下次批量导入会重复入库
            target = raw_dir / raw
            if target.exists():
                target.unlink()
        httpd.shutdown()
        _restore_env(saved)


if __name__ == "__main__":
    raise SystemExit(main())
