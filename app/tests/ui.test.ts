/**
 * Smoke tests for the app shell.
 *
 * There is no browser here, so the DOM is stubbed to the few methods the app
 * actually uses. This will not catch a layout problem, but it does catch the
 * things that break a page outright -- a render path that throws, a helper
 * that builds the wrong node, a screen that comes up empty -- which otherwise
 * only show up by opening the page and finding it blank.
 *
 *   node --experimental-strip-types --test app/tests/ui.test.ts
 */

import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

/* ---------- a DOM, just enough of one ---------- */

class StubNode {
  tagName: string;
  children: StubNode[] = [];
  attributes = new Map<string, string>();
  style: Record<string, string> = {};
  private text = "";
  hidden = false;
  disabled = false;
  title = "";
  value = "";
  private listeners = new Map<string, Array<() => void>>();

  constructor(tagName: string) {
    this.tagName = tagName.toLowerCase();
  }

  set textContent(value: string) {
    this.text = value;
    this.children = [];
  }
  get textContent(): string {
    return this.text + this.children.map((child) => child.textContent).join("");
  }

  set innerHTML(value: string) {
    if (value === "") {
      this.children = [];
      this.text = "";
    }
  }

  append(...nodes: Array<StubNode | string>): void {
    for (const node of nodes) {
      if (typeof node === "string") {
        const text = new StubNode("#text");
        text.textContent = node;
        this.children.push(text);
      } else {
        this.children.push(node);
      }
    }
  }

  setAttribute(name: string, value: string): void {
    this.attributes.set(name, value);
  }
  getAttribute(name: string): string | null {
    return this.attributes.get(name) ?? null;
  }
  addEventListener(name: string, fn: () => void): void {
    const list = this.listeners.get(name) ?? [];
    list.push(fn);
    this.listeners.set(name, list);
  }
  click(): void {
    for (const fn of this.listeners.get("click") ?? []) fn();
  }
  focus(): void {}
  setSelectionRange(): void {}

  get className(): string {
    return this.attributes.get("class") ?? "";
  }

  /** Every node in the subtree, this one included. */
  all(): StubNode[] {
    return [this, ...this.children.flatMap((child) => child.all())];
  }
  querySelector(selector: string): StubNode | null {
    const tag = selector.toLowerCase();
    return this.all().find((node) => node.tagName === tag) ?? null;
  }
  find(className: string): StubNode[] {
    return this.all().filter((node) => node.className.split(" ").includes(className));
  }
}

const app = new StubNode("main");
const backButton = new StubNode("button");

const documentStub = {
  createElement: (tag: string) => new StubNode(tag),
  getElementById: (id: string) => (id === "app" ? app : backButton),
};

const dataDir = fileURLToPath(new URL("../public/data/", import.meta.url));
const files: Record<string, unknown> = {
  "data/headwords.json": JSON.parse(readFileSync(`${dataDir}headwords.json`, "utf8")),
  "data/entries.json": JSON.parse(readFileSync(`${dataDir}entries.json`, "utf8")),
  "data/meta.json": JSON.parse(readFileSync(`${dataDir}meta.json`, "utf8")),
};

(globalThis as Record<string, unknown>).document = documentStub;
(globalThis as Record<string, unknown>).window = {
  addEventListener: () => {},
  requestIdleCallback: (fn: () => void) => fn(),
};
// Node defines `navigator` as a getter-only global, so it has to be replaced
// rather than assigned.
Object.defineProperty(globalThis, "navigator", { value: {}, configurable: true });
(globalThis as Record<string, unknown>).fetch = async (url: string) => ({
  ok: true,
  json: async () => files[url],
});

await import("../src/ui/app.ts");
// Let the module's own async start() settle.
await new Promise((resolve) => setTimeout(resolve, 2500));

/* ---------- tests ---------- */

test("the home screen renders rather than staying on the loader", () => {
  const text = app.textContent;
  assert.ok(!text.includes("Opening the encyclopaedia"), "stuck on the loading state");
  assert.ok(text.includes("Mackey"), "no title on the home screen");
  assert.ok(/3,9\d\d articles/.test(text), `entry count missing from: ${text.slice(0, 120)}`);
});

test("the alphabet strip is built from real counts", () => {
  const letters = app.find("letter");
  assert.ok(letters.length >= 24, `only ${letters.length} letters`);

  const labels = letters.map((l) => l.getAttribute("aria-label") ?? "");
  assert.ok(labels.every((label) => /^[A-Z], \d+ entries$/.test(label)),
    `bad label: ${labels.find((l) => !/^[A-Z], \d+ entries$/.test(l))}`);

  // The bars must differ, or the strip is telling the reader nothing.
  const heights = letters.map((l) => l.all().find((n) => n.tagName === "i")?.style.height);
  assert.ok(new Set(heights).size > 5, "every bar is the same height");
});

test("clicking a letter lists that letter's entries", () => {
  const letterA = app.find("letter").find((l) =>
    (l.getAttribute("aria-label") ?? "").startsWith("A,"));
  assert.ok(letterA, "no A in the strip");
  letterA!.click();

  const text = app.textContent;
  assert.ok(/entries under A/.test(text), `expected a letter listing, got: ${text.slice(0, 120)}`);
  assert.ok(app.find("result").length > 10, "too few results listed");
});

test("an entry opens with its text and printed page", () => {
  const first = app.find("result")[0];
  assert.ok(first, "nothing to click");
  first.click();

  const text = app.textContent;
  assert.ok(app.find("entry").length === 1, "no entry rendered");
  assert.ok(/Page \d+ of the printed edition|Page number not recovered/.test(text),
    "no page reference on the entry");
  const body = app.find("entry-body")[0];
  assert.ok(body && body.textContent.length > 60, "entry body is empty");
});

test("back returns to the previous screen", () => {
  assert.equal(backButton.hidden, false, "back button hidden when there is history");
  backButton.click();
  assert.ok(/entries under A/.test(app.textContent), "back did not return to the listing");
});
