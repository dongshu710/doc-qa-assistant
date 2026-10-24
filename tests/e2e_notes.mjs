/**
 * 笔记 UI 端到端：知识库页的「笔记」分区 + 问答页的「存为笔记」。
 *
 * 为什么不塞进 e2e_pages.mjs：这一组要写真实文件、要断言 rev 冲突与导出内容，
 * 环境准备（临时 NOTE_HOME）和断言粒度都不一样，合在一起会让两边都难读。
 *
 * 运行：node tests/e2e_notes.mjs [--base http://127.0.0.1:8011]
 * 依赖：playwright-core + 本机 Edge/Chrome；没装就明确跳过。
 */
import { spawn } from 'node:child_process';
import { createServer } from 'node:net';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import fs from 'node:fs';
import os from 'node:os';

const require = createRequire(import.meta.url);
const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const args = process.argv.slice(2);
const baseArg = args.includes('--base') ? args[args.indexOf('--base') + 1] : null;

function loadPlaywright() {
  for (const name of ['playwright-core', 'playwright']) {
    try { return { mod: require(name), name }; } catch { /* 继续找 */ }
  }
  return null;
}

function freePort() {
  return new Promise((resolve, reject) => {
    const srv = createServer();
    srv.once('error', reject);
    srv.listen(0, '127.0.0.1', () => {
      const { port } = srv.address();
      srv.close(() => resolve(port));
    });
  });
}

