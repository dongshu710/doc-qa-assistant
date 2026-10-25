/**
 * 设置抽屉端到端：接口 / 存储 / 对话 / 已存 / 安装 五个分区都得真的能点。
 *
 * 为什么要 E2E 而不是只测接口：这些控件是「用户唯一能改配置的入口」，
 * 接口通了但抽屉打不开、tab 切不过去，等于功能不存在。
 *
 * 运行：PYTHON=<python 路径> node tests/e2e_settings.mjs
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
let base = null;
let browser = null;

try {
  const port = await freePort();
  base = `http://127.0.0.1:${port}`;
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'rag-settings-e2e-'));
  const py = process.env.PYTHON || 'python';
  const env = { ...process.env, PYTHONUTF8: '1', PYTHONPATH: ROOT, RETRIEVAL: 'vector',
                NOTE_HOME: path.join(tmp, 'notes'), APP_CONFIG: path.join(tmp, 'app.json'),
                // 原生目录框会真的弹窗并卡住无头测试；关掉后走「返回可读提示」分支
                SETTINGS_PICKER: 'off' };
  delete env.LLM_API_KEY;
  delete env.DEEPSEEK_API_KEY;
  const logPath = path.join(ROOT, 'tests', 'e2e-settings-server.log');
  const fd = fs.openSync(logPath, 'w');
  server = spawn(py, ['-m', 'src.server', '--host', '127.0.0.1', '--port', String(port)], {
    cwd: ROOT, env, stdio: ['ignore', fd, fd],
  });
  server.on('exit', (code) => { if (code) console.error(`server exited ${code}; log: ${logPath}`); });

  const health = await waitHealth(base);
  console.log(`服务就绪 ${base} · ${health.chunks} 块 · ${health.version}`);

  browser = await launchBrowser();
  const page = await browser.newPage({ viewport: { width: 1180, height: 820 } });
  const errors = [];
  const calls = [];
  page.on('console', (msg) => { if (msg.type() === 'error') errors.push(msg.text()); });
  page.on('pageerror', (err) => errors.push(String(err)));
  page.on('response', (r) => {
    if (r.url().includes('/api/settings')) calls.push(`${r.request().method()} ${r.status()}`);
  });

  await page.goto(`${base}/ask`, { waitUntil: 'networkidle' });

  check('导航有设置按钮', await page.isVisible('#setBtn'));
  check('设置面板默认隐藏', !(await page.isVisible('#setPanel')));

  await page.click('#setBtn');
  await page.waitForSelector('#setPanel', { state: 'visible', timeout: 5000 });
  check('点设置后面板打开', await page.isVisible('#setPanel'));
  check('默认停在接口分区', await page.isVisible('[data-pane="api"]'));

  // ---- 接口 ----
  check('接口地址已回显默认值', (await page.inputValue('#setBase')).includes('http') ||
        (await page.getAttribute('#setBase', 'placeholder')) !== null);
  await page.fill('#setBase', 'https://api.example.com/v1');
  await page.fill('#setModel', 'demo-model');
  await page.click('#setSave');
  await page.waitForTimeout(1500);
  const saveNote = (await page.locator('#setApiNote').textContent()) || '';
  check('保存接口配置有成功反馈', saveNote.includes('已保存'),
        `${saveNote} | ${calls.join(',')} | ${errors.join(' / ')}`);
  const saved = await (await fetch(`${base}/api/settings`)).json();
  check('保存后的地址已落到服务端', saved.llm.base_url === 'https://api.example.com/v1');
  check('保存后的模型已落到服务端', saved.llm.model === 'demo-model');

  // ---- 存储 ----
  // 先在旧位置留一篇，切换后才有的可搬——迁移提示要靠它才有内容
  const oldHome = (await (await fetch(`${base}/api/settings`)).json()).notes.home_effective;
  const seedOld = await fetch(`${base}/api/notes`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ messages: [
      { role: 'user', text: '旧位置的一篇' },
      { role: 'assistant', text: '切换后应该能搬过去。' },
    ] }),
  });
  check('旧位置先有一篇笔记', seedOld.status === 201, `HTTP ${seedOld.status}`);

  await page.click('[data-tab="store"]');
  check('切到存储分区', await page.isVisible('[data-pane="store"]'));
  await page.click('[data-home="custom"]');
  check('选自定义后出现目录输入框', await page.isVisible('#setHomeWrap'));
  check('目录旁有原生选择按钮', await page.isVisible('#setPick'));

  const pickRes = await (await fetch(`${base}/api/settings/pick-folder`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}',
  })).json();
  check('选择器不可用时给结构化提示', pickRes.ok === false && pickRes.error === 'disabled',
        JSON.stringify(pickRes));

  await page.click('#setPick');
  await page.waitForTimeout(600);
  const pickNote = (await page.locator('#setHomeNote').textContent()) || '';
  check('点选择按钮不会静默失败', /已关闭|手动填/.test(pickNote), pickNote);

  const target = fs.mkdtempSync(path.join(os.tmpdir(), 'rag-notes-'));
  await page.fill('#setHome', target);
  await page.click('#setHomeSave');
  await page.waitForFunction(
    (t) => (document.getElementById('setHomeNote')?.textContent || '').includes(t.slice(-8)),
    target, { timeout: 8000 },
  );
  check('切换存储位置有反馈', true);

  await page.waitForSelector('#setMigrate:not([hidden])', { timeout: 5000 }).catch(() => {});
  check('切换后提示可以把旧笔记搬过来', await page.isVisible('#setMigrate'));
  const migText = (await page.locator('#setMigrateText').textContent()) || '';
  check('提示里带篇数', /\d+\s*篇/.test(migText), migText);
  await page.click('#setMigrateGo');
  await page.waitForTimeout(1200);
  const migrated = fs.existsSync(path.join(target, 'notes'))
    && fs.readdirSync(path.join(target, 'notes'), { recursive: true })
      .some((f) => String(f).endsWith('.md'));
  check('旧笔记已复制到新位置', migrated, target);
  check('迁移后提示条收起', !(await page.isVisible('#setMigrate')));
  check('旧位置仍在（复制不是移动）', fs.existsSync(oldHome));
  const moved = await (await fetch(`${base}/api/settings`)).json();
  check('服务端已采用新位置', moved.notes.home_effective.startsWith(target));
  check('新位置目录已创建', fs.existsSync(target));

  // ---- 对话 ----
  await page.click('[data-tab="chat"]');
  check('切到对话分区', await page.isVisible('[data-pane="chat"]'));
  check('储存开关默认关闭', !(await page.isChecked('#setStoreChat')));
  // 开关只约束「问答页沉淀」这条路径；智能体显式保存不该被连坐
  const blocked = await fetch(`${base}/api/notes`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ from: 'chat', messages: [
      { role: 'user', text: '会被拦下的一轮' },
      { role: 'assistant', text: '不该落盘。' },
    ] }),
  });
  check('关闭时对话保存被拒', blocked.status === 403, `HTTP ${blocked.status}`);
  const agentPath = await fetch(`${base}/api/notes`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ messages: [
      { role: 'user', text: '智能体直接写入' },
      { role: 'assistant', text: '这条应该成功。' },
    ] }),
  });
  check('关闭时智能体保存不受影响', agentPath.status === 201, `HTTP ${agentPath.status}`);
  // 开关的 input 是视觉隐藏的（只留轨道），点 label 才是用户真实动作
  await page.click('.set-switch');
  await page.waitForFunction(
    () => (document.getElementById('setChatNote')?.textContent || '').includes('已开启'),
    null, { timeout: 8000 },
  );
  const chatOn = await (await fetch(`${base}/api/settings`)).json();
  check('开关状态已落到服务端', chatOn.notes.store_chat === true);

  // 开启后才能存：这条顺序本身就验证了「关闭时不让存」
  const seeded = await fetch(`${base}/api/notes`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ messages: [
      { role: 'user', text: '稳盈系列起购金额多少？' },
      { role: 'assistant', text: '起购金额 1 元，风险等级 R1。' },
    ] }),
  });
  check('开启后可以保存笔记', seeded.status === 201, `HTTP ${seeded.status}`);

  // ---- 已存 ----
  await page.click('[data-tab="save"]');
  await page.waitForSelector('.set-note-item', { timeout: 8000 }).catch(() => {});
  check('已存列表出现笔记', (await page.locator('.set-note-item').count()) >= 1);
  check('已存分区有导出入口', await page.isVisible('#setNotesExport'));

  // ---- 备份提醒 ----
  check('有笔记但没备份过时显示提醒点', await page.isVisible('#setDot'));
  const beforeBackup = (await page.locator('#setBackupNote').textContent()) || '';
  check('备份状态文案可读', /还没备份过|上次备份|今天备份/.test(beforeBackup), beforeBackup);

  const [download] = await Promise.all([
    page.waitForEvent('download', { timeout: 8000 }).catch(() => null),
    page.click('#setNotesExport'),
  ]);
  check('导出真的触发下载', download !== null, download ? download.suggestedFilename() : '无下载事件');
  await page.waitForTimeout(1000);
  check('导出后提醒点消失', !(await page.locator('#setDot').isVisible()));
  const afterBackup = (await page.locator('#setBackupNote').textContent()) || '';
  check('备份文案更新为今天', afterBackup.includes('今天'), afterBackup);
  await page.locator('.set-note-item').first().click();
  // 展开是异步取全文：等到不是「加载中…」才算数，否则断言打在占位文案上
  await page.waitForFunction(
    () => {
      const el = document.querySelector('.set-note-view');
      const text = (el && el.textContent) || '';
      return el && !el.hidden && text.length > 0 && text !== '加载中…';
    }, null, { timeout: 6000 },
  );
  const body = await page.locator('.set-note-view').first().textContent();
  // 不断言具体某句话：列表顺序按时间倒序，种了多条之后第一条会变
  check('展开后能看到正文', (body || '').length > 8 && !(body || '').includes('加载中'),
        (body || '').slice(0, 60));

  // ---- 安装 ----
  await page.click('[data-tab="install"]');
  check('切到安装分区', await page.isVisible('[data-pane="install"]'));
  const mcp = await page.locator('#setMcpPre').textContent();
  check('MCP 配置已生成', (mcp || '').includes('src.notes.mcp_server'), (mcp || '').slice(0, 80));
  const href = await page.getAttribute('#setDownload', 'href');
  check('下载链接指向 releases', (href || '').includes('/releases/latest'), href || '');

  // ---- 关闭 ----
  await page.keyboard.press('Escape');
  check('Esc 关闭面板', !(await page.isVisible('#setPanel')));

  // ---- 精简 ----
  const keybarHidden = await page.locator('#keyBar').getAttribute('hidden');
  check('Key 输入条默认收起', keybarHidden !== null);

  check('页面无脚本报错', errors.length === 0, errors.slice(0, 2).join(' | '));

  console.log(`\n${failures.length ? 'FAILED' : 'E2E SETTINGS OK'}（${failures.length} 项失败）`);
} catch (err) {
  console.error('E2E 异常：', err);
  failures.push({ name: 'exception', detail: String(err) });
} finally {
  if (browser) await browser.close().catch(() => {});
  if (server) server.kill();
}

process.exit(failures.length ? 1 : 0);
