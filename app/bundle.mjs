/**
 * Build a one-file copy of the encyclopaedia that opens from disk.
 *
 *     node app/bundle.mjs  ->  app/dist/mackey-encyclopaedia.html
 *
 * The published app is a normal site: separate modules, separate data files,
 * a service worker. That needs a server. Opened straight from a folder, a
 * browser refuses to import one module from another and refuses to fetch the
 * data, both for the same origin rule, so the page comes up empty.
 *
 * This builds the same application as a single file with the data inside it.
 * It is the copy to fall back on when the hosted one cannot be reached -- no
 * server, no network, no account, just a file that opens.
 *
 * The modules are not rewritten by hand. Each is wrapped in a function that
 * returns what it exported, and each one's imports become local bindings
 * taken from the module that exported them, which keeps names apart: both
 * reading.js and history.js export something called `load`, and
 * concatenating them would silently leave one of the two.
 */

import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const DIST = fileURLToPath(new URL("dist/", import.meta.url));

/** Dependency order: a module appears after everything it imports. */
const MODULES = [
  "core/normalise.js",
  "core/search/headwords.js",
  "core/search/definitions.js",
  "core/search/engine.js",
  "core/data/load.js",
  "ui/reading.js",
  "ui/history.js",
  "ui/gate.js",
  "ui/app.js",
];

// Adding a module to the application and forgetting it here produces a page
// that throws on load with a name nobody will recognise, and only when
// someone opens the file. Better to fail the build.
{
  const { readdirSync } = await import("node:fs");
  const walk = (dir) => readdirSync(DIST + dir, { withFileTypes: true })
    .flatMap((e) => e.isDirectory() ? walk(dir + e.name + "/")
                  : e.name.endsWith(".js") ? [dir + e.name] : []);
  const built = walk("").filter((f) => f !== "sw.js");
  const missing = built.filter((f) => !MODULES.includes(f));
  if (missing.length) {
    throw new Error(`bundle.mjs does not list: ${missing.join(", ")}`);
  }
}

const nameOf = (path) => "M_" + path.replace(/[./]/g, "_");

/** The names a module exports, read from its own source. */
function exportsOf(source) {
  const names = new Set();
  for (const m of source.matchAll(
    /^export\s+(?:async\s+)?(?:function|class|const|let|var)\s+([A-Za-z_$][\w$]*)/gm)) {
    names.add(m[1]);
  }
  for (const m of source.matchAll(/^export\s*\{([^}]*)\}/gm)) {
    for (const part of m[1].split(",")) {
      const name = part.trim().split(/\s+as\s+/).pop().trim();
      if (name) names.add(name);
    }
  }
  return [...names];
}

/** Turn each import into a const taken from the module that exported it. */
function bindings(source, here) {
  const lines = [];
  const resolve = (specifier) => {
    const url = new URL(specifier, "file:///" + here);
    return nameOf(url.pathname.replace(/^\/+/, ""));
  };
  for (const m of source.matchAll(
    /^import\s+(?:\*\s+as\s+([\w$]+)|\{([^}]*)\})\s+from\s+"([^"]+)";?$/gm)) {
    const [, star, named, specifier] = m;
    if (star) {
      lines.push(`const ${star} = ${resolve(specifier)};`);
    } else {
      const names = named.split(",").map((s) => s.trim()).filter(Boolean).join(", ");
      lines.push(`const { ${names} } = ${resolve(specifier)};`);
    }
  }
  return lines.join("\n");
}

function wrap(path) {
  const source = readFileSync(DIST + path, "utf8");
  const names = exportsOf(source);
  const body = source
    .replace(/^import\s+[^;]*;?$/gm, "")
    // The data loader resolves its URLs from the module's own address, which
    // a one-file page has no equivalent of and does not need, since the data
    // is already here. A classic script may not even mention import.meta.
    .replace(/import\.meta\.url/g, "location.href")
    .replace(/^export\s*\{[^}]*\};?$/gm, "")
    .replace(/^export\s+/gm, "");
  return `const ${nameOf(path)} = (() => {
${bindings(source, path)}
${body}
return { ${names.join(", ")} };
})();`;
}

// The one image the page shows comes along as a data URL; a single file has
// nowhere to keep a picture beside it.
const titlePage =
  "data:image/png;base64," + readFileSync(DIST + "img/title-page.png").toString("base64");

const data = {
  headwords: readFileSync(DIST + "data/headwords.json", "utf8"),
  entries: readFileSync(DIST + "data/entries.json", "utf8"),
  meta: readFileSync(DIST + "data/meta.json", "utf8"),
};

const page = readFileSync(DIST + "index.html", "utf8");
const styles = readFileSync(DIST + "ui/styles.css", "utf8");

// The loader fetches three files; here they are already in the page, so its
// one network function is replaced before the application module runs.
const loader = nameOf("core/data/load.js");
const inlineLoader = `
${loader}.loadDictionary = async () => ({
  dictionary: ${loader}.buildDictionary(DATA.headwords, DATA.entries),
  meta: DATA.meta,
});`;

const script = [
  "const DATA = {",
  `  headwords: ${data.headwords},`,
  `  entries: ${data.entries},`,
  `  meta: ${data.meta},`,
  "};",
  ...MODULES.slice(0, -1).map(wrap),
  inlineLoader,
  wrap(MODULES[MODULES.length - 1]).replaceAll("img/title-page.png", titlePage),
].join("\n");

const html = page
  .replace(/<link rel="manifest"[^>]*>/, "")
  .replace(/<link rel="icon"[^>]*>/, "")
  .replace(/<link rel="apple-touch-icon"[^>]*>/, "")
  .replace(/<link rel="stylesheet"[^>]*>/, `<style>\n${styles}\n</style>`)
  .replace(/<script type="module" src="ui\/app\.js"><\/script>/,
           `<script>\n${script}\n</script>`);

const out = DIST + "mackey-encyclopaedia.html";
writeFileSync(out, html);
console.log(`${out}  ${(html.length / 1e6).toFixed(1)} MB`);
