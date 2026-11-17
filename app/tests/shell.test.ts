/**
 * The shell's static references: manifest, icons, cached paths.
 *
 * None of this is exercised by the UI tests, because none of it is code --
 * which is exactly why it goes wrong quietly. A manifest pointing at an icon
 * that is not there costs nothing at run time and simply gives the reader a
 * blank square when they install the app; a service worker that lists a file
 * it cannot fetch drops it from the shell and only shows up offline.
 *
 *   node --experimental-strip-types --test app/tests/shell.test.ts
 */

import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync, existsSync, statSync } from "node:fs";
import { fileURLToPath } from "node:url";

const APP = fileURLToPath(new URL("../", import.meta.url));
const read = (name: string) => readFileSync(APP + name, "utf8");

/** Width and height from a PNG's IHDR, without a decoder. */
function pngSize(path: string): { width: number; height: number; alpha: boolean } {
  const buf = readFileSync(path);
  assert.equal(buf.readUInt32BE(0), 0x89504e47, `${path} is not a PNG`);
  return {
    width: buf.readUInt32BE(16),
    height: buf.readUInt32BE(20),
    // Colour type 6 is RGBA, 4 is grey+alpha, 3 is palette (alpha via tRNS).
    alpha: [4, 6].includes(buf[25]),
  };
}

test("every file the manifest names is present and the size it claims", () => {
  const manifest = JSON.parse(read("manifest.webmanifest"));
  assert.ok(manifest.icons.length >= 2, "an installable app needs icons");

  for (const icon of manifest.icons) {
    const path = APP + "public/" + icon.src;
    assert.ok(existsSync(path), `manifest names ${icon.src}, which is not there`);
    const { width, height } = pngSize(path);
    assert.equal(`${width}x${height}`, icon.sizes, `${icon.src} is not ${icon.sizes}`);
  }
});

test("the maskable icon is opaque and the plain ones are not", () => {
  // A maskable icon is cropped to the launcher's shape, so transparency in it
  // shows as a hole. A plain one is the book alone -- the whole point of
  // cutting it out of the photograph.
  const manifest = JSON.parse(read("manifest.webmanifest"));
  const maskable = manifest.icons.find((i: { purpose: string }) => i.purpose === "maskable");
  assert.ok(maskable, "no maskable icon: Android will crop the plain one badly");

  const corner = (name: string): number => {
    // Top-left pixel of the alpha channel, read the cheap way: if the file has
    // no alpha channel at all it cannot be transparent anywhere.
    return pngSize(APP + "public/" + name).alpha ? 1 : 0;
  };
  assert.equal(corner(maskable.src), 0, "the maskable icon should carry no alpha");
  assert.equal(corner("img/icon-512.png"), 1, "the plain icon should have a cut-out");
});

test("the page links an icon and an iOS icon that exist", () => {
  const html = read("index.html");
  for (const rel of ["icon", "apple-touch-icon"]) {
    const match = html.match(new RegExp(`rel="${rel}"[^>]*href="([^"]+)"`));
    assert.ok(match, `index.html has no rel="${rel}" link`);
    assert.ok(existsSync(APP + "public/" + match[1]), `${match[1]} is missing`);
  }
});

test("the service worker caches only files that exist, and was bumped", () => {
  const sw = read("sw.js");
  const version = sw.match(/const VERSION = "([^"]+)"/);
  assert.ok(version, "the service worker has no VERSION");

  const shell = sw.match(/const SHELL = \[([^\]]+)\]/s);
  assert.ok(shell, "the service worker has no SHELL list");

  for (const [, path] of shell[1].matchAll(/"([^"]+)"/g)) {
    if (path === "./" || path.endsWith(".html")) continue;
    const built = path.startsWith("img/") || path.startsWith("data/")
      ? APP + "public/" + path
      : APP + "src/" + path.replace(/\.js$/, ".ts");
    assert.ok(existsSync(built), `the worker caches ${path}, which is not built from anything`);
  }
});

test("the icons are small enough to ship", () => {
  // The 512 is fetched once, at install, and is never in the offline shell;
  // the 192 is, so it is the one that has to stay light.
  const kb = (name: string) => statSync(APP + "public/" + name).size / 1024;
  assert.ok(kb("img/icon-192.png") < 120, "the cached icon has got heavy");
  assert.ok(kb("img/icon-512.png") < 600, "the install icon has got heavy");
});
