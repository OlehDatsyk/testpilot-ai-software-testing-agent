// Capture genuine screenshots of a running TestPilot instance into docs/screenshots/.
//
// Prerequisites:
//   * API on http://localhost:8000, worker running, frontend on http://localhost:5173
//   * EXECUTION_PROVIDER=docker with the runner image built (for real run screenshots)
//   * Microsoft Edge or Google Chrome installed (no browser download needed)
//
// Usage (from the repository root):
//   node scripts/capture-screenshots.mjs [msedge|chrome]
//
// The script drives the REAL API to set up the demo workflow (local demo account,
// demo project, generate + approve tests, execute runs, bug reports, QA report)
// and then photographs the real UI. Nothing is mocked: if execution is
// unavailable the screenshots show exactly that.
import { createRequire } from 'node:module';
import { mkdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const require = createRequire(join(dirname(fileURLToPath(import.meta.url)), '../frontend/package.json'));
const { chromium } = require('playwright-core');

const API = process.env.TESTPILOT_API ?? 'http://localhost:8000';
const WEB = process.env.TESTPILOT_WEB ?? 'http://localhost:5173';
const OUT = join(dirname(fileURLToPath(import.meta.url)), '..', 'docs', 'screenshots');
// Local-only demo credentials, used solely against a local development instance.
const DEMO = { email: 'screenshots@example.com', password: 'ScreenShot2026', name: 'Demo Reviewer' };

async function call(method, path, token, body) {
  const res = await fetch(API + path, {
    method,
    headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (res.status === 409 || res.status === 401) return { _status: res.status };
  if (!res.ok) throw new Error(`${method} ${path} -> ${res.status} ${await res.text()}`);
  return res.status === 204 ? null : res.json();
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function waitJob(token, id, timeout = 300_000) {
  const end = Date.now() + timeout;
  while (Date.now() < end) {
    const j = await call('GET', `/api/jobs/${id}`, token);
    if (!['queued', 'preparing', 'running'].includes(j.status)) return j;
    await sleep(1500);
  }
  throw new Error(`job ${id} did not finish — is the worker running?`);
}

async function setup() {
  let r = await call('POST', '/api/auth/register', null, DEMO);
  if (r._status === 409) r = await call('POST', '/api/auth/login', null, { email: DEMO.email, password: DEMO.password });
  const token = r.access_token;
  const projects = (await call('GET', '/api/projects', token)).items;
  let demo = projects.find((p) => p.is_demo);
  const runs = {};
  if (!demo) {
    demo = await call('POST', '/api/projects/demo', token);
    const pid = demo.id;
    for (let i = 0; i < 2; i++) for (const j of await call('GET', `/api/projects/${pid}/jobs`, token)) await waitJob(token, j.id);
    await waitJob(token, (await call('POST', `/api/projects/${pid}/generate`, token, {})).id);
    const tests = (await call('GET', `/api/projects/${pid}/generated-tests?page_size=200`, token)).items;
    const approve = tests.slice(1).map((t) => t.id); // leave one in the review queue for the screenshots
    await call('POST', `/api/projects/${pid}/generated-tests/review`, token, { ids: approve, status: 'approved' });
    for (const lang of ['JavaScript', 'Python']) { // Python last, so the latest run shows real failures
      const fam = tests.filter((t) => approve.includes(t.id) && (t.language === 'Python') === (lang === 'Python')).map((t) => t.id);
      const run = await call('POST', `/api/projects/${pid}/runs`, token, { language: lang, include_existing: true, generated_test_ids: fam });
      await waitJob(token, run.job_id);
      runs[lang] = run.id;
    }
    const res = await call('GET', `/api/projects/${pid}/runs/${runs.Python}/results`, token);
    const failed = res.filter((x) => x.status === 'failed' || x.status === 'error');
    if (failed.length) await call('POST', `/api/projects/${pid}/bugs/from-source`, token, { source_type: 'test_result', source_id: failed[0].id });
    const f = (await call('GET', `/api/projects/${pid}/findings?severity=medium`, token)).items;
    if (f.length) await call('POST', `/api/projects/${pid}/bugs/from-source`, token, { source_type: 'finding', source_id: f[0].id });
    await waitJob(token, (await call('POST', `/api/projects/${pid}/reports`, token, { run_id: runs.Python })).id);
  } else {
    for (const run of (await call('GET', `/api/projects/${demo.id}/runs`, token)).items.reverse()) runs[run.language] = run.id;
  }
  return { token, pid: demo.id, runs };
}

const { token, pid, runs } = await setup();
mkdirSync(OUT, { recursive: true });
const browser = await chromium.launch({ channel: process.argv[2] ?? 'msedge' });
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1, colorScheme: 'dark' });
const page = await ctx.newPage();
await page.goto(WEB + '/login');
await page.evaluate(([t, p]) => { localStorage.setItem('testpilot.token', t); localStorage.setItem('testpilot.project', String(p)); }, [token, pid]);

async function shot(path, name, before) {
  await page.goto(WEB + path);
  await page.waitForLoadState('networkidle');
  await page.waitForTimeout(900);
  if (before) { await before(); await page.waitForTimeout(700); }
  await page.screenshot({ path: join(OUT, name) });
  console.log('saved', name);
}

await shot('/', 'dashboard.png');
await shot('/projects', 'projects.png');
await shot('/analysis', 'repository-analysis.png');
await shot('/analysis', 'static-analysis.png', async () => {
  await page.getByRole('tab', { name: 'Static analysis findings' }).click();
  await page.waitForTimeout(600);
  await page.locator('li > button[aria-expanded]').nth(1).click();
});
await shot('/generation', 'test-generation.png', async () => {
  await page.getByLabel('Review status').selectOption('');
  await page.waitForTimeout(700);
  await page.getByText('test_average_price_handles_empty_list_prices', { exact: true }).click();
});
await shot('/runs', 'test-approval.png', async () => { await page.getByRole('button', { name: 'New test run' }).click(); });
await shot('/runs', 'test-execution.png');
await shot(`/runs/${runs.Python}`, 'test-results.png');
await shot(`/runs/${runs.Python}`, 'failure-analysis.png', async () => {
  await page.getByText('test_average_price_handles_empty_list_prices', { exact: true }).click();
  await page.waitForTimeout(500);
  await page.getByText('Rule-based explanation').scrollIntoViewIfNeeded();
});
await shot('/coverage', 'coverage-dashboard.png');
await shot('/bugs', 'bug-reports.png', async () => { await page.locator('main ul button').last().click(); });
await shot('/reports', 'reports.png');
await shot('/assistant', 'ai-assistant.png', async () => {
  await page.getByRole('button', { name: 'Why did the tests fail?', exact: true }).click();
  await page.waitForTimeout(1500);
});
await shot('/settings', 'settings.png');
await browser.close();
