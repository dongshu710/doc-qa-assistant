/* 汇报页的管理面板。
   为什么单独成文件：这里有近 300 行分支，塞进 report.py 的三引号里既没有语法高亮，
   也没法 `node --check`。导出时仍会被内联进 <script>，离线文件依旧自包含。

   两个运行态由「探活」决定，不是构建时决定：
   - 在线（jiyi-server 起服务后访问 /report）：管理面板可用，走真实 API；
   - 离线（双击 dist/report.html）：只读，面板显式说明「改不了、怎么才能改」。
   这样同一份文件既能贴进仓库当汇报，也能当管理台，且不会假装自己有权改数据。 */
(function () {
  'use strict';

  var body = document.body;
  var $ = function (id) { return document.getElementById(id); };
  var online = false;
  var opened = false;
  var armed = null;          // 已进入「再点一次确认」的按钮
  var armTimer = 0;
  var loaded = false;        // 五个分组是否已真正发起加载

  /* ---------------- 基础 ---------------- */

  function markState(kind, text) {
    var el = $('rpState');
    if (!el) return;
    el.dataset.state = kind;
    var label = el.querySelector('span');
    if (label) label.textContent = text;
  }

  function errBox(e) {
    var msg = (e && e.message) || String(e);
    var hint = /管理员/.test(msg)
      ? '<button class="ag-link" data-act="auth">填写管理员令牌</button>'
      : '';
    return '<p class="ag-error">' + esc(msg) + hint + '</p>';
  }

  function adminToken() {
    try { return sessionStorage.getItem('rag_admin_token') || ''; } catch (e) { return ''; }
  }

  /* 所有管理请求的唯一出口：Key、管理员令牌、站内标记只在这里加。
     reqHeaders() 只处理 API Key（主站共用），管理员令牌必须在这里补上——
     漏了它的表现是"界面让你填令牌，填完仍然 403"。 */
  async function api(path, opt) {
    opt = opt || {};
    var headers = reqHeaders(!!opt.body);
    var token = adminToken();
    if (token) headers['X-Admin-Token'] = token;
    var init = {
      method: opt.method || 'GET',
      headers: headers,
      cache: 'no-store'
    };
    if (opt.body) init.body = JSON.stringify(opt.body);
    var resp = await fetch(path, init);
    var data = null;
    try { data = await resp.json(); } catch (e) { data = null; }
    if (!resp.ok) {
      var msg = (data && (data.message || data.error)) || ('HTTP ' + resp.status);
      if (resp.status === 401) msg = '需要 API Key：在下方「访问凭据」里填一次';
      if (resp.status === 403) msg = '需要管理员权限：填令牌，或从本机访问';
      throw new Error(msg);
    }
    return data || {};
  }

  /* 危险操作的二次确认：第一次点进入「待确认」，3 秒内再点才执行。
     只用颜色+边框表示状态，不改文字——列表列宽只有 54px，换文案会把它撑成两行。 */
  function armConfirm(btn, done) {
    if (armed === btn) {
      clearTimeout(armTimer);
      armed = null;
      btn.classList.remove('armed');
      return true;
    }
    if (armed) { clearTimeout(armTimer); armed.classList.remove('armed'); }
    armed = btn;
    btn.classList.add('armed');
    btn.title = '再点一次确认';
    armTimer = setTimeout(function () {
      if (armed === btn) { btn.classList.remove('armed'); btn.title = done; armed = null; }
    }, 3000);
    return false;
  }

  /* 数据变了但当前页面还是旧快照：给一条明确的「刷新展示」提示，
     而不是偷偷 reload——评审可能正看到一半。 */
  function markStale() {
    var bar = $('rpStale');
    if (!bar || !bar.hidden) return;
    bar.hidden = false;
  }

  /* ---------------- 四个分组 ---------------- */

  async function loadContent() {
    var box = $('agContent');
    if (!box) return;
    try {
      var d = await api('/api/knowledge');
      var files = d.files || [];
      $('agContentCount').textContent = files.length ? files.length + ' 份' : '';
      if (!files.length) {
        box.innerHTML = '<p class="ag-empty">知识库为空，先上传一份文档。</p>';
      } else {
        box.innerHTML =
          '<table class="ag-table"><thead><tr><th>文档</th><th class="num">块</th><th></th></tr></thead><tbody>' +
          files.map(function (f) {
            return '<tr><td class="ag-name" title="' + esc(f.name) + '">' + esc(f.name) +
              '</td><td class="num">' + (f.chunks || 0) + '</td>' +
              '<td><button class="ag-del" data-act="del" data-name="' + esc(f.name) +
              '" title="删除" aria-label="删除 ' + esc(f.name) + '">×</button></td></tr>';
          }).join('') +
          '</tbody></table>';
      }
      // 新增文档只在知识库页做（那边有拖拽、多格式、进度与重试）。
      // 管理台再放一个「粘贴 Markdown」等于第二套上传，两条路径的校验还不一样。
      box.insertAdjacentHTML('beforeend',
        '<p class="ag-hint">新增文档走 <a href="/kb" target="_blank" rel="noopener">知识库</a>；' +
        '这里只管查看与删除。</p>');
    } catch (e) {
      box.innerHTML = errBox(e);
    }
  }

  async function loadApproval() {
    var box = $('agApproval');
    if (!box) return;
    try {
      var d = await api('/api/kb/changes?status=pending');
      var items = d.items || [];
      $('agApprovalCount').textContent = items.length ? items.length + ' 待审' : '';
      if (!items.length) { box.innerHTML = '<p class="ag-empty">没有待审批变更。</p>'; return; }
      box.innerHTML = items.map(function (c) {
        var files = (c.files || []).map(function (f) {
          return '<span class="ag-file">' + esc(f.name) + ' <i>' + esc(f.action || '') + '</i></span>';
        }).join('');
        var warns = (c.warnings || []).map(function (w) {
          return '<div class="ag-warn">' + esc(w) + '</div>';
        }).join('');
        return '<div class="ag-change"><div class="ag-change-h"><b>' + esc(c.change_id) + '</b>' +
          '<span class="ag-mut">' + esc(String(c.created_at || '').slice(0, 16).replace('T', ' ')) + '</span></div>' +
          '<div class="ag-mut">' + esc(c.author || '-') + ' · 基线 ' + esc(c.base_version || '-') +
          ' · ' + (c.files || []).length + ' 个文件</div>' +
          '<div class="ag-files">' + files + '</div>' + warns +
          '<div class="ag-row"><button data-act="approve" data-id="' + esc(c.change_id) + '">通过并发布</button>' +
          '<button class="ag-ghost" data-act="reject" data-id="' + esc(c.change_id) + '">驳回</button></div></div>';
      }).join('');
    } catch (e) {
      box.innerHTML = errBox(e);
    }
  }

  /* ---------------- 评测 ---------------- */

  function evalSummary(last) {
    if (!last || !last.run_at) return '<p class="ag-empty">还没有运行记录。</p>';
    return '<div class="ag-kv"><span>最近运行</span><b>' + esc(fmtTime(last.run_at)) + '</b></div>' +
      '<div class="ag-kv"><span>范围 / 通道</span><b>' + esc(last.scope || '-') +
      ' · ' + esc(last.channel || '-') + '</b></div>' +
      '<div class="ag-kv"><span>通过</span><b>' + (last.passed || 0) + ' / ' + (last.total || 0) +
      ' · ' + Math.round((last.pass_rate || 0) * 100) + '%</b></div>';
  }

  function evalResult(r) {
    var fails = r.failed || [];
    var html = '<div class="ag-kv"><span>运行时间</span><b>' + esc(fmtTime(r.run_at)) + '</b></div>' +
      '<div class="ag-kv"><span>通过</span><b>' + (r.passed || 0) + ' / ' + (r.total || 0) +
      ' · ' + Math.round((r.pass_rate || 0) * 100) + '%</b></div>' +
      '<div class="ag-kv"><span>耗时</span><b>' +
      Math.round((r.duration_ms || 0) / 1000) + 's</b></div>';
    if ((r.skipped || []).length) {
      html += '<div class="ag-kv"><span>跳过</span><b>' + r.skipped.length + ' 条（缺文档）</b></div>';
    }
    if (fails.length) {
      html += '<div class="ag-sub">失败 ' + fails.length + ' 条</div>' +
        fails.slice(0, 8).map(function (f) {
          return '<div class="ag-fail"><b>' + esc(f.id) + '</b> ' + esc(f.input) +
            '<i>' + esc((f.failures || []).join('；')) + '</i></div>';
        }).join('');
    } else if (r.total) {
      html += '<p class="ag-hint">本次没有失败用例。</p>';
    }
    html += '<div class="ag-row"><button data-act="runEval">再跑一次</button></div>';
    return html;
  }

  async function loadEval() {
    var box = $('agEval');
    if (!box) return;
    try {
      var d = await api('/api/cases');
      var last = d.last_run || {};
      $('agEvalCount').textContent = last.run_at
        ? Math.round((last.pass_rate || 0) * 100) + '%' : '';
      box.innerHTML = evalSummary(last) +
        '<div class="ag-kv"><span>已收集用例</span><b>人工 ' + (d.curated || 0) +
        ' · 反馈 ' + (d.feedback || 0) + ' · 文档 ' + (d.docs || 0) + '</b></div>' +
        '<div class="ag-row"><button data-act="runEval">跑一遍 L1 用例</button></div>' +
        '<p class="ag-hint">跑的是全部已收集用例（人工 + 未覆盖基线 + 反馈），' +
        '所以条数比上面这一行多。同步执行，真模型约 1-2 分钟。结果写 ' +
        '<code>tests/report_doc_cases.json</code>，<b>不</b>会改页面上方那组指标——' +
        '它们来自 <code>tests/eval_run.py</code> 生成的报告，口径更大。</p>';
    } catch (e) {
      box.innerHTML = errBox(e);
    }
  }

  /* 跑评测是唯一一个可能持续一两分钟的操作：按钮上直接跑秒表，
     否则用户会以为点击没生效，然后再点一次。 */
  async function runEval(btn) {
    if (!online) { toast('离线副本不能运行评测', true); return; }
    var box = $('agEval');
    var started = Date.now();
    btn.disabled = true;
    var tick = setInterval(function () {
      btn.textContent = '运行中 ' + Math.round((Date.now() - started) / 1000) + 's';
    }, 1000);
    try {
      var r = await api('/api/cases/run', { method: 'POST', body: { scope: 'all' } });
      toast('评测完成：' + (r.passed || 0) + '/' + (r.total || 0) + ' 通过');
      receipt('跑评测', (r.total || 0) + ' 条用例',
        (r.passed || 0) + ' 通过 · ' + Math.round((r.pass_rate || 0) * 100) + '% · ' +
        // 离线跑一轮只有几十毫秒，`Math.round` 会写成「0s」——看起来像没跑
        ((r.duration_ms || 0) < 1000 ? '<1s' : Math.round(r.duration_ms / 1000) + 's') +
        '，写 tests/report_doc_cases.json');
      var cnt = $('agEvalCount');
      if (cnt) cnt.textContent = Math.round((r.pass_rate || 0) * 100) + '%';
      box.innerHTML = evalResult(r);
    } catch (e) {
      toast(e.message || String(e), true);
    } finally {
      clearInterval(tick);
      if (btn.isConnected) { btn.disabled = false; btn.textContent = '跑一遍 L1 用例'; }
    }
  }

  async function loadOps() {    var box = $('agOps');
    if (!box) return;
    try {
      var cfg = await api('/api/admin/config');
      var rt = cfg.runtime || {};
      lastCanary = rt.canary_percent || 0;
      box.innerHTML =
        '<div class="ag-kv"><span>当前模型</span><b>' + esc(cfg.model || '-') + '</b></div>' +
        '<div class="ag-kv"><span>灰度比例</span><b>' + (rt.canary_percent || 0) + '%</b></div>' +
        '<div class="ag-kv"><span>灰度模型</span><b>' + esc(rt.canary_model || '未设置') + '</b></div>' +
        '<div class="ag-kv"><span>配置修订</span><b>' + esc(rt.revision == null ? '-' : rt.revision) + '</b></div>' +
        '<form class="ag-inline" id="agCanary"><input type="number" name="p" min="0" max="100" value="' +
        (rt.canary_percent || 0) + '" aria-label="灰度比例"><button type="submit">应用灰度</button></form>' +
        '<div class="ag-row"><button class="ag-ghost" data-act="rebuild">重建索引</button>' +
        '<button class="ag-ghost" data-act="rollback">回滚配置</button></div>' +
        '<p class="ag-hint">灰度按比例把请求切到 CANARY_MODEL；回滚恢复上一版运行时配置。</p>';
      var f = $('agCanary');
      if (f) f.addEventListener('submit', onCanary);
    } catch (e) {
      box.innerHTML = errBox(e);
    }
  }

  async function onCanary(ev) {
    ev.preventDefault();
    var p = parseInt(ev.currentTarget.p.value, 10);
    if (isNaN(p) || p < 0 || p > 100) { toast('灰度比例需为 0-100', true); return; }
    try {
      await api('/api/admin/config', { method: 'POST', body: { canary_percent: p, note: 'report 管理面板' } });
      toast('灰度已设为 ' + p + '%');
      receipt('调整灰度', lastCanary + '% → ' + p + '%',
        p ? '新请求按比例切到灰度模型' : '全部回到主模型');
      await loadOps();
      await loadDiag();
    } catch (e) {
      toast(e.message || String(e), true);
    }
  }

  async function loadDiag() {
    var box = $('agDiag');
    if (!box) return;
    try {
      var h = await api('/api/health');
      box.innerHTML =
        '<div class="ag-kv"><span>版本</span><b>v' + esc(h.version || '-') + '</b></div>' +
        '<div class="ag-kv"><span>索引块</span><b>' + (h.chunks || 0) + '</b></div>' +
        '<div class="ag-kv"><span>模型</span><b>' + esc(h.model || '抽取式') + '</b></div>' +
        '<div class="ag-kv"><span>状态后端</span><b>' + esc((h.runtime || {}).state_backend || '-') + '</b></div>' +
        '<div class="ag-sub">最近审计</div><div id="agAudit" class="ag-audit">读取中…</div>';
      try {
        var a = await api('/api/audit?limit=8');
        var items = a.items || [];
        $('agAudit').innerHTML = items.length ? items.map(function (x) {
          return '<div class="ag-audit-row"><span>' + esc(String(x.ts || '').slice(11, 19)) + '</span>' +
            '<b>' + esc(x.action || '-') + '</b></div>';
        }).join('') : '<p class="ag-empty">暂无审计记录。</p>';
      } catch (e) {
        $('agAudit').innerHTML = errBox(e);
      }
    } catch (e) {
      box.innerHTML = errBox(e);
    }
  }

  /* 反馈 → 用例 → 评测 这条线原来断成三截：点踩在答案卡片里、建用例在知识库行内、
     跑评测在这里。三处都能用，但没人知道它们是一件事。这一组把它们接起来：
     看到未命中 → 看检索明细 → 建为用例 → 下次跑评测自动带上。 */
  async function loadFeedback() {
    var box = $('agFeedback');
    if (!box) return;
    try {
      var d = await api('/api/feedback/list?limit=20');
      var items = d.items || [];
      var cnt = $('agFeedbackCount');
      if (cnt) cnt.textContent = items.length ? String(items.length) : '';
      if (!items.length) {
        box.innerHTML = '<p class="ag-empty">还没有反馈。问答页每条答案下面都有「有用 / 有问题」，'
          + '点踩的记录会出现在这里，可以直接转成评测用例。</p>';
        return;
      }
      box.innerHTML = items.map(function (f) {
        var meta = fmtTime(f.ts) + ' · ' + (f.behavior || '-')
          + (f.expected ? ' · 期望：' + esc(f.expected) : '')
          + (f.document ? ' · 缺文档：' + esc(f.document) : '')
          + (f.comment ? ' · ' + esc(f.comment) : '');
        return '<div class="ag-fail"><b>' + esc(f.query || '（无问题）') + '</b><i>' + meta + '</i>'
          + '<div class="ag-row">'
          + '<button data-act="caseFromFb" data-trace="' + esc(f.trace_id || '') + '"'
          + (f.trace_id ? '' : ' disabled title="这条反馈没带 trace_id，无法定位原问题"') + '>建为用例</button>'
          + (f.query ? '<a class="ag-link" target="_blank" rel="noopener" href="/debug?q='
            + encodeURIComponent(f.query) + '">看检索明细</a>' : '')
          + '</div></div>';
      }).join('');
    } catch (e) {
      box.innerHTML = errBox(e);
    }
  }

  function loadAll() {
    loadContent();
    loadApproval();
    loadFeedback();
    loadEval();
    loadOps();
    loadDiag();
  }

  /* 离线时四个组不该各报一次错：那看起来像四个 bug，其实只有一个原因。 */
  function offlineHint() {
    ['agContent', 'agApproval', 'agFeedback', 'agEval', 'agOps', 'agDiag'].forEach(function (id) {
      var el = $(id);
      if (el) el.innerHTML = '<p class="ag-empty">离线副本只读；连接服务后这里会显示可操作的数据。</p>';
    });
  }

  /* ---------------- 操作回执 ----------------
     toast 三秒就消失，而「我刚才删的是哪一份」半分钟后还要能查。
     每条记四件事：几点、做了什么、对谁、结果摘要。
     只写 sessionStorage、关标签页即清空——它回答的是「这一次会话里我干了什么」，
     不是长期日志（权威记录在服务端 /api/audit，面板「诊断」组里能直接看到）。 */
  var receipts = [];
  var lastCanary = 0;        // 上一次读到的灰度比例，用来把回执写成「10% → 30%」

  function loadReceipts() {
    try {
      var raw = sessionStorage.getItem('rp_receipts');
      var arr = raw ? JSON.parse(raw) : [];
      receipts = Array.isArray(arr) ? arr : [];
    } catch (e) { receipts = []; }
  }

  function saveReceipts() {
    try {
      sessionStorage.setItem('rp_receipts', JSON.stringify(receipts.slice(0, 20)));
    } catch (e) { /* 隐私模式写不进去，本次会话内仍然显示 */ }
  }

  function stamp(d) {
    var p = function (n) { return (n < 10 ? '0' : '') + n; };
    return p(d.getHours()) + ':' + p(d.getMinutes()) + ':' + p(d.getSeconds());
  }

  function renderReceipts() {
    var wrap = $('agReceipts');
    var list = $('agReceiptList');
    if (!wrap || !list) return;
    wrap.hidden = !receipts.length;
    var cnt = $('agReceiptCount');
    if (cnt) cnt.textContent = receipts.length ? receipts.length + ' 项' : '';
    list.innerHTML = receipts.map(function (r) {
      return '<div class="ag-receipt' + (r.bad ? ' is-bad' : '') + '">' +
        '<time>' + esc(r.at || '') + '</time>' +
        '<span class="what"><b>' + esc(r.act || '') + '</b> ' + esc(r.target || '') + '</span>' +
        (r.detail ? '<span class="said">' + esc(r.detail) + '</span>' : '') +
        '</div>';
    }).join('');
  }

  /* 只记成功。失败已经在 toast 里喊过，记进回执会把这里变成一份错误日志。 */
  function receipt(act, target, detail) {
    receipts.unshift({ at: stamp(new Date()), act: act, target: target || '', detail: detail || '' });
    if (receipts.length > 20) receipts.pop();
    saveReceipts();
    renderReceipts();
  }

  /* ---------------- 操作分派 ---------------- */

  async function runAction(act, el) {
    if (act === 'runEval') { await runEval(el); return; }
    if (act === 'caseFromFb') {
      var trace = el.dataset.trace || '';
      if (!trace) { toast('这条反馈没有 trace_id，定位不到原问题', true); return; }
      try {
        var made = await api('/api/cases/from_feedback', {
          method: 'POST',
          body: { trace_id: trace, behavior: 'no_answer', note: '由汇报页的未命中反馈生成' }
        });
        var cid = (made && made.case && made.case.id) || '';
        toast('已生成用例 ' + cid);
        receipt('建为用例', cid || '反馈 ' + trace.slice(0, 8),
          '已加入反馈用例集，下次跑 L1 用例时一起执行');
        await loadFeedback();
        await loadEval();
      } catch (e) { toast(e.message || String(e), true); }
      return;
    }
    if (!online) { toast('离线副本不能修改数据', true); return; }
    if (act === 'del') {
      if (!armConfirm(el, '删除')) return;
      var gone = el.dataset.name || '';
      try {
        await api('/api/knowledge/delete', { method: 'POST', body: { name: gone } });
        toast('已删除：' + gone);
        // 不要写「可用文档历史回滚」：`/api/kb/rollback_doc` 只对**当前存在**的文档生效，
        // 对已删除的文件直接回 conflict（"新增文档请走上传流程"）。回执要是写了个
        // 做不到的补救方式，等于骗人回头去点一个必然失败的按钮。
        receipt('删除文档', gone, '已从当前版本移除 · 恢复需重新上传该文件');
        await loadContent();
        markStale();
      } catch (e) { toast(e.message || String(e), true); }
      return;
    }
    if (act === 'approve' || act === 'reject') {
      var id = el.dataset.id;
      // 通过即生成新版本并切索引，等于改线上语料：一次误点不该生效
      if (act === 'approve' && !armConfirm(el, '通过并发布')) return;
      el.disabled = true;
      try {
        var apr = await api('/api/kb/' + act, { method: 'POST', body: { change_id: id } });
        toast((act === 'approve' ? '已通过并发布：' : '已驳回：') + id);
        receipt(act === 'approve' ? '通过并发布' : '驳回变更', id,
          act === 'approve'
            ? '生成新版本 ' + ((apr && apr.version) || '') + '，索引已切换'
            : '变更已关闭，语料未改动');
        await loadApproval();
        await loadContent();
        markStale();
      } catch (e) { toast(e.message || String(e), true); }
      el.disabled = false;
      return;
    }
    if (act === 'rebuild') {
      if (!armConfirm(el, '重建索引')) return;
      try {
        var r = await api('/api/reload', { method: 'POST', body: {} });
        toast(r.rebuilding ? '索引重建已排队' : '索引已重建');
        receipt('重建索引', '全部文档', r.rebuilding
          ? '已排队，后台执行 · 期间问答仍用旧索引'
          : '已重建 · 块数 ' + (r.chunks == null ? '-' : r.chunks));
        markStale();
      } catch (e) { toast(e.message || String(e), true); }
      return;
    }
    if (act === 'rollback') {
      if (!armConfirm(el, '回滚配置')) return;
      try {
        var back = await api('/api/admin/rollback', { method: 'POST', body: {} });
        toast(back.rolled_back ? '已回滚到修订 ' + back.revision : '没有可回滚的修订');
        receipt('回滚配置', '运行时设置', back.rolled_back
          ? '已回到修订 ' + back.revision + ' · 灰度与模型随之恢复'
          : '没有可回滚的修订，未做改动');
        await loadOps();
      } catch (e) { toast(e.message || String(e), true); }
      return;
    }
    if (act === 'auth') {
      var d = document.querySelector('.agroup[data-group="auth"]');
      if (d) { d.open = true; }
    }
  }

  /* ---------------- 面板开合 ---------------- */

  function openPanel(group) {
    var panel = $('rpAdmin');
    if (!panel) return;
    if (!opened) {
      opened = true;
      if (online && !loaded) { loaded = true; loadAll(); }
    }
    body.classList.add('admin-on');
    panel.setAttribute('aria-hidden', 'false');
    $('rpAdminBtn').setAttribute('aria-expanded', 'true');
    if (group) {
      var target = document.querySelector('.agroup[data-group="' + group + '"]');
      if (target) {
        target.open = true;
        target.scrollIntoView({ block: 'nearest' });
      }
    }
  }

  function closePanel() {
    var panel = $('rpAdmin');
    if (!panel) return;
    body.classList.remove('admin-on');
    panel.setAttribute('aria-hidden', 'true');
    $('rpAdminBtn').setAttribute('aria-expanded', 'false');
    $('rpAdminBtn').focus();
  }

  /* ---------------- 启动 ---------------- */

  async function probe() {
    if (body.dataset.standalone === '1') {
      markState('offline', '离线副本 · 只读');
      offlineHint();
      return;
    }
    try {
      var ctl = new AbortController();
      var timer = setTimeout(function () { ctl.abort(); }, 2500);
      var resp = await fetch('/api/health', { signal: ctl.signal, cache: 'no-store' });
      clearTimeout(timer);
      if (!resp.ok) throw new Error('bad status');
      var d = await resp.json();
      online = true;
      markState('online', '服务在线 · v' + (d.version || ''));
      var off = $('rpOffline');
      if (off) off.hidden = true;
      var st = $('rpAdminState');
      if (st) st.textContent = '已连接';
      // 面板可能在探活返回前就被打开了：补一次加载，否则一直停在「加载中…」
      if (opened && !loaded) { loaded = true; loadAll(); }
      var btn = $('rpAdminBtn');
      btn.classList.remove('is-off');
      btn.title = '打开管理面板';
    } catch (e) {
      markState('offline', '离线副本 · 只读');
      offlineHint();
    }
  }

  function bind() {
    var btn = $('rpAdminBtn');
    if (btn) {
      btn.addEventListener('click', function () {
        if (body.classList.contains('admin-on')) closePanel();
        else openPanel('');
      });
    }
    var close = $('rpClose');
    if (close) close.addEventListener('click', closePanel);

    var print = $('rpPrint');
    if (print) print.addEventListener('click', function () { window.print(); });

    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && body.classList.contains('admin-on')) closePanel();
    });

    /* 展示区每个区块右上角的「管理」入口：点哪块就开对应的组，
       而不是让人在面板里自己找——这是两部分之间唯一的显式连接。 */
    document.addEventListener('click', function (e) {
      var jump = e.target.closest('[data-admin-jump]');
      if (jump) { openPanel(jump.dataset.adminJump); return; }
      var act = e.target.closest('[data-act]');
      if (act) { runAction(act.dataset.act, act); }
    });

    var auth = $('agAuthForm');
    if (auth) {
      auth.addEventListener('submit', function (ev) {
        ev.preventDefault();
        try {
          var k = (auth.key.value || '').trim();
          var t = (auth.token.value || '').trim();
          if (k) sessionStorage.setItem('rag_api_key', k); else sessionStorage.removeItem('rag_api_key');
          if (t) sessionStorage.setItem('rag_admin_token', t); else sessionStorage.removeItem('rag_admin_token');
        } catch (err) { /* 隐私模式下写不进去，本次请求仍然带上 */ }
        toast('凭据已用于本次会话');
        loadAll();
      });
    }

    var stale = $('rpStaleBtn');
    if (stale) {
      stale.addEventListener('click', function () {
        try { sessionStorage.setItem('rp_scroll', String(window.scrollY)); } catch (e) { /* 忽略 */ }
        location.reload();
      });
    }
  }

  /* 面板里换了数据、整页刷新后回到原位置：否则每次都从顶部重新读一遍。 */
  function restoreScroll() {
    try {
      var y = sessionStorage.getItem('rp_scroll');
      if (y !== null) {
        sessionStorage.removeItem('rp_scroll');
        window.scrollTo(0, parseInt(y, 10) || 0);
      }
    } catch (e) { /* 忽略 */ }
  }

  bind();
  loadReceipts();
  renderReceipts();
  restoreScroll();
  /* `?admin=1` 直接打开面板：管理台地址可以被收藏，
     也方便把「带面板的样子」截给同事看。 */
  probe().then(function () {
    try {
      if (new URLSearchParams(location.search).get('admin') === '1') openPanel('');
    } catch (e) { /* 老浏览器没有 URLSearchParams 时静默跳过 */ }
  });
})();

/* 下载按钮：必须走 fetch。
   直接给 a[href] 的话浏览器导航带不上 X-API-Key，服务端按匿名处理并
   静默返回脱敏副本（文档清单被清空、模型显示「已隐藏」）——用户以为拿到了完整版。 */
(function () {
  var btns = [].slice.call(document.querySelectorAll('[data-dl]'));
  if (!btns.length || !window.fetch) return;
  btns.forEach(function (b) {
    b.addEventListener('click', function () {
      var label = b.textContent;
      b.disabled = true; b.textContent = '生成中…';
      fetch('/report?download=1', { headers: reqHeaders(false) })
        .then(function (r) {
          if (!r.ok) throw new Error('HTTP ' + r.status);
          return r.text();
        })
        .then(function (t) { saveBlob(t, 'report.html', 'text/html;charset=utf-8'); })
        .catch(function (e) { toast('下载失败：' + ((e && e.message) || e), true); })
        .finally(function () { b.disabled = false; b.textContent = label; });
    });
  });
})();
