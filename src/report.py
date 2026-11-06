"""汇报页：把功能、链路、评测结果与生产控制汇总成一页自包含 HTML。

两个用途：
1. `GET /report`（服务在线时实时渲染）；
2. `python -m src.report --out dist/report.html`（导出独立文件，无服务也能打开，可直接分享或存档）。

关键点：导出的 HTML **不依赖任何 API**，数据在渲染时全部内联，双击即可看。
"""
import argparse
import itertools
import json
import os
import re
import threading
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

from .metrics import summarize
from .theme import (BASE_CSS, BRAND, JS_UTIL, MARK, THEME_HEAD, THEME_JS, footer)
from .version import __version__
from .webassets import load

# 管理面板脚本单独成文件：300 行分支塞进 Python 字符串既没高亮也没法 node --check。
# 导出时仍然内联，离线文件保持自包含。
REPORT_JS = load("report_admin.js")

REPORT_CSS = """
/* ---------- 汇报页 ----------
   .rp-hero 是深色封面：它在亮色和暗色主题下都保持深底，所以这一块的配色
   故意不走 var(--surface) 之类会翻转的令牌，用的是固定暖黑。
   除这块之外一律走令牌——翻不翻是设计决定，不是漏写。 */
/* 汇报页整页滚动：主站是 .main 内部滚动，这里让 body 滚——
   目录高亮脚本用的是 window.scrollY，整页滚动才对得上 */
.page-insights .main{height:auto;min-height:100vh;}
.page-insights .stage{overflow:visible;}
.rp-hero{position:relative;overflow:hidden;background:#1b1a17;color:#e6e0d4;border-radius:20px;padding:28px 32px 26px;margin-bottom:16px;
  box-shadow:0 30px 70px -40px rgba(27,26,23,.75);}
.rp-hero::before{content:"";position:absolute;inset:0;pointer-events:none;
  background:radial-gradient(560px 300px at 6% 0%,rgba(47,111,94,.42),transparent 62%),
             radial-gradient(520px 340px at 96% 10%,rgba(188,217,205,.26),transparent 66%);}
.rp-hero::after{content:"";position:absolute;inset:0;
  background-image:linear-gradient(rgba(255,255,255,.05) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.05) 1px,transparent 1px);
  background-size:42px 42px;mask-image:radial-gradient(600px 320px at 20% 10%,#000,transparent 78%);
  -webkit-mask-image:radial-gradient(600px 320px at 20% 10%,#000,transparent 78%);
  pointer-events:none;}
.rp-hero > *{position:relative;z-index:1;}
.rp-hero .eyebrow{color:#bcd9cd;margin-bottom:12px;}
.rp-hero .eyebrow::before{background:#82c0a9;}
.rp-hero h1{font-size:clamp(23px,2.4vw,31px);margin:0 0 10px;letter-spacing:-.03em;color:#f2efe8;line-height:1.28;}
.rp-hero p{color:#c9c3b8;max-width:64ch;margin:0 0 16px;line-height:1.85;font-size:13.5px;
  /* 中文没有单词边界，默认换行容易把「答案」拆成「答/案」两行；
     pretty 会让最后一行不至于只剩一两个字（Chromium 117+，其余浏览器无副作用） */
  text-wrap:pretty;}
.rp-hero .badges{display:flex;flex-wrap:wrap;gap:7px;}
.rp-hero .b{font-size:11.5px;padding:4px 10px;border-radius:999px;background:rgba(255,255,255,.09);color:#e6e0d4;border:1px solid rgba(255,255,255,.1);}
.rp-hero .b.solid{background:rgba(47,111,94,.92);border-color:rgba(188,217,205,.45);color:#fff;}
.rp-hero .actions{margin-top:20px;display:flex;gap:9px;flex-wrap:wrap;align-items:center;}
/* 首屏两栏：左边一句话说清是什么，右边三个数字回答「行不行」。
   原来是单栏 340px 的自述长文，一份汇报的第一屏不该全是形容词。 */
.hero-grid{display:grid;grid-template-columns:1.5fr .72fr;gap:28px;align-items:start;}
.hero-stats{display:flex;flex-direction:column;border-left:1px solid rgba(255,255,255,.13);padding-left:20px;}
.hs{padding:8px 0;border-bottom:1px solid rgba(255,255,255,.07);}
.hs:last-child{border-bottom:0;}
.hs .k{display:block;font-size:11px;color:#a9a297;letter-spacing:.02em;}
.hs .v{display:block;font-size:27px;font-weight:700;color:#f4f1ea;letter-spacing:-.035em;
  line-height:1.15;font-variant-numeric:tabular-nums;}
.hs .s{display:block;font-size:11px;color:#9c968b;margin-top:1px;}
@media (max-width:820px){
  .hero-grid{grid-template-columns:1fr;gap:16px;}
  .hero-stats{flex-direction:row;border-left:0;padding-left:0;
    border-top:1px solid rgba(255,255,255,.12);padding-top:4px;}
  .hs{flex:1;border-bottom:0;padding:7px 10px 0 0;}
  .hs .v{font-size:20px;}
}
.rp-hero a.btn{background:#fff;color:#12201b;box-shadow:0 10px 24px -16px rgba(0,0,0,.8);}
.rp-hero a.btn:hover{background:#e4efe9;}
.rp-hero a.btn.ghost2{background:rgba(255,255,255,.08);border:1px solid rgba(255,255,255,.24);color:#e6e0d4;}
.rp-hero a.btn.ghost2:hover{background:rgba(255,255,255,.14);}
/* 公开视图提示：同在深色 hero 内，颜色必须固定，不能用会翻转的令牌 */
.rp-redacted{margin-top:14px;padding:9px 12px;border-radius:9px;font-size:12px;line-height:1.7;
  background:rgba(251,191,36,.14);border:1px solid rgba(251,191,36,.32);color:#f0d9a8;}

/* 目录 */
.rp-nav{position:sticky;top:0;z-index:30;display:flex;gap:2px;overflow:auto;scrollbar-width:none;
  padding:9px 0;margin-bottom:16px;background:var(--bg);box-shadow:inset 0 -1px 0 var(--line);}
.rp-nav::-webkit-scrollbar{display:none;}
.rp-nav a{padding:6px 11px;border-radius:8px;font-size:12.5px;color:var(--muted);white-space:nowrap;transition:background .15s,color .15s;}
.rp-nav a:hover{background:var(--hover);color:var(--ink);}
.rp-nav a.active{background:var(--surface);color:var(--brand-600);font-weight:600;border:1px solid var(--line);box-shadow:var(--sh-1);}

.sec{margin-bottom:24px;scroll-margin-top:110px;}
/* 首列都是「接入 / 输入 / 关键词」这种两三个字的短词：被挤成两行
   （「关键/词」）比让整张表窄一点更难看，也不利于竖着扫。 */
.sec table td:first-child{white-space:nowrap;}
.sec-head{display:flex;align-items:center;gap:10px;margin-bottom:12px;flex-wrap:wrap;min-height:24px;}
.sec-head h2{font-size:16px;letter-spacing:-.02em;}
.sec-head .n{font-family:var(--mono);font-size:10.5px;font-weight:600;color:var(--brand);background:var(--brand-soft);border-radius:5px;padding:2px 6px;}
.sec-head .note{font-size:12px;color:var(--muted);margin-left:auto;text-align:right;background:none;border:0;padding:0;display:block;line-height:1.6;}
@media (max-width:760px){.sec-head .note{margin-left:0;text-align:left;}}
.two-col{display:grid;grid-template-columns:1fr 1fr;gap:16px;}
@media (max-width:860px){.two-col{grid-template-columns:1fr;}}
/* 能力区三组：每组一个主题，不再是一条条平铺的 ✓（15 条全勾等于零信息量）。
   三列在 1440 下每列约 430px，正好放 4 条短句；窄了就退回单列。 */
.three-col{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;}
@media (max-width:1080px){.three-col{grid-template-columns:1fr;}}
.axis{display:flex;gap:10px;align-items:flex-start;margin:10px 0;font-size:13px;line-height:1.8;}
.axis .ic{flex:none;width:19px;height:19px;border-radius:6px;display:flex;align-items:center;justify-content:center;font-size:11px;margin-top:3px;font-weight:700;}
.axis .ic.is{background:var(--ok-soft);color:var(--ok);}
.axis .ic.not{background:var(--bad-soft);color:var(--bad);}
.axis b{font-weight:650;color:var(--ink);}
.score{display:inline-block;min-width:36px;text-align:center;font-weight:650;border-radius:6px;padding:2px 6px;font-variant-numeric:tabular-nums;}
.score.s5,.score.s4{background:var(--ok-soft);color:var(--ok);}
.score.s3{background:var(--warn-soft);color:var(--warn);}
.score.s2,.score.s1{background:var(--bad-soft);color:var(--bad);}
.arch{background:linear-gradient(180deg,var(--surface-2),var(--surface));border:1px solid var(--line);border-radius:14px;padding:10px 8px;}
.rp-list{margin:0;padding-left:18px;line-height:1.95;font-size:12.8px;color:var(--text);}
.rp-list li{margin-bottom:3px;}
.rp-list li::marker{color:var(--faint);}
/* 失败样本：用 bad 语义色标 ID 就够，不要整块铺红底——
   一片红会让人直接跳过，而这一块恰恰是最该被读完的。 */
.edge-fail{padding:8px 0;border-bottom:1px solid var(--line);font-size:12.5px;line-height:1.7;}
.edge-fail:last-of-type{border-bottom:0;}
.edge-fail b{display:inline-block;min-width:40px;font-family:var(--mono);font-size:11.5px;
  color:var(--bad);font-weight:600;}
.edge-fail span{color:var(--text);}
.edge-fail i{display:block;font-style:normal;color:var(--muted);font-size:12px;
  margin-top:2px;padding-left:40px;}
.edge-ok{margin:0 0 5px;font-size:13px;color:var(--text);}
.edge-degrade{margin-top:12px;padding-top:11px;border-top:1px solid var(--line);}
.edge-reasons{display:flex;justify-content:space-between;gap:10px;margin:3px 0;
  font-size:12px;line-height:1.6;}
.edge-reasons span{color:var(--muted);flex:none;}
.edge-reasons em{font-style:normal;text-align:right;color:var(--ink);}
/* 两栏内容量不可能刚好相等：默认 stretch 会把矮的那张拉高留白，
   顶端对齐更接近排版常识——宁可高矮不一，也不要一张卡空着半屏。 */
#s-edge{align-items:start;}
.foot{margin-top:22px;padding-top:14px;border-top:1px solid var(--line);color:var(--faint);font-size:11.5px;line-height:1.85;}

/* L3 语义质量 */
.rp-l3{display:grid;grid-template-columns:1.1fr .9fr;gap:22px;align-items:center;}
.rp-scores{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;}
.rp-score{border:1px solid var(--line);border-radius:12px;padding:13px 14px;background:linear-gradient(180deg,var(--surface),var(--surface-2));}
.rp-score .k{font-size:11.5px;color:var(--muted);}
.rp-score .v{font-size:26px;font-weight:700;color:var(--ink);letter-spacing:-.035em;margin:3px 0 8px;line-height:1.1;font-variant-numeric:tabular-nums;}
.rp-score .v small{font-size:11.5px;color:var(--faint);font-weight:500;letter-spacing:0;margin-left:2px;}
.rp-score .bar{height:5px;}
.rp-l3-note{font-size:12.5px;color:var(--muted);line-height:1.9;}
.rp-l3-note b{color:var(--ink);font-weight:600;}
.pill{display:inline-flex;align-items:center;gap:5px;font-size:11.5px;padding:5px 10px;border-radius:999px;
  border:1px solid var(--line);background:var(--surface-2);color:var(--text);font-weight:500;}
@media (max-width:860px){.rp-l3{grid-template-columns:1fr;gap:16px;}}

/* 让汇报页的 6 个 KPI 排成整齐的 3 × 2 */
.kpis.six{grid-template-columns:repeat(3,1fr);}
/* 副标题是「口径」不是装饰：--faint 在米色底上约 3.4:1，读不清等于没写 */
.kpi .sub{color:var(--muted);font-size:11.5px;line-height:1.55;margin-top:4px;}
@media (max-width:900px){.kpis.six{grid-template-columns:repeat(2,1fr);}}

.rp-hero .live{display:inline-flex;align-items:center;gap:7px;font-size:11px;color:#8fd4ae;}
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
/* ============ 外壳：顶栏 + 展示/管理双态 ============
   这一页要同时干两件事：给别人看（展示）和给自己改（管理）。
   原则：展示永远是主体，管理按需从右侧进入，且**不遮挡正文**——
   打开面板时收窄正文容器，而不是拿浮层盖上去。 */
.rp-top{position:sticky;top:0;z-index:80;display:flex;align-items:center;gap:10px;
  height:52px;padding:0 18px;background:var(--surface);border-bottom:1px solid var(--line);}
.rp-brand{display:flex;align-items:center;gap:9px;font-size:13.5px;font-weight:600;color:var(--ink);}
.rp-brand .mark{width:24px;height:24px;border-radius:7px;}
.rp-brand .mark svg{width:14px;height:14px;}
.rp-brand .sep{font-weight:400;color:var(--faint);font-size:12.5px;}
.rp-state{display:inline-flex;align-items:center;gap:6px;font-size:11.5px;
  padding:3px 9px;border-radius:999px;background:var(--surface-2);
  border:1px solid var(--line);color:var(--muted);}
.rp-state i{width:6px;height:6px;border-radius:50%;background:var(--faint);}
.rp-state[data-state="online"]{color:var(--ok);background:var(--ok-soft);border-color:var(--ok-soft);}
.rp-state[data-state="online"] i{background:var(--ok);box-shadow:0 0 0 3px rgba(44,122,91,.16);}
.rp-tbtn{display:inline-flex;align-items:center;height:32px;padding:0 11px;
  border:1px solid var(--line-2);border-radius:8px;background:var(--surface);
  color:var(--text);font-size:12.5px;font-family:inherit;white-space:nowrap;cursor:pointer;
  transition:background .14s,border-color .14s,color .14s,transform .12s;}
.rp-tbtn:hover{background:var(--surface-2);color:var(--ink);}
.rp-tbtn.primary{border-color:var(--brand-line);background:var(--brand-soft);color:var(--brand-600);font-weight:600;}
.rp-tbtn.primary:hover{background:var(--brand-tint);border-color:var(--brand);}
.rp-tbtn.primary[aria-expanded="true"]{background:var(--brand);border-color:var(--brand);color:var(--on-brand);}
.rp-tbtn.is-off{opacity:.65;}

/* 管理面板：固定右侧，打开时正文让位 */
.rp-admin{position:fixed;top:52px;right:0;bottom:0;width:380px;z-index:75;
  display:flex;flex-direction:column;background:var(--surface);
  border-left:1px solid var(--line);box-shadow:-24px 0 48px -32px rgba(17,18,22,.35);
  transform:translateX(100%);transition:transform .22s ease;overflow:hidden;}
body.admin-on .rp-admin{transform:none;}
.main{transition:padding-right .22s ease;}
body.admin-on .main{padding-right:380px;}
.rp-admin-head{flex:none;display:flex;align-items:center;gap:9px;height:46px;
  padding:0 10px 0 16px;border-bottom:1px solid var(--line);}
.rp-admin-head h2{font-size:13.5px;}
.rp-admin-head .spacer{flex:1;}
.rp-admin-head .rp-tbtn{width:28px;padding:0;justify-content:center;font-size:16px;line-height:1;}
.rp-admin-body{flex:1;overflow-y:auto;padding:12px 14px 48px;}
.rp-admin-body::-webkit-scrollbar{width:6px;}
.rp-admin-body::-webkit-scrollbar-thumb{background:var(--line-2);border-radius:3px;}

/* 分组：用 details，天然可折叠、键盘可达，不需要额外 JS */
.agroup{border:1px solid var(--line);border-radius:10px;margin-bottom:10px;overflow:hidden;}
.agroup>summary{display:flex;align-items:center;gap:8px;padding:10px 12px;
  font-size:13px;font-weight:600;color:var(--ink);cursor:pointer;list-style:none;}
.agroup>summary::-webkit-details-marker{display:none;}
.agroup>summary::before{content:"+";width:10px;color:var(--faint);font-weight:400;}
.agroup[open]>summary::before{content:"−";}
.agroup[open]>summary{border-bottom:1px solid var(--line);background:var(--surface-2);}
.ag-count{margin-left:auto;font-size:11px;font-weight:600;color:var(--brand-600);
  background:var(--brand-soft);border-radius:999px;padding:1px 7px;}
.ag-count:empty{display:none;}
.ag-body{padding:12px 12px 14px;font-size:13px;line-height:1.7;color:var(--text);}
.ag-empty{margin:0;color:var(--muted);font-size:12px;}
.ag-hint{margin:7px 0 0;color:var(--muted);font-size:12px;line-height:1.65;}
.ag-mut{color:var(--muted);font-size:12px;}
.ag-error{margin:0;padding:8px 10px;border-radius:7px;background:var(--bad-soft);
  color:var(--bad);font-size:12px;line-height:1.7;}
.ag-error .ag-link{display:block;margin-top:4px;padding:0;border:0;background:none;
  color:var(--brand);font-size:11.5px;text-decoration:underline;cursor:pointer;}

/* 文档台账 */
.ag-table{table-layout:fixed;width:100%;border-collapse:collapse;font-size:13px;}
.ag-table th{text-align:left;padding:4px 5px;font-size:11px;font-weight:600;
  color:var(--muted);border-bottom:1px solid var(--line);}
.ag-table td{padding:6px 5px;border-bottom:1px solid var(--line);}
.ag-table tr:last-child td{border-bottom:0;}
/* 列宽固定：不定宽时第一列会被长文件名撑开，把「块」和「删除」挤出可视区 */
.ag-table th:nth-child(2),.ag-table td:nth-child(2){width:38px;text-align:right;color:var(--muted);}
.ag-table th:nth-child(3),.ag-table td:nth-child(3){width:54px;text-align:right;white-space:nowrap;}
.ag-name{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
  max-width:0;/* table-layout:fixed 下 0 + width:100% 才会真正按剩余宽度省略 */}
/* 删除：图标按钮。列表里每行都写「删除」既是噪音，也会在 54px 列里折行 */
.ag-del{width:24px;height:24px;padding:0 !important;border:0 !important;
  background:none !important;border-radius:6px !important;color:var(--muted) !important;
  font-size:15px !important;line-height:1 !important;font-weight:400 !important;
  white-space:nowrap !important;}
.ag-del:hover{background:var(--bad-soft) !important;color:var(--bad) !important;}
.ag-del.armed{background:var(--bad) !important;color:var(--surface) !important;}
.ag-body button.armed{background:var(--bad);border-color:var(--bad);color:var(--surface);}

/* 表单与按钮 */
.ag-upload{display:flex;flex-direction:column;gap:7px;margin-top:12px;
  padding-top:12px;border-top:1px dashed var(--line);}
.ag-upload input,.ag-upload textarea,.ag-inline input{width:100%;padding:7px 9px;
  border:1px solid var(--line-3);border-radius:7px;background:var(--bg);color:var(--text);
  font-family:inherit;font-size:12.5px;line-height:1.6;outline:none;}
.ag-upload input:focus,.ag-upload textarea:focus,.ag-inline input:focus{
  border-color:var(--brand);box-shadow:0 0 0 3px rgba(47,111,94,.12);}
.ag-upload input:focus-visible,.ag-upload textarea:focus-visible,.ag-inline input:focus-visible{
  outline:2px solid var(--brand);outline-offset:1px;box-shadow:none;}
.ag-upload textarea{resize:vertical;min-height:64px;}
.ag-inline{display:flex;gap:7px;margin:10px 0;}
.ag-inline input{width:80px;flex:none;}
.ag-body button{height:32px;padding:0 11px;border:1px solid var(--brand-line);
  border-radius:var(--r-sm);background:var(--brand-soft);color:var(--brand-600);
  font-family:inherit;font-size:12.5px;font-weight:600;cursor:pointer;
  transition:background .14s,transform .12s;}
.rp-tbtn:active,.ag-body button:active{transform:translateY(1px);}
.rp-tbtn[disabled],.ag-body button[disabled]{opacity:.55;cursor:not-allowed;transform:none;}
.ag-body button:hover{background:var(--brand-tint);}
.ag-body button:disabled{opacity:.6;cursor:not-allowed;}
.ag-body button.ag-ghost{background:var(--surface);border-color:var(--line-2);
  color:var(--text);font-weight:500;}
.ag-body button.ag-ghost:hover{background:var(--surface-2);}
.ag-row{display:flex;gap:7px;flex-wrap:wrap;margin-top:9px;}

/* 键值行 / 变更卡 / 审计 */
.ag-kv{display:flex;align-items:baseline;justify-content:space-between;gap:10px;
  padding:6px 0;border-bottom:1px solid var(--line);font-size:12px;}
.ag-kv span{color:var(--muted);}
.ag-kv b{font-weight:600;color:var(--ink);font-variant-numeric:tabular-nums;text-align:right;}
.ag-change{border:1px solid var(--line);border-radius:8px;padding:9px 10px;margin-bottom:8px;}
.ag-change-h{display:flex;align-items:baseline;justify-content:space-between;gap:8px;font-size:12px;}
.ag-files{margin-top:4px;}
.ag-file{display:inline-block;margin:3px 4px 0 0;padding:1px 6px;border-radius:5px;
  background:var(--surface-2);font-size:11.5px;}
.ag-file i{font-style:normal;color:var(--faint);}
.ag-warn{margin-top:5px;padding:3px 7px;border-radius:5px;background:var(--warn-soft);
  color:var(--warn);font-size:11.5px;}
.ag-sub{margin:11px 0 5px;font-size:11px;font-weight:600;letter-spacing:.1em;
  text-transform:uppercase;color:var(--muted);}
/* 失败用例：这是评测里最该被看见的部分，不要只给一个通过率 */
.ag-fail{padding:7px 9px;border-radius:7px;background:var(--bad-soft);margin-bottom:6px;
  color:var(--bad);font-size:12.5px;line-height:1.65;}
.ag-fail b{font-weight:600;}
.ag-fail i{display:block;margin-top:2px;font-style:normal;color:var(--muted);}
.ag-audit{max-height:180px;overflow:auto;}
.ag-audit-row{display:flex;gap:8px;padding:3px 0;border-bottom:1px solid var(--line);font-size:11.5px;}
.ag-audit-row span{color:var(--muted);font-variant-numeric:tabular-nums;}
.ag-audit-row b{font-weight:500;color:var(--text);}

/* 操作回执：时间 / 动作 / 对象 / 结果四段对齐，扫一眼就知道刚才干了什么。
   toast 是「现在发生了什么」，回执是「这次会话都发生过什么」——两者不能互相替代。 */
.ag-receipts[hidden]{display:none;}
.ag-receipt{display:grid;grid-template-columns:52px 1fr;gap:3px 8px;
  padding:7px 0;border-bottom:1px solid var(--line);font-size:12px;line-height:1.6;}
.ag-receipt:last-child{border-bottom:0;}
.ag-receipt time{color:var(--muted);font-variant-numeric:tabular-nums;font-size:11.5px;}
.ag-receipt .what{color:var(--ink);}
.ag-receipt .what b{font-weight:600;}
.ag-receipt .said{grid-column:2;color:var(--muted);font-size:11.5px;}
.ag-receipt.is-bad .what{color:var(--bad);}

/* 离线态说明：不能改的时候要说清楚为什么、怎么办 */
.ag-offline{padding:12px 13px;border:1px solid var(--line);border-radius:10px;
  background:var(--surface-2);color:var(--muted);font-size:12px;line-height:1.8;}
.ag-offline b{color:var(--ink);}
.ag-offline code{display:block;margin-top:7px;padding:7px 9px;border-radius:6px;
  background:var(--surface);border:1px solid var(--line);
  font-family:var(--mono);font-size:11.5px;color:var(--text);overflow-x:auto;}

/* 展示区里的管理入口：只在管理态出现，平时不打扰阅读 */
.sec-head .adm{display:none;margin-left:8px;padding:2px 9px;border-radius:999px;
  border:1px solid var(--brand-line);background:var(--brand-soft);color:var(--brand-600);
  font-family:inherit;font-size:11.5px;font-weight:600;cursor:pointer;}
body.admin-on .sec-head .adm{display:inline-flex;}

/* 数据已变更提示 */
.rp-stale{position:fixed;left:50%;bottom:20px;z-index:90;transform:translateX(-50%);
  display:flex;align-items:center;gap:12px;padding:9px 10px 9px 16px;border-radius:999px;
  background:#1b1a17;color:#e6e0d4;font-size:12.5px;box-shadow:var(--sh-3);}
.rp-stale button{border:0;border-radius:999px;padding:5px 11px;background:rgba(255,255,255,.16);
  color:inherit;font-family:inherit;font-size:12px;font-weight:600;cursor:pointer;}
.rp-stale button:hover{background:rgba(255,255,255,.26);}

/* 顶栏占了 52px，原来的吸顶偏移要跟着改 */
.rp-nav{top:52px;}
.sec{scroll-margin-top:110px;}

@media (max-width:760px){
  /* 960 宽的架构图缩进 390 视口后字高只剩 3.8px：改成横向滚动，保住可读尺寸 */
  #s-arch{overflow-x:auto;}
  #s-arch .arch{width:660px;max-width:none;}
}

@media (max-width:900px){
  /* 窄屏没有并排的空间：面板直接盖住，正文不再让位 */
  body.admin-on .main{padding-right:0;}
  .rp-admin{width:100%;box-shadow:none;}
  .rp-top{padding:0 12px;gap:7px;}
  .rp-brand .sep,.rp-state span{display:none;}
  .rp-tbtn{padding:0 9px;font-size:12px;}
}

@media (max-width:560px){
  /* 390px 下四个按钮必然撑破一行：只留「管理」，其余在正文 hero 里都有 */
  .rp-top .rp-tbtn:not(.primary){display:none;}
}

@media print{
  body{background:#fff;}
  .site-foot,.rp-nav,.rp-top,.rp-admin,.rp-stale,.side{display:none !important;}
  body.admin-on .main{padding-right:0;}
  .card,.kpi,.sec,.rp-score,.agroup{break-inside:avoid;}
  .rp-hero{background:#1b1a17 !important;-webkit-print-color-adjust:exact;print-color-adjust:exact;}
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
        return "离线基线（抽取式，不调模型）"
    return f"{channel} / {model}"


_COLLECT_CACHE: dict[tuple, tuple[float, dict]] = {}
_COLLECT_LOCK = threading.Lock()
_CACHE_STATS = {"hit": 0, "miss": 0}
# 参与签名的静态输入：评测报告与用例集变更就重算
_CACHE_FILES = (
    "baseline.json", "report_llm.json", "report_l3.json", "report_hard.json",
    "report_retrieval.json", "report_l3_hard_same.json", "report_l3_hard_cross.json",
    "eval_cases.jsonl", "eval_cases_feedback.jsonl", "eval_cases_uncovered.jsonl",
)


def _stat_sig(path: Path) -> tuple:
    try:
        st = path.stat()
        return (st.st_mtime_ns, st.st_size)
    except OSError:
        return (0, 0)


def _collect_key(pipe, tests_dir: Path) -> tuple:
    """缓存键：知识库文件 + 评测报告 mtime/size + 检索配置。

    trace 不参与签名：每问一次都会变，参与就等于永不命中。指标改用 TTL
    （REPORT_CACHE_TTL，默认 60s）容忍最多一分钟延迟，汇报页不需要秒级。
    """
    kb = []
    try:
        for name in sorted(os.listdir(pipe.knowledge_dir)):
            if name.lower().endswith((".md", ".txt")):
                kb.append((name, _stat_sig(Path(pipe.knowledge_dir) / name)))
    except OSError:
        # 读不到目录时不能给一个「空签名」：那会让旧缓存一直命中，
        # 目录恢复后也看不出数据是旧的。留一个明确标记，下次必然重算。
        kb.append(("__unreadable__", (0, 0)))
    settings = pipe.settings
    # 只取渲染用到的字段。原来用 repr(settings)：整个对象里含 api_keys 与
    # embedding_api_key，缓存键会把密钥原文留在内存里；而且无关字段一动就整页重算。
    config_sig = repr((settings.channel, settings.model, settings.top_k, settings.min_score,
                       settings.llm_timeout_s, settings.llm_max_retries,
                       settings.keyword_top_n))
    return (
        str(Path(pipe.knowledge_dir).resolve()), len(pipe.chunks),
        tuple(kb), tuple((name, _stat_sig(tests_dir / name)) for name in _CACHE_FILES),
        config_sig,
    )


def collect(pipe=None, root: Path | None = None, use_cache: bool = True) -> dict:
    """汇总页面所需的全部数据；带 mtime 签名缓存，静态输入不变就直接复用。"""
    project_root = Path(root) if root else Path(__file__).resolve().parents[1]
    tests_dir = project_root / "tests"
    if pipe is None:
        from .pipeline import RAGPipeline
        pipe = RAGPipeline(str(project_root / "data" / "knowledge"))

    try:
        ttl = max(0, int(os.getenv("REPORT_CACHE_TTL", "60") or "60"))
    except ValueError:
        # 写成 "60s"/"1m" 时不该整页 500：那是配置笔误，不该让页面塌掉
        ttl = 60
    key = _collect_key(pipe, tests_dir) if (use_cache and ttl) else None
    now = time.monotonic()
    if key is not None:
        with _COLLECT_LOCK:
            entry = _COLLECT_CACHE.get(key)
        if entry and now - entry[0] <= ttl:
            _CACHE_STATS["hit"] += 1
            data = dict(entry[1])
            data["cache"] = {"hit": True, "age_s": round(now - entry[0], 1), "ttl_s": ttl}
            return data

    _CACHE_STATS["miss"] += 1
    data = _collect_uncached(pipe, project_root, tests_dir)
    data["cache"] = {"hit": False, "age_s": 0.0, "ttl_s": ttl}
    if key is not None:
        with _COLLECT_LOCK:
            _COLLECT_CACHE[key] = (now, data)
            # 同一进程里换知识库/重建会留下旧键，只保留最近 8 个
            if len(_COLLECT_CACHE) > 8:
                oldest = min(_COLLECT_CACHE, key=lambda k: _COLLECT_CACHE[k][0])
                _COLLECT_CACHE.pop(oldest, None)
    return data


def cache_stats() -> dict:
    with _COLLECT_LOCK:
        return {**_CACHE_STATS, "entries": len(_COLLECT_CACHE)}


def _collect_uncached(pipe, project_root: Path, tests_dir: Path) -> dict:
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
    # 语料未覆盖基线：这些用例期望的行为是「明确说不知道」，
    # 计入总用例数才对得上 `evaluator.default_case_files()` 的真实合并集
    # （人工 25 + 拒答 10 + 反馈 1 = 36）。以前只算前两项，页面写 26，
    # 而 `tests/eval_run.py` 默认跑的是 36 条——两个数字对不上，读者无法判断谁对。
    uncovered = len([l for l in (tests_dir / "eval_cases_uncovered.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]) \
        if (tests_dir / "eval_cases_uncovered.jsonl").exists() else 0

    l1 = []
    for name in ("baseline.json", "report_llm.json"):
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
            # 只有报告自带 run_at 才可信。拿文件 mtime 兜底会把「git checkout 恢复的
            # 旧报告」标成今天跑的——页面因此看起来像刚验过，实际是两周前的结论。
            "reported_at": str(data.get("run_at") or "")[:16].replace("T", " "),
        })

    l3 = _read_json(tests_dir / "report_l3.json") if (tests_dir / "report_l3.json").exists() else None
    hard_l1 = _read_json(tests_dir / "report_hard.json") if (tests_dir / "report_hard.json").exists() else None
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
        "cases": {"curated": curated, "feedback": fb_cases, "uncovered": uncovered,
                  "total": curated + fb_cases + uncovered},
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
            "keyword_top_n": pipe.settings.keyword_top_n,
        },
    }


def _kpi(value, key: str, sub: str = "") -> str:
    body = f'<div class="v">{_esc(value)}</div><div class="k">{_esc(key)}</div>'
    if sub:
        body += f'<div class="sub">{_esc(sub)}</div>'
    return f'<div class="kpi">{body}</div>'


def kpi_subs(data: dict) -> list[str]:
    """每个 KPI 的样本量与口径，与 kpi_rows 一一对应。

    放副标题而不是标题里：数字要能被一眼扫到，口径是「想深究时再看」的第二层。
    单独成函数是为了能直接断言——没有样本量的通过率，读者没法判断该信几分。
    """
    m = data.get("metrics") or {}
    l1 = data.get("l1") or []
    l3 = (data.get("l3") or {}).get("avg") or {}
    cases = data.get("cases") or {}
    best = max(l1, key=lambda x: (x["pass_rate"] or 0)) if l1 else None
    n = m.get("requests") or 0
    total_cases = cases.get("total") or 0
    # 报告条数 ≠ 当前用例集条数时要说出来：读者看到「100%」却不知道
    # 它只覆盖了 26 条、而默认集已经 36 条，会高估结论的适用范围。
    l1_sub = "尚无 L1 报告"
    if best:
        stamp = best.get("reported_at") or ""
        l1_sub = f"{best['total']} 条"
        if total_cases and best["total"] != total_cases:
            l1_sub += f" · 集已扩到 {total_cases} 条"
        elif stamp:
            l1_sub += f" · {stamp[5:10]} 报告"
    return [
        f"{len(data['knowledge']['files'])} 份文档已切分索引",
        f"人工 {cases.get('curated', 0)} · 拒答 {cases.get('uncovered', 0)} · "
        f"反馈 {cases.get('feedback', 0)}",
        l1_sub,
        f"裁判 {l3.get('judge_model') or '同源'} · 1-5 分" if l3 else "未运行",
        f"answer 类均值 · {n} 条 trace" if n else "无 trace 记录",
        "含关键词直出 · 不代表模型耗时" if n else "无 trace 记录",
    ]


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
      <path d="M0,0 L10,5 L0,10 z" fill="var(--faint)"/>
    </marker>
  </defs>
  <g font-family="-apple-system, 'Microsoft YaHei', sans-serif">
    <rect x="18" y="18" width="270" height="64" rx="11" fill="var(--surface)" stroke="var(--line)"/>
    <circle cx="39" cy="40" r="9" fill="var(--brand-soft)"/>
    <text x="39" y="43.6" font-size="10" font-weight="700" fill="var(--brand)" text-anchor="middle">1</text>
    <text x="55" y="44" font-size="12.5" font-weight="600" fill="var(--ink)">输入校验</text>
    <text x="55" y="62" font-size="10.5" fill="var(--muted)">归一化去零宽 · 注入 / 越权 / 荐股拦截</text>

    <rect x="345" y="18" width="270" height="64" rx="11" fill="var(--surface)" stroke="var(--line)"/>
    <circle cx="366" cy="40" r="9" fill="var(--brand-soft)"/>
    <text x="366" y="43.6" font-size="10" font-weight="700" fill="var(--brand)" text-anchor="middle">2</text>
    <text x="382" y="44" font-size="12.5" font-weight="600" fill="var(--ink)">向量召回 + 重排</text>
    <text x="382" y="62" font-size="10.5" fill="var(--muted)">字符 n-gram 向量 · 词覆盖 / 长片段重排</text>

    <rect x="672" y="18" width="270" height="64" rx="11" fill="var(--warn-soft)" stroke="var(--warn)"/>
    <circle cx="693" cy="40" r="9" fill="var(--warn-soft)"/>
    <text x="693" y="43.6" font-size="10" font-weight="700" fill="var(--warn)" text-anchor="middle">3</text>
    <text x="709" y="44" font-size="12.5" font-weight="600" fill="var(--ink)">置信度闸门</text>
    <text x="709" y="62" font-size="10.5" fill="var(--warn)">低于阈值返回未命中 · 附相似问题</text>

    <rect x="672" y="150" width="270" height="64" rx="11" fill="var(--brand-soft)" stroke="var(--brand-line)"/>
    <circle cx="693" cy="172" r="9" fill="var(--brand-tint)"/>
    <text x="693" y="175.6" font-size="10" font-weight="700" fill="var(--brand-600)" text-anchor="middle">4</text>
    <text x="709" y="176" font-size="12.5" font-weight="600" fill="var(--ink)">生成层</text>
    <text x="709" y="194" font-size="10.5" fill="var(--muted)">LLM 生成 · 超时重试 · 抽取式兜底</text>

    <rect x="345" y="150" width="270" height="64" rx="11" fill="var(--surface)" stroke="var(--line)"/>
    <circle cx="366" cy="172" r="9" fill="var(--brand-soft)"/>
    <text x="366" y="175.6" font-size="10" font-weight="700" fill="var(--brand)" text-anchor="middle">5</text>
    <text x="382" y="176" font-size="12.5" font-weight="600" fill="var(--ink)">引用校验</text>
    <text x="382" y="194" font-size="10.5" fill="var(--muted)">无有效 [n] → 降级为可追溯答案</text>

    <rect x="18" y="150" width="270" height="64" rx="11" fill="var(--ok-soft)" stroke="var(--ok)"/>
    <circle cx="39" cy="172" r="9" fill="var(--ok-soft)"/>
    <text x="39" y="175.6" font-size="10" font-weight="700" fill="var(--ok)" text-anchor="middle">6</text>
    <text x="55" y="176" font-size="12.5" font-weight="600" fill="var(--ink)">答案 · 引用 · 观测</text>
    <text x="55" y="194" font-size="10.5" fill="var(--ok)">trace · 审计 · 指标看板</text>

    <line x1="292" y1="50" x2="338" y2="50" stroke="var(--faint)" stroke-width="1.3" marker-end="url(#ar)"/>
    <line x1="619" y1="50" x2="665" y2="50" stroke="var(--faint)" stroke-width="1.3" marker-end="url(#ar)"/>
    <line x1="807" y1="86" x2="807" y2="143" stroke="var(--faint)" stroke-width="1.3" marker-end="url(#ar)"/>
    <line x1="668" y1="182" x2="622" y2="182" stroke="var(--faint)" stroke-width="1.3" marker-end="url(#ar)"/>
    <line x1="341" y1="182" x2="295" y2="182" stroke="var(--faint)" stroke-width="1.3" marker-end="url(#ar)"/>
  </g>
</svg>
"""


