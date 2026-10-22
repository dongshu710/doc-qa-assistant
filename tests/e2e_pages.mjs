/**
 * 五页 E2E：首页 / 问答 / 知识库 / 看板 / 汇报。
 *
 * 为什么用 Playwright：这五页的交互（SSE、抽屉、审批、主题切换）靠 curl 测不到；
 * 但项目运行时仍是零依赖，Playwright 只作为开发期工具，没装就明确跳过。
 *
 * 运行：
 *   node tests/e2e_pages.mjs
 *   node tests/e2e_pages.mjs --base http://127.0.0.1:8011   # 测已启动的服务
 *
 * 环境变量：
 *   PYTHON     指定 Python 解释器（默认 python）
 *   NODE_PATH  指向 playwright-core 所在 node_modules
 */
import { spawn } from 'node:child_process';
import { createServer } from 'node:net';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import fs from 'node:fs';

const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const args = process.argv.slice(2);
const baseArg = args.includes('--base') ? args[args.indexOf('--base') + 1] : null;

function loadPlaywright() {
  for (const name of ['playwright-core', 'playwright']) {
    try { return { mod: require(name), name }; } catch { /* 继续找 */ }
  }
  return null;
}

const { createRequire } = await import('node:module');
const require = createRequire(import.meta.url);

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

