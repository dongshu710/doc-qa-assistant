"""汇报页：把「是什么 / 怎么跑 / 跑成什么样 / 边界在哪」汇总成一页自包含 HTML。

两个用途：
1. `GET /report`（服务在线时实时渲染）；
2. `python -m src.report --out dist/report.html`（导出独立文件，无服务也能打开，可直接发给面试官）。

关键点：导出的 HTML **不依赖任何 API**，数据在渲染时全部内联，双击即可看。
"""
import argparse
import json
import os
from collections import Counter
from datetime import datetime
from pathlib import Path

from .metrics import summarize
from .theme import BASE_CSS, BRAND, footer, nav
from .version import __version__

REPORT_CSS = """
/* ---------- 汇报页 ---------- */
.rp-hero{position:relative;overflow:hidden;background:#070c1b;color:#eaf0ff;border-radius:20px;padding:36px 34px 32px;margin-bottom:16px;
  box-shadow:0 30px 70px -40px rgba(7,12,27,.75);}
.rp-hero::before{content:"";position:absolute;inset:0;
  background:radial-gradient(560px 300px at 6% 0%,rgba(47,92,246,.42),transparent 62%),
             radial-gradient(520px 340px at 96% 10%,rgba(122,92,251,.34),transparent 66%);}
.rp-hero::after{content:"";position:absolute;inset:0;
  background-image:linear-gradient(rgba(255,255,255,.05) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.05) 1px,transparent 1px);
  background-size:42px 42px;mask-image:radial-gradient(600px 320px at 20% 10%,#000,transparent 78%);
  -webkit-mask-image:radial-gradient(600px 320px at 20% 10%,#000,transparent 78%);}
.rp-hero > *{position:relative;}
.rp-hero .eyebrow{color:#9db4ff;margin-bottom:12px;}
.rp-hero .eyebrow::before{background:#7f9cff;}
.rp-hero h1{font-size:clamp(23px,2.4vw,31px);margin:0 0 10px;letter-spacing:-.03em;color:#fff;line-height:1.28;}
.rp-hero p{color:#a7b6d6;max-width:780px;margin:0 0 16px;line-height:1.85;font-size:13.5px;}
.rp-hero .badges{display:flex;flex-wrap:wrap;gap:7px;}
.rp-hero .b{font-size:11.5px;padding:4px 10px;border-radius:999px;background:rgba(255,255,255,.09);color:#dbe4fb;border:1px solid rgba(255,255,255,.1);}
.rp-hero .b.solid{background:rgba(47,92,246,.9);border-color:rgba(120,150,255,.5);color:#fff;}
.rp-hero .actions{margin-top:20px;display:flex;gap:9px;flex-wrap:wrap;align-items:center;}
.rp-hero a.btn{background:#fff;color:#101a3a;box-shadow:0 10px 24px -16px rgba(0,0,0,.8);}
.rp-hero a.btn:hover{background:#f2f5ff;}
.rp-hero a.btn.ghost2{background:rgba(255,255,255,.08);border:1px solid rgba(255,255,255,.24);color:#e2e8f0;}
.rp-hero a.btn.ghost2:hover{background:rgba(255,255,255,.14);}

/* 目录 */
.rp-nav{position:sticky;top:var(--nav-h);z-index:30;display:flex;gap:2px;overflow:auto;scrollbar-width:none;
  padding:9px 0;margin-bottom:16px;background:linear-gradient(180deg,rgba(246,247,251,.97) 62%,rgba(246,247,251,0));}
.rp-nav::-webkit-scrollbar{display:none;}
.rp-nav a{padding:6px 11px;border-radius:8px;font-size:12.5px;color:var(--muted);white-space:nowrap;transition:background .15s,color .15s;}
.rp-nav a:hover{background:#eef1f9;color:var(--ink);}
.rp-nav a.active{background:#fff;color:var(--brand-600);font-weight:600;border:1px solid var(--line);box-shadow:var(--sh-1);}

.sec{margin-bottom:14px;scroll-margin-top:calc(var(--nav-h) + 58px);}
.sec-head{display:flex;align-items:center;gap:10px;margin-bottom:13px;flex-wrap:wrap;min-height:24px;}
.sec-head h2{font-size:16px;letter-spacing:-.02em;}
.sec-head .n{font-family:var(--mono);font-size:10.5px;font-weight:600;color:var(--brand);background:var(--brand-soft);border-radius:5px;padding:2px 6px;}
.sec-head .note{font-size:12px;color:var(--muted);margin-left:auto;text-align:right;background:none;border:0;padding:0;display:block;line-height:1.6;}
@media (max-width:760px){.sec-head .note{margin-left:0;text-align:left;}}
.two-col{display:grid;grid-template-columns:1fr 1fr;gap:14px;}
@media (max-width:860px){.two-col{grid-template-columns:1fr;}}
.axis{display:flex;gap:10px;align-items:flex-start;margin:10px 0;font-size:13px;line-height:1.8;}
.axis .ic{flex:none;width:19px;height:19px;border-radius:6px;display:flex;align-items:center;justify-content:center;font-size:11px;margin-top:3px;font-weight:700;}
.axis .ic.is{background:#e9f9f1;color:#0a7a4d;}
.axis .ic.not{background:#fef1f0;color:#a91e13;}
.axis b{font-weight:650;color:var(--ink);}
.score{display:inline-block;min-width:36px;text-align:center;font-weight:650;border-radius:6px;padding:2px 6px;font-variant-numeric:tabular-nums;}
.score.s5,.score.s4{background:#e9f9f1;color:#0a7a4d;}
.score.s3{background:#fff7e8;color:#8f5400;}
.score.s2,.score.s1{background:#fef1f0;color:#a91e13;}
.arch{background:linear-gradient(180deg,#fbfcff,#fff);border:1px solid var(--line);border-radius:14px;padding:10px 8px;}
.rp-list{margin:0;padding-left:18px;line-height:1.95;font-size:12.8px;color:#3b4657;}
.rp-list li{margin-bottom:3px;}
.rp-list li::marker{color:#a9b3c6;}
.foot{margin-top:22px;padding-top:14px;border-top:1px solid var(--line);color:var(--faint);font-size:11.5px;line-height:1.85;}

/* L3 语义质量 */
.rp-l3{display:grid;grid-template-columns:1.1fr .9fr;gap:22px;align-items:center;}
.rp-scores{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;}
.rp-score{border:1px solid var(--line);border-radius:12px;padding:13px 14px;background:linear-gradient(180deg,#fff,#fbfcff);}
.rp-score .k{font-size:11.5px;color:var(--muted);}
.rp-score .v{font-size:26px;font-weight:700;color:var(--ink);letter-spacing:-.035em;margin:3px 0 8px;line-height:1.1;font-variant-numeric:tabular-nums;}
.rp-score .v small{font-size:11.5px;color:var(--faint);font-weight:500;letter-spacing:0;margin-left:2px;}
.rp-score .bar{height:5px;}
.rp-l3-note{font-size:12.5px;color:var(--muted);line-height:1.9;}
.rp-l3-note b{color:var(--ink);font-weight:600;}
.pill{display:inline-flex;align-items:center;gap:5px;font-size:11.5px;padding:5px 10px;border-radius:999px;
  border:1px solid var(--line);background:#f7f9fd;color:#475467;font-weight:500;}
@media (max-width:860px){.rp-l3{grid-template-columns:1fr;gap:16px;}}

/* 让汇报页的 6 个 KPI 排成整齐的 3 × 2 */
.kpis.six{grid-template-columns:repeat(3,1fr);}
@media (max-width:900px){.kpis.six{grid-template-columns:repeat(2,1fr);}}

.rp-hero .live{display:inline-flex;align-items:center;gap:7px;font-size:11px;color:#a7f3d0;}
.rp-hero .live i{width:6px;height:6px;border-radius:50%;background:#34d399;box-shadow:0 0 0 3px rgba(52,211,153,.2);}
@media (max-width:640px){
  .rp-hero{padding:26px 20px;border-radius:16px;}
  .rp-hero h1{font-size:22px;}
  .sec.card{padding:16px;}
  .rp-scores{gap:7px;}
  .rp-score{padding:11px 10px;}
  .rp-score .v{font-size:21px;}
  .rp-nav a{padding:6px 9px;font-size:12px;}
}
@media print{
  body{background:#fff;}
  .nav,.site-foot,.rp-nav,.rp-hero .actions{display:none !important;}
  .card,.kpi,.sec{break-inside:avoid;}
  .rp-hero{background:#0f172a !important;-webkit-print-color-adjust:exact;print-color-adjust:exact;}
}
"""