def redact(data: dict) -> dict:
    """公开视图：去掉文档清单与模型端点，指标照常展示。

    为什么不是整页 403：汇报页的用途就是发给别人看，整页挡掉等于让分享失效。
    真正敏感的是「用了哪些文档」和「接的哪个模型」——这两样隐掉，
    通过率、延迟、架构这些可核对的部分仍然成立。
    """
    out = dict(data)
    knowledge = dict(out.get("knowledge") or {})
    knowledge["files"] = []
    knowledge["redacted"] = True
    out["knowledge"] = knowledge
    out["channel"] = "已隐藏"
    out["model"] = "已隐藏"
    return out


def kpi_rows(data: dict) -> list[tuple[str, str]]:
    """KPI 字段表：标签固定、取值随数据。单独成函数是为了能直接断言。"""
    k = data["knowledge"]
    cases = data["cases"]
    metrics = data["metrics"]
    l1 = data["l1"]
    l3_avg = (data.get("l3") or {}).get("avg") or {}
    best = max(l1, key=lambda x: (x["pass_rate"] or 0)) if l1 else None
    cov = metrics.get("avg_citation_coverage")
    p95 = (metrics.get("latency_ms") or {}).get("p95")
    return [
        ("知识库规模", f"{k['chunks']} 块 / {'—' if k.get('redacted') else len(k['files'])} 份"),
        ("评测用例", str(cases["total"])),
        ("L1 通过率", f"{round((best['pass_rate'] or 0) * 100)}%" if best else "-"),
        ("L3 忠实度", str(l3_avg.get("faithfulness") or "-")),
        ("引用覆盖率", f"{round(cov * 100)}%" if cov is not None else "-"),
        ("P95 延迟（近 500 条）", f"{round(p95)}ms" if p95 else "-"),
    ]


