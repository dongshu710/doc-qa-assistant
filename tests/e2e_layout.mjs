/**
 * 布局端到端：验证「像 DeepSeek 的那一套」真的能用，而不只是看起来像。
 *
 * 覆盖四件事：
 * 1. 左侧常驻栏：收起 / 展开、刷新后保持、移动端抽屉；
 * 2. 多会话：新建、切换、搜索、删除，切回去正文还在；
 * 3. 设置弹窗：居中、分区切换、接口三步说明；
 * 4. 存储：占用数字有值，清理按钮能返回结果。
 *
 * 运行：PYTHON=<python 路径> node tests/e2e_layout.mjs
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
    console.log('SKIP: 未安装 playwright/playwright-core');
    process.exit(0);
  }
  const { chromium } = pw.mod;
  const attempts = [
    { channel: 'msedge' }, { channel: 'chrome' }, {},
    { executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe' },
    { executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe' },
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
let browser = null;

try {
  const port = await freePort();
  const base = `http://127.0.0.1:${port}`;
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'rag-layout-e2e-'));
  const py = process.env.PYTHON || 'python';
  const env = { ...process.env, PYTHONUTF8: '1', PYTHONPATH: ROOT,
                NOTE_HOME: path.join(tmp, 'notes'), APP_CONFIG: path.join(tmp, 'app.json'),
                SETTINGS_PICKER: 'off' };
  delete env.LLM_API_KEY;
  delete env.DEEPSEEK_API_KEY;
  const logPath = path.join(ROOT, 'tests', 'e2e-layout-server.log');
  const fd = fs.openSync(logPath, 'w');
  server = spawn(py, ['-m', 'src.server', '--host', '127.0.0.1', '--port', String(port)], {
    cwd: ROOT, env, stdio: ['ignore', fd, fd],
  });
  server.on('exit', (code) => { if (code) console.error(`server exited ${code}; log: ${logPath}`); });

  const health = await waitHealth(base);
  console.log(`服务就绪 ${base} · ${health.version}`);

  browser = await launchBrowser();
  const page = await browser.newPage({ viewport: { width: 1280, height: 860 } });
  const errors = [];
  page.on('console', (msg) => { if (msg.type() === 'error') errors.push(msg.text()); });
  page.on('pageerror', (err) => errors.push(String(err)));

  // ---------- 侧栏 ----------
  await page.goto(`${base}/ask?new=1`, { waitUntil: 'networkidle' });
  check('左侧常驻栏出现', await page.isVisible('#sideBar'));
  const width = await page.evaluate(() => document.getElementById('sideBar').getBoundingClientRect().width);
  check('侧栏宽度约 260', width >= 250 && width <= 275, String(width));
  check('空态在中间显示问候', await page.isVisible('#hero h1'));

  await page.click('#sideMini');
  await page.waitForTimeout(300);
  const mini = await page.evaluate(() => document.body.classList.contains('side-mini'));
  const miniWidth = await page.evaluate(() => document.getElementById('sideBar').getBoundingClientRect().width);
  check('收起后进入 mini 态', mini && miniWidth <= 70, `${mini} / ${miniWidth}`);
  await page.reload({ waitUntil: 'networkidle' });
  check('收起状态刷新后保持',
    await page.evaluate(() => document.body.classList.contains('side-mini')));
  await page.click('#sideMini');
  await page.waitForTimeout(250);

  // ---------- 多会话 ----------
  await page.fill('#q', '大额存单的具体标准是多少？');
  await page.keyboard.press('Enter');
  await page.waitForFunction(
    () => (document.getElementById('tbTitle') || {}).textContent !== '新对话',
    null, { timeout: 20000 },
  ).catch(() => {});
  check('回答后标题变成问题', (await page.locator('#tbTitle').textContent())?.includes('大额存单'),
        await page.locator('#tbTitle').textContent());
  check('空态已让位给对话', !(await page.isVisible('#hero')));
  check('侧栏出现一条会话', (await page.locator('.conv').count()) === 1);

  await page.click('#newChat');
  await page.waitForTimeout(400);
  check('新对话回到空态', await page.isVisible('#hero h1'));
  check('侧栏变成两条会话', (await page.locator('.conv').count()) === 2);
  check('顶栏标题复位', (await page.locator('#tbTitle').textContent()) === '新对话');

  // 切回第一条，正文要还在
  await page.locator('.conv').nth(1).click();
  await page.waitForTimeout(500);
  const restored = (await page.locator('#list').textContent()) || '';
  check('切回旧会话能看到原文', restored.includes('20 万元'), restored.slice(0, 40));
  check('切回后标题同步', (await page.locator('#tbTitle').textContent())?.includes('大额存单'));

  // 搜索
  await page.fill('#convSearch', '不存在的关键词');
  await page.waitForTimeout(250);
  check('搜索无结果给出提示', (await page.locator('#convList').textContent())?.includes('没有匹配'));
  await page.fill('#convSearch', '大额');
  await page.waitForTimeout(250);
  check('搜索按标题过滤', (await page.locator('.conv').count()) === 1);
  await page.fill('#convSearch', '');
  await page.waitForTimeout(200);

  // 删除（确认框直接接受）
  page.once('dialog', (d) => d.accept());
  await page.locator('.conv').first().hover();
  await page.locator('.conv .x').first().click();
  await page.waitForTimeout(400);
  check('删除后只剩一条', (await page.locator('.conv').count()) === 1);

  // ---------- 设置弹窗 ----------
  await page.click('#setBtn');
  await page.waitForSelector('#setPanel:not([hidden])', { timeout: 6000 });
  const panel = await page.evaluate(() => {
    const el = document.getElementById('setPanel');
    const r = el.getBoundingClientRect();
    const cs = getComputedStyle(el);
    return { display: cs.display, left: r.left, right: window.innerWidth - r.right,
             top: r.top, width: r.width, height: r.height };
  });
  check('设置是居中弹窗', panel.display === 'grid' && Math.abs(panel.left - panel.right) < 6,
        JSON.stringify(panel));
  check('弹窗有固定高度', panel.height > 420 && panel.height < 900, String(panel.height));

  const apiText = (await page.locator('#apiState').textContent()) || '';
  check('接口分区给出当前状态', apiText.includes('未接入模型'), apiText.slice(0, 40));
  check('接口步骤写了三步', (await page.locator('.api-steps li').count()) === 3);
  check('保存按钮写明会启用', (await page.locator('#setSave').textContent())?.includes('启用'));

  await page.click('[data-tab="store"]');
  await page.waitForTimeout(400);
  const st = await page.evaluate(() => ({
    kb: (document.getElementById('stKb') || {}).textContent,
    notes: (document.getElementById('stNotes') || {}).textContent,
    index: (document.getElementById('stIndex') || {}).textContent,
    free: (document.getElementById('stFree') || {}).textContent,
    keep: (document.getElementById('stKeep') || {}).value,
  }));
  check('知识库占用有数字', !!st.kb && st.kb !== '—', st.kb);
  check('笔记占用有数字', !!st.notes && st.notes !== '—', st.notes);
  check('磁盘剩余有数字', !!st.free && st.free !== '—', st.free);
  check('保留版本可配置', st.keep === '30', st.keep);

  await page.click('#stClean');
  await page.waitForFunction(
    () => /已清理|清理失败/.test((document.getElementById('stMsg') || {}).textContent || ''),
    null, { timeout: 20000 },
  ).catch(() => {});
  const stMsg = (await page.locator('#stMsg').textContent()) || '';
  check('清理给出明确结果', /已清理|清理失败/.test(stMsg), stMsg.slice(0, 60));

  await page.keyboard.press('Escape');
  check('Esc 关闭设置', !(await page.isVisible('#setPanel')));

  // ---------- 移动端 ----------
  await page.setViewportSize({ width: 390, height: 844 });
  await page.waitForTimeout(300);
  const offscreen = await page.evaluate(() => document.getElementById('sideBar').getBoundingClientRect().right <= 1);
  check('移动端侧栏默认收起', offscreen);
  await page.click('#sideOpen');
  await page.waitForTimeout(350);
  const opened = await page.evaluate(() => ({
    open: document.body.classList.contains('side-open'),
    left: document.getElementById('sideBar').getBoundingClientRect().left,
  }));
  check('点按钮滑出侧栏', opened.open && opened.left >= 0, JSON.stringify(opened));
  // 遮罩被侧栏盖住一半，点它的几何中心会落在侧栏上；真实用户点的是右侧空白区
  await page.mouse.click(370, 420);
  await page.waitForTimeout(300);
  check('点遮罩收起侧栏',
    await page.evaluate(() => !document.body.classList.contains('side-open')));

  check('控制台无报错', errors.length === 0, errors.slice(0, 2).join(' | '));

  console.log(`\n完成：${failures.length ? `${failures.length} 项失败` : '全部通过'}`);
  if (failures.length) {
    console.log(JSON.stringify(failures, null, 1));
    process.exitCode = 1;
  }
} catch (err) {
  console.error('E2E 崩溃：', err);
  process.exitCode = 1;
} finally {
  if (browser) await browser.close().catch(() => {});
  if (server) server.kill();
}

