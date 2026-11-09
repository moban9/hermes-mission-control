import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const { parseSpec } = require('../harness/spec.js');

function fixture(value) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'mc-panel-spec-'));
  const file = path.join(dir, 'panels.json');
  fs.writeFileSync(file, JSON.stringify(value));
  return { file, cleanup: () => fs.rmSync(dir, { recursive: true, force: true }) };
}

test('parses three panels with defaults and explicit tolerance', () => {
  const f = fixture([
    { panelName: 'KPI row', selector: '#kpis', viewports: ['1440x900', '390x844'] },
    { panelName: 'Agents', selector: '#orgChart', viewports: ['1440x900'] },
    { panelName: 'Alerts', selector: '#alerts', viewports: ['390x844'], tolerancePx: 1, notes: 'Fractional border rounding.' },
  ]);
  try {
    assert.deepEqual(parseSpec(f.file), [
      { panelName: 'KPI row', selector: '#kpis', viewports: ['1440x900', '390x844'], tolerancePx: 0, notes: '' },
      { panelName: 'Agents', selector: '#orgChart', viewports: ['1440x900'], tolerancePx: 0, notes: '' },
      { panelName: 'Alerts', selector: '#alerts', viewports: ['390x844'], tolerancePx: 1, notes: 'Fractional border rounding.' },
    ]);
  } finally { f.cleanup(); }
});

test('names malformed entry in error', () => {
  const f = fixture([{ panelName: 'KPI row', selector: '', viewports: ['1440x900'] }]);
  try { assert.throws(() => parseSpec(f.file), /entry 1.*selector/i); }
  finally { f.cleanup(); }
});