def _block_l1(l1: list[dict], total_cases: int = 0) -> str:
    """L1 各轮次通过率表。

    `total_cases` 是当前默认用例集（人工 + 拒答基线 + 反馈）。与报告里的 `total`
    不一致时必须写出来：读者看到「100%」会默认它盖住了全部用例，而实际上
    那份报告可能是用例集扩容前跑的——这是最容易被当成注水的一处。
    """
    rows = ""
    for r in l1:
        cats = r["by_category"]
        detail = " · ".join(f"{c} {v['passed']}/{v['total']}" for c, v in cats.items())
        ok = (r["pass_rate"] or 0) >= 0.9
        stale = total_cases and r["total"] != total_cases
        rows += (
            f"<tr><td>{_esc(r['label'])}"
            f"{' <span class=\"pill\">旧轮次</span>' if stale else ''}</td>"
            f"<td>{r['total']}</td>"
            f"<td class=\"{'ok' if ok else 'bad'}\">{round((r['pass_rate'] or 0) * 100)}%</td>"
            f"<td class=\"muted\">{_esc(r.get('reported_at') or '—')}</td>"
            f"<td class=\"muted\">{_esc(detail)}</td></tr>"
        )
    if not rows:
        return '<div class="muted">尚未生成 L1 报告</div>'
    table = ('<div class="table-wrap"><table><thead><tr><th>评测轮次</th><th>用例</th>'
             f'<th>通过率</th><th>生成于</th><th>分类明细</th></tr></thead><tbody>{rows}</tbody></table></div>')
    stale_note = ""
    if total_cases and all(r["total"] != total_cases for r in l1):
        stale_note = (
            '<p class="muted" style="font-size:12.5px;margin:10px 0 0;line-height:1.8">'
            f'当前默认用例集 <b>{total_cases}</b> 条，上表是扩容前跑的历史轮次。'
            '要拿到覆盖全集的一轮：<code>python tests/eval_run.py</code>；'
            '页面顶部的 L1 通过率取自最新可用报告，不代表当前用例集。</p>'
        )
    return table + stale_note


