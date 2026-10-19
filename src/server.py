"""最小可用 Web 服务：五页原型（首页 / 问答 / 知识库 / 评测看板 / 汇报）+ HTTP API。

  python -m src.server --port 8000

路由：
  GET  /                 首页
  GET  /ask              问答（输入/答案/引用/追问/转人工/反馈）
  GET  /kb               知识库（上传/检索/出题/删除）
  GET  /dashboard        评测看板（指标/语义质量/用例/反馈/最近对话）
  GET  /api/health       端点 / 模型 / 知识块数
  GET  /api/metrics      聚合指标
  GET  /api/knowledge    知识库文件与块数
  GET  /api/feedback/list?limit=20
  GET  /api/trace?limit=20
  POST /api/ask          {"query": "..."}
  POST /api/feedback     {"trace_id","useful","comment"}
  POST /api/reload       重新加载知识库
  POST /api/knowledge/upload      {"name","content"} 上传 .md/.txt
  POST /api/knowledge/upload_file {"name","data_b64"} 上传 PDF/DOCX（服务端解析成 Markdown）
  POST /api/knowledge/upload_pdf  同上（兼容旧名）
  POST /api/cases/from_doc        {"name","n"} 为某份文档自动生成评测用例
  POST /api/cases/run             {"scope":"docs"|"all"} 跑用例并回传结果
  POST /api/knowledge/delete      {"name"} 删除知识库文件
"""
import argparse
import base64
import binascii
import json
import os
import time
from collections import Counter
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import casegen, evaluator, ingest
from .metrics import summarize
from .pipeline import RAGPipeline
from .report import collect as collect_report, render as render_report
from .version import __version__
from .web_pages import ASK_HTML, DASHBOARD_HTML, HOME_HTML, KB_HTML

MAX_BODY_BYTES = 8192
UPLOAD_MAX_BYTES = 512 * 1024          # 单个文本文件上限（.md/.txt）
DOC_MAX_BYTES = 6 * 1024 * 1024         # 单个 PDF/DOCX 上限（解码后）
DOC_B64_MAX_BYTES = DOC_MAX_BYTES * 4 // 3 + 4096
ALLOWED_EXT = (".md", ".txt")


def _safe_kb_name(name) -> str | None:
    """只接受「纯文件名」的 .md/.txt。

    显式拒绝路径分隔符而不是 basename 静默改名：
    静默改名虽然安全，但会让用户以为传了 `../x.md` 却出现 `x.md`，属于隐性行为。
    """
    raw = str(name or "").strip()
    if not raw or "/" in raw or "\\" in raw or ".." in raw:
        return None
    if len(raw) > 80 or not raw.lower().endswith(ALLOWED_EXT):
        return None
    if any(ch in raw for ch in '<>:"|?*\x00'):
        return None
    return raw


def _knowledge_dir() -> str:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(root, "data", "knowledge")


def _raw_dir() -> str:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(root, "data", "raw")
    os.makedirs(path, exist_ok=True)
    return path


def _safe_doc_name(name) -> str | None:
    """上传文档名：只接受纯文件名，且必须是 .pdf / .docx。"""
    raw = str(name or "").strip()
    if not raw or "/" in raw or "\\" in raw or ".." in raw:
        return None
    if len(raw) > 120 or not raw.lower().endswith(ingest.SUPPORTED_EXT):
        return None
    if any(ch in raw for ch in '<>:"|?*\x00'):
        return None
    return raw