async function launchBrowser() {
  const pw = loadPlaywright();
  if (!pw) {
    console.log('SKIP: 未安装 playwright/playwright-core（npm i -D playwright-core）');
    process.exit(0);
  }
  const { chromium } = pw.mod;
  const attempts = [
    { channel: 'msedge' },
    { channel: 'chrome' },
    {},
    { executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe' },
    { executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe' },
    { executablePath: '/usr/bin/chromium' },
    { executablePath: '/usr/bin/google-chrome' },
  ];
  let last;
  for (const opts of attempts) {
    try {
      return await chromium.launch({ headless: true, ...opts });
    } catch (err) { last = err; }
  }
  throw new Error(`没有可用浏览器（${pw.name}）：${last?.message || last}`);
}

const failures = [];
function check(name, ok, detail = '') {
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? ' · ' + detail : ''}`);
  if (!ok) failures.push({ name, detail });
}

function attachConsole(page, bucket) {
  page.on('console', (msg) => {
    if (msg.type() === 'error') {
      const text = msg.text();
      if (!/favicon|ERR_ABORTED|Failed to load resource/i.test(text)) bucket.push(text);
    }
  });
  page.on('pageerror', (err) => bucket.push(`pageerror: ${err.message}`));
}

async function overflow(page) {
  return page.evaluate(() => ({
    scroll: document.documentElement.scrollWidth,
    inner: window.innerWidth,
  }));
}

const PAGES = [
  {
    path: '/', name: '首页',
    ready: ['.hero h1', 'a[href="/ask"]'],
    titleHint: '文档问答',
  },
  {
    path: '/ask', name: '问答页',
    ready: ['#q', '#send', '#exportMd', '.composer'],
    titleHint: '问答',
  },
  {
    path: '/kb', name: '知识库',
    ready: ['#kbFile', '#kbBody', '#kbVersion', '#reload'],
    titleHint: '知识库',
    after: async (page) => {
      await page.waitForFunction(() => {
        const el = document.getElementById('kbVersion');
        return el && el.textContent && el.textContent !== '—';
      }, null, { timeout: 15000 });
    },
  },
  {
    path: '/dashboard', name: '看板',
    ready: ['#tabs a', '.kpi', '#fbBody'],
    titleHint: '看板',
    after: async (page) => {
      await page.waitForFunction(() => document.querySelectorAll('.kpi').length >= 4,
        null, { timeout: 15000 });
    },
  },
  {
    path: '/report', name: '汇报',
    ready: ['.rp-hero h1', '.kpis .kpi', '.table-wrap'],
    titleHint: '汇报',
    after: async (page) => {
      await page.waitForFunction(() => document.querySelectorAll('.kpis .kpi').length >= 6,
        null, { timeout: 15000 });
    },
  },
];

let server = null;
let base = baseArg;

try {
  if (!base) {
    const port = await freePort();
    base = `http://127.0.0.1:${port}`;
    const py = process.env.PYTHON || 'python';
    const env = { ...process.env, PYTHONUTF8: '1', PYTHONPATH: ROOT, RETRIEVAL: 'vector' };
    delete env.LLM_API_KEY;
    delete env.DEEPSEEK_API_KEY;
    const logPath = path.join(ROOT, 'tests', 'e2e-server.log');
    const fd = fs.openSync(logPath, 'w');
    server = spawn(py, ['-m', 'src.server', '--host', '127.0.0.1', '--port', String(port)], {
      cwd: ROOT, env, stdio: ['ignore', fd, fd],
    });
    server.on('exit', (code) => {
      if (code && code !== 0) console.error(`server exited ${code}; log: ${logPath}`);
    });
  }

  const health = await waitHealth(base);
  console.log(`服务就绪 ${base} · ${health.chunks} 块 · ${health.version}`);

  const browser = await launchBrowser();
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const page = await context.newPage();
  const consoleErrors = [];
  attachConsole(page, consoleErrors);

  for (const spec of PAGES) {
    consoleErrors.length = 0;
    const resp = await page.goto(base + spec.path, { waitUntil: 'domcontentloaded' });
    check(`${spec.name} HTTP 200`, resp?.status() === 200, `status=${resp?.status()}`);
    for (const sel of spec.ready) {
      check(`${spec.name} 选择器 ${sel}`, await page.locator(sel).count() > 0);
    }
    if (spec.after) {
      try { await spec.after(page); check(`${spec.name} 数据就绪`, true); }
      catch (err) { check(`${spec.name} 数据就绪`, false, String(err).slice(0, 160)); }
    }
    const title = await page.title();
    check(`${spec.name} 标题非空`, title.length > 0 && title.includes(spec.titleHint), title);

    const navCount = await page.locator('header.nav nav a').count();
    check(`${spec.name} 导航 5 项`, navCount === 5, `nav=${navCount}`);

    const wide = await overflow(page);
    check(`${spec.name} 1280px 无横向溢出`, wide.scroll <= wide.inner + 1,
      `${wide.scroll}/${wide.inner}`);

    await page.setViewportSize({ width: 390, height: 844 });
    await page.waitForTimeout(150);
    const narrow = await overflow(page);
    check(`${spec.name} 390px 无横向溢出`, narrow.scroll <= narrow.inner + 1,
      `${narrow.scroll}/${narrow.inner}`);
    await page.setViewportSize({ width: 1280, height: 900 });

    check(`${spec.name} 无控制台错误`, consoleErrors.length === 0,
      consoleErrors.slice(0, 2).join(' | ').slice(0, 220));
  }

  // ---------- 深色模式 ----------
  await page.goto(base + '/ask', { waitUntil: 'domcontentloaded' });
  await page.click('#themeToggle');
  const dark = await page.evaluate(() => {
    const body = getComputedStyle(document.body);
    const card = document.querySelector('.chat-shell');
    const rgb = (s) => (s.match(/\d+/g) || []).slice(0, 3).map(Number);
    return {
      theme: document.documentElement.getAttribute('data-theme'),
      bg: rgb(body.backgroundColor),
      fg: rgb(body.color),
      card: card ? rgb(getComputedStyle(card).backgroundColor) : null,
    };
  });
  check('主题切换写入 data-theme', dark.theme === 'dark');
  check('深色背景足够暗', dark.bg.reduce((a, b) => a + b, 0) < 180, dark.bg.join(','));
  check('深色模式文字足够亮', dark.fg.reduce((a, b) => a + b, 0) > 480, dark.fg.join(','));
  check('深色模式卡片不再用白底', dark.card && dark.card.reduce((a, b) => a + b, 0) < 180,
    dark.card ? dark.card.join(',') : 'missing');
  await page.reload({ waitUntil: 'domcontentloaded' });
  check('深色模式刷新后保持',
    await page.evaluate(() => document.documentElement.getAttribute('data-theme')) === 'dark');

  // ---------- 减动效 ----------
  const rmContext = await browser.newContext({ reducedMotion: 'reduce' });
  const rmPage = await rmContext.newPage();
  await rmPage.goto(base + '/ask', { waitUntil: 'domcontentloaded' });
  const rm = await rmPage.evaluate(() => {
    const btn = document.querySelector('.btn') || document.body;
    return {
      media: matchMedia('(prefers-reduced-motion: reduce)').matches,
      duration: getComputedStyle(btn).transitionDuration,
      scroll: getComputedStyle(document.documentElement).scrollBehavior,
    };
  });
  // 浏览器把 0.01ms 序列化成 "1e-05s"；按单位换算再比较，别用字符串白名单
  const durNum = parseFloat(rm.duration) || 0;
  const durSec = rm.duration.endsWith('ms') ? durNum / 1000 : durNum;
  check('减动效媒体查询生效', rm.media);
  check('减动效时过渡被压到近零', durSec <= 0.001, rm.duration);
  check('减动效时平滑滚动关闭', rm.scroll === 'auto', rm.scroll);
  await rmContext.close();

  await context.close();
  await browser.close();
} catch (err) {
  console.error('ERROR:', err?.stack || err);
  failures.push({ name: '运行异常', detail: String(err?.message || err) });
} finally {
  if (server) {
    server.kill();
    await new Promise((r) => setTimeout(r, 300));
  }
}

console.log('');
if (failures.length) {
  console.log(`E2E FAILED: ${failures.length} 项`);
  for (const f of failures) console.log(` - ${f.name}${f.detail ? ': ' + f.detail : ''}`);
  process.exit(1);
}
console.log('ALL E2E PAGES PASSED');
