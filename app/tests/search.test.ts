/**
 * The search engine, tested against the real dictionary.
 *
 * Deliberately not against fixtures invented for the test: the Phase 1 spike
 * passed on a sample and still lost "Zerubbabel." across the whole book. These
 * run on all 3,952 entries, and the test matrix is the one the brief sets out
 * in Module 9.
 *
 *   node --experimental-strip-types --test app/tests/search.test.ts
 */

import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync, existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { buildDictionary } from "../src/core/data/load.ts";
import { Band } from "../src/core/search/engine.ts";
import { editDistance } from "../src/core/search/headwords.ts";

const dataDir = fileURLToPath(new URL("../public/data/", import.meta.url));
const available = existsSync(`${dataDir}headwords.json`);

if (!available) {
  test("dictionary bundle is missing", () => {
    assert.fail(`no bundle at ${dataDir}; run pipeline/export_web.py first`);
  });
}

const headwords = JSON.parse(readFileSync(`${dataDir}headwords.json`, "utf8"));
const file = JSON.parse(readFileSync(`${dataDir}entries.json`, "utf8"));
const started = Date.now();
const dictionary = buildDictionary(headwords, file);
const buildMs = Date.now() - started;

test("index builds over the whole dictionary", () => {
  assert.ok(dictionary.size > 3500, `only ${dictionary.size} entries`);
  assert.ok(dictionary.definitions.vocabulary > 20000,
    `vocabulary only ${dictionary.definitions.vocabulary}`);
  console.log(`      built ${dictionary.size} entries, ` +
    `${dictionary.definitions.vocabulary} distinct terms, in ${buildMs} ms`);
});

test("A. exact headword", () => {
  const hits = dictionary.search("Acacia");
  assert.equal(hits[0].headword, "Acacia.");
  assert.equal(hits[0].band, Band.ExactHeadword);
});

test("A. exact match ignores case, accents and trailing stop", () => {
  for (const query of ["acacia", "ACACIA", "Acacia.", "  acacia  "]) {
    const hits = dictionary.search(query);
    assert.equal(hits[0].headword, "Acacia.", `failed for ${JSON.stringify(query)}`);
    assert.equal(hits[0].band, Band.ExactHeadword);
  }
});

test("B. beginning of word", () => {
  const hits = dictionary.search("Tetra", { only: Band.HeadwordPrefix });
  assert.ok(hits.length >= 2, `expected several, got ${hits.length}`);
  for (const hit of hits) {
    assert.ok(hit.headword.toLowerCase().startsWith("tetra"), hit.headword);
  }
});

test("C. middle of word", () => {
  const hits = dictionary.search("aut", { only: Band.HeadwordContains });
  const words = hits.map((h) => h.headword);
  assert.ok(hits.length >= 3, `expected several, got ${hits.length}`);
  // The point of substring search: a match that is not at the start.
  assert.ok(words.some((w) => !w.toLowerCase().startsWith("aut")),
    `all matches were prefixes: ${words.slice(0, 5).join(", ")}`);
});

test("D. end of word", () => {
  const ids = dictionary.headwords.suffix("tion");
  assert.ok(ids.length >= 5, `expected several, got ${ids.length}`);
  for (const id of ids.slice(0, 10)) {
    const entry = dictionary.entry(id)!;
    const plain = entry.headword.toLowerCase().replace(/[^a-z]+$/, "");
    assert.ok(plain.endsWith("tion"), entry.headword);
  }
});

test("E. search within meanings", () => {
  const hits = dictionary.search("sprig of acacia");
  assert.ok(hits.length > 0, "no hits for a phrase that occurs in the text");
  const inDefinitions = hits.filter((h) => h.band >= Band.DefinitionPhrase);
  assert.ok(inDefinitions.length > 0, "nothing matched in definitions");
});

test("E. phrase search is contiguous, not just co-occurrence", () => {
  const phrase = dictionary.definitions.phrase("king of tyre");
  assert.ok(phrase.length > 0, "known phrase not found");
  for (const hit of phrase.slice(0, 5)) {
    const body = dictionary.entry(hit.id)!.body.toLowerCase();
    assert.ok(body.includes("king of tyre"), `not contiguous in ${hit.id}`);
  }
});

test("F. all fields at once, each entry in its best band only", () => {
  const hits = dictionary.search("temple", { limit: 200 });
  const ids = hits.map((h) => h.id);
  assert.equal(new Set(ids).size, ids.length, "an entry appeared twice");
  const bands = hits.map((h) => h.band);
  assert.deepEqual(bands, [...bands].sort((a, b) => a - b), "bands out of order");
});

test("G. misspellings suggest the right entry", () => {
  const hits = dictionary.search("Kadsoh", { includeFuzzy: true });
  const headwords = hits.map((h) => h.headword.toLowerCase());
  assert.ok(headwords.some((h) => h.startsWith("kadosh")),
    `no Kadosh among: ${headwords.slice(0, 5).join(", ")}`);
});

test("G. punctuation and spacing are handled", () => {
  const a = dictionary.search("Rose-Croix");
  const b = dictionary.search("rose croix");
  assert.ok(a.length > 0 && b.length > 0, "one spelling found nothing");
  assert.equal(a[0].id, b[0].id, "hyphen changed the result");
});

