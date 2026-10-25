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

  // ---- 文件抽屉：已存内容的实体入口 ----
  // 设置抽屉还开着，它盖住了导航栏右侧；先关掉再点文件入口（真实用户也是这个顺序）
  if (await page.isVisible('#setPanel')) await page.keyboard.press('Escape');
  await page.waitForTimeout(250);
  // 上面是用接口种的笔记，没走页面里的保存按钮；刷新一次模拟「下次再来」，
  // 否则入口的数量与红点还停在种笔记之前的 0 篇。
  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.waitForFunction(
    () => ((document.getElementById('filesCount') || {}).textContent || '') !== '',
    null, { timeout: 8000 },
  ).catch(() => {});
  check('导航栏有文件入口', await page.isVisible('#filesBtn'));
  check('入口带数量角标', /^\d+\+?$/.test(((await page.locator('#filesCount').textContent()) || '').trim()),
        (await page.locator('#filesCount').textContent()) || '');
  // ---- 小红点：点一下就消，刷新也不回来 ----
  // 抽屉打开时遮罩盖住导航栏，所以这一步必须在抽屉关着的时候做（真实用户也是这样）
  check('有笔记但没备份过时显示提醒点', await page.isVisible('#filesDot'));
  await page.click('#filesDot');
  check('点红点即消除提醒', !(await page.locator('#filesDot').isVisible()));
  await page.reload({ waitUntil: 'domcontentloaded' });
  // 等首屏那次 /api/settings 回来再断言，否则「没出现」可能只是还没加载
  await page.waitForFunction(
    () => ((document.getElementById('filesCount') || {}).textContent || '') !== '',
    null, { timeout: 8000 },
  ).catch(() => {});
  check('刷新后提醒不再回来', !(await page.locator('#filesDot').isVisible()));
  // 复原本地标记，继续验证「导出后也消失」这条路径
  await page.evaluate(() => localStorage.removeItem('rag_dot_off'));
  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(300);

  // ---- 文件抽屉 ----
  await page.click('#filesBtn');
  await page.waitForSelector('.file-item', { timeout: 8000 }).catch(() => {});
  check('文件抽屉已打开', await page.isVisible('#filesPanel'));
  check('列表里有文件', (await page.locator('.file-item').count()) >= 1);
  check('提醒点回到入口上', await page.isVisible('#filesDot'));

  await page.locator('.file-item').first().click();
  await page.waitForFunction(
    () => {
      const el = document.getElementById('filesDetail');
      const text = (el && el.textContent) || '';
      return text.length > 12 && !text.includes('读取中') && !text.includes('从左侧选');
    }, null, { timeout: 6000 },
  );
  const body = await page.locator('#filesDetail').textContent();
  // 不断言具体某句话：列表按时间倒序，种了多条之后第一条会变
  check('点开后能看到正文', (body || '').length > 12, (body || '').slice(0, 40));

  const beforeBackup = (await page.locator('#filesBackup').textContent()) || '';
  check('备份状态文案可读', /还没备份过|上次备份|今天备份/.test(beforeBackup), beforeBackup);

  const [download] = await Promise.all([
    page.waitForEvent('download', { timeout: 8000 }).catch(() => null),
    page.click('#filesExport'),
  ]);
  check('导出真的触发下载', download !== null, download ? download.suggestedFilename() : '无下载事件');
  await page.waitForTimeout(1000);
  check('导出后提醒点消失', !(await page.locator('#filesDot').isVisible()));
  const afterBackup = (await page.locator('#filesBackup').textContent()) || '';
  check('备份文案已更新', /已导出|今天/.test(afterBackup), afterBackup);

  await page.click('#filesClose');
  check('抽屉可以关闭', await page.isHidden('#filesPanel'));

  // HEAD 复用 GET 的处理分支，但不能被当成「下载过」——否则探测一下红点就没了
  const beforeHead = await page.evaluate(
    () => fetch('/api/settings').then((r) => r.json()).then((d) => d.notes.backup.last_export_at));
  await page.evaluate(() => fetch('/api/notes/export', { method: 'HEAD' }));
  const afterHead = await page.evaluate(
    () => fetch('/api/settings').then((r) => r.json()).then((d) => d.notes.backup.last_export_at));
  check('HEAD 探测不算备份', beforeHead === afterHead, `${beforeHead} -> ${afterHead}`);

  // ---- 独立文件页 /files：加不进客户端工具栏时的固定地址 ----
  await page.goto(`${base}/files`, { waitUntil: 'networkidle' });
  await page.waitForSelector('.file-item', { timeout: 8000 }).catch(() => {});
  check('/files 是独立页', await page.isVisible('.pf-grid'));
  check('/files 列出文件', (await page.locator('.file-item').count()) >= 1);
  await page.waitForFunction(
    () => {
      const t = (document.getElementById('pfDetail') || {}).textContent || '';
      return t.length > 12 && !t.includes('读取中') && !t.includes('从左侧选');
    }, null, { timeout: 6000 },
  ).catch(() => {});
  const pfBody = (await page.locator('#pfDetail').textContent()) || '';
  check('/files 默认展开第一篇', pfBody.length > 12, pfBody.slice(0, 40));

  // ---- 安装 ----
  await page.goto(`${base}/ask`, { waitUntil: 'networkidle' });
  await page.click('#setBtn');
  await page.waitForSelector('#setPanel:not([hidden])', { timeout: 6000 });
  await page.click('[data-tab="install"]');
  check('切到安装分区', await page.isVisible('[data-pane="install"]'));
  const mcp = await page.locator('#setMcpPre').textContent();
  check('MCP 配置已生成', (mcp || '').includes('src.notes.mcp_server'), (mcp || '').slice(0, 80));
  const href = await page.getAttribute('#setDownload', 'href');
  check('应用包链接指向 releases', (href || '').includes('/releases'),
        href || '');
  const pluginHref = await page.getAttribute('#setDownloadPlugin', 'href');
  check('插件包链接指向 releases', (pluginHref || '').includes('/releases'),
        pluginHref || '');

  // 检查更新：结果必须落到三种明确状态之一，不能停在「检查中…」
  await page.click('#setUpdate');
  await page.waitForFunction(
    () => /已是最新|发现新版本|连不上|检查失败|出错/
      .test((document.getElementById('setUpdateNote') || {}).textContent || ''),
    null, { timeout: 15000 },
  ).catch(() => {});
  const upd = (await page.locator('#setUpdateNote').textContent()) || '';
  check('检查更新给出明确结果', /已是最新|发现新版本|连不上|检查失败|出错/.test(upd),
        upd.slice(0, 70));

  // ---- 配置写坏时的可见提示 ----
  // 手改 app.json 少个逗号，界面必须说清楚「显示的是默认值」，不能装作密钥丢了
  fs.writeFileSync(path.join(tmp, 'app.json'), '{ 这不是 JSON', 'utf-8');
  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.click('#setBtn');
  await page.waitForFunction(
    () => {
      const el = document.getElementById('setCfgWarn');
      return el && !el.hidden && (el.textContent || '').includes('无法解析');
    }, null, { timeout: 8000 },
  );
  check('配置损坏时给出提示', true);

  await page.click('[data-tab="api"]');
  await page.click('#setSave');
  await page.waitForFunction(
    () => (document.getElementById('setCfgWarn')?.textContent || '').includes('已备份'),
    null, { timeout: 8000 },
  );
  check('覆盖前已备份并告知路径', true);

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
