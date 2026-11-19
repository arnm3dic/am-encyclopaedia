/**
 * The door: the word, the count, and the wait.
 *
 *   node --experimental-strip-types --test app/tests/gate.test.ts
 */

import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const store = new Map<string, string>();
Object.defineProperty(globalThis, "localStorage", {
  configurable: true,
  value: {
    getItem: (key: string) => store.get(key) ?? null,
    setItem: (key: string, value: string) => void store.set(key, value),
    removeItem: (key: string) => void store.delete(key),
  },
});

const gate = await import("../src/ui/gate.ts");

test("the word is admitted, and nothing else is", () => {
  assert.ok(gate.admits("LOTG#102"));
  assert.ok(gate.admits("  LOTG#102  "), "surrounding spaces should not matter");
  for (const wrong of ["lotg#102", "LOTG#103", "LOTG102", "", "LOTG#1021", "LOTG #102"]) {
    assert.ok(!gate.admits(wrong), `${JSON.stringify(wrong)} was admitted`);
  }
});

test("the word is not in the source in plain sight", () => {
  // Obscurity, not security -- but the answer should not be readable at a
  // glance in a public repository.
  const source = readFileSync(new URL("../src/ui/gate.ts", import.meta.url), "utf8");
  assert.ok(!source.includes("LOTG#102"), "the word is written out in gate.ts");
});

test("four wrong answers close the door for twenty seconds", () => {
  store.clear();
  const now = 1_000_000;
  assert.equal(gate.refuse(now), 0);
  assert.equal(gate.refuse(now), 0);
  assert.equal(gate.refuse(now), 0);
  assert.equal(gate.triesLeft(), 1, "the count should show one attempt left");
  assert.equal(gate.refuse(now), 20_000, "the fourth should close it");
  assert.equal(gate.closedFor(now), 20_000);
  assert.equal(gate.closedFor(now + 19_999), 1);
  assert.equal(gate.closedFor(now + 20_000), 0, "it should open again after the wait");
});

test("the wait survives a reload, and the count resets with it", () => {
  store.clear();
  const now = 2_000_000;
  for (let i = 0; i < 4; i++) gate.refuse(now);
  // A reload only re-reads storage, which is where both of these live.
  assert.equal(gate.closedFor(now + 5_000), 15_000, "reloading reopened the door");
  assert.equal(gate.triesLeft(), 4, "the count should start again after a wait");
});

test("the question is asked once per installation", () => {
  store.clear();
  assert.ok(!gate.admittedBefore(), "a fresh installation should be asked");
  gate.admitted();
  assert.ok(gate.admittedBefore(), "an admitted installation should not be asked again");
  // Clearing site data is a new installation as far as this is concerned.
  store.clear();
  assert.ok(!gate.admittedBefore(), "clearing storage should ask again");
});

test("being admitted clears the count and the wait", () => {
  store.clear();
  const now = 3_000_000;
  for (let i = 0; i < 4; i++) gate.refuse(now);
  gate.admitted();
  assert.equal(gate.closedFor(now), 0);
  assert.equal(gate.triesLeft(), 4);
});

test("a digest is stable and does not collide on near misses", () => {
  assert.equal(gate.digest("LOTG#102"), gate.digest("LOTG#102"));
  const seen = new Set<string>();
  for (const word of ["LOTG#102", "LOTG#103", "lotg#102", "LOTG#101", "LOTG#112"]) {
    seen.add(gate.digest(word));
  }
  assert.equal(seen.size, 5, "two different words produced the same digest");
});
