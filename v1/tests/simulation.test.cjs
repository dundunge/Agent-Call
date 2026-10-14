const { test } = require('node:test');
const assert = require('node:assert/strict');
const { Simulator, TEAM, totalSteps } = require('../agent_team_v1/web/simulation.js');
const fresh = (mode = 'success') => new Simulator({ clock: () => '2026-10-14T12:00:00Z' }).reset('fixture objective', mode);
const complete = (sim) => { while (sim.step()) {} return sim; };

test('a parent cannot finish before all its child results are observed', () => {
  const sim = fresh();
  while (sim.step()) {
    for (const parent of sim.nodes.filter(n => n.outcome === 'completed')) {
      assert.ok(sim.nodes.filter(n => n.parent === parent.id).every(n => n.outcome === 'completed'));
    }
  }
  assert.equal(sim.phase, 'review');
  assert.equal(sim.cursor, totalSteps);
  assert.equal(sim.nodes.length, 7);
  assert.ok(sim.nodes.every(n => n.acceptance === 'passed' || n.id === 'root'));
  assert.equal(sim.node('root').acceptance, 'not_run');
});

test('secondary threads preserve parent family and dispatch only once', () => {
  const sim = complete(fresh());
  for (const child of TEAM.filter(n => n.level === 2)) assert.equal(child.family, sim.node(child.parent).family);
  assert.equal(sim.events.filter(e => e.kind === 'dispatch').length, 6);
  assert.equal(new Set(sim.events.filter(e => e.kind === 'dispatch').map(e => e.childRequestId)).size, 6);
  assert.equal(sim.step(), false);
});

test('uncertain delivery hard stops, reconciles original request, and never resends', () => {
  const sim = fresh('unknown');
  while (sim.step()) {}
  assert.equal(sim.phase, 'blocked');
  const id = sim.node('deepseek-flash').requestId;
  const count = sim.events.length;
  assert.equal(sim.step(), false);
  assert.equal(sim.events.length, count);
  assert.equal(sim.reconcile(), id);
  complete(sim);
  assert.equal(sim.phase, 'review');
  assert.equal(sim.events.filter(e => e.kind === 'dispatch' && e.target === 'deepseek-flash').length, 1);
  assert.equal(sim.events.find(e => e.kind === 'reconciled').reconciledRequestId, id);
});

test('final acceptance requires completed branches and three evidence checks', () => {
  const sim = fresh();
  assert.throws(() => sim.accept(['a', 'b', 'c']), /observed root result/);
  complete(sim);
  assert.throws(() => sim.accept(['a', 'b']), /Three evidence/);
  sim.accept(['hierarchy checked', 'branches collected', 'protocol checked']);
  assert.equal(sim.phase, 'accepted');
  assert.equal(sim.node('root').acceptance, 'passed');
  assert.throws(() => sim.accept(['a', 'b', 'c']), /observed root result/);
});

test('reset cancels state and gives a fresh attempt; exported snapshot cannot mutate runtime', () => {
  const sim = complete(fresh());
  const previous = sim.node('root').requestId;
  const snapshot = sim.snapshot();
  snapshot.nodes[0].state = 'corrupted';
  assert.equal(sim.node('root').state, 'completed');
  sim.reset('new target');
  assert.notEqual(sim.node('root').requestId, previous);
  assert.equal(sim.events.length, 0);
  assert.equal(sim.artifacts.length, 0);
  assert.equal(sim.phase, 'ready');
  assert.ok(sim.nodes.every(n => n.outcome === 'not_started'));
});