_DIM_CN = {"faithfulness": "忠实度", "relevance": "相关性", "completeness": "完整性"}


def _cal_text(items: list[dict]) -> str:
    parts = []
    for c in items:
        if c.get("skipped"):
            parts.append(f"{c.get('label')}：跳过")
            continue
        mark = "—" if c.get("caught") is None else ("✓" if c.get("caught") else "✗")
        parts.append(f"{c.get('label')} {_DIM_CN.get(c.get('dim'), c.get('dim'))}={c.get('score')}{mark}")
    return "；".join(parts) or "未运行"


def _num_text(v) -> str:
    if v is None:
        return "—"
    try:
        n = float(v)
    except (TypeError, ValueError):
        return _esc(v)
    s = f"{round(n, 2):g}"
    return s if "." in s else s + ".0"


def _block_l3(l3: dict | None) -> str:
    """L3 语义评分（三维度 + 门禁 + 区分力校准）。"""
    if not (l3 and l3.get("avg")):
        return '<div class="muted">尚未运行 L3（需要可用的模型 Key）。</div>'
    l3_avg = l3["avg"]
    gate = l3.get("gate") or {}
    badge = ('<span class="ok">门禁通过</span>' if gate.get("passed")
             else f'<span class="bad">门禁未过：{_esc("；".join(gate.get("reasons") or []))}</span>')
    cal_txt = _cal_text(l3.get("calibration") or [])
    tiles = "".join(
        f'<div class="rp-score"><div class="k">{label}</div>'
        f'<div class="v">{_num_text(l3_avg.get(key))}<small>/ 5</small></div>'
        f'<div class="bar"><i style="width:{int((l3_avg.get(key) or 0) * 20)}%"></i></div></div>'
        for label, key in (("忠实度", "faithfulness"), ("相关性", "relevance"), ("完整性", "completeness"))
    )
    tokens = l3.get("total_tokens")
    return (
        '<div class="rp-l3">'
        f'<div class="rp-scores">{tiles}</div>'
        '<div class="rp-l3-note">'
        f'<div class="row" style="flex-wrap:wrap;gap:7px;margin-bottom:9px">{badge}'
        f'<span class="pill">语义通过率 {round((l3.get("pass_rate") or 0) * 100)}%</span></div>'
        f'<div>样本 <b>{l3.get("answer_cases")}</b> 条答案类 + <b>{l3.get("safety_cases")}</b> 条拒答类；'
        f'编造告警 <b>{len(l3.get("hallucinations") or [])}</b> 条；裁判消耗 '
        f'<b>{"—" if tokens is None else tokens}</b> tokens。</div>'
        f'<div style="margin-top:7px">裁判：<b>{_esc(l3.get("judge_model") or l3.get("judge_channel") or "同源")}</b></div>'
        f'<div style="margin-top:7px"><b>区分力校准</b>（植入错误答案后是否降分）：{_esc(cal_txt)}</div>'
        "</div></div>"
    )


