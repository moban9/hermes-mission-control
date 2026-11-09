'use strict';

const fs = require('node:fs');

function parseSpec(filePath) {
  let parsed;
  try {
    parsed = JSON.parse(fs.readFileSync(filePath, 'utf8'));
  } catch (error) {
    throw new Error(`Invalid panel spec ${filePath}: ${error.message}`, { cause: error });
  }
  if (!Array.isArray(parsed)) throw new Error('Invalid panel spec entry 1: expected a JSON array');
  return parsed.map((entry, index) => {
    const label = `entry ${index + 1}`;
    if (!entry || typeof entry !== 'object' || Array.isArray(entry)) throw new Error(`Invalid panel spec ${label}: expected an object`);
    const { panelName, selector, viewports, tolerancePx = 0, notes = '' } = entry;
    if (typeof panelName !== 'string' || !panelName.trim()) throw new Error(`Invalid panel spec ${label}: panelName must be non-empty`);
    if (typeof selector !== 'string' || !selector.trim()) throw new Error(`Invalid panel spec ${label}: selector must be a non-empty CSS selector`);
    if (!Array.isArray(viewports) || viewports.length === 0 || viewports.some(v => typeof v !== 'string' || !/^\d+x\d+$/.test(v))) throw new Error(`Invalid panel spec ${label}: viewports must contain at least one WIDTHxHEIGHT string`);
    if (!Number.isFinite(tolerancePx) || tolerancePx < 0) throw new Error(`Invalid panel spec ${label}: tolerancePx must be a non-negative number`);
    if (typeof notes !== 'string') throw new Error(`Invalid panel spec ${label}: notes must be a string`);
    return { panelName: panelName.trim(), selector: selector.trim(), viewports: [...viewports], tolerancePx, notes };
  });
}

module.exports = { parseSpec };
