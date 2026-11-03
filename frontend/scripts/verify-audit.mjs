import fs from 'node:fs';

const auditPath = process.argv[2];
if (!auditPath) {
  throw new Error('usage: node scripts/verify-audit.mjs <npm-audit.json>');
}

const audit = JSON.parse(fs.readFileSync(auditPath, 'utf8'));
const lock = JSON.parse(fs.readFileSync(new URL('../package-lock.json', import.meta.url), 'utf8'));

// @astrojs/vercel 11.0.18 is the newest adapter release, and every remaining
// finding sits beneath it. It depends on @vercel/routing-utils 6.6.1, where
// Vercel intentionally ships path-to-regexp 6.1.0 alongside the patched 6.3.0
// while comparing migration behavior upstream, and on @vercel/nft 1.11.0, which
// brings glob 13.0.6 and minimatch 10.2.6. npm's only offered fix is a downgrade
// to adapter 8.1.0, and we do not override Vercel's dependency graph because
// that would put Lead Desk on an unsupported routing stack.
//
// This exception is deliberately exact and self-expiring: any package/version
// change or any additional vulnerability fails CI and requires review.
const expectedPackages = new Map([
  ['node_modules/@astrojs/vercel', '11.0.18'],
  ['node_modules/@vercel/routing-utils', '6.6.1'],
  ['node_modules/@vercel/nft', '1.11.0'],
  ['node_modules/glob', '13.0.6'],
  ['node_modules/minimatch', '10.2.6'],
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
const expectedSeverity = new Map([
  ['@astrojs/vercel', 'high'],
  ['@vercel/routing-utils', 'high'],
  ['path-to-regexp', 'high'],
  ['@vercel/nft', 'moderate'],
  ['glob', 'moderate'],
  ['minimatch', 'moderate'],
]);

const unexpected = names.filter((name) => !expectedSeverity.has(name));
if (unexpected.length > 0) {
  throw new Error(`Unexpected npm audit vulnerabilities: ${unexpected.join(', ')}`);
}

for (const name of names) {
  const item = vulnerabilities[name];
  if (item.severity !== expectedSeverity.get(name)) {
    throw new Error(
      `Audit exception changed for ${name}: expected ${expectedSeverity.get(name)} severity, found ${item.severity}`,
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
    'PASS npm audit: only the pinned upstream Astro/Vercel adapter dependency chain remains; no unsupported override applied.',
  );
} else {
  console.log('PASS npm audit: no vulnerabilities reported.');
}