def _block_hard(hard: dict, l3_hard: dict) -> str:
    """难题集 L1 + 同源 / 异构裁判对比。"""
    if not hard.get("total"):
        return ""
    same = l3_hard.get("same")
    cross = l3_hard.get("cross")
    cols = []
    if same:
        cols.append((f"同源裁判（{same.get('judge_model') or '同源'}）", same))
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
    return (
        '<section class="sec card" id="s-hard"><div class="sec-head"><span class="n">06</span><h2>难题集与裁判对比</h2>'
        f'<span class="note">{hard.get("total")} 条：多跳 / 数值边界 / 跨文件口径 / 资料空白</span></div>'
        f'<p class="muted" style="font-size:13px;margin:0 0 10px">L1 确定性断言：'
        f'<b>{hard.get("total") - sum(1 for r in hard.get("results", []) if not r.get("passed"))}/{hard.get("total")}'
        f' = {round((hard.get("pass_rate") or 0) * 100)}%</b>（{_esc(cats)}）</p>'
        + (f'<div class="table-wrap"><table>{head}<tbody>{rows}</tbody></table></div>' if cols else "")
        + '<p class="muted" style="font-size:12.5px;margin:10px 0 0">'
        '同一批答案、同一套 rubric，只换裁判模型。两者分数差距即「裁判偏好」的量级——'
        '所以 L3 分数只作趋势对比，门禁取更严的一侧。'
        + ("" if cols else "（尚未运行难题集 L3，先执行 tests/eval_l3.py --report tests/report_hard.json）")
        + "</p></section>"
    )


def _block_retrieval(ret: dict) -> str:
    """检索策略对比表。"""
    if not ret.get("configs"):
        return ""
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
    vec = ret["configs"].get("vector") or {}
    vec_txt = ""
    if vec:
        vec_txt = (f"默认使用 vector（字符 n-gram 向量 + 重排）：R@1 {format(vec.get('recall_at_1') or 0, '.1%')}、"
                   f"R@4 {format(vec.get('recall_at_4') or 0, '.1%')}、MRR {format(vec.get('mrr') or 0, '.3f')}。")
    return (
        '<section class="sec card" id="s-ret"><div class="sec-head"><span class="n">05</span><h2>检索策略对比</h2>'
        f'<span class="note">Recall@1 / Recall@4 / MRR · {ret_cases} 条带召回标签的难题</span></div>'
        '<div class="table-wrap"><table><thead><tr><th>策略</th><th>R@1</th><th>R@4</th><th>MRR</th><th>未命中</th></tr></thead>'
        f"<tbody>{rows}</tbody></table></div>"
        '<p class="muted" style="font-size:12.5px;margin:10px 0 0">'
        f"{vec_txt}未命中项多为同义改写（如「测评 R3 想买 R5」），由查询扩展补充召回；"
        "样本量较小，结果用于版本间对比。</p></section>"
    )


