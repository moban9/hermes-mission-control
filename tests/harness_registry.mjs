// Check modules import this function to self-register in the harness registry.
const checks = new Map();
export function registerCheck(name, run, options = {}) {
  if (!/^[a-zA-Z0-9][a-zA-Z0-9._-]*$/.test(name) || typeof run !== 'function') throw new TypeError('registerCheck requires a valid name and run function');
  if (checks.has(name)) throw new Error(`Duplicate check: ${name}`);
  checks.set(name, { name, run, ...options });
}
export function registeredChecks() { return [...checks.values()]; }
export function clearChecks() { checks.clear(); }