def _esc(value) -> str:
    return (
        str("" if value is None else value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _report_label(report: dict, filename: str) -> str:
    channel = report.get("channel") or "-"
    model = report.get("model") or "-"
    if filename == "baseline.json":
        return f"离线基线（{channel} / 抽取）"
    if channel == "glm":
        return f"glm 测试通道（{model}）"
    return f"默认通道（{channel} / {model}）"


def collect(pipe=None, root: Path | None = None) -> dict:
    """汇总页面所需的全部数据（不发起任何网络请求）。"""
    project_root = root or Path(__file__).resolve().parents[1]
    tests_dir = project_root / "tests"

    if pipe is None:
        from .pipeline import RAGPipeline
        pipe = RAGPipeline(str(project_root / "data" / "knowledge"))

    counts = Counter(c.doc_id for c in pipe.chunks)
    files = []
    kb_dir = Path(pipe.knowledge_dir)
    if kb_dir.is_dir():
        for name in sorted(os.listdir(kb_dir)):
            if name.lower().endswith((".md", ".txt")):
                files.append({"name": name, "chunks": counts.get(name.rsplit(".", 1)[0], 0)})

    curated = len([l for l in (tests_dir / "eval_cases.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]) \
        if (tests_dir / "eval_cases.jsonl").exists() else 0
    fb_cases = len([l for l in (tests_dir / "eval_cases_feedback.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]) \
        if (tests_dir / "eval_cases_feedback.jsonl").exists() else 0

    l1 = []
    for name in ("baseline.json", "report_llm_deepseek.json", "report_llm_glm.json"):
        path = tests_dir / name
        data = _read_json(path) if path.exists() else None
        if not data or not data.get("total"):
            continue
        l1.append({
            "file": name,
            "label": _report_label(data, name),
            "channel": data.get("channel"),
            "model": data.get("model"),
            "total": data.get("total"),
            "pass_rate": data.get("pass_rate"),
            "by_category": data.get("by_category", {}),
            "failures": [r for r in data.get("results", []) if not r.get("passed")][:5],
        })

    l3 = _read_json(tests_dir / "report_l3.json") if (tests_dir / "report_l3.json").exists() else None
    hard_l1 = _read_json(tests_dir / "report_hard_glm.json") if (tests_dir / "report_hard_glm.json").exists() else None
    retrieval = _read_json(tests_dir / "report_retrieval.json") if (tests_dir / "report_retrieval.json").exists() else None
    l3_hard = {}
    for key, name in (("same", "report_l3_hard_same.json"), ("cross", "report_l3_hard_cross.json")):
        path = tests_dir / name
        if path.exists():
            l3_hard[key] = _read_json(path)

    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "channel": pipe.settings.channel,
        "model": pipe.settings.model,
        "knowledge": {"files": files, "chunks": len(pipe.chunks)},
        "cases": {"curated": curated, "feedback": fb_cases, "total": curated + fb_cases},
        "l1": l1,
        "l3": l3,
        "hard": hard_l1,
        "l3_hard": l3_hard,
        "retrieval": retrieval,
        "metrics": summarize(pipe.log_path, limit=500),
        "config": {
            "top_k": pipe.settings.top_k,
            "min_score": pipe.settings.min_score,
            "timeout": pipe.settings.llm_timeout_s,
            "retries": pipe.settings.llm_max_retries,
        },
    }


def _kpi(value, key: str) -> str:
    return f'<div class="kpi"><div class="v">{_esc(value)}</div><div class="k">{_esc(key)}</div></div>'


def _score_badge(v) -> str:
    """评分徽标：保留小数（4.92 与 5.0 的差异必须看得出来，不能被四舍五入吃掉）。"""
    if v is None:
        return '<span class="score">-</span>'
    try:
        num = float(v)
    except (TypeError, ValueError):
        return f'<span class="score">{_esc(v)}</span>'
    cls = max(1, min(5, int(round(num))))
    label = f"{num:.1f}" if float(num).is_integer() else f"{num:.2f}".rstrip("0").rstrip(".")
    return f'<span class="score s{cls}">{label}</span>'


ARCH_SVG = """
<svg class="arch" viewBox="0 0 960 232" width="100%" role="img" aria-label="问答链路架构图">
  <defs>
    <marker id="ar" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6.5" markerHeight="6.5" orient="auto">
      <path d="M0,0 L10,5 L0,10 z" fill="#b6c0d4"/>
    </marker>
  </defs>
  <g font-family="-apple-system, 'Microsoft YaHei', sans-serif">
    <rect x="18" y="18" width="270" height="64" rx="11" fill="#fff" stroke="#dfe5f1"/>
    <circle cx="39" cy="40" r="9" fill="#eef2ff"/>
    <text x="39" y="43.6" font-size="10" font-weight="700" fill="#2f5cf6" text-anchor="middle">1</text>
    <text x="55" y="44" font-size="12.5" font-weight="600" fill="#0a1020">输入校验</text>
    <text x="55" y="62" font-size="10.5" fill="#6b7280">归一化去零宽 · 注入 / 越权 / 荐股拦截</text>

    <rect x="345" y="18" width="270" height="64" rx="11" fill="#fff" stroke="#dfe5f1"/>
    <circle cx="366" cy="40" r="9" fill="#eef2ff"/>
    <text x="366" y="43.6" font-size="10" font-weight="700" fill="#2f5cf6" text-anchor="middle">2</text>
    <text x="382" y="44" font-size="12.5" font-weight="600" fill="#0a1020">BM25 检索</text>
    <text x="382" y="62" font-size="10.5" fill="#6b7280">标题感知切分 · 中文二元组 · 查询扩展</text>

    <rect x="672" y="18" width="270" height="64" rx="11" fill="#fffaef" stroke="#f2dcb0"/>
    <circle cx="693" cy="40" r="9" fill="#fdeccc"/>
    <text x="693" y="43.6" font-size="10" font-weight="700" fill="#b26a00" text-anchor="middle">3</text>
    <text x="709" y="44" font-size="12.5" font-weight="600" fill="#0a1020">置信度闸门</text>
    <text x="709" y="62" font-size="10.5" fill="#92703a">最高分低于阈值不硬答 · 转人工</text>

    <rect x="672" y="150" width="270" height="64" rx="11" fill="#eef2ff" stroke="#cfd9fb"/>
    <circle cx="693" cy="172" r="9" fill="#dfe6ff"/>
    <text x="693" y="175.6" font-size="10" font-weight="700" fill="#2449d8" text-anchor="middle">4</text>
    <text x="709" y="176" font-size="12.5" font-weight="600" fill="#0a1020">生成层</text>
    <text x="709" y="194" font-size="10.5" fill="#4b5f9e">LLM 生成 · 超时重试 · 抽取式兜底</text>

    <rect x="345" y="150" width="270" height="64" rx="11" fill="#fff" stroke="#dfe5f1"/>
    <circle cx="366" cy="172" r="9" fill="#eef2ff"/>
    <text x="366" y="175.6" font-size="10" font-weight="700" fill="#2f5cf6" text-anchor="middle">5</text>
    <text x="382" y="176" font-size="12.5" font-weight="600" fill="#0a1020">引用校验</text>
    <text x="382" y="194" font-size="10.5" fill="#6b7280">无有效 [n] → 降级为可追溯答案</text>

    <rect x="18" y="150" width="270" height="64" rx="11" fill="#eafaf2" stroke="#c4eeda"/>
    <circle cx="39" cy="172" r="9" fill="#d3f4e4"/>
    <text x="39" y="175.6" font-size="10" font-weight="700" fill="#0a7a4d" text-anchor="middle">6</text>
    <text x="55" y="176" font-size="12.5" font-weight="600" fill="#0a1020">答案 · 引用 · 观测</text>
    <text x="55" y="194" font-size="10.5" fill="#2f7d5e">trace.jsonl · 反馈 · 指标看板</text>

    <line x1="292" y1="50" x2="338" y2="50" stroke="#b6c0d4" stroke-width="1.3" marker-end="url(#ar)"/>
    <line x1="619" y1="50" x2="665" y2="50" stroke="#b6c0d4" stroke-width="1.3" marker-end="url(#ar)"/>
    <line x1="807" y1="86" x2="807" y2="143" stroke="#b6c0d4" stroke-width="1.3" marker-end="url(#ar)"/>
    <line x1="668" y1="182" x2="622" y2="182" stroke="#b6c0d4" stroke-width="1.3" marker-end="url(#ar)"/>
    <line x1="341" y1="182" x2="295" y2="182" stroke="#b6c0d4" stroke-width="1.3" marker-end="url(#ar)"/>
  </g>
</svg>
"""


def render(data: dict, standalone: bool = False) -> str:
    """渲染汇报页。standalone=True 时隐藏「下载」按钮（导出文件本身）。"""
    k = data["knowledge"]
    cases = data["cases"]
    metrics = data["metrics"]
    l1 = data["l1"]
    l3 = data.get("l3")
    cfg = data["config"]

    best_l1 = max(l1, key=lambda x: (x["pass_rate"] or 0)) if l1 else None
    cov = metrics.get("avg_citation_coverage")
    p95 = (metrics.get("latency_ms") or {}).get("p95")
    l3_avg = (l3 or {}).get("avg") or {}

    # ---------- KPI ----------
    kpis = "".join([
        _kpi(f"{k['chunks']} 块 / {len(k['files'])} 份", "知识库规模"),
        _kpi(cases["total"], "评测用例"),
        _kpi(f"{round((best_l1['pass_rate'] or 0) * 100)}%" if best_l1 else "-", "L1 通过率"),
        _kpi(l3_avg.get("faithfulness") or "-", "L3 忠实度"),
        _kpi(cov if cov is not None else "-", "引用覆盖率"),
        _kpi(f"{round(p95)}ms" if p95 else "-", "P95 延迟（近 500 条）"),
    ])

    # ---------- L1 表 ----------
    l1_rows = ""
    for r in l1:
        cats = r["by_category"]
        detail = " · ".join(f"{c} {v['passed']}/{v['total']}" for c, v in cats.items())
        ok = (r["pass_rate"] or 0) >= 0.9
        l1_rows += (
            f"<tr><td>{_esc(r['label'])}</td><td>{r['total']}</td>"
            f"<td class=\"{'ok' if ok else 'bad'}\">{round((r['pass_rate'] or 0) * 100)}%</td>"
            f"<td class=\"muted\">{_esc(detail)}</td></tr>"
        )
    l1_table = (
        '<div class="table-wrap"><table><thead><tr><th>评测轮次</th><th>用例</th><th>通过率</th><th>分类明细</th></tr></thead>'
        f"<tbody>{l1_rows}</tbody></table></div>"
        if l1_rows else '<div class="muted">尚未生成 L1 报告</div>'
    )

    # ---------- L3 ----------
    if l3 and l3.get("avg"):
        gate = l3.get("gate") or {}
        badge = ('<span class="ok">门禁通过</span>' if gate.get("passed")
                 else f'<span class="bad">门禁未过：{_esc("；".join(gate.get("reasons") or []))}</span>')
        cal = l3.get("calibration") or []
        dim_cn = {"faithfulness": "忠实度", "relevance": "相关性", "completeness": "完整性"}

        def _cal_text(items: list[dict]) -> str:
            parts = []
            for c in items:
                if c.get("skipped"):
                    parts.append(f"{c.get('label')}：跳过")
                    continue
                mark = "—" if c.get("caught") is None else ("✓" if c.get("caught") else "✗")
                parts.append(f"{c.get('label')} {dim_cn.get(c.get('dim'), c.get('dim'))}={c.get('score')}{mark}")
            return "；".join(parts) or "未运行"

        cal_txt = _cal_text(cal)
        def _num(v) -> str:
            if v is None:
                return "—"
            try:
                n = float(v)
            except (TypeError, ValueError):
                return _esc(v)
            s = f"{round(n, 2):g}"
            return s if "." in s else s + ".0"

        tiles = "".join(
            f'<div class="rp-score"><div class="k">{label}</div>'
            f'<div class="v">{_num(l3_avg.get(key))}<small>/ 5</small></div>'
            f'<div class="bar"><i style="width:{int((l3_avg.get(key) or 0) * 20)}%"></i></div></div>'
            for label, key in (("忠实度", "faithfulness"), ("相关性", "relevance"), ("完整性", "completeness"))
        )
        tokens = l3.get("total_tokens")
        l3_block = (
            '<div class="rp-l3">'
            f'<div class="rp-scores">{tiles}</div>'
            '<div class="rp-l3-note">'
            f'<div class="row" style="flex-wrap:wrap;gap:7px;margin-bottom:9px">{badge}'
            f'<span class="pill">语义通过率 {round((l3.get("pass_rate") or 0) * 100)}%</span></div>'
            f'<div>样本 <b>{l3.get("answer_cases")}</b> 条答案类 + <b>{l3.get("safety_cases")}</b> 条拒答类；'
            f'编造告警 <b>{len(l3.get("hallucinations") or [])}</b> 条；裁判消耗 '
            f'<b>{"—" if tokens is None else tokens}</b> tokens。</div>'
            f'<div style="margin-top:7px">裁判：<b>{_esc(l3.get("judge_model") or l3.get("judge_channel") or "同通道")}</b></div>'
            f'<div style="margin-top:7px"><b>区分力校准</b>（植入错误答案后是否降分）：{_esc(cal_txt)}</div>'
            "</div></div>"
        )
    else:
        l3_block = '<div class="muted">尚未运行 L3（需要可用的模型 Key）。</div>'

    # ---------- 难题集 + 异构裁判 ----------
    hard = data.get("hard") or {}
    l3_hard = data.get("l3_hard") or {}
    hard_block = ""
    if hard.get("total"):
        same = l3_hard.get("same")
        cross = l3_hard.get("cross")
        cols = []
        if same:
            cols.append((f"同源裁判（{same.get('judge_model') or '同通道'}）", same))
        if cross:
            cols.append((f"异构裁判（{cross.get('judge_model') or '其他模型'}）", cross))
        head = "<tr><th>指标</th>" + "".join(f"<th>{_esc(n)}</th>" for n, _ in cols) + "</tr>" if cols else ""
        rows = ""
        for label, key in (("忠实度", "faithfulness"), ("相关性", "relevance"), ("完整性", "completeness")):
            cells = "".join(
                f"<td>{_score_badge((c.get('avg') or {}).get(key))}</td>" for _, c in cols
            )
            rows += f"<tr><td>{label}</td>{cells}</tr>"
        if cols:
            rows += "<tr><td>语义通过率</td>" + "".join(
                f"<td>{round((c.get('pass_rate') or 0) * 100)}%</td>" for _, c in cols
            ) + "</tr>"
            rows += "<tr><td>编造告警</td>" + "".join(
                f"<td>{len(c.get('hallucinations') or [])} 条</td>" for _, c in cols
            ) + "</tr>"
        cats = " · ".join(f"{c} {v['passed']}/{v['total']}" for c, v in (hard.get("by_category") or {}).items())
        hard_block = (
            '<section class="sec card" id="s-hard"><div class="sec-head"><span class="n">06</span><h2>难题集与裁判对比</h2>'
            f'<span class="note">{hard.get("total")} 条：多跳 / 数值边界 / 跨文件口径 / 资料空白</span></div>'
            f'<p class="muted" style="font-size:13px;margin:0 0 10px">L1 确定性断言：'
            f'<b>{hard.get("total") - sum(1 for r in hard.get("results", []) if not r.get("passed"))}/{hard.get("total")}'
            f' = {round((hard.get("pass_rate") or 0) * 100)}%</b>（{_esc(cats)}）</p>'
            + (f'<div class="table-wrap"><table>{head}<tbody>{rows}</tbody></table></div>' if cols else "")
            + '<p class="muted" style="font-size:12.5px;margin:10px 0 0">'
            '同一批答案、同一套 rubric，只换裁判模型。两者分数差距即「裁判偏好」的量级——'
            '所以 L3 分数只作趋势对比，门禁取更严的一侧。'
            + ("" if cols else "（尚未运行难题集 L3，先执行 tests/eval_l3.py --report tests/report_hard_glm.json）")
            + "</p></section>"
        )

    # ---------- 检索策略对比 ----------
    ret = data.get("retrieval") or {}
    ret_block = ""
    if ret.get("configs"):
        rows = ""
        for name, rconf in ret["configs"].items():
            r1, r4 = rconf.get("recall_at_1"), rconf.get("recall_at_4")
            mrr = rconf.get("mrr")
            rows += (
                f"<tr><td>{_esc(name)}</td>"
                f"<td>{'—' if r1 is None else format(r1, '.1%')}</td>"
                f"<td>{'—' if r4 is None else format(r4, '.1%')}</td>"
                f"<td>{'—' if mrr is None else format(mrr, '.3f')}</td>"
                f'<td class="muted">{_esc("、".join(rconf.get("misses") or []) or "—")}</td></tr>'
            )
        ret_cases = ret.get("cases") or max((c.get("cases") or 0) for c in ret["configs"].values())
        ret_block = (
            '<section class="sec card" id="s-ret"><div class="sec-head"><span class="n">05</span><h2>检索策略对比</h2>'
            f'<span class="note">Recall@1 / Recall@4 / MRR · {ret_cases} 条带召回标签的难题</span></div>'
            '<div class="table-wrap"><table><thead><tr><th>策略</th><th>R@1</th><th>R@4</th><th>MRR</th><th>未命中</th></tr></thead>'
            f"<tbody>{rows}</tbody></table></div>"
            '<p class="muted" style="font-size:12.5px;margin:10px 0 0">'
            "结论：<b>查询扩展是真正的增益点</b>（H10 从漏召回变成第 1 名命中）；"
            "<b>Hybrid 在本语料没有增益</b>，因此默认仍是 BM25——不为架构而架构。"
            "样本量小，结论是方向性的。</p></section>"
        )

    _kb_total = max(1, k["chunks"])
    kb_rows = "".join(
        f"<tr><td>{_esc(f['name'])}</td><td class=\"num\">{f['chunks']}</td>"
        f'<td style="width:42%"><div class="bar" style="height:6px"><i style="width:{f["chunks"] / _kb_total * 100:.0f}%"></i></div></td></tr>'
        for f in k["files"]
    )

    download = (
        "" if standalone else
        '<a class="btn ghost2" href="/api/report/export" download>下载独立 HTML</a>'
    )
    actions = "" if standalone else (
        f'<div class="actions"><a class="btn" href="/ask">去试真实问答</a>{download}'
        '<a class="btn ghost2" href="/dashboard">返回看板</a></div>'
    )
    header = nav("report", links=not standalone)
    if standalone:
        header = header.replace('href="/"', 'href="#"')

    html = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>项目汇报 · {BRAND}</title><style>{BASE_CSS}{REPORT_CSS}</style></head>
<body>
{header}
<main class="wrap">

<section class="rp-hero">
  <div class="eyebrow">Project Brief · 投前补充材料</div>
  <h1>一个能跑、能评测、也敢说自己边界的产品原型</h1>
  <p>可自建知识库的「文档问答助手」：把制度、手册、产品说明或任意文档放进知识库，用检索增强生成回答问题，
  每条结论都带出处，答不出来就转人工。当前挂载金融知识库作为第一版示例，换一套文档、切一个 profile 就能复用到别的领域。</p>
  <div class="badges">
    <span class="b solid">v{_esc(__version__)}</span>
    <span class="b solid">通道 {_esc(data['channel'])} / {_esc(data['model'])}</span>
    <span class="b">知识库 {k['chunks']} 块 / {len(k['files'])} 份</span>
    <span class="b">用例 {cases['total']} 条</span>
    <span class="b">零第三方运行时依赖</span>
    <span class="b">生成于 {_esc(data['generated_at'])}</span>
  </div>
  {actions}
</section>

<nav class="rp-nav" id="rpNav">
  <a href="#s-kpi" class="active">关键指标</a>
  <a href="#s-scope">定位</a>
  <a href="#s-arch">链路与闸门</a>
  <a href="#s-eval">评测结果</a>
  {('<a href="#s-ret">检索策略</a>' if ret_block else '')}
  {('<a href="#s-hard">难题集</a>' if hard_block else '')}
  <a href="#s-kb">知识库</a>
  <a href="#s-limits">边界</a>
  <a href="#s-run">怎么跑</a>
</nav>

<section class="sec card" id="s-kpi">
  <div class="sec-head"><span class="n">01</span><h2>关键指标</h2>
    <span class="note">实时聚合自 trace 与评测报告</span></div>
  <div class="kpis six">{kpis}</div>
  <p class="muted" style="font-size:12.5px;margin:10px 0 0;line-height:1.8">
    L1 = 确定性断言（行为 / 事实 / 安全）；L3 = 裁判模型语义评分（忠实度 / 相关性 / 完整性）。
    L1 是对抗零容忍的发布门禁，L3 用于发现「关键词对了但答案是编的」这类隐性质量问题。
  </p>
</section>

<section class="sec two-col" id="s-scope">
  <div class="card">
    <div class="sec-head"><span class="n">02</span><h2>它是什么</h2></div>
    <div class="axis"><span class="ic is">✓</span><div><b>一条可复现的 RAG 工作流。</b>切分 → 检索 → 生成 → 引用校验 → 观测，每步都能单独测。</div></div>
    <div class="axis"><span class="ic is">✓</span><div><b>有出处的答案。</b>强制 <code>[n]</code> 引用；模型不给出处，就降级成可追溯的抽取式答案。</div></div>
    <div class="axis"><span class="ic is">✓</span><div><b>会承认不知道。</b>检索置信度不足时转人工，不硬答。</div></div>
    <div class="axis"><span class="ic is">✓</span><div><b>坏了能看见。</b>降级、限流、超时都会写进 trace，并在看板上暴露。</div></div>
  </div>
  <div class="card">
    <div class="sec-head"><span class="n" style="visibility:hidden" aria-hidden="true">02</span><h2>它不是什么</h2></div>
    <div class="axis"><span class="ic not">✕</span><div><b>不是自主 Agent。</b>分支可穷举，按 C3 判断就该用固定链路，不该上 Agent 自治循环。</div></div>
    <div class="axis"><span class="ic not">✕</span><div><b>不给投资建议。</b>不预测涨跌、不推荐个股、不承诺收益，触发即拒答。</div></div>
    <div class="axis"><span class="ic not">✕</span><div><b>不替代柜面双录。</b>产品要素与制度口径可以答，风险测评和签约必须走线下合规流程。</div></div>
    <div class="axis"><span class="ic not">✕</span><div><b>不是生产系统。</b>缺鉴权、限流、审计与灰度；上线前需补生产八件套。</div></div>
  </div>
</section>

<section class="sec card" id="s-arch">
  <div class="sec-head"><span class="n">03</span><h2>链路与闸门</h2>
    <span class="note">每一层都有明确的失败动作</span></div>
  {ARCH_SVG}
  <div class="table-wrap" style="margin-top:12px"><table><thead><tr><th>环节</th><th>策略</th><th>失败时怎么办</th></tr></thead><tbody>
    <tr><td>输入</td><td>归一化去零宽 / 控制字符；注入、越权、荐股关键词拦截</td><td>直接拒答，不进检索与生成</td></tr>
    <tr><td>检索</td><td>BM25 + 中文二元组，top_k={cfg['top_k']}</td><td>异常时降级为不检索，并标 <code>degraded</code></td></tr>
    <tr><td>置信度</td><td>最高分低于 {cfg['min_score']} 视为未命中</td><td>转人工，不给“看起来像”的答案</td></tr>
    <tr><td>生成</td><td>OpenAI 兼容 LLM，温度 0.1，超时 {int(cfg['timeout'])}s，重试 {cfg['retries']} 次并尊重 Retry-After</td><td>降级为抽取式，并把 error 透传到结果</td></tr>
    <tr><td>引用</td><td>答案必须含有效 <code>[n]</code></td><td>无出处则降级为可追溯答案，标 <code>no_citation</code></td></tr>
  </tbody></table></div>
</section>

<section class="sec card" id="s-eval">
  <div class="sec-head"><span class="n">04</span><h2>评测结果</h2>
    <span class="note">L1 确定性断言 + L3 语义评分</span></div>
  {l1_table}
  <div style="margin-top:16px">{l3_block}</div>
</section>
{ret_block}
{hard_block}

<section class="sec card" id="s-kb">
  <div class="sec-head"><span class="n">07</span><h2>知识库构成</h2>
    <span class="note">{len(k['files'])} 份 · {k['chunks']} 块</span></div>
  <div class="table-wrap"><table><thead><tr><th>文件</th><th class="num">知识块</th><th>占比</th></tr></thead><tbody>{kb_rows}</tbody></table></div>
  <p class="muted" style="font-size:12.5px;margin:10px 0 0;line-height:1.8">
    其中 3 份为手写的产品与制度样本，3 份由 PDF 解析而来（含《商业银行理财业务监督管理办法》公开条款摘录）。
    PDF 接入方式：<code>python -m src.pdf_ingest --raw data/raw --out data/knowledge</code>。
    演示制度已明确标注为模拟样本，不代表任何机构正式制度。
  </p>
</section>

<section class="sec two-col" id="s-limits">
  <div class="card">
    <div class="sec-head"><span class="n">08</span><h2>已知边界（不藏）</h2></div>
    <ul class="rp-list">
      <li>默认 DeepSeek 官方通道<b>尚未接官方 Key</b>，演示走 glm 测试通道或离线抽取。</li>
      <li>L1 用例与知识库自洽，<b>换成真实制度 PDF 后需用真实 badcase 重建</b>。</li>
      <li>扫描件 PDF 不支持，需 OCR；当前只处理文本型 PDF。</li>
      <li>服务默认只绑 127.0.0.1，<b>对外暴露前必须加鉴权与限流</b>。</li>
      <li>L3 裁判本身不确定，分数用于趋势对比，不作逐条绝对判定。</li>
    </ul>
  </div>
  <div class="card">
    <div class="sec-head"><span class="n" style="visibility:hidden" aria-hidden="true">08</span><h2>下一步</h2></div>
    <ul class="rp-list">
      <li>接真实制度 PDF，用真实差评重建评测集（看板已支持差评一键转用例）。</li>
      <li>检索从 BM25 升级为向量召回 + 重排，接口已隔离。</li>
      <li>补生产八件套：幂等、限流、审计、成本上限、灰度、回滚。</li>
      <li>L3 扩到全量与多裁判投票，降低单模型偏好。</li>
    </ul>
  </div>
</section>

<section class="sec card" id="s-run">
  <div class="sec-head"><span class="n">09</span><h2>怎么跑起来</h2>
    <span class="note">未配置 Key 时自动走离线抽取，全链路仍可跑通</span></div>
<pre class="cmd"><span class="c"># 单次问答</span>
python -m src.cli "稳盈系列的起购金额是多少"
<span class="c"># 启动 Web：首页 / 问答 / 看板 / 汇报</span>
python -m src.server --port 8000
<span class="c"># L1 确定性断言 + L3 语义评分</span>
python tests/eval_run.py
python tests/eval_l3.py --report tests/report_llm_glm.json
<span class="c"># 导出这份汇报（独立 HTML，无需服务）</span>
python -m src.report --out dist/report.html</pre>
  <p class="muted" style="font-size:12.5px;margin:10px 0 0">配置 <code>LLM_API_KEY</code> 即切换真实模型；Key 只走环境变量，源码零硬编码。</p>
</section>

<div class="foot">
  该页面由项目自身数据生成，导出文件不依赖任何 API。<br>
  评测口径：L1 通过率 = 确定性断言全通过的比例；忠实度 = 回答事实能否在检索资料中找到依据（1-5，裁判模型评分）。<br>
  生成时间 {_esc(data['generated_at'])} · 通道 {_esc(data['channel'])} / {_esc(data['model'])}
</div>
</main>
{footer(links=not standalone)}
<script>
(function(){{
  var links=[].slice.call(document.querySelectorAll('#rpNav a'));
  var secs=links.map(function(a){{return document.querySelector(a.getAttribute('href'));}}).filter(Boolean);
  function sync(){{
    var y=window.scrollY+180, cur=secs[0];
    secs.forEach(function(s){{ if(s.offsetTop<=y) cur=s; }});
    links.forEach(function(a){{ a.classList.toggle('active', a.getAttribute('href')==='#'+cur.id); }});
  }}
  window.addEventListener('scroll',sync,{{passive:true}}); sync();
}})();
</script>
</body></html>"""
    return html


def main() -> None:
    ap = argparse.ArgumentParser(description="导出项目汇报页（独立 HTML）")
    ap.add_argument("--out", default=str(Path(__file__).resolve().parents[1] / "dist" / "report.html"))
    ap.add_argument("--json", action="store_true", help="同时打印汇总数据")
    args = ap.parse_args()

    data = collect()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(data, standalone=True), encoding="utf-8")
    if args.json:
        print(json.dumps({k: data[k] for k in ("channel", "model", "knowledge", "cases", "config")},
                         ensure_ascii=False, indent=2))
    print(f"已导出：{out}  ({out.stat().st_size / 1024:.1f} KB)")


if __name__ == "__main__":
    main()