test("edit distance counts a transposition as one edit", () => {
  assert.equal(editDistance("kadosh", "kadsoh", 2), 1);
  assert.equal(editDistance("acacia", "acacia", 2), 0);
  assert.ok(editDistance("acacia", "zzzzzz", 2) > 2);
});

test("empty and junk queries return nothing, and do not throw", () => {
  for (const query of ["", "   ", ".", "!!!", "—"]) {
    assert.deepEqual(dictionary.search(query), [], `for ${JSON.stringify(query)}`);
  }
});

test("multiple meanings under one headword are kept apart", () => {
  const hits = dictionary.search("Cross", { limit: 100 });
  const crosses = hits.filter((h) => h.headword.toLowerCase().startsWith("cross"));
  assert.ok(crosses.length >= 5,
    `expected several Cross entries, got ${crosses.length}`);
  assert.equal(new Set(crosses.map((h) => h.headword)).size, crosses.length);
});

test("alphabetical index covers A to Z with counts", () => {
  const counts = dictionary.letterCounts();
  const letters = Object.keys(counts).filter((k) => /[A-Z]/.test(k));
  assert.ok(letters.length >= 24, `only ${letters.length} letters`);
  const total = Object.values(counts).reduce((a, b) => a + b, 0);
  assert.equal(total, dictionary.size);
  const a = dictionary.byLetter("A");
  assert.equal(a.length, counts["A"]);
});

test("entries carry their printed page", () => {
  const hits = dictionary.search("Acacia");
  const entry = dictionary.entry(hits[0].id)!;
  assert.ok(entry.printedPage > 0, "no printed page");
  assert.ok(entry.body.length > 50, "body too short to be real");
});

test("cross-references resolve to real entries", () => {
  let checked = 0;
  for (const row of dictionary.headwords.rows.slice(0, 400)) {
    for (const ref of dictionary.referencesFrom(row[0])) {
      if (ref.toEntry !== null) {
        assert.ok(dictionary.entry(ref.toEntry), `dangling ref to ${ref.toEntry}`);
        checked += 1;
      }
    }
  }
  assert.ok(checked > 0, "no resolved cross-references in the first 400 entries");
});

test("highlight offsets land on the query", () => {
  const hits = dictionary.search("acacia", { limit: 5 });
  const target = hits.find((h) => h.band >= Band.DefinitionTerms) ?? hits[0];
  const spans = dictionary.highlights(target.id, "acacia");
  for (const [from, to] of spans.slice(0, 3)) {
    assert.ok(to > from, "empty span");
  }
});

test("search stays fast across many queries", () => {
  const queries = ["acacia", "temple", "kadosh", "aut", "tetra", "blazing star",
    "wisdom strength beauty", "hiram", "lodge", "rose croix"];
  const start = Date.now();
  const rounds = 20;
  for (let i = 0; i < rounds; i++) {
    for (const query of queries) dictionary.search(query);
  }
  const elapsed = Date.now() - start;
  const perQuery = elapsed / (rounds * queries.length);
  console.log(`      ${rounds * queries.length} searches in ${elapsed} ms ` +
    `(${perQuery.toFixed(2)} ms each)`);
  assert.ok(perQuery < 25, `too slow: ${perQuery.toFixed(2)} ms per query`);
});

test("suggestions are headword-only and instant", () => {
  const start = Date.now();
  for (let i = 0; i < 200; i++) dictionary.suggest("tem");
  const perCall = (Date.now() - start) / 200;
  const hits = dictionary.suggest("tem");
  for (const hit of hits) assert.ok(hit.band <= Band.HeadwordContains);
  assert.ok(perCall < 10, `too slow: ${perCall.toFixed(2)} ms per keystroke`);
});

test("known entries that regressions have hidden before are present", () => {
  for (const term of ["Zerubbabel", "Tetragrammaton", "Lodge of St. John",
    "Babylon", "Acacia", "Cowan"]) {
    const hits = dictionary.search(term);
    assert.ok(hits.length > 0, `${term} is missing from the dictionary`);
    assert.ok(hits[0].band <= Band.HeadwordContains,
      `${term} only matched in definitions`);
  }
});

test("headword search works before the definition index is built", () => {
  // A fresh dictionary, deliberately not warmed.
  const cold = buildDictionary(headwords, file);
  assert.equal(cold.isWarm, false, "started warm");

  const start = Date.now();
  const hits = cold.search("Acacia", { definitions: false });
  const elapsed = Date.now() - start;

  assert.ok(hits.length > 0, "no headword results on the cold path");
  assert.equal(cold.isWarm, false, "the fast path built the index anyway");
  assert.ok(elapsed < 100, `cold headword search took ${elapsed} ms`);

  cold.warm();
  assert.equal(cold.isWarm, true, "warm() did not build the index");
});

test("suggestions never build the definition index", () => {
  const cold = buildDictionary(headwords, file);
  cold.suggest("tem");
  assert.equal(cold.isWarm, false, "a keystroke built the whole index");
});
