"""DOCX 上传 + 自动出题 + 一起跑：端到端冒烟（零第三方依赖）。

覆盖三件事：
1. `.docx` 解析（标题层级、表格转 Markdown）；
2. 上传入库并立即可问；
3. 给该文档自动生成评测用例，和基础集一起跑；文档删除后用例被跳过。

  python tests/test_docx_upload.py
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

from src.docx_text import extract_docx  # noqa: E402
from src.server import create_server  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"
DOCX = FIXTURES / "sample_doc.docx"
UPLOAD_NAME = "银杏计划采购管理办法.docx"
HOST = "127.0.0.1"


_KEY_ENVS = ("LLM_API_KEY", "SENSENOVA_API_KEY", "DEEPSEEK_API_KEY")


def _force_offline():
    """临时清掉密钥，确保测的是「无 Key 也能跑」的确定性链路（退出时还原）。"""
    saved = {k: os.environ.pop(k, None) for k in _KEY_ENVS}
    return saved


def _restore_env(saved):
    for k, v in saved.items():
        if v is not None:
            os.environ[k] = v


def _post(port: int, path: str, payload: dict):
    req = urllib.request.Request(
        f"http://{HOST}:{port}{path}", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8", "ignore") or "{}")


def _get(port: int, path: str):
    with urllib.request.urlopen(f"http://{HOST}:{port}{path}", timeout=30) as resp:
        return json.loads(resp.read().decode())


def _drop_cases(doc_id: str) -> None:
    """清掉本测试生成的用例，避免污染看板和后续评测。"""
    path = ROOT / "tests" / "eval_cases_docs.jsonl"
    if not path.exists():
        return
    keep = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        case = json.loads(line)
        if case.get("doc_id") != doc_id:
            keep.append(json.dumps(case, ensure_ascii=False))
    if keep:
        path.write_text("\n".join(keep) + "\n", encoding="utf-8")
    else:
        path.unlink(missing_ok=True)
    # 运行报告也清掉，否则看板「上次运行」会停测试留下的 0/0
    (ROOT / "tests" / "report_doc_cases.json").unlink(missing_ok=True)


def main() -> int:
    assert DOCX.exists(), "缺少 docx 样本，先跑 .venv/Scripts/python.exe tests/fixtures/build_fixtures.py"

    # 1) 解析器
    md, meta = extract_docx(DOCX.read_bytes(), title="银杏计划采购管理办法")
    assert meta["tables"] == 1 and meta["headings"] >= 4, meta
    assert "## 二、审批额度" in md and "12.6 万元" in md, md[:200]
    assert "| 需求提报 | 3 个工作日 | 业务部门 |" in md, "表格没还原成 Markdown"
    print(f"[1] DOCX 解析：{meta['paragraphs']} 段 / {meta['headings']} 个标题 / {meta['tables']} 张表")

    saved = _force_offline()
    httpd, _pipe = create_server(HOST, 0)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    kb_dir = ROOT / "data" / "knowledge"
    raw_dir = ROOT / "data" / "raw"
    md_name = ""
    doc_id = ""

    try:
        # 2) 上传
        code, up = _post(port, "/api/knowledge/upload_file", {
            "name": UPLOAD_NAME,
            "data_b64": base64.b64encode(DOCX.read_bytes()).decode(),
        })
        assert code == 200 and up.get("ok"), up
        md_name = up["md"]
        doc_id = md_name.rsplit(".", 1)[0]
        assert md_name.startswith("docx_"), md_name
        assert up["added_chunks"] >= 2, up
        print(f"[2] 上传成功：{md_name}｜{up['paragraphs']} 段 / {up['tables']} 表 / "
              f"新增 {up['added_chunks']} 块 / 引擎 {up['engine']}")

        # 3) 立即可问
        code, ans = _post(port, "/api/ask", {"query": "银杏计划单笔采购超过多少金额需要报采购委员会审批"})
        assert code == 200 and ans.get("behavior") == "answer", ans
        assert "12.6" in ans["answer"].replace(" ", ""), ans["answer"][:120]
        print(f"[3] 问答命中：{ans['answer'][:56]}…")

        # 4) 自动出题（强制走 heuristic，保证无 Key 也能复现）
        code, gen = _post(port, "/api/cases/from_doc", {"name": md_name, "n": 2, "use_llm": False})
        assert code == 200 and gen.get("ok") and gen["added"] >= 1, gen
        for case in gen["cases"]:
            assert case["doc_id"] == doc_id, case
            assert case["expect"]["output_contains"], case
            assert case["generated_by"] == "heuristic", case
        print(f"[4] 自动出题：新增 {gen['added']} 条（{gen['mode']}），"
              f"示例：{gen['cases'][0]['input'][:42]}… → 断言 {gen['cases'][0]['expect']['output_contains']}")

        # 5) 一起跑
        code, run = _post(port, "/api/cases/run", {"scope": "docs"})
        assert code == 200 and run["total"] >= 1, run
        assert run["passed"] == run["total"], run
        print(f"[5] 文档用例运行：{run['passed']}/{run['total']} 通过（{run['duration_ms']}ms）")

        # 6) 删文档后，用例应被跳过而不是误判失败
        code, dl = _post(port, "/api/knowledge/delete", {"name": md_name})
        assert code == 200 and dl.get("ok"), dl
        md_name = ""
        code, run2 = _post(port, "/api/cases/run", {"scope": "docs"})
        assert code == 200, run2
        assert any(s["id"].startswith("D") for s in run2["skipped"]), run2
        print(f"[6] 删除文档后：跳过 {len(run2['skipped'])} 条（不会算成失败）")

        print("DOCX 上传 + 自动出题冒烟通过")
        return 0
    finally:
        if md_name:
            target = kb_dir / md_name
            if target.exists():
                target.unlink()
        raw = raw_dir / UPLOAD_NAME
        if raw.exists():
            raw.unlink()
        _drop_cases(doc_id)
        httpd.shutdown()
        _restore_env(saved)


if __name__ == "__main__":
    raise SystemExit(main())
