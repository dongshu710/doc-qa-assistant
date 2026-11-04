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
                  NOTE_HOME: path.join(noteHome, 'notes'),
                  SETUP_DONE: '1',
                  // 配置也要隔离：否则「存为笔记」按钮取决于本机 data/app.json 的开关，
                  // 干净环境（CI）默认关闭 → 按钮不渲染 → 整条用例超时
                  APP_CONFIG: path.join(noteHome, 'app.json'),
                  STORE_CHAT: 'on' };
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

  // ---------- /files：唯一完整入口 ----------
  await page.goto(`${base}/files`, { waitUntil: 'networkidle' });
  await page.waitForSelector('.file-item', { timeout: 15000 });
  check('/files 列出笔记', (await page.locator('.file-item').count()) === 1);
  check('列表带标题', (await page.textContent('.file-item b')).includes('出口退税'));

  await page.click('.file-item');
  await page.waitForSelector('.pf-detail h3', { timeout: 15000 });
  check('详情显示标题', (await page.textContent('.pf-detail h3')).includes('出口退税'));

  // 编辑原文：改标题后列表要跟着变（这条链路以前只有抽屉能做）
  await page.click('[data-edit]');
  await page.waitForSelector('.fe-area', { timeout: 15000 });
  const raw = await page.inputValue('.fe-area');
  check('原文含 front matter', raw.trimStart().startsWith('---'), raw.slice(0, 40));
  await page.fill('.fe-area', raw.replace('出口退税口径', '出口退税口径（已核对）'));
  await page.click('[data-save]');
  await page.waitForFunction(
    () => (document.querySelector('.file-item b')?.textContent || '').includes('已核对'),
    null, { timeout: 15000 });
  check('保存后列表标题同步', true);

  // 服务端搜索：与问答页共用同一套索引
  await page.fill('#pfSearch', '税务');
  await page.waitForTimeout(800);
  check('搜索命中', (await page.locator('.file-item').count()) === 1);

  // 清空搜索并重新选中，附件区才会挂上来
  await page.fill('#pfSearch', '');
  await page.waitForTimeout(800);
  await page.click('.file-item');
  await page.waitForSelector('[data-upload]', { timeout: 15000 });

  // 附件上传（知识库那边的入口已经并到这里）
  const tmpFile = path.join(noteHome, '附件样例.txt');
  fs.writeFileSync(tmpFile, '附件内容');
  await page.setInputFiles('#pfAssetFile', tmpFile);
  await page.waitForSelector('.pf-asset', { timeout: 15000 });
  check('附件上传后出现在列表',
    (await page.textContent('.pf-asset .nm')).includes('附件样例'));

  // 导出 HTML（内容要自包含，能离线打开）
  const [download] = await Promise.all([
    page.waitForEvent('download', { timeout: 15000 }),
    page.click('#pfExportHtml'),
  ]);
  const exported = await fs.promises.readFile(await download.path(), 'utf8');
  check('导出 HTML 可下载', exported.includes('<!doctype html>') && exported.includes('已核对'));
  check('导出文件自包含', !exported.includes('<link') && !exported.includes('src="http'));

  await page.setViewportSize({ width: 390, height: 844 });
  await page.waitForTimeout(300);
  // 溢出时把「谁越界」打出来，否则只看到一个数字，下次还得再猜一次
  const narrow = await page.evaluate(() => {
    const doc = document.documentElement;
    const limit = doc.clientWidth;
    const offenders = [];
    document.querySelectorAll('body *').forEach((el) => {
      const rect = el.getBoundingClientRect();
      if (rect.width > 0 && rect.right > limit + 0.5) {
        const cls = String(el.className || '').split(' ')[0];
        offenders.push(el.tagName.toLowerCase() + (cls ? '.' + cls : ''));
      }
    });
    return { diff: doc.scrollWidth - doc.clientWidth, offenders: offenders.slice(0, 4) };
  });
  // 容差 4px：CI 的 Linux 环境没有「微软雅黑」，同一段字的度量比 Windows 宽；
  // 滚动条宽度也各平台不同。真正的破版是几十像素，不是 3 像素的字体舍入。
  check('窄屏无横向溢出', narrow.diff <= 4,
    `overflow=${narrow.diff} ${narrow.offenders.join(' ')}`);
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
