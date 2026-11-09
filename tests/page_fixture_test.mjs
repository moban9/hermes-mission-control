import assert from 'node:assert/strict';
import { newPage } from './new_page.mjs';

const results = [];
function report(name, fn) {
  fn();
  results.push(name);
  console.log(`PASS ${name}`);
}

report('full page script evaluates successfully', () => {
  const page = newPage();
  assert.doesNotThrow(() => page.run());
  assert.equal(typeof page.drawAll, 'function');
});

report('drawAll paints main sections observable through fixture DOM accessors', () => {
  const page = newPage();
  page.run();
  page.drawAll();
  assert.ok(page.getHTML('orgChart').length > 0, 'org chart should be painted');
  assert.ok(page.getHTML('tasks').length > 0, 'tasks should be painted');
  assert.ok(page.getHTML('tools').length > 0, 'tools should be painted');
  assert.ok(page.paintedSections() >= 3, 'paint accessor should observe painted sections');
});

report('drawTopo failure is isolated while other sections still paint', () => {
  const page = newPage();
  page.run();
  // Replace the page's top-level drawing hook to simulate a renderer failure.
  page.context.drawTopo = () => { throw new Error('forced topology failure'); };
  assert.doesNotThrow(() => page.drawAll());
  assert.ok(page.getHTML('orgChart').length > 0, 'org chart should still paint');
  assert.ok(page.getHTML('tasks').length > 0, 'tasks should still paint');
  assert.ok(page.getHTML('tools').length > 0, 'tools should still paint');
});

report('teardown detects no leaked errors or unhandled rejections', () => {
  const page = newPage();
  page.run();
  page.drawAll();
  assert.doesNotThrow(() => page.h.assertNoLeaks());
});