async function launchBrowser() {
  const pw = loadPlaywright();
  if (!pw) {
    console.log('SKIP: 未安装 playwright/playwright-core（npm i -D playwright-core）');
    process.exit(0);
  }
  const { chromium } = pw.mod;
  const attempts = [
    { channel: 'msedge' }, { channel: 'chrome' }, {},
    { executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe' },
    { executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe' },
    { executablePath: '/usr/bin/chromium' },
  ];
  let last;
  for (const opts of attempts) {
    try { return await chromium.launch({ headless: true, ...opts }); } catch (err) { last = err; }
  }
  throw new Error(`没有可用浏览器（${pw.name}）：${last?.message || last}`);
}

const failures = [];
function check(name, ok, detail = '') {
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail && !ok ? ' · ' + detail : ''}`);
  if (!ok) failures.push({ name, detail });
}

async function waitHealth(base, timeoutMs = 30000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const r = await fetch(`${base}/api/health`);
      if (r.ok) return await r.json();
    } catch { /* 还没起来 */ }
    await new Promise((r) => setTimeout(r, 250));
  }
  throw new Error(`服务在 ${timeoutMs}ms 内未就绪: ${base}`);
}

let server = null;
let noteHome = null;
let base = baseArg;

try {
  if (!base) {
    const port = await freePort();
    base = `http://127.0.0.1:${port}`;
    noteHome = fs.mkdtempSync(path.join(os.tmpdir(), 'notes-e2e-'));
    const py = process.env.PYTHON || 'python';
    const env = { ...process.env, PYTHONUTF8: '1', PYTHONPATH: ROOT, RETRIEVAL: 'vector',
                  NOTE_HOME: path.join(noteHome, 'notes') };
    delete env.LLM_API_KEY;
    delete env.DEEPSEEK_API_KEY;
    const logPath = path.join(ROOT, 'tests', 'e2e-notes-server.log');
    const fd = fs.openSync(logPath, 'w');
    server = spawn(py, ['-m', 'src.server', '--host', '127.0.0.1', '--port', String(port)], {
      cwd: ROOT, env, stdio: ['ignore', fd, fd],
    });
    server.on('exit', (code) => { if (code) console.error(`server exited ${code}; log: ${logPath}`); });
  }

  const health = await waitHealth(base);
  console.log(`服务就绪 ${base} · ${health.chunks} 块 · ${health.version}`);

  // 先种一条笔记：UI 的列表/编辑/导出都需要有内容
  const seeded = await fetch(`${base}/api/notes`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      messages: [
        { role: 'user', text: '出口退税按什么标准执行？' },
        { role: 'assistant', text: '根据办法第十二条按 13% 执行。决定由财务部每月 5 日前复核申报表。' },
      ],
      hint: { title: '出口退税口径', kind: 'decision', tags: ['税务', '出口退税'] },
      source: { agent: 'e2e-seed' },
    }),
  }).then((r) => r.json());
  check('种子笔记写入成功', seeded.ok === true, JSON.stringify(seeded).slice(0, 120));

  const browser = await launchBrowser();
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const page = await context.newPage();
  const consoleErrors = [];
  page.on('console', (msg) => {
    if (msg.type() !== 'error') return;
    const text = msg.text();
    // 409 是我们主动构造的并发冲突，浏览器会记一条资源错误，不算缺陷
    if (!/favicon|ERR_ABORTED|Failed to load resource/i.test(text)) consoleErrors.push(text);
  });
  page.on('pageerror', (err) => consoleErrors.push(`pageerror: ${err.message}`));

  // ---------- 知识库页：笔记分区 ----------
  await page.goto(`${base}/kb`, { waitUntil: 'networkidle' });
  check('默认停在文档分区', await page.isVisible('#panelDocs') && !(await page.isVisible('#panelNotes')));
  await page.click('.kb-tabs button[data-tab="notes"]');
  await page.waitForSelector('.note-item', { timeout: 15000 });
  check('切到笔记分区并加载出列表', (await page.locator('.note-item').count()) === 1);
  check('列表带标题', (await page.textContent('.note-item b')).includes('出口退税'));
  check('标题栏不被遮挡', await page.isVisible('#noteCount'));

  await page.click('.note-item');
  await page.waitForSelector('#noteEditor:not([hidden])');
  check('打开后标题回填', (await page.inputValue('#neTitle')).includes('出口退税'));
  check('小节可编辑', (await page.locator('#neSections textarea').count()) >= 2);
  check('标签回填', (await page.inputValue('#neTags')).includes('税务'));

  await page.fill('#neTitle', '出口退税口径（已核对）');
  page.once('dialog', (d) => d.accept('补充'));
  await page.click('#neAddSec');
  await page.waitForSelector('#neSections .ne-sec:last-child textarea');
  await page.fill('#neSections .ne-sec:last-child textarea', '- 与报关行确认口径');
  await page.click('#neSave');
  await page.waitForTimeout(800);
  check('保存后列表标题同步', (await page.textContent('.note-item b')).includes('已核对'));

  const detail = await page.evaluate(async () => {
    const list = await (await fetch('/api/notes')).json();
    return await (await fetch('/api/notes/' + list.items[0].id)).json();
  });
  check('磁盘内容含新增小节',
    detail.sections.some((s) => s.title === '补充' && s.body.includes('报关行')),
    JSON.stringify(detail.sections.map((s) => s.title)));

  const conflict = await page.evaluate(async () => {
    const list = await (await fetch('/api/notes')).json();
    const r = await fetch('/api/notes/' + list.items[0].id, {
      method: 'PATCH', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ base_rev: 'deadbeefdeadbeef', changes: { title: '旧 rev 覆盖' } }),
    });
    return { status: r.status, body: await r.json() };
  });
  check('旧 rev 修改被拒 409', conflict.status === 409, JSON.stringify(conflict).slice(0, 120));

  await page.fill('#noteSearch', '不存在的关键词');
  await page.waitForTimeout(200);
  check('搜不到时给空提示', (await page.textContent('#noteList')).includes('没有匹配'));
  await page.fill('#noteSearch', '税务');
  await page.waitForTimeout(200);
  check('按标签能搜到', (await page.locator('.note-item').count()) === 1);

  const [download] = await Promise.all([
    page.waitForEvent('download', { timeout: 15000 }),
    page.click('#noteExportHtml'),
  ]);
  const exported = await fs.promises.readFile(await download.path(), 'utf8');
  check('导出 HTML 可下载', exported.includes('<!doctype html>') && exported.includes('已核对'));
  check('导出文件自包含', !exported.includes('<link') && !exported.includes('src="http'));

  await page.setViewportSize({ width: 390, height: 844 });
  await page.waitForTimeout(300);
  const overflow = await page.evaluate(() =>
    document.documentElement.scrollWidth - document.documentElement.clientWidth);
  check('窄屏无横向溢出', overflow <= 0, `overflow=${overflow}`);
  await page.setViewportSize({ width: 1280, height: 900 });

  // ---------- 问答页：存为笔记 ----------
  await page.goto(`${base}/ask`, { waitUntil: 'networkidle' });
  await page.fill('#q', '理财产品风险等级怎么划分？');
  await page.click('#send');
  await page.waitForSelector('.fb-save', { timeout: 40000 });
  check('回答下方出现「存为笔记」', await page.isVisible('.fb-save'));

  await page.click('.fb-save');
  await page.waitForSelector('#noteDialog:not([hidden])');
  await page.waitForFunction(() => !document.getElementById('ndSave').disabled, null, { timeout: 20000 });
  check('弹窗给出整理预览', (await page.textContent('#ndPreview')).includes('## 摘要'));
  check('标题已预填', (await page.inputValue('#ndTitle')).length > 0);
  await page.fill('#ndTitle', '风险等级划分（网页存稿）');
  await page.fill('#ndTags', '产品, 风险');
  await page.click('#ndSave');
  await page.waitForTimeout(900);
  check('保存后弹窗关闭', await page.isHidden('#noteDialog'));

  const listed = await page.evaluate(async () => (await (await fetch('/api/notes?limit=50')).json()));
  check('网页存稿已入库', listed.count === 2, `count=${listed.count}`);
  check('新笔记标题正确', listed.items.some((n) => n.title === '风险等级划分（网页存稿）'),
    JSON.stringify(listed.items.map((n) => n.title)));

  check('无控制台错误', consoleErrors.length === 0, consoleErrors.join(' | ').slice(0, 300));

  await browser.close();
} finally {
  if (server) server.kill();
  if (noteHome) fs.rmSync(noteHome, { recursive: true, force: true });
}

console.log(`\n通过 ${failures.length ? '部分' : '全部'}；失败 ${failures.length} 项`);
if (failures.length) {
  console.log(failures.map((f) => `- ${f.name} ${f.detail}`).join('\n'));
  process.exit(1);
}
console.log('NOTES E2E OK');
