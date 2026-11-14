// Pure-state regression checks for the LIVE Boxes module; no DOM/browser mocks.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const source = fs.readFileSync(path.join(__dirname, '../static/js/main.js'), 'utf8');
const start = source.indexOf('const BoxState =');
const end = source.indexOf('\n};', source.indexOf('serialize(list, W, H)')) + 3;
assert.ok(start >= 0 && end > start, 'Live Boxes module must be located');
const context = {};
vm.runInNewContext(source.slice(start, end) + '; globalThis.Boxes = Boxes;', context);
const boxes = context.Boxes;
const detection = {id: 'model', cls: 0, x: 10, y: 10, w: 20, h: 20, conf: .9};
let checks = 0;
function check(name, fn) { fn(); checks++; console.log('PASS ' + name); }
check('legacy boxes remain confirmed', () => assert.equal(boxes.isConfirmed({...detection}), true));
check('null background labels survive empty autosaves but allow human annotations', () => {
  assert.equal(boxes.preservesNull(true, []), true);
  assert.equal(boxes.preservesNull(true, [{...detection, st: 'rejected'}]), true);
  assert.equal(boxes.preservesNull(true, [{...detection, st: 'confirmed'}]), false);
  assert.equal(boxes.preservesNull(false, []), false);
});
check('review never changes overlapping human work', () => {
  const human = {...detection, x: 11, st: 'confirmed'};
  const result = boxes.reconcile([human], [detection]);
  assert.equal(result.boxes.length, 1);
  assert.equal(human.x, 11);
  assert.equal(result.summary.skippedConfirmed, 1);
});
check('repeated review refreshes suggestions without duplication', () => {
  const first = boxes.reconcile([], [detection]);
  const next = boxes.reconcile(first.boxes, [{...detection, x: 11}]);
  assert.equal(next.boxes.length, 1);
  assert.equal(next.boxes[0].st, 'suggested');
  assert.equal(next.boxes[0].x, 11);
});
check('rejection survives persisted state and suppresses reruns', () => {
  const suggestion = {...detection, st: 'suggested'};
  boxes.reject(suggestion);
  const restored = JSON.parse(JSON.stringify([suggestion]));
  assert.equal(boxes.reconcile(restored, [detection]).summary.skippedRejected, 1);
  assert.equal(boxes.reconcileAutoSave(restored, [detection]).summary.skippedRejected, 1);
  assert.equal(boxes.visible(restored).length, 0);
});
check('human acceptance clears model confidence and exports confirmation', () => {
  const suggestion = {...detection, st: 'suggested'};
  assert.equal(boxes.accept(suggestion), true);
  assert.equal(suggestion.conf, undefined);
  assert.equal(boxes.serialize([suggestion], 100, 100)[0].state, 'confirmed');
});
check('transient pending prompts do not serialize; rejected prompts do', () => {
  const suggestion = {...detection, st: 'suggested', _transient: true};
  assert.equal(boxes.serialize([suggestion], 100, 100).length, 0);
  boxes.reject(suggestion);
  assert.equal(boxes.serialize([suggestion], 100, 100)[0].state, 'rejected');
});
check('auto-approve updates existing geometry and promotes suggestions', () => {
  const suggestion = {...detection, st: 'suggested'};
  const result = boxes.reconcileAutoSave([suggestion], [{...detection, x: 11}]);
  assert.equal(result.boxes.length, 1);
  assert.equal(suggestion.st, 'confirmed');
  assert.equal(suggestion.x, 11);
});
check('wire coordinates normalize to image dimensions', () => {
  const wire = boxes.serialize([{...detection, st: 'confirmed'}], 100, 200)[0];
  assert.equal(wire.x_center, .2);
  assert.equal(wire.y_center, .1);
  assert.equal(wire.width, .2);
  assert.equal(wire.height, .1);
  assert.equal(boxes.serialize([detection], 0, 100).length, 0);
});
console.log(`${checks} lifecycle checks passed. Browser canvas interactions are not covered.`);
