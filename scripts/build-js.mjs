// Transpiles the TypeScript sources under src/web/static/js to JavaScript in place.
// Each foo.ts becomes foo.js next to it. No bundling: the browser still loads the
// same ES module graph from index.js. Run with `npm run build:js`.
import { readdir } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { build } from 'esbuild';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', 'src/web/static/js');

async function collectTypeScript(dir) {
  const entries = await readdir(dir, { withFileTypes: true });
  const files = [];
  for (const entry of entries) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      if (entry.name !== 'vendor') files.push(...(await collectTypeScript(full)));
    } else if (entry.name.endsWith('.ts') && !entry.name.endsWith('.d.ts')) {
      files.push(full);
    }
  }
  return files;
}

const entryPoints = await collectTypeScript(root);
if (entryPoints.length === 0) {
  console.log('No TypeScript sources found.');
} else {
  await build({
    entryPoints,
    outbase: root,
    outdir: root,
    bundle: false,
    format: 'esm',
    target: 'es2022',
    sourcemap: false,
    logLevel: 'warning',
  });
  console.log(`Transpiled ${entryPoints.length} TypeScript file(s).`);
}
