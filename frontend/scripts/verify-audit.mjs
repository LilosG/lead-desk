import fs from 'node:fs';

const auditPath = process.argv[2];
if (!auditPath) {
  throw new Error('usage: node scripts/verify-audit.mjs <npm-audit.json>');
}

const audit = JSON.parse(fs.readFileSync(auditPath, 'utf8'));
const lock = JSON.parse(fs.readFileSync(new URL('../package-lock.json', import.meta.url), 'utf8'));

// @astrojs/vercel 11.0.10 currently depends on @vercel/routing-utils 6.5.0.
// Vercel intentionally ships path-to-regexp 6.1.0 alongside the patched 6.3.0
// while comparing migration behavior upstream. npm therefore reports the same
// GHSA through all three nodes. There is no supported patched adapter release
// to upgrade to today. We do not override Vercel's dependency graph because
// that would put Lead Desk on an unsupported routing stack.
//
// This exception is deliberately exact and self-expiring: any package/version
// change or any additional vulnerability fails CI and requires review.
const expectedPackages = new Map([
  ['node_modules/@astrojs/vercel', '11.0.10'],
  ['node_modules/@vercel/routing-utils', '6.5.0'],
  ['node_modules/path-to-regexp', '6.1.0'],
  ['node_modules/path-to-regexp-updated', '6.3.0'],
]);

for (const [path, expectedVersion] of expectedPackages) {
  const actualVersion = lock.packages?.[path]?.version;
  if (actualVersion !== expectedVersion) {
    throw new Error(
      `Known Vercel audit exception changed: ${path} expected ${expectedVersion}, found ${actualVersion ?? 'missing'}. Review the dependency chain before merging.`,
    );
  }
}

const vulnerabilities = audit.vulnerabilities ?? {};
const names = Object.keys(vulnerabilities).sort();
const allowedNames = ['@astrojs/vercel', '@vercel/routing-utils', 'path-to-regexp'].sort();

const unexpected = names.filter((name) => !allowedNames.includes(name));
if (unexpected.length > 0) {
  throw new Error(`Unexpected npm audit vulnerabilities: ${unexpected.join(', ')}`);
}

for (const name of names) {
  const item = vulnerabilities[name];
  if (item.severity !== 'high') {
    throw new Error(
      `Audit exception changed for ${name}: expected high severity, found ${item.severity}`,
    );
  }
}

if (vulnerabilities['path-to-regexp']) {
  const advisoryUrls = (vulnerabilities['path-to-regexp'].via ?? [])
    .filter((entry) => typeof entry === 'object' && entry !== null)
    .map((entry) => entry.url)
    .filter(Boolean);
  if (!advisoryUrls.some((url) => String(url).includes('GHSA-9wv6-86v2-598j'))) {
    throw new Error('path-to-regexp audit finding is not the reviewed GHSA-9wv6-86v2-598j exception');
  }
}

const critical = audit.metadata?.vulnerabilities?.critical ?? 0;
if (critical !== 0) {
  throw new Error(`npm audit reports ${critical} critical vulnerabilities`);
}

if (names.length > 0) {
  console.log(
    'PASS npm audit: only the pinned upstream Astro/Vercel GHSA-9wv6-86v2-598j dependency chain remains; no unsupported override applied.',
  );
} else {
  console.log('PASS npm audit: no vulnerabilities reported.');
}