# 已知边界：这些不是「还没做」，是「做了但确实会错」的地方。
# 写在页面上而不是只留在代码注释里——读者要先知道边界，才谈得上信结论。
EDGE_LIMITS: tuple[tuple[str, str], ...] = (
    ("否定与反问",
     "只处理命中词前 3 字的简单否定（「不包含」「无需」）。双重否定、反问句"
     "仍可能判反，命中后会过四道闸门兜底，但不保证全对。"),
    ("扫描件 PDF",
     "没有文本层，必须先 OCR 再入库。直接上传只会得到一份空文档，"
     "页面上能看出块数为 0。"),
    ("表格样式",
     "只取单元格文本：日期是序列号、合并单元格只在左上角有值、"
     "只有表头没有数据行的表会被跳过。"),
    ("注入防护",
     "规则版检测，改写措辞可以绕过。兜底靠「文档标记为不可信 + 引用可核验」，"
     "不是靠拦住每一句话。"),
    ("答与不答的边界",
     "正确回答与误答的检索分落在 0.685–0.967 与 0.642–0.775，两段重叠。"
     "所以本该拒答的用例可能拿到低置信度答案，而不是明确说「不知道」。"),
)


def _block_edge(data: dict) -> str:
    """边界与失败：整页最该被相信的部分。

    「15 条全 ✓」不构成证据——读者想知道的是「什么情况下它会错」。
    这里放三样东西：跑出来的失败样本、线上真发生的降级、以及设计上承认的边界。
    没有失败样本时也必须解释为什么，否则「0 失败」会被读成「没问题」。
    """
    m = data.get("metrics") or {}
    l1 = data.get("l1") or []
    n = m.get("requests") or 0

    fail_rows = []
    for r in l1:
        for f in (r.get("failures") or []):
            fail_rows.append(
                f'<div class="edge-fail"><b>{_esc(f.get("id") or "-")}</b>'
                f'<span>{_esc(f.get("input") or "")}</span>'
                f'<i>{_esc("；".join(f.get("failures") or []) or "未给出原因")}</i></div>'
            )
    if fail_rows:
        fail_body = "".join(fail_rows[:6])
        fail_note = f"共 {len(fail_rows)} 条，列前 {min(len(fail_rows), 6)} 条"
    else:
        totals = " + ".join(str(r["total"]) for r in l1) or "0"
        fail_body = (
            f'<p class="edge-ok">现有 {len(l1)} 份 L1 报告（用例数 {totals}）里没有失败样本。</p>'
            '<p class="ag-hint">失败为 0 不等于没问题：更可能说明用例集还没覆盖到难的场景。'
            '难题集 13 条单独跑（<code>--include-hard</code>），按约定不进发布门禁，'
            '所以上面的通过率不含它们——需要时自己跑一次，别把它当成能力上限。</p>'
        )
        fail_note = "零失败也要说清为什么"

    reasons = m.get("degrade_reasons") or {}
    reason_txt = "、".join(f"{k} {v} 次" for k, v in reasons.items()) or "无"
    degrade = (
        '<div class="edge-degrade">'
        f'<div class="ag-kv"><span>降级回答</span><b>{m.get("degraded", 0)}'
        f'{" / " + str(n) + " 条" if n else ""}</b></div>'
        f'<div class="ag-kv"><span>引用自动补全</span><b>'
        f'{m.get("citation_repaired", 0)} 次</b></div>'
        # 降级原因可能有 3-5 项，右对齐会挤成三行；单独一段更清楚
        f'<div class="edge-reasons"><span>降级原因</span><em>{_esc(reason_txt)}</em></div>'
        '</div>'
    )
    limits = "".join(
        f'<div class="axis"><span class="ic not">!</span><div><b>{_esc(k)}。</b>{v}</div></div>'
        for k, v in EDGE_LIMITS
    )
    # 口径单独成段：这一页最容易被人当注水的地方，就是「100%」到底算了什么。
    calibre = (
        '<p class="ag-hint" style="margin-top:12px">'
        '<b style="color:var(--ink)">这一页的口径</b>：L1 = 确定性断言全过的比例；'
        'L3 = 同源裁判 1-5 分，只用于版本间趋势；引用覆盖率只统计 answer 类；'
        'P95 含关键词直出（不调模型）。几个数字各自有出处，<b style="color:var(--ink)">'
        '不合并成一个总分</b>——合并之后就没人能回查了。</p>'
    )
    return (
        '<section class="sec two-col" id="s-edge">'
        '<div class="card"><div class="sec-head">'
        '<span class="n" style="visibility:hidden" aria-hidden="true">00</span>'
        f'<h2>失败样本与线上降级</h2><span class="note">{_esc(fail_note)}</span></div>'
        f'{fail_body}{degrade}{calibre}</div>'
        '<div class="card"><div class="sec-head">'
        '<span class="n" style="visibility:hidden" aria-hidden="true">00</span>'
        '<h2>已知边界</h2><span class="note">写下来，才不用读者自己踩</span></div>'
        f'{limits}</div></section>'
    )


def hero_stats(data: dict) -> list[tuple[str, str, str]]:
    """首屏只放三个结论：够不够好、答得实不实、找不找得到。

    六个指标平铺在首屏等于没有重点。剩余三项留给下面「关键指标」区，
    那里每张卡都带样本量与口径，是「想深究时再看」的第二层。
    """
    l1 = data.get("l1") or []
    best = max(l1, key=lambda x: (x["pass_rate"] or 0)) if l1 else None
    l3 = (data.get("l3") or {}).get("avg") or {}
    vec = ((data.get("retrieval") or {}).get("configs") or {}).get("vector") or {}
    faith = l3.get("faithfulness")
    r4 = vec.get("recall_at_4")
    num = (int, float)
    return [
        ("L1 通过率",
         f"{round((best['pass_rate'] or 0) * 100)}%" if best else "—",
         f"{best['total']} 条确定性断言" if best else "尚无报告"),
        ("忠实度",
         f"{faith:.1f}" if isinstance(faith, num) else "—",
         "裁判 1-5 分 · 同源评分" if isinstance(faith, num) else "未运行 L3"),
        ("Recall@4",
         f"{round(r4 * 100)}%" if isinstance(r4, num) else "—",
         "带召回标签的难题" if isinstance(r4, num) else "未跑召回评测"),
    ]


def _hero_stat_html(triples: list[tuple[str, str, str]]) -> str:
    return "".join(
        f'<div class="hs"><span class="k">{_esc(k)}</span>'
        f'<span class="v">{_esc(v)}</span><span class="s">{_esc(s)}</span></div>'
        for k, v, s in triples
    )


def _number_sections(html: str) -> str:
    """按出现顺序重排 `.sec-head .n` 的编号。

    原来编号是手写的 01…09：插一个区块要改后面所有数字，1.30.0 加「线上行为」
    时 05 就撞过一次（两个 05、没有 06）。带 `aria-hidden` 的是对齐占位，
    不参与计数。
    """
    counter = itertools.count(1)

    def repl(m: re.Match) -> str:
        return f'{m.group(1)}>{next(counter):02d}</span>'

    return re.sub(r'(<span class="n"(?![^>]*aria-hidden)[^>]*?)>\d{2}</span>', repl, html)


def topbar(standalone: bool = False) -> str:
    """顶栏：品牌 + 在线状态 + 展示/管理入口。

    状态灯由前端探活决定（GET /api/health），不做构建期判断：
    同一个文件双击打开就是灰的，挂到服务上就是绿的，不会撒谎。
    """
    home = 'href="#"' if standalone else 'href="/ask"'
    links = "" if standalone else (
        '<a class="rp-tbtn" href="/ask">去问答</a>'
        '<a class="rp-tbtn" href="/report?download=1" download>下载 HTML</a>'
    )
    return (
        '<div class="rp-top">'
        f'<a class="rp-brand" {home}>{MARK}<span>{BRAND}</span>'
        '<span class="sep">· 项目汇报</span></a>'
        '<span class="rp-state" id="rpState" data-state="pending">'
        '<i></i><span>检测中…</span></span>'
        '<span class="spacer"></span>'
        + links +
        '<button class="rp-tbtn" id="rpPrint" type="button">打印</button>'
        '<button class="rp-tbtn primary" id="rpAdminBtn" type="button" '
        'aria-expanded="false" aria-controls="rpAdmin">管理</button>'
        '</div>'
    )


