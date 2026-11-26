// Fails the build when a page script looks up an element id that the page never renders.
// The Outreach page's el() helper throws on a missing element, so one stale lookup
// stops the whole script and the page loads empty. astro check can't see this.
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';

const root = new URL('../src', import.meta.url).pathname;

function astroFiles(dir) {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return astroFiles(path);
    return path.endsWith('.astro') ? [path] : [];
  });
}

const lookup = /\bel(?:<[^>()]+>)?\(\s*['"`]#([A-Za-z][\w-]*)['"`]\s*\)/g;
let failures = 0;

for (const file of astroFiles(root)) {
  const source = readFileSync(file, 'utf8');
  const ids = new Set([...source.matchAll(/\bid=["']([A-Za-z][\w-]*)["']/g)].map((m) => m[1]));
  const missing = new Set();
  for (const [, id] of source.matchAll(lookup)) {
    if (!ids.has(id)) missing.add(id);
  }
  for (const id of missing) {
    failures += 1;
    console.error(`${relative(root, file)}: script looks up #${id}, but no element has id="${id}"`);
  }
}

if (failures) {
  console.error(`\n${failures} missing element id(s). Remove the stale lookup or add the element.`);
  process.exit(1);
}
console.log('Selector check passed: every el("#id") lookup has a matching element.');
