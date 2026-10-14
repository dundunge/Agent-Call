const { test } = require('node:test');
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const { JSDOM } = require('jsdom');
const web = join(__dirname, '../agent_team_v1/web');
function harness() {
  const dom = new JSDOM(readFileSync(join(web, 'index.html'), 'utf8'), { runScripts: 'outside-only', url: 'https://demo.invalid/' });
  const w = dom.window;
  let clock = 0, serial = 0;
  const timers = new Map();
  w.setTimeout = (fn, delay) => { timers.set(++serial, { fn, at: clock + delay }); return serial; };
  w.clearTimeout = (id) => timers.delete(id);
  w.matchMedia = () => ({ matches: false });
  w.HTMLDialogElement.prototype.showModal = function () { this.open = true; };
  w.HTMLDialogElement.prototype.close = function () { this.open = false; };
  let downloads = 0;
  w.URL.createObjectURL = () => 'blob:demo'; w.URL.revokeObjectURL = () => {};
  w.HTMLAnchorElement.prototype.click = function () { downloads++; };
  w.eval(readFileSync(join(web, 'simulation.js'), 'utf8'));
  w.eval(readFileSync(join(web, 'app.js'), 'utf8'));
  function flush(limit = 100) {
    for (let i = 0; i < limit && timers.size; i++) {
      const [id, task] = [...timers.entries()].sort((a, b) => a[1].at - b[1].at)[0];
      timers.delete(id); clock = task.at; task.fn();
    }
  }
  const $ = (q) => w.document.querySelector(q);
  return { dom, w, $, flush, downloads: () => downloads, close: () => dom.window.close() };
}

test('complete UI flow: dispatch, independent child view, pause/resume, and evidence-gated acceptance', () => {
  const h = harness();
  try {
    assert.equal(h.$('#thread-tree').querySelectorAll('[role=treeitem]').length, 7);
    h.$('#play-run').click();
    h.$('#play-run').click();
    assert.equal(h.$('#run-status').textContent, '已暂停');
    h.flush();
    assert.equal(h.$('#run-progress').textContent, '1 / 24');
    h.$('#play-run').click(); h.flush();
    assert.equal(h.$('#run-status').textContent, '执行完成 · 待验收');
    h.$('[data-thread="deepseek-flash"]').click();
    assert.match(h.$('#view-content').textContent, /已整理四项职责/);
    assert.match(h.$('#breadcrumbs').textContent, /主控.*研究.*证据抽取/);
    h.$('[data-inspector="protocol"]').click();
    assert.match(h.$('#inspector-content').textContent, /parentThreadId.*deepseek-pro/s);
    h.$('#play-run').click();
    assert.equal(h.$('#accept-dialog').open, true);
    assert.equal(h.$('#confirm-accept').disabled, true);
    for (const checkbox of h.w.document.querySelectorAll('[name="accept-evidence"]')) {
      checkbox.checked = true;
      checkbox.dispatchEvent(new h.w.Event('change', { bubbles: true }));
    }
    h.$('#confirm-accept').click();
    assert.equal(h.$('#accept-dialog').open, false);
    assert.equal(h.$('#run-status').textContent, '模拟已验收');
    assert.match(h.$('#view-content').textContent, /主控最终验收已记录/);
  } finally { h.close(); }
});

test('unknown scenario blocks playback and can reconcile without a new attempt', () => {
  const h = harness();
  try {
    h.$('#scenario-select').value = 'unknown';
    h.$('#scenario-select').dispatchEvent(new h.w.Event('change', { bubbles: true }));
    h.$('#play-run').click(); h.flush();
    assert.equal(h.$('#run-status').textContent, '送达不明 · 已停止');
    assert.equal(h.$('#play-run').disabled, true);
    h.$('[data-action="reconcile"]').click();
    assert.equal(h.$('#play-run').disabled, false);
    h.$('#play-run').click(); h.flush();
    assert.equal(h.$('#run-status').textContent, '执行完成 · 待验收');
    h.$('[data-view="events"]').click();
    assert.match(h.$('#view-content').textContent, /reconciled/);
  } finally { h.close(); }
});

test('topology, folding, artifacts, export, and prompt escaping are usable', () => {
  const h = harness();
  try {
    h.$('[data-fold="root"]').click();
    assert.equal(h.$('#thread-tree').querySelectorAll('[role=treeitem]').length, 1);
    h.$('[data-fold="root"]').click();
    h.$('#prompt-input').value = '<img src=x onerror=alert(1)>';
    h.$('#send-prompt').click(); h.flush();
    assert.equal(h.$('#view-content').querySelectorAll('img').length, 0);
    assert.match(h.$('#view-content').textContent, /<img src=x/);
    h.$('[data-view="topology"]').click();
    assert.equal(h.$('#view-content').querySelectorAll('.topology-node').length, 7);
    h.$('[data-view="artifacts"]').click();
    assert.equal(h.$('#view-content').querySelectorAll('.artifact-card').length, 7);
    h.$('[data-action="artifact"]').click();
    h.$('[data-view="events"]').click(); h.$('[data-action="export"]').click();
    assert.equal(h.downloads(), 2);
  } finally { h.close(); }
});
