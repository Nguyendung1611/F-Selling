const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

const source = fs.readFileSync('static/js/onboarding-r2.js', 'utf8');
const start = source.indexOf('// ONBOARDING_R2_STATE_START');
const end = source.indexOf('// ONBOARDING_R2_STATE_END');
assert(start >= 0 && end > start);
const context = {};
vm.runInNewContext(`${source.slice(start, end)}; this.key = firstRunDismissKey; this.next = firstRunNextAction;`, context);

assert.strictEqual(
  context.key('chu shop a'),
  'fselling.onboarding.r2.dismissed:chu%20shop%20a'
);
assert.strictEqual(context.next([], null), 'shop');
assert.strictEqual(context.next([{ id: 9 }], null), null);
assert.strictEqual(context.next([{ id: 9 }], { product_created: false }), 'product');
assert.strictEqual(context.next([{ id: 9 }], { product_created: true, sale_completed: false }), 'sale');
assert.strictEqual(context.next([{ id: 9 }], { product_created: true, sale_completed: true }), null);
