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

class StubClassList {
  private readonly names = new Set<string>();
  private readonly owner: StubNode;
  // Written out rather than declared in the parameter list: a parameter
  // property emits runtime code and cannot be type-stripped, like an enum.
  constructor(owner: StubNode) {
    this.owner = owner;
  }
  add(...values: string[]): void {
    for (const v of values) this.names.add(v);
    this.sync();
  }
  remove(...values: string[]): void {
    for (const v of values) this.names.delete(v);
    this.sync();
  }
  toggle(value: string, force?: boolean): void {
    const on = force ?? !this.names.has(value);
    if (on) this.names.add(value);
    else this.names.delete(value);
    this.sync();
  }
  contains(value: string): boolean {
    return this.names.has(value);
  }
  private sync(): void {
    this.owner.setAttribute("class", [...this.names].join(" "));
  }
}

class StubNode {
  tagName: string;
  parentElement: StubNode | null = null;
  classList: StubClassList;
  type = "";
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
    this.classList = new StubClassList(this);
  }

  insertBefore(node: StubNode, reference: StubNode | null): void {
    const at = reference ? this.children.indexOf(reference) : -1;
    if (at === -1) this.children.push(node);
    else this.children.splice(at, 0, node);
    node.parentElement = this;
  }

  get nextSibling(): StubNode | null {
    const siblings = this.parentElement?.children ?? [];
    const at = siblings.indexOf(this);
    return at === -1 ? null : siblings[at + 1] ?? null;
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
        node.parentElement = this;
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
  addEventListener(name: string, fn: (event?: unknown) => void): void {
    const list = this.listeners.get(name) ?? [];
    list.push(fn as () => void);
    this.listeners.set(name, list);
  }
  dispatch(name: string, event: Record<string, unknown> = {}): void {
    const payload = { preventDefault: () => {}, ...event };
    for (const fn of this.listeners.get(name) ?? []) {
      (fn as (e: unknown) => void)(payload);
    }
  }
  remove(): void {
    const siblings = this.parentElement?.children;
    if (siblings) siblings.splice(siblings.indexOf(this), 1);
    this.parentElement = null;
  }
  click(): void {
    this.dispatch("click");
  }
  focus(): void {
    activeElement = this;
  }
  blur(): void {
    if (activeElement === this) activeElement = null;
  }
  setSelectionRange(): void {}

  /** Type into this node as a person would, character by character.
   *  Named typeInto because `type` is an element property the app sets. */
  typeInto(text: string): void {
    for (const character of text) {
      this.value += character;
      this.dispatch("input");
    }
  }

  get className(): string {
    return this.attributes.get("class") ?? "";
  }
  set className(value: string) {
    this.attributes.set("class", value);
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
const searchbar = new StubNode("div");
const typeset = new StubNode("button");
const bodyNode = new StubNode("body");
const shell = new StubNode("div");
shell.append(searchbar);
let activeElement: StubNode | null = null;

const nodesById: Record<string, StubNode> = {
  app, back: backButton, searchbar, typeset,
};

const store = new Map<string, string>();
Object.defineProperty(globalThis, "localStorage", {
  configurable: true,
  value: {
    getItem: (key: string) => store.get(key) ?? null,
    setItem: (key: string, value: string) => void store.set(key, value),
    removeItem: (key: string) => void store.delete(key),
  },
});

const docListeners = new Map<string, Array<() => void>>();
function documentListeners(type: string): number {
  return docListeners.get(type)?.length ?? 0;
}

const documentStub = {
  body: bodyNode,
  addEventListener(type: string, fn: () => void) {
    const list = docListeners.get(type) ?? [];
    list.push(fn);
    docListeners.set(type, list);
  },
  removeEventListener(type: string, fn: () => void) {
    const list = docListeners.get(type) ?? [];
    const at = list.indexOf(fn);
    if (at !== -1) list.splice(at, 1);
  },
  createElement: (tag: string) => new StubNode(tag),
  createTextNode: (text: string) => {
    const node = new StubNode("#text");
    node.textContent = text;
    return node;
  },
  getElementById: (id: string) => nodesById[id] ?? new StubNode("div"),
  get activeElement() {
    return activeElement;
  },
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
// The app resolves data from its own module URL, so match on the file name
// rather than on a path the test would have to keep in step.
const requested: string[] = [];
(globalThis as Record<string, unknown>).fetch = async (url: string) => {
  requested.push(String(url));
  const name = Object.keys(files).find((key) => String(url).endsWith(key));
  if (!name) {
    return { ok: false, status: 404, statusText: "Not Found", json: async () => ({}) };
  }
  return { ok: true, status: 200, json: async () => files[name] };
};

await import("../src/ui/app.ts");
// Let the module's own async start() settle.
await new Promise((resolve) => setTimeout(resolve, 2500));

/* ---------- tests ---------- */

test("the home screen renders rather than staying on the loader", () => {
  const text = app.textContent;
  assert.ok(!text.includes("Opening the encyclopaedia"), "stuck on the loading state");
  assert.ok(app.find("cover").length === 1, "no front page on the home screen");
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


/* ---------- the search box ---------- */

function searchInput(): StubNode {
  const found = searchbar.all().find((node) => node.tagName === "input");
  assert.ok(found, "no search input on the page");
  return found!;
}

function suggestionButtons(): StubNode[] {
  return searchbar.find("suggestion").filter((node) =>
    !node.className.includes("suggest-all"));
}

test("typed characters stay in the box", () => {
  const box = searchInput();
  box.value = "";
  box.typeInto("acac");
  assert.equal(box.value, "acac", "the box lost what was typed into it");
  assert.equal(searchInput(), box, "the input element was replaced while typing");
});

test("suggestions appear while typing, without pressing anything", () => {
  const box = searchInput();
  box.value = "";
  box.typeInto("tetra");

  const options = suggestionButtons();
  assert.ok(options.length > 0, "no suggestions offered");
  for (const option of options) {
    assert.ok(option.textContent.toLowerCase().includes("tetra"),
      `unrelated suggestion: ${option.textContent}`);
  }
});

test("suggestions narrow as more characters arrive", () => {
  const box = searchInput();
  box.value = "";
  box.typeInto("te");
  const broad = suggestionButtons().length;
  box.typeInto("tragram");
  const narrow = suggestionButtons().length;
  assert.ok(narrow <= broad, `got wider: ${broad} then ${narrow}`);
  assert.ok(narrow > 0, "narrowing lost everything");
});

test("the matched part of each suggestion is marked", () => {
  const box = searchInput();
  box.value = "";
  box.typeInto("acac");
  const marks = searchbar.all().filter((node) => node.tagName === "mark");
  assert.ok(marks.length > 0, "nothing marked in the suggestions");
  assert.ok(marks.every((m) => m.textContent.toLowerCase() === "acac"),
    "marked the wrong characters");
});

test("choosing a suggestion opens that entry", () => {
  const box = searchInput();
  box.value = "";
  box.typeInto("acacia");
  const first = suggestionButtons()[0];
  const wanted = first.textContent;
  first.click();

  assert.equal(app.find("entry").length, 1, "no entry opened");
  const heading = app.all().find((node) => node.tagName === "h1");
  assert.ok(heading && wanted.startsWith(heading.textContent.slice(0, 6)),
    `opened ${heading?.textContent} for ${wanted}`);
  assert.equal(suggestionButtons().length, 0, "suggestions stayed open");
});

test("a misspelling still offers the right entry", () => {
  const box = searchInput();
  box.value = "";
  box.typeInto("Kadsoh");
  const options = suggestionButtons();
  assert.ok(options.length > 0, "no near matches offered");
  assert.ok(options.some((o) => o.textContent.toLowerCase().includes("kadosh")),
    `no Kadosh among: ${options.map((o) => o.textContent).join(", ")}`);
});

test("Enter searches everything rather than opening a suggestion", () => {
  const box = searchInput();
  box.value = "";
  box.typeInto("temple");
  box.dispatch("keydown", { key: "Enter" });
  assert.ok(/results? for/.test(app.textContent),
    `expected a results screen, got: ${app.textContent.slice(0, 100)}`);
});

test("Escape dismisses the suggestions", () => {
  const box = searchInput();
  box.value = "";
  box.typeInto("tem");
  assert.ok(suggestionButtons().length > 0, "nothing to dismiss");
  box.dispatch("keydown", { key: "Escape" });
  assert.equal(suggestionButtons().length, 0, "suggestions survived Escape");
});

test("italics from the book are rendered as emphasis", () => {
  const box = searchInput();
  box.value = "";
  box.typeInto("arts");
  const option = suggestionButtons().find((o) => o.textContent.startsWith("Arts."));
  assert.ok(option, "Arts. not offered");
  option!.click();

  const body = app.find("entry-body")[0];
  assert.ok(body, "no entry body");
  const emphasised = body.all().filter((n) => n.tagName === "em").map((n) => n.textContent);
  assert.ok(emphasised.length > 0, "nothing italic in an entry that is italic in the book");
  assert.ok(emphasised.some((t) => t.includes("Parts")),
    `expected the cross-reference italic, got: ${emphasised.join(" | ")}`);
});

test("italic markers never reach the reader as characters", () => {
  const body = app.find("entry-body")[0];
  assert.ok(!body.textContent.includes("\u0002"), "an opening marker leaked into the text");
  assert.ok(!body.textContent.includes("\u0003"), "a closing marker leaked into the text");
});

test("markers do not leak into result snippets either", () => {
  const box = searchInput();
  box.value = "";
  box.typeInto("masonry");
  box.dispatch("keydown", { key: "Enter" });
  const text = app.textContent;
  assert.ok(!text.includes("\u0002") && !text.includes("\u0003"),
    "markers visible on the results screen");
});


test("data is requested by absolute URL, not relative to the page", () => {
  assert.ok(requested.length >= 3, `only ${requested.length} requests made`);
  for (const url of requested) {
    // A bare relative path resolves against the page, and a page served
    // without a trailing slash drops its last segment -- which is what left
    // the app reporting that the dictionary could not be loaded.
    assert.match(url, /^[a-z]+:\/\//, `not absolute: ${url}`);
    assert.match(url, /\/data\/[a-z]+\.json$/, `wrong shape: ${url}`);
  }
});

test("a failed load says what went wrong", async () => {
  const { loadDictionary } = await import("../src/core/data/load.ts");
  const saved = (globalThis as Record<string, unknown>).fetch;
  (globalThis as Record<string, unknown>).fetch = async () => ({
    ok: false, status: 404, statusText: "Not Found", json: async () => ({}),
  });
  try {
    await loadDictionary();
    assert.fail("a 404 should have thrown");
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    assert.match(message, /404/, `message hides the cause: ${message}`);
    assert.match(message, /\.json/, `message does not name the file: ${message}`);
  } finally {
    (globalThis as Record<string, unknown>).fetch = saved;
  }
});

/* ---------- reading options ---------- */

function optionButtons(): StubNode[] {
  return shell.all().filter((n) => n.tagName === "button" &&
    n.parentElement?.className.includes("steps"));
}

test("reading options open from the masthead", () => {
  const panel = shell.all().find((n) => n.className.includes("options"));
  assert.ok(panel, "no options panel was built");
  assert.equal(panel!.hidden, true, "panel starts open");
  typeset.click();
  assert.equal(panel!.hidden, false, "panel did not open");
  assert.equal(typeset.getAttribute("aria-expanded"), "true");
});

test("text size offers four steps with one chosen", () => {
  const sizes = optionButtons().filter((b) => b.getAttribute("aria-label") &&
    ["Small", "Default", "Large", "Largest"].includes(b.getAttribute("aria-label")!));
  assert.equal(sizes.length, 4, `expected four sizes, got ${sizes.length}`);
  const pressed = sizes.filter((b) => b.getAttribute("aria-pressed") === "true");
  assert.equal(pressed.length, 1, "exactly one size should be chosen");
  assert.equal(pressed[0].getAttribute("aria-label"), "Default");
});

test("choosing a larger size applies it to the page and is remembered", () => {
  const large = optionButtons().find((b) => b.getAttribute("aria-label") === "Large");
  assert.ok(large, "no large option");
  large!.click();
  assert.ok(bodyNode.classList.contains("size-l"), "size not applied to the body");
  assert.ok(!bodyNode.classList.contains("size-m"), "old size left behind");
  assert.ok(store.get("am-reading")?.includes("\"l\""), "preference not stored");
});

test("reading mode toggles on and off", () => {
  const toggle = optionButtons().find((b) => b.textContent === "Off");
  assert.ok(toggle, "no reading-mode toggle");
  toggle!.click();
  assert.ok(bodyNode.classList.contains("reading"), "reading mode not applied");
  assert.equal(toggle!.textContent, "On");
  assert.equal(toggle!.getAttribute("aria-pressed"), "true");

  toggle!.click();
  assert.ok(!bodyNode.classList.contains("reading"), "reading mode not cleared");
  assert.equal(toggle!.textContent, "Off");
});

test("a stored preference is restored, and a broken one does not break the page", async () => {
  const module = await import("../src/ui/reading.ts");
  store.set("am-reading", JSON.stringify({ size: "xl", reading: true, theme: "dark" }));
  assert.deepEqual(module.load(), { size: "xl", reading: true, theme: "dark" });

  store.set("am-reading", "not json at all");
  assert.deepEqual(module.load(), { size: "m", reading: false, theme: "system" },
    "a corrupt preference should fall back, not throw");

  store.set("am-reading", JSON.stringify({ size: "enormous" }));
  assert.equal(module.load().size, "m", "an unknown size should fall back");
});

/* ---------- cover, appearance, history ---------- */

test("the app opens on the book's own front page", () => {
  // Earlier tests navigated away; return to the opening screen.
  while (!backButton.hidden) backButton.click();
  const cover = app.find("cover")[0];
  assert.ok(cover, "no front page on the home screen");

  const image = cover.all().find((n) => n.tagName === "img");
  assert.ok(image, "the front page has no image");
  assert.match(image!.getAttribute("src") ?? "", /title-page\.png$/);
  assert.match(image!.getAttribute("alt") ?? "", /Mackey/,
    "the scan has no useful alternative text");
  assert.match(cover.textContent, /3,9\d\d articles/);
});

test("appearance offers auto, light and dark", () => {
  const names = optionButtons()
    .map((b) => b.getAttribute("aria-label"))
    .filter((n) => n === "Auto" || n === "Light" || n === "Dark");
  assert.deepEqual(names, ["Auto", "Light", "Dark"]);
});

test("choosing dark applies it, and auto clears both", () => {
  optionButtons().find((b) => b.getAttribute("aria-label") === "Dark")!.click();
  assert.ok(bodyNode.classList.contains("theme-dark"), "dark not applied");
  assert.ok(!bodyNode.classList.contains("theme-light"), "both themes at once");

  optionButtons().find((b) => b.getAttribute("aria-label") === "Light")!.click();
  assert.ok(bodyNode.classList.contains("theme-light"), "light not applied");
  assert.ok(!bodyNode.classList.contains("theme-dark"), "dark not cleared");

  optionButtons().find((b) => b.getAttribute("aria-label") === "Auto")!.click();
  assert.ok(!bodyNode.classList.contains("theme-dark"));
  assert.ok(!bodyNode.classList.contains("theme-light"));
});

test("an unknown stored theme falls back to following the system", async () => {
  const module = await import("../src/ui/reading.ts");
  store.set("am-reading", JSON.stringify({ theme: "sepia" }));
  assert.equal(module.load().theme, "system");
});

test("opening an entry records it and the home screen lists it", async () => {
  const module = await import("../src/ui/history.ts");
  module.clear();

  const box = searchInput();
  box.value = "";
  box.typeInto("acacia");
  suggestionButtons()[0].click();

  const visits = module.load();
  assert.equal(visits.length, 1, `expected one visit, got ${visits.length}`);
  assert.match(visits[0].headword, /Acacia/);

  while (!backButton.hidden) backButton.click();
  const recent = app.find("recent")[0];
  assert.ok(recent, "no recently viewed section after visiting an entry");
  assert.match(recent.textContent, /Acacia/);
});

test("revisiting moves an entry up rather than duplicating it", async () => {
  const module = await import("../src/ui/history.ts");
  module.clear();
  module.record(1, "First.");
  module.record(2, "Second.");
  module.record(1, "First.");
  const visits = module.load();
  assert.equal(visits.length, 2, "a revisit duplicated the entry");
  assert.equal(visits[0].headword, "First.", "the revisit did not move to the front");
});

test("a corrupt history does not break the page", async () => {
  const module = await import("../src/ui/history.ts");
  store.set("am-history", "{{ not json");
  assert.deepEqual(module.load(), []);
  store.set("am-history", JSON.stringify([{ nonsense: true }, { id: 5, headword: "Ok." }]));
  assert.deepEqual(module.load().map((v) => v.id), [5], "malformed rows should be dropped");
});

test("history is capped so it cannot grow without bound", async () => {
  const module = await import("../src/ui/history.ts");
  module.clear();
  for (let i = 0; i < 60; i++) module.record(i, `Entry ${i}.`);
  assert.ok(module.load().length <= 40, `history grew to ${module.load().length}`);
});

test("relative times read naturally", async () => {
  const module = await import("../src/ui/history.ts");
  const now = Date.UTC(2026, 0, 2, 12, 0, 0);
  assert.equal(module.when(now - 10_000, now), "just now");
  assert.equal(module.when(now - 60_000, now), "1 minute ago");
  assert.equal(module.when(now - 3_600_000, now), "1 hour ago");
  assert.equal(module.when(now - 86_400_000 * 3, now), "3 days ago");
});

/* ---------- page by page ---------- */

function pageBar(): StubNode | undefined {
  return app.find("pagebar")[0];
}

function pageButton(label: RegExp): StubNode | undefined {
  return app.find("pagestep").find((b) => label.test(b.textContent));
}

test("the front page offers reading the book page by page", () => {
  while (!backButton.hidden) backButton.click();
  const browse = app.find("browse")[0];
  assert.ok(browse, "no way into the page-by-page view");
  browse.click();
  assert.ok(pageBar(), "the page view did not open");
  assert.match(pageBar()!.textContent, /Page \d+ of \d+/);
});

test("printed page numbers are plausible for a 950-page book", () => {
  const label = pageBar()!.textContent;
  const numbers = (label.match(/\d+/g) ?? []).map(Number);
  for (const n of numbers) {
    assert.ok(n >= 1 && n <= 1000,
      `page number out of range for this book: ${n} (folio OCR errors once gave 8387)`);
  }
});

test("a page lists the articles that begin on it", () => {
  const rows = app.find("result");
  assert.ok(rows.length > 0, "no articles listed for this page");
  for (const row of rows.slice(0, 3)) {
    assert.match(row.textContent, /p\. \d+/, "an article shows no page reference");
  }
});

test("next and previous move through the book in order", () => {
  const readPage = () => Number((pageBar()!.textContent.match(/Page (\d+)/) ?? [])[1]);
  const first = readPage();

  pageButton(/Next/)!.click();
  const second = readPage();
  assert.ok(second > first, `next went backwards: ${first} then ${second}`);

  pageButton(/Previous/)!.click();
  assert.equal(readPage(), first, "previous did not return to where we were");
});

test("previous is disabled on the first page of the book", () => {
  const readPage = () => Number((pageBar()!.textContent.match(/Page (\d+)/) ?? [])[1]);
  // Walk back to the start.
  let guard = 0;
  while (!pageButton(/Previous/)!.disabled && guard++ < 2000) {
    pageButton(/Previous/)!.click();
  }
  assert.ok(pageButton(/Previous/)!.disabled, "previous never became unavailable");
  assert.ok(readPage() >= 1, "walked off the front of the book");
  assert.ok(!pageButton(/Next/)!.disabled, "next unavailable at the start");
});

test("jumping to a page lands on or near it", () => {
  const field = app.all().find((n) => n.tagName === "input" &&
    n.getAttribute("aria-label") === "Go to printed page");
  assert.ok(field, "no page jump field");
  field!.value = "500";
  app.find("pagestep").find((b) => b.textContent === "Go")!.click();

  const landed = Number((pageBar()!.textContent.match(/Page (\d+)/) ?? [])[1]);
  assert.ok(Math.abs(landed - 500) <= 5, `asked for 500, landed on ${landed}`);
});

test("opening an article from a page view works", () => {
  const row = app.find("result")[0];
  assert.ok(row, "nothing to open");
  row.click();
  assert.equal(app.find("entry").length, 1, "the article did not open");
});

test("the home page offers an about panel", () => {
  while (!backButton.hidden) backButton.click();
  const about = app.find("about-link")[0];
  assert.ok(about, "no About control on the home page");
  assert.equal(about.textContent, "About");
});

test("about names the compiler and states the disclaimer", () => {
  while (!backButton.hidden) backButton.click();
  bodyNode.find("modal").forEach((node) => node.remove());
  app.find("about-link")[0].click();

  const card = bodyNode.find("modal-card")[0];
  assert.ok(card, "clicking About opened nothing");
  const text = card.textContent;
  assert.match(text, /Arnie T\./, "the compiler is not credited");
  assert.match(text, /Brethren's reference/, "who it was compiled for is missing");
  assert.match(text, /Hughan/, "the edition is not named");
  assert.match(text, /free of charge for education and private study/);
  assert.match(text, /may not be sold/);
  assert.match(text, /neither published nor endorsed by any Grand Lodge/);
});

test("about closes again, and does not leave its key handler behind", () => {
  while (!backButton.hidden) backButton.click();
  bodyNode.find("modal").forEach((node) => node.remove());
  app.find("about-link")[0].click();
  const before = documentListeners("keydown");
  bodyNode.find("close")[0].click();
  assert.equal(bodyNode.find("modal-card").length, 0, "the panel did not close");
  assert.equal(documentListeners("keydown"), before - 1,
    "the Escape handler outlived the panel it belonged to");
});
