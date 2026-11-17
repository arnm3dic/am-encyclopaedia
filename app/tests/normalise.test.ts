/**
 * The TypeScript side of the normalisation contract.
 *
 * Runs the same fixtures the Python implementation runs. If these two drift,
 * search silently returns nothing for the affected terms.
 *
 *   node --experimental-strip-types --test app/tests/
 */

import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { normalise, sortKey, firstLetter } from "../src/core/normalise.ts";

type Fixture = {
  input: string;
  normalise: string;
  sort_key: string;
  first_letter: string;
};

const fixtures: Fixture[] = JSON.parse(
  readFileSync(new URL("../../pipeline/tests/normalise_fixtures.json", import.meta.url), "utf8"),
);

test("fixtures are present", () => {
  assert.ok(fixtures.length > 100, `expected a real fixture set, got ${fixtures.length}`);
});

test("normalise matches the Python implementation", () => {
  const failures: string[] = [];
  for (const fixture of fixtures) {
    const actual = normalise(fixture.input);
    if (actual !== fixture.normalise) {
      failures.push(`normalise(${JSON.stringify(fixture.input)}): expected ${JSON.stringify(fixture.normalise)}, got ${JSON.stringify(actual)}`);
    }
  }
  assert.deepEqual(failures, [], `${failures.length} mismatches:\n${failures.slice(0, 12).join("\n")}`);
});

test("sortKey matches the Python implementation", () => {
  const failures: string[] = [];
  for (const fixture of fixtures) {
    const actual = sortKey(fixture.input);
    if (actual !== fixture.sort_key) {
      failures.push(`sortKey(${JSON.stringify(fixture.input)}): expected ${JSON.stringify(fixture.sort_key)}, got ${JSON.stringify(actual)}`);
    }
  }
  assert.deepEqual(failures, [], `${failures.length} mismatches:\n${failures.slice(0, 12).join("\n")}`);
});

test("firstLetter matches the Python implementation", () => {
  const failures: string[] = [];
  for (const fixture of fixtures) {
    const actual = firstLetter(fixture.input);
    if (actual !== fixture.first_letter) {
      failures.push(`firstLetter(${JSON.stringify(fixture.input)}): expected ${fixture.first_letter}, got ${actual}`);
    }
  }
  assert.deepEqual(failures, [], `${failures.length} mismatches:\n${failures.slice(0, 12).join("\n")}`);
});

test("invariants hold whatever the rules are", () => {
  for (const fixture of fixtures) {
    const value = normalise(fixture.input);
    assert.equal(value, value.trim(), `padding survived: ${JSON.stringify(value)}`);
    assert.ok(!value.includes("  "), `double space: ${JSON.stringify(value)}`);
    assert.equal(value, value.toLowerCase(), `uppercase survived: ${JSON.stringify(value)}`);
  }
});

test("normalisation is idempotent", () => {
  for (const fixture of fixtures) {
    const once = normalise(fixture.input);
    assert.equal(normalise(once), once, `not idempotent: ${JSON.stringify(fixture.input)}`);
  }
});
