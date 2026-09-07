import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { chromium } from 'playwright';

test('selfhost page exposes unavailable GPU and requests microphone only after connect', async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const context = await browser.newContext({ viewport: { width: 1280, height: 900 }, serviceWorkers: 'block' });
    const page = await context.newPage(), requests = [], errors = [];
    let ready = false;
    page.on('pageerror', error => errors.push(error.message));
    await page.addInitScript(() => {
      window.microphoneRequests = [];
      Object.defineProperty(navigator.mediaDevices, 'getUserMedia', { value: async constraints => {
        window.microphoneRequests.push(constraints);
        throw new DOMException('Permission denied', 'NotAllowedError');
      } });
    });
    await page.route('**/*', async route => {
      const path = new URL(route.request().url()).pathname;
      requests.push(path);
      if (path === '/api/selfhost/health') {
        await route.fulfill({ status: ready ? 200 : 503, contentType: 'application/json',
          body: JSON.stringify(ready ? { ready: true, status: 'ready' }
            : { ready: false, status: 'unconfigured', error: 'GPU 服务未配置' }) });
      } else {
        const files = { '/joi': '../web/joi-selfhost.html', '/studio/joi-selfhost.js': '../web/joi-selfhost.js',
          '/studio/lib/selfhost_client.js': '../web/lib/selfhost_client.js' };
        if (!(path in files)) { await route.abort(); return; }
        await route.fulfill({ contentType: path === '/joi' ? 'text/html' : 'text/javascript',
          body: await readFile(new URL(files[path], import.meta.url), 'utf8') });
      }
    });
    await page.goto('http://127.0.0.1:8899/joi?body=selfhost');
    await page.waitForFunction(() => !document.querySelector('#status').textContent.includes('正在检查'), null, { timeout: 5000 });
    assert.deepEqual(errors, []);
    assert.match(await page.locator('#status').textContent(), /GPU 未配置/);
    assert.equal(await page.locator('#connect').isDisabled(), true);
    assert.equal(await page.locator('img, canvas, iframe').count(), 0);
    assert.equal(await page.locator('#face').evaluate(video => video.srcObject), null);
    assert.deepEqual(await page.evaluate(() => window.microphoneRequests), []);
    if (process.env.SELFHOST_SCREENSHOT) await page.screenshot({ path: process.env.SELFHOST_SCREENSHOT });
    ready = true; await page.locator('#refresh').click();
    await page.waitForFunction(() => !document.querySelector('#connect').disabled, null, { timeout: 5000 })
      .catch(error => { throw new Error(`${error.message}; requests=${JSON.stringify(requests)}; pageErrors=${JSON.stringify(errors)}`); });
    assert.deepEqual(await page.evaluate(() => window.microphoneRequests), []);
    await page.locator('#connect').click();
    await page.waitForFunction(() => document.querySelector('#status').textContent.includes('麦克风许可'));
    const permissions = await page.evaluate(() => window.microphoneRequests);
    assert.equal(permissions.length, 1); assert.equal(permissions[0].video, false);
    assert.equal(requests.some(path => path.includes('tavus') || path.includes('daily') || path.endsWith('/sessions')), false);
    assert.deepEqual(errors, []);
  } finally { await browser.close(); }
});
