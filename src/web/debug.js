/* 检索调试台：只做一件事——把「候选 + 分数 + 是否被阈值挡掉」摊开。
 *
 * 为什么不用问答页复用：问答页的目标是「给答案」，这里的目标是「解释为什么没有答案」。
 * 两者的默认动作相反（一个收起细节，一个必须摊开），硬塞进同一个页面会让两边都别扭。
 */
(function () {
  var q = document.getElementById('dbgQuery');
  var topk = document.getElementById('dbgTopK');
  var run = document.getElementById('dbgRun');
  var summary = document.getElementById('dbgSummary');
  var list = document.getElementById('dbgList');
  var empty = document.getElementById('dbgEmpty');
  var minScoreEl = document.getElementById('dbgMinScore');

  function pct(x) { return Math.max(0, Math.min(1, Number(x) || 0)) * 100; }

  function render(d) {
    minScoreEl.textContent = String(d.min_score);
    summary.hidden = false;
    summary.innerHTML =
      '<div class="dbg-sum">'
      + '<span>召回 <b>' + d.recalled + '</b> 条</span>'
      + '<span>保留 <b>' + d.kept + '</b> 条</span>'
      + '<span>阈值 <b class="mono">' + d.min_score + '</b></span>'
      + '<span>检索模式 <b>' + esc(d.retrieval || '-') + '</b></span>'
      + '<span>全库 <b>' + d.chunks_total + '</b> 块</span>'
      + '<span>耗时 <b>' + d.elapsed_ms + '</b> ms</span>'
      + (d.degraded ? '<span class="bad">降级：' + esc(d.degrade_reason || '') + '</span>' : '')
      + '</div>';

    if (!d.candidates || !d.candidates.length) {
      list.innerHTML = '';
      empty.hidden = false;
      empty.textContent = '这条问题一块都没召回。多半是问法和资料用词完全对不上，'
        + '不是阈值问题——调低阈值不会有帮助。';
      return;
    }
    empty.hidden = true;
    list.innerHTML = d.candidates.map(function (c) {
      var cls = c.kept ? 'kept' : 'dropped';
      var page = c.page ? ' · 第 ' + esc(c.page) + ' 页' : '';
      return '<article class="dbg-item ' + cls + '">'
        + '<div class="dbg-head">'
        + '<span class="dbg-ref">' + esc(c.ref) + '</span>'
        + '<b>' + esc(c.title || c.doc_id) + '</b>'
        + '<span class="dbg-meta">' + esc(c.section || '') + page
        + ' · 第 ' + (c.chunk_index + 1) + ' 块 · ' + c.chars + ' 字</span>'
        + '<span class="dbg-score ' + cls + '">' + c.score + (c.kept ? '' : ' · 未保留') + '</span>'
        + '</div>'
        + '<div class="dbg-bar"><i style="width:' + pct(c.score).toFixed(1) + '%"></i></div>'
        + '<div class="dbg-text">' + esc(c.text || '') + '</div>'
        + '</article>';
    }).join('');
  }

  async function search() {
    var text = (q.value || '').trim();
    if (!text) { q.focus(); return; }
    run.disabled = true;
    run.textContent = '检索中';
    try {
      var r = await fetch('/api/search/debug', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: text, top_k: Number(topk.value) || 4 })
      });
      var d = await r.json();
      if (!r.ok || d.ok === false) throw new Error(d.message || d.error || ('HTTP ' + r.status));
      render(d);
    } catch (e) {
      summary.hidden = false;
      summary.innerHTML = '<div class="dbg-sum"><span class="bad">检索失败：'
        + esc(String(e.message || e)) + '</span></div>';
    } finally {
      run.disabled = false;
      run.textContent = '检索';
    }
  }

  run.addEventListener('click', search);
  q.addEventListener('keydown', function (e) {
    if (e.key === 'Enter') { e.preventDefault(); search(); }
  });
})();
