import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const source = await readFile(new URL('../web/lib/provider_status.js', import.meta.url), 'utf8');
const { summarizeProviderHealth: classify } = await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));
const healthy = { status: 'ok', ready: true, memory: { persistent: true, ready: true },
  providers: [{ provider: 'model-provider', status: 'ok', fallback_active: false }] };
assert.equal(classify(healthy).level, 'ok');
assert.equal(classify({ ...healthy, fallback_active: true }).label, '兜底模式');
assert.equal(classify({ ...healthy, providers: [{ status: 'degraded', fallback_active: true }] }).level, 'fallback');
assert.equal(classify({ ...healthy, status: 'unknown' }).level, 'unknown');
assert.equal(classify({ ...healthy, memory: { persistent: false } }).level, 'unknown');
assert.equal(classify({ ...healthy, memory: { persistent: true, last_error: 'offline' } }).level, 'unknown');
assert.equal(classify({ ...healthy, providers: [] }).level, 'unknown');
assert.equal(classify(healthy, false).label, '大脑未连接');
assert.equal(classify(null).level, 'unknown');
assert.equal(classify({ status: 'unavailable' }).level, 'unknown');
assert.ok(!source.includes('innerHTML'), 'provider/error text must never become HTML');
assert.ok(!source.includes('Authorization'), 'the browser must never send a service token');
for (const page of ['index', 'live', 'joi']) {
  const html = await readFile(new URL(`../web/${page}.html`, import.meta.url), 'utf8');
  assert.ok(html.includes('src="/studio/lib/provider_status.js"'), `${page} has the status indicator`);
}
console.log('Provider status: healthy, fallback, unavailable, memory and safe rendering checks passed.');