def _read_jsonl(path: str, limit: int) -> list[dict]:
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        lines = [line for line in f.read().splitlines() if line.strip()][-limit:]
    rows = []
    for line in lines:
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def create_server(host: str, port: int, knowledge_dir: str | None = None):
    pipe = RAGPipeline(knowledge_dir or _knowledge_dir())
    feedback_path = os.path.join(os.path.dirname(pipe.log_path), "feedback.jsonl")
    handoff_path = os.path.join(os.path.dirname(pipe.log_path), "handoff.jsonl")
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    feedback_cases_path = os.path.join(project_root, "tests", "eval_cases_feedback.jsonl")
    kb_dir = pipe.knowledge_dir
    raw_dir = _raw_dir()
    doc_cases_path = os.path.join(project_root, "tests", "eval_cases_docs.jsonl")
    run_report_path = os.path.join(project_root, "tests", "report_doc_cases.json")

    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, body: str, content_type: str = "application/json; charset=utf-8") -> None:
            data = body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _json(self, obj, code: int = 200) -> None:
            self._send(code, json.dumps(obj, ensure_ascii=False))

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            path = parsed.path
            qs = parse_qs(parsed.query)

            if path in ("/", "/index.html"):
                self._send(200, HOME_HTML, "text/html; charset=utf-8")
            elif path == "/ask":
                self._send(200, ASK_HTML, "text/html; charset=utf-8")
            elif path == "/kb":
                self._send(200, KB_HTML, "text/html; charset=utf-8")
            elif path == "/dashboard":
                self._send(200, DASHBOARD_HTML, "text/html; charset=utf-8")
            elif path == "/report":
                self._send(200, render_report(collect_report(pipe)), "text/html; charset=utf-8")
            elif path == "/api/report/export":
                html = render_report(collect_report(pipe), standalone=True).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Disposition", 'attachment; filename="report.html"')
                self.send_header("Content-Length", str(len(html)))
                self.end_headers()
                self.wfile.write(html)
            elif path == "/api/l3":
                l3_path = os.path.join(project_root, "tests", "report_l3.json")
                if not os.path.exists(l3_path):
                    self._json({"available": False})
                else:
                    with open(l3_path, encoding="utf-8") as f:
                        d = json.load(f)
                    self._json({
                        "available": True,
                        "judged_at": d.get("judged_at"),
                        "judge_channel": d.get("judge_channel"),
                        "judge_model": d.get("judge_model"),
                        "answer_cases": d.get("answer_cases"),
                        "safety_cases": d.get("safety_cases"),
                        "avg": d.get("avg"),
                        "pass_rate": d.get("pass_rate"),
                        "safety_compliant_rate": d.get("safety_compliant_rate"),
                        "hallucinations": len(d.get("hallucinations") or []),
                        "gate": d.get("gate"),
                    })
            elif path == "/api/health":
                self._json({
                    "status": "ok",
                    "version": __version__,
                    "channel": pipe.settings.channel,
                    "model": pipe.settings.model,
                    "llm_ready": pipe.llm_ready,
                    "chunks": len(pipe.chunks),
                })
            elif path == "/api/metrics":
                self._json(summarize(pipe.log_path))
            elif path == "/api/cases":
                curated = _read_jsonl(os.path.join(project_root, "tests", "eval_cases.jsonl"), 100000)
                fb_cases = _read_jsonl(feedback_cases_path, 100000)
                doc_cases = _read_jsonl(doc_cases_path, 100000)
                last_run = None
                if os.path.exists(run_report_path):
                    with open(run_report_path, encoding="utf-8") as f:
                        rep = json.load(f)
                    last_run = {k: rep.get(k) for k in
                                ("run_at", "scope", "total", "passed", "pass_rate", "channel", "model")}
                self._json({
                    "curated": len(curated),
                    "feedback": len(fb_cases),
                    "docs": len(doc_cases),
                    "total": len(curated) + len(fb_cases) + len(doc_cases),
                    "doc_items": [{
                        "id": c.get("id"),
                        "input": c.get("input"),
                        "doc_id": c.get("doc_id"),
                        "generated_by": c.get("generated_by"),
                        "keywords": (c.get("expect") or {}).get("output_contains", []),
                    } for c in doc_cases[-20:]],
                    "last_run": last_run,
                })
            elif path == "/api/knowledge":
                counts = Counter(c.doc_id for c in pipe.chunks)
                files = []
                if os.path.isdir(kb_dir):
                    for name in sorted(os.listdir(kb_dir)):
                        if name.lower().endswith(ALLOWED_EXT):
                            path = os.path.join(kb_dir, name)
                            files.append({
                                "name": name,
                                "chunks": counts.get(name.rsplit(".", 1)[0], 0),
                                "size": os.path.getsize(path),
                                "mtime": datetime.fromtimestamp(os.path.getmtime(path)).strftime("%Y-%m-%d %H:%M"),
                            })
                self._json({"files": files, "total_chunks": len(pipe.chunks)})
            elif path == "/api/feedback/list":
                limit = int(qs.get("limit", ["20"])[0])
                self._json({"items": list(reversed(_read_jsonl(feedback_path, limit)))})
            elif path == "/api/trace":
                limit = int(qs.get("limit", ["20"])[0])
                rows = list(reversed(_read_jsonl(pipe.log_path, limit)))
                items = [{
                    "ts": r.get("ts"),
                    "query": r.get("query"),
                    "behavior": r.get("behavior"),
                    "mode": r.get("mode"),
                    "latency_ms": r.get("latency_ms"),
                    "channel": r.get("channel"),
                } for r in rows]
                self._json({"items": items})
            else:
                self._json({"error": "not found"}, 404)

        def do_POST(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            if path not in ("/api/ask", "/api/feedback", "/api/reload", "/api/cases/from_feedback",
                            "/api/handoff", "/api/knowledge/upload", "/api/knowledge/upload_pdf",
                            "/api/knowledge/upload_file", "/api/knowledge/delete",
                            "/api/cases/from_doc", "/api/cases/run"):
                self._json({"error": "not found"}, 404)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                self._json({"error": "invalid content-length"}, 400)
                return
            if path == "/api/knowledge/upload":
                limit = UPLOAD_MAX_BYTES
            elif path in ("/api/knowledge/upload_pdf", "/api/knowledge/upload_file"):
                limit = DOC_B64_MAX_BYTES
            else:
                limit = MAX_BODY_BYTES
            if length <= 0 or length > limit:
                self._json({"error": "body empty or too large"}, 400)
                return
            try:
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                self._json({"error": "invalid json"}, 400)
                return

            if path == "/api/knowledge/upload":
                name = _safe_kb_name(payload.get("name"))
                content = str(payload.get("content") or "")
                if not name:
                    self._json({"ok": False, "error": "只支持 .md / .txt，文件名不合法"}, 400)
                    return
                if not content.strip():
                    self._json({"ok": False, "error": "文件内容为空"}, 400)
                    return
                with open(os.path.join(kb_dir, name), "w", encoding="utf-8") as f:
                    f.write(content)
                try:
                    total = pipe.reload()
                except Exception as exc:  # noqa: BLE001
                    self._json({"ok": False, "error": f"已写入但重载失败：{exc}"}, 500)
                    return
                self._json({"ok": True, "name": name, "chunks": total,
                            "files": len([n for n in os.listdir(kb_dir) if n.lower().endswith(ALLOWED_EXT)])})
                return

            if path in ("/api/knowledge/upload_pdf", "/api/knowledge/upload_file"):
                name = _safe_doc_name(payload.get("name"))
                if not name:
                    self._json({"ok": False, "error": "只接受纯文件名的 .pdf / .docx 文件"}, 400)
                    return
                blob = payload.get("data_b64") or payload.get("file") or ""
                if not isinstance(blob, str) or not blob.strip():
                    self._json({"ok": False, "error": "PDF 内容为空"}, 400)
                    return
                try:
                    data = base64.b64decode(blob, validate=False)
                except (binascii.Error, ValueError):
                    self._json({"ok": False, "error": "base64 解码失败，请重试"}, 400)
                    return
                if len(data) > DOC_MAX_BYTES:
                    self._json({"ok": False,
                                "error": f"文件超过 {DOC_MAX_BYTES // 1024 // 1024} MB 上限"}, 413)
                    return
                # 文件头先校验：改后缀的假文件属于「请求有问题」（400），
                # 真文件解析失败（加密/扫描件）才是「内容不可用」（422）。
                ext = os.path.splitext(name)[1].lower()
                magic = {".pdf": b"%PDF", ".docx": b"PK"}.get(ext, b"")
                if magic and not data.startswith(magic):
                    self._json({"ok": False,
                                "error": f"不是有效的 {ext.lstrip('.').upper()} 文件（文件头不匹配）"}, 400)
                    return

                before = len(pipe.chunks)
                try:
                    res = ingest.ingest_bytes(
                        data, name, kb_dir,
                        engine=os.getenv("PDF_ENGINE", "auto"),
                    )
                except Exception as exc:  # noqa: BLE001 —— 任何解析异常都要回给用户，不能 500 空响应
                    self._json({"ok": False, "error": f"解析异常：{type(exc).__name__}: {exc}"}, 422)
                    return
                if not res.get("ok"):
                    self._json({"ok": False, "error": res.get("error")}, 422)
                    return

                # 原始 PDF 只在校验通过后落盘，避免失败的上传在 data/raw 里堆垃圾
                with open(os.path.join(raw_dir, name), "wb") as f:
                    f.write(data)
                try:
                    total = pipe.reload()
                except Exception as exc:  # noqa: BLE001
                    self._json({"ok": False, "error": f"已转换但索引重建失败：{exc}"}, 500)
                    return
                self._json({
                    "ok": True,
                    "name": name,
                    "md": res["md"],
                    "chars": res["chars"],
                    "engine": res["engine"],
                    "format": res.get("format"),
                    "pages": res.get("pages"),
                    "paragraphs": res.get("paragraphs"),
                    "tables": res.get("tables"),
                    "note": res.get("note"),
                    "chunks": total,
                    "added_chunks": total - before,
                    "files": len([n for n in os.listdir(kb_dir) if n.lower().endswith(ALLOWED_EXT)]),
                })
                return

            if path == "/api/knowledge/delete":
                name = _safe_kb_name(payload.get("name"))
                target = os.path.join(kb_dir, name) if name else ""
                if not name or not os.path.exists(target):
                    self._json({"ok": False, "error": "文件不存在"}, 404)
                    return
                remaining = [n for n in os.listdir(kb_dir) if n.lower().endswith(ALLOWED_EXT) and n != name]
                if not remaining:
                    self._json({"ok": False, "error": "知识库至少要保留一个文件"}, 400)
                    return
                os.remove(target)
                total = pipe.reload()
                self._json({"ok": True, "name": name, "chunks": total})
                return

            if path == "/api/cases/from_doc":
                name = _safe_kb_name(payload.get("name"))
                if not name:
                    self._json({"ok": False, "error": "请指定知识库里的 .md 文件名"}, 400)
                    return
                doc_id = name.rsplit(".", 1)[0]
                chunks = [c for c in pipe.chunks if c.doc_id == doc_id]
                if not chunks:
                    self._json({"ok": False, "error": f"文档 {name} 没有可用的知识块"}, 404)
                    return
                try:
                    n = max(1, min(8, int(payload.get("n") or 3)))
                except (TypeError, ValueError):
                    n = 3
                res = casegen.generate_for_document(
                    doc_id, chunks, doc_cases_path, n=n,
                    prefer_llm=bool(payload.get("use_llm", True)),
                )
                if not res["added"]:
                    self._json({"ok": False, "error": res.get("reason") or "未能生成用例",
                                "mode": res.get("mode")}, 422)
                    return
                self._json({"ok": True, "doc": name, **res})
                return

            if path == "/api/cases/run":
                scope = str(payload.get("scope") or "docs")
                files = (evaluator.default_case_files() if scope == "all"
                         else ([evaluator.DOCS] if evaluator.DOCS.exists() else []))
                cases = evaluator.load_cases(files)
                if not cases:
                    self._json({"ok": True, "scope": scope, "total": 0, "passed": 0,
                                "pass_rate": 0.0, "by_category": {}, "failed": [],
                                "skipped": [], "run_at": datetime.now(timezone.utc).isoformat(),
                                "error": "没有可运行的用例"})
                    return
                try:
                    sleep_s = max(0.0, min(10.0, float(payload.get("sleep") or 0)))
                except (TypeError, ValueError):
                    sleep_s = 0.0
                started = time.time()
                results, skipped = evaluator.run_cases(
                    pipe, cases, sleep=sleep_s, skip_missing_doc=True, kb_dir=kb_dir)
                summary = evaluator.summarize(results, skipped)
                report = {
                    "run_at": datetime.now(timezone.utc).isoformat(),
                    "scope": scope,
                    "channel": pipe.settings.channel,
                    "model": pipe.settings.model,
                    **summary,
                    "duration_ms": int((time.time() - started) * 1000),
                    "results": results,
                }
                with open(run_report_path, "w", encoding="utf-8") as f:
                    json.dump(report, f, ensure_ascii=False, indent=2)
                self._json({
                    "ok": True,
                    "scope": scope,
                    "total": summary["total"],
                    "passed": summary["passed"],
                    "pass_rate": summary["pass_rate"],
                    "by_category": summary["by_category"],
                    "skipped": summary["skipped"],
                    "failed": [{"id": r["id"], "input": r["input"], "failures": r["failures"]}
                               for r in results if not r["passed"]],
                    "duration_ms": report["duration_ms"],
                    "run_at": report["run_at"],
                })
                return

            if path == "/api/feedback":
                record = {
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "trace_id": str(payload.get("trace_id", "")),
                    "useful": bool(payload.get("useful")),
                    "comment": str(payload.get("comment", ""))[:500],
                }
                with open(feedback_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")
                self._json({"ok": True})
                return

            if path == "/api/reload":
                try:
                    total = pipe.reload()
                    self._json({"ok": True, "chunks": total})
                except Exception as exc:  # noqa: BLE001
                    self._json({"ok": False, "error": str(exc)}, 500)
                return

            if path == "/api/cases/from_feedback":
                trace_id = str(payload.get("trace_id", ""))
                rows = list(reversed(_read_jsonl(pipe.log_path, 5000)))
                query = next((r.get("query", "") for r in rows if r.get("trace_id") == trace_id), "")
                if not query:
                    self._json({"ok": False, "error": "未找到该 trace 对应的问题"}, 400)
                    return
                keywords = [str(k).strip() for k in (payload.get("keywords") or []) if str(k).strip()]
                behavior = str(payload.get("behavior") or "answer")
                note = str(payload.get("note") or "")[:200]
                existing = _read_jsonl(feedback_cases_path, 100000)
                seq = len(existing) + 1
                case_id = f"F{seq:03d}"
                expect = {"behavior": behavior}
                if keywords:
                    expect["output_contains"] = keywords
                case = {
                    "id": case_id,
                    "category": "regression",
                    "input": query,
                    "expect": expect,
                    "source": "feedback",
                    "source_trace": trace_id,
                    "note": note,
                }
                os.makedirs(os.path.dirname(feedback_cases_path), exist_ok=True)
                with open(feedback_cases_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(case, ensure_ascii=False) + "\n")
                self._json({"ok": True, "case": case, "total": seq})
                return

            if path == "/api/handoff":
                ticket = "H" + datetime.now().strftime("%Y%m%d%H%M%S")
                record = {
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "ticket": ticket,
                    "trace_id": str(payload.get("trace_id", "")),
                    "query": str(payload.get("query", ""))[:500],
                    "contact": str(payload.get("contact", ""))[:100],
                }
                with open(handoff_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")
                self._json({"ok": True, "ticket": ticket})
                return

            result = pipe.ask(str(payload.get("query", "")))
            self._json(result)

        def log_message(self, fmt: str, *args) -> None:
            pass

    httpd = ThreadingHTTPServer((host, port), Handler)
    return httpd, pipe


def main() -> None:
    ap = argparse.ArgumentParser(description="文档问答助手 Web 服务")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--model", help="临时指定模型（等价于设置 LLM_MODEL）")
    args = ap.parse_args()

    if args.model:
        os.environ["LLM_MODEL"] = args.model

    httpd, pipe = create_server(args.host, args.port)
    print(f"serving http://{args.host}:{args.port}  model={pipe.settings.model} base={pipe.settings.api_base}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.shutdown()


if __name__ == "__main__":
    main()
