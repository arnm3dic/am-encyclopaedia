#!/usr/bin/env node
/**
 * Build the app, with no dependencies.
 *
 *   node app/build.mjs
 *
 * Node strips the TypeScript itself, so there is nothing to install and no
 * toolchain to keep in step. Import specifiers are rewritten from .ts to .js
 * because browsers resolve what is written, not what was compiled.
 */

import { stripTypeScriptTypes } from "node:module";
import { readdir, readFile, writeFile, mkdir, rm, cp } from "node:fs/promises";
import { existsSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";

const APP = dirname(fileURLToPath(import.meta.url));
const SRC = join(APP, "src");
const DIST = join(APP, "dist");

const SPECIFIER = /(\bfrom\s*|\bimport\s*\(\s*)(["'])([^"']+)\.ts\2/g;

async function* walk(directory) {
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) yield* walk(path);
    else yield path;
  }
}

async function main() {
  await rm(DIST, { recursive: true, force: true });
  await mkdir(DIST, { recursive: true });

  let compiled = 0;
  let copied = 0;

  for await (const path of walk(SRC)) {
    const target = join(DIST, relative(SRC, path));
    await mkdir(dirname(target), { recursive: true });

    if (path.endsWith(".ts")) {
      const source = await readFile(path, "utf8");
      const stripped = stripTypeScriptTypes(source, { mode: "strip" });
      // Type-only imports erase to a bare `import "./x.ts";`, which would make
      // the browser fetch a module for nothing. Drop those lines.
      const cleaned = stripped
        .replace(SPECIFIER, (_m, head, quote, path) => `${head}${quote}${path}.js${quote}`)
        .replace(/^\s*import\s*(["'])[^"']+\1\s*;?\s*$/gm, "");
      await writeFile(target.replace(/\.ts$/, ".js"), cleaned, "utf8");
      compiled += 1;
    } else {
      await cp(path, target);
      copied += 1;
    }
  }

  // Static shell and data sit beside the modules.
  for (const name of ["index.html", "manifest.webmanifest", "sw.js", "icon.svg"]) {
    const from = join(APP, name);
    if (existsSync(from)) {
      await cp(from, join(DIST, name));
      copied += 1;
    }
  }
  // Everything under public/ ships as-is: the data bundle and the cover image.
  const publicDir = join(APP, "public");
  if (existsSync(publicDir)) {
    for (const entry of await readdir(publicDir, { withFileTypes: true })) {
      await cp(join(publicDir, entry.name), join(DIST, entry.name), { recursive: true });
    }
  }

  console.log(`built ${compiled} modules, copied ${copied} files -> ${relative(process.cwd(), DIST)}`);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