def admin_panel() -> str:
    """右侧管理面板。

    四个组对应页面上的四类数据：内容（知识库）、审批（变更）、
    运行（灰度/索引）、诊断（健康/审计）。分组边界跟展示区的区块一致，
    这样"看到哪块、改哪块"是同一个心智模型。
    """
    return (
        '<aside class="rp-admin" id="rpAdmin" aria-hidden="true" aria-label="管理面板">'
        '<div class="rp-admin-head"><h2>管理</h2>'
        '<span class="ag-mut" id="rpAdminState">只读副本</span>'
        '<span class="spacer"></span>'
        '<button class="rp-tbtn" id="rpClose" type="button" aria-label="关闭管理面板">×</button>'
        '</div><div class="rp-admin-body">'

        '<div class="ag-offline" id="rpOffline"><b>当前是离线副本</b>，只能看不能改。'
        '<br>要在同一份页面上管理知识库、灰度与索引，先在本机起服务：'
        '<code>python -m src.server --port 8000</code>'
        '然后访问 <code>http://127.0.0.1:8000/report</code>。</div>'

        '<details class="agroup" data-group="auth"><summary>访问凭据</summary>'
        '<div class="ag-body"><form class="ag-upload" id="agAuthForm">'
        '<input name="key" placeholder="API Key（配了 API_KEYS 时必填）" autocomplete="off">'
        '<input name="token" placeholder="管理员令牌 X-Admin-Token" autocomplete="off">'
        '<button type="submit">保存到本次会话</button>'
        '<p class="ag-hint">只写 sessionStorage，关掉标签页即失效；不写 Cookie、不写硬盘。</p>'
        '</form></div></details>'

        # 操作回执：改了什么都不该只靠一条 3 秒就消失的 toast 记住。
        # 默认折叠成一行摘要，做完第一件事才出现——没操作过就不占位置。
        '<details class="agroup ag-receipts" data-group="receipts" id="agReceipts" hidden>'
        '<summary>本次会话做了什么<span class="ag-count" id="agReceiptCount"></span></summary>'
        '<div class="ag-body"><div id="agReceiptList"></div>'
        '<p class="ag-hint">回执只在当前标签页有效，关掉即清空；'
        '服务端的权威记录在「诊断」组顶部的审计里（<code>/api/audit</code>）。</p>'
        '</div></details>'

        '<details class="agroup" data-group="content" open>'
        '<summary>内容 · 文档台账<span class="ag-count" id="agContentCount"></span></summary>'
        '<div class="ag-body" id="agContent">加载中…</div></details>'

        '<details class="agroup" data-group="approval">'
        '<summary>审批 · 待发布变更<span class="ag-count" id="agApprovalCount"></span></summary>'
        '<div class="ag-body" id="agApproval">加载中…</div></details>'

        '<details class="agroup" data-group="eval">'
        '<summary>评测 · L1 用例<span class="ag-count" id="agEvalCount"></span></summary>'
        '<div class="ag-body" id="agEval">加载中…</div></details>'

        '<details class="agroup" data-group="ops">'
        '<summary>运行 · 灰度与索引</summary>'
        '<div class="ag-body" id="agOps">加载中…</div></details>'

        '<details class="agroup" data-group="diag">'
        '<summary>诊断 · 健康与审计</summary>'
        '<div class="ag-body" id="agDiag">加载中…</div></details>'

        '</div></aside>'
    )


def render(data: dict, standalone: bool = False, redacted: bool = False) -> str:
    """渲染汇报页。standalone=True 时隐藏「下载」按钮（导出文件本身）。

    每个区块单独一个函数（`_block_*`），这里只做组装——原来 363 行的函数里
    「算数据」和「拼 HTML」缠在一起，改一处配色都要滚三屏。
    """
    k = data["knowledge"]
    cases = data["cases"]
    l1 = data["l1"]
    cfg = data["config"]
    # 公开视图：文档清单已在 collect 后清空，这里只负责把「为什么空」说清楚，
    # 否则读者会以为知识库真的没有文档。
    notice = (
        '<div class="rp-redacted">公开视图：文档清单与模型端点已隐藏。'
        '带 API Key 访问可看完整版；管理操作需要管理员令牌。</div>'
        if redacted else ""
    )

    subs = kpi_subs(data)
    kpis = "".join(_kpi(v, lab, s) for (lab, v), s in zip(kpi_rows(data), subs))
    l1_table = _block_l1(l1, cases["total"])
    edge_block = _block_edge(data)
    hero_infos = hero_stats(data)
    l3_block = _block_l3(data.get("l3"))
    hard_block = _block_hard(data.get("hard") or {}, data.get("l3_hard") or {})
    ret_block = _block_retrieval(data.get("retrieval") or {})

    _kb_total = max(1, k["chunks"])
    kb_rows = "".join(
        f"<tr><td>{_esc(f['name'])}</td><td class=\"num\">{f['chunks']}</td>"
        f'<td style="width:42%"><div class="bar" style="height:6px"><i style="width:{f["chunks"] / _kb_total * 100:.0f}%"></i></div></td></tr>'
        for f in k["files"]
    )
    kb_table = (
        '<p class="muted" style="font-size:12.5px;margin:0;line-height:1.8">'
        '公开视图不展示文档清单；文件数、块数与切分方式属于内部信息。</p>'
        if k.get("redacted") else
        f'<div class="table-wrap"><table><thead><tr><th>文件</th><th class="num">知识块</th>'
        f'<th>占比</th></tr></thead><tbody>{kb_rows}</tbody></table></div>'
    )
    kb_note = "" if k.get("redacted") else (
        '<p class="muted" style="font-size:12.5px;margin:10px 0 0;line-height:1.8">'
        "其中 3 份为手写的产品与制度样本，3 份由 PDF 解析而来"
        "（含《商业银行理财业务监督管理办法》公开条款摘录）。"
        "PDF 接入方式：<code>python -m src.pdf_ingest --raw data/raw --out data/knowledge</code>。"
        "演示制度已明确标注为模拟样本，不代表任何机构正式制度。</p>"
    )

    actions = "" if standalone else (
        '<div class="actions"><a class="btn" href="/ask">去试真实问答</a>'
        '<a class="btn ghost2" href="/report?download=1" download>下载独立 HTML</a></div>'
    )

    html = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{THEME_HEAD}
<meta name="color-scheme" content="light dark">
<link rel="icon" href="data:,">
<title>项目汇报 · {BRAND}</title><style>{BASE_CSS}{REPORT_CSS}</style></head>
<body class="page-insights" data-standalone="{1 if standalone else 0}">
{topbar(standalone)}
<div class="main"><div class="stage stage-insights">
<main class="wrap">

<section class="rp-hero">
  <div class="hero-grid">
    <div class="hero-lead">
      <div class="eyebrow">Project Brief · 文档问答</div>
      <h1>文档问答系统：检索、引用与评测</h1>
      <p>文档入库后，每个结论都带原文片段和可点开的出处；<br>
      检索不到时明确说「不知道」，并列出相似问题，而不是编一个。</p>
      <div class="badges">
        <span class="b solid">v{_esc(__version__)}</span>
        <span class="b solid">端点 {_esc(data['channel'])} / {_esc(data['model'])}</span>
        <span class="b">知识库 {k['chunks']} 块{'' if k.get('redacted') else ' / ' + str(len(k['files'])) + ' 份'}</span>
        <span class="b">核心零第三方依赖</span>
      </div>
      {actions}
    </div>
    <div class="hero-stats" aria-label="三个主指标">{_hero_stat_html(hero_infos)}</div>
  </div>
  {notice}
</section>

<nav class="rp-nav" id="rpNav">
  <a href="#s-kpi" class="active">关键指标</a>
  <a href="#s-scope">能力</a>
  <a href="#s-arch">链路与闸门</a>
  <a href="#s-eval">评测结果</a>
  <a href="#s-edge">边界与失败</a>
  {('<a href="#s-ret">检索策略</a>' if ret_block else '')}
  {('<a href="#s-hard">难题集</a>' if hard_block else '')}
  <a href="#s-kb">知识库</a>
  <a href="#s-limits">生产控制</a>
  <a href="#s-run">怎么跑</a>
</nav>

<section class="sec card" id="s-kpi">
  <div class="sec-head"><span class="n">01</span><h2>关键指标</h2>
    <span class="note">实时聚合自 trace 与评测报告</span>
    <button class="adm" type="button" data-admin-jump="diag">管理</button></div>
  <div class="kpis six">{kpis}</div>
  <p class="muted" style="font-size:12.5px;margin:10px 0 0;line-height:1.8">
    L1 = 确定性断言（行为 / 事实 / 安全）；L3 = 裁判模型按忠实度 / 相关性 / 完整性打分（1-5）。
    引用覆盖率 = 答案中有效 <code>[n]</code> 占全部标注的比例。
  </p>
</section>

<section class="sec three-col" id="s-scope">
  <div class="card">
    <div class="sec-head"><span class="n">00</span><h2>答得准</h2>
      <span class="note">检索与生成</span></div>
    <div class="axis"><span class="ic is">✓</span><div><b>多格式入库。</b>支持 <code>.md</code> / <code>.txt</code> / <code>.pdf</code> / <code>.docx</code>，PDF 与 Word 在服务端转成 Markdown 后切分索引。</div></div>
    <div class="axis"><span class="ic is">✓</span><div><b>关键词直出。</b>清单项、表格行、<code>标签：值</code> 精确命中时直接返回原文片段与出处，不调用模型；被四道闸门挡下或未命中才继续检索。</div></div>
    <div class="axis"><span class="ic is">✓</span><div><b>召回 + 重排。</b>embedding 召回（FAISS 或 NumPy 索引）后按原问题词覆盖、长片段命中、BM25 与标题命中重排；没配模型时用字符 n-gram 向量兜底。</div></div>
    <div class="axis"><span class="ic is">✓</span><div><b>多轮追问。</b>保留最近 3 轮上下文，「那 R2 呢」会补全成可检索的问题；独立问题不拼上一轮。</div></div>
  </div>
  <div class="card">
    <div class="sec-head"><span class="n" style="visibility:hidden" aria-hidden="true">00</span><h2>答得可核</h2>
      <span class="note">引用与拒答</span></div>
    <div class="axis"><span class="ic is">✓</span><div><b>引用可点开。</b>每条 <code>[n]</code> 带文档与知识块定位，点击打开原文抽屉并高亮命中行。</div></div>
    <div class="axis"><span class="ic is">✓</span><div><b>引用校验。</b>答案必须包含有效 <code>[n]</code>；模型没给出处时先补引用，补不上则降级为抽取式答案，不会带着「无来源」的结论交付。</div></div>
    <div class="axis"><span class="ic is">✓</span><div><b>不知道就说不知道。</b>置信度低于阈值时返回「无法找到答案」，同时给出最高分与阈值、列出相似问题，并收「应该怎么答 / 缺哪份文档」的反馈。</div></div>
    <div class="axis"><span class="ic is">✓</span><div><b>脚注可复算。</b>答案末尾给出版本号、引用条数与覆盖率、检索分，读者可以拿这几个数回查。</div></div>
    <div class="axis"><span class="ic is">✓</span><div><b>相似问题兜底。</b>未命中时列出知识库里最接近的几问，点一下换问题重试，比让人自己改写措辞更快。</div></div>
  </div>
  <div class="card">
    <div class="sec-head"><span class="n" style="visibility:hidden" aria-hidden="true">00</span><h2>跑得住</h2>
      <span class="note">工程与运维</span></div>
    <div class="axis"><span class="ic is">✓</span><div><b>三层评测。</b>L1 确定性断言、L3 语义评分、Recall@1/@4 与 MRR 召回评测；断言内核与线上走同一份代码。</div></div>
    <div class="axis"><span class="ic is">✓</span><div><b>生产控制。</b>幂等键、按 IP 限流、审计日志、每日 token 上限、按比例灰度、配置回滚；多实例把限流/幂等/成本状态放 Redis 共享。</div></div>
    <div class="axis"><span class="ic is">✓</span><div><b>可观测。</b>每次问答写 <code>logs/trace.jsonl</code>（16 MB 轮转、接口只读文件尾），<code>/metrics</code> 输出 Prometheus 指标，<code>/api/health</code> 返回检索与防护状态。</div></div>
    <div class="axis"><span class="ic is">✓</span><div><b>核心零第三方依赖。</b>切分、BM25、PDF/DOCX 解析、HTTP 服务均用标准库；真向量检索时可选 NumPy / FAISS 加速。</div></div>
  </div>
</section>

<section class="sec card" id="s-arch">
  <div class="sec-head"><span class="n">03</span><h2>链路与闸门</h2>
    <span class="note">每一层都有明确的失败动作</span></div>
  {ARCH_SVG}
  <div class="table-wrap" style="margin-top:12px"><table><thead><tr><th>环节</th><th>策略</th><th>失败时怎么办</th></tr></thead><tbody>
    <tr><td>接入</td><td>幂等键去重 · 按 IP 令牌桶限流（多实例走 Redis）· 按比例灰度到 CANARY_MODEL</td><td>重复请求回放首次结果；超限返回 <code>429</code> + <code>Retry-After</code></td></tr>
    <tr><td>输入</td><td>归一化去零宽 / 控制字符；注入、越权、荐股关键词拦截</td><td>直接拒答，不进检索与生成</td></tr>
    <tr><td>关键词</td><td>清单 / 表格 / 标签条目精确命中，最多 {cfg.get('keyword_top_n', 3)} 条；命中后过否定 / 极性 / 解释型意图 / 单文档四道闸门</td><td>直接返回原文片段，标 <code>path=keyword</code>、<code>api_called=false</code>；被闸门挡下或未命中则继续检索</td></tr>
    <tr><td>检索</td><td>embedding 召回（可切 n-gram / BM25）+ 多信号重排，top_k={cfg['top_k']}；查询扩展可选</td><td>embedding 失败回退词法检索并标 <code>degraded</code></td></tr>
    <tr><td>置信度</td><td>最高分低于 {cfg['min_score']} 视为未命中</td><td>返回「无法找到答案」+ 相似问题</td></tr>
    <tr><td>会话</td><td>最近 3 轮、30 分钟过期；只有指代式追问才补全问题</td><td>独立问题不拼上文；会话过期后退化为单轮</td></tr>
    <tr><td>生成</td><td>OpenAI 兼容 LLM，温度 0.1，SSE 流式；超时 {int(cfg['timeout'])}s，重试 {cfg['retries']} 次并尊重 Retry-After；每日 token 上限</td><td>上游截断或失败整体降级为抽取式并替换前端文本，把 error / <code>budget_exceeded</code> 透传到结果</td></tr>
    <tr><td>引用</td><td>答案必须含有效 <code>[n]</code></td><td>无出处则降级为可追溯答案，标 <code>no_citation</code></td></tr>
    <tr><td>记录</td><td>trace、审计、成本与 Prometheus 指标</td><td>写盘/采集失败不阻塞响应，但健康检查可见</td></tr>
  </tbody></table></div>
</section>

<section class="sec card" id="s-eval">
  <div class="sec-head"><span class="n">04</span><h2>评测结果</h2>
    <span class="note">L1 确定性断言 + L3 语义评分</span>
    <button class="adm" type="button" data-admin-jump="eval">管理</button></div>
  {l1_table}
  <div style="margin-top:16px">{l3_block}</div>
</section>
{ret_block}
{hard_block}
{edge_block}

<section class="sec card" id="s-kb">
  <div class="sec-head"><span class="n">07</span><h2>知识库构成</h2>
    <span class="note">{('—' if k.get('redacted') else len(k['files']))} 份 · {k['chunks']} 块</span>
    <button class="adm" type="button" data-admin-jump="content">管理</button></div>
  {kb_table}
  {kb_note}
</section>

<section class="sec two-col" id="s-limits">
  <div class="card">
    <div class="sec-head"><span class="n">08</span><h2>生产控制</h2>
      <button class="adm" type="button" data-admin-jump="ops">管理</button></div>
    <div class="table-wrap"><table><thead><tr><th>能力</th><th>实现与配置</th></tr></thead><tbody>
      <tr><td>幂等</td><td><code>Idempotency-Key</code> 复用首次结果，TTL <code>IDEMPOTENCY_TTL_S</code>（300s）</td></tr>
      <tr><td>限流</td><td>按客户端 IP 令牌桶，<code>RATE_LIMIT_RPS</code> / <code>RATE_LIMIT_BURST</code>（5 / 10）</td></tr>
      <tr><td>审计</td><td>写入 <code>logs/audit.jsonl</code>，<code>GET /api/audit</code> 读取</td></tr>
      <tr><td>传输</td><td>gzip + 弱 ETag + 304；JSON 一律 no-store</td></tr>
      <tr><td>成本上限</td><td>每日 token 预算 <code>DAILY_TOKEN_BUDGET</code>，超限跳过模型调用</td></tr>
      <tr><td>灰度</td><td><code>CANARY_PERCENT</code> / <code>CANARY_MODEL</code>，<code>POST /api/admin/config</code> 调整</td></tr>
      <tr><td>回滚</td><td><code>POST /api/admin/rollback</code> 恢复上一版配置</td></tr>
    </tbody></table></div>
    <p class="muted" style="font-size:11.5px;margin:9px 0 0;line-height:1.7">加上 trace / metrics 观测与 <code>/api/health</code> 健康检查，共八项。</p>
  </div>
  <div class="card">
    <div class="sec-head"><span class="n" style="visibility:hidden" aria-hidden="true">00</span><h2>运行约束</h2></div>
    <ul class="rp-list">
      <li>未配置 <code>LLM_API_KEY</code> 时使用抽取式答案，检索、引用与评测链路仍可运行。</li>
      <li>扫描件 PDF 未做 OCR，仅处理文本型 PDF。</li>
      <li>默认绑定 <code>127.0.0.1</code>；对外部署需设置 <code>ADMIN_TOKEN</code>，并通过反向代理提供 HTTPS。</li>
      <li>幂等缓存位于单进程内存，多实例部署需替换为 Redis。</li>
      <li>L3 分数受裁判模型影响，用于版本间趋势对比。</li>
    </ul>
  </div>
</section>

<section class="sec card" id="s-run">
  <div class="sec-head"><span class="n">09</span><h2>怎么跑起来</h2>
    <span class="note">未配置 Key 时自动走离线抽取，全链路仍可跑通</span></div>
<pre class="cmd"><span class="c"># 单次问答</span>
python -m src.cli "稳盈系列的起购金额是多少"
<span class="c"># 启动 Web：首页 / 问答 / 知识库 / 看板 / 汇报</span>
python -m src.server --port 8000
<span class="c"># L1 确定性断言 + L3 语义评分</span>
python tests/eval_run.py
python tests/eval_l3.py --report tests/report_llm.json
<span class="c"># 灰度与回滚（需 ADMIN_TOKEN，未设置时仅本机可调用）</span>
curl -X POST /api/admin/config -d '{{"canary_percent":10,"canary_model":"<model>"}}'
curl -X POST /api/admin/rollback -d '{{}}'
<span class="c"># 导出这份汇报（独立 HTML，无需服务）</span>
python -m src.report --out dist/report.html</pre>
  <p class="muted" style="font-size:12.5px;margin:10px 0 0">配置 <code>LLM_API_KEY</code> 即切换真实模型；Key 只走环境变量，源码零硬编码。</p>
</section>

<div class="foot">
  该页面由项目自身数据生成，导出文件不依赖任何 API。<br>
  评测口径：L1 通过率 = 确定性断言全通过的比例；忠实度 = 回答事实能否在检索资料中找到依据（1-5，裁判模型评分）。<br>
  生成时间 {_esc(data['generated_at'])} · 端点 {_esc(data['channel'])} / {_esc(data['model'])}
</div>
</main>
{footer(links=not standalone)}
</div></div>
{admin_panel()}
<div class="rp-stale" id="rpStale" hidden>
  <span>管理操作已生效，当前页面仍是旧快照</span>
  <button id="rpStaleBtn" type="button">刷新展示</button>
</div>
<div id="toasts"></div>
<script>{JS_UTIL}</script>
<script>{REPORT_JS}</script>
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
<script>{THEME_JS}</script>
</body></html>"""
    # 编号按渲染顺序生成：插区块不用再改后面所有数字（历史上撞过号）
    return _number_sections(html)


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
