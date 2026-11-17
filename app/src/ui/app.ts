/**
 * The app shell: home, results, entry.
 *
 * No framework. The three screens render from one state object into one
 * container, which at this size is less code than wiring a library would be
 * and leaves nothing to download.
 *
 * Headword search answers immediately. The definition index takes about two
 * seconds to build over 4 MB of text, so it is warmed once the first paint is
 * done and the current query is then re-run for the fuller result set.
 */

import { loadDictionary } from "../core/data/load.ts";
import type { Dictionary, Result, Meta } from "../core/search/engine.ts";
import { Band, BAND_LABEL } from "../core/search/engine.ts";

type Screen =
  | { name: "home" }
  | { name: "results"; query: string }
  | { name: "entry"; id: number; query: string };

let dictionary: Dictionary | null = null;
let meta: Meta | null = null;
let screen: Screen = { name: "home" };
let history: Screen[] = [];

const root = document.getElementById("app") as HTMLElement;
const backButton = document.getElementById("back") as HTMLButtonElement;
const searchbar = document.getElementById("searchbar") as HTMLElement;

/*
  The search field is created once and never replaced.

  It used to be part of each screen, so every keystroke rebuilt the element
  being typed into: the caret jumped, and on a phone the keyboard closed and
  reopened. Keeping it outside the screens also means suggestions can appear
  under it without the screen behind them re-rendering.
*/
let input: HTMLInputElement;
let suggestPanel: HTMLElement;
let suggestions: Result[] = [];
let activeSuggestion = -1;

function go(next: Screen, replace = false): void {
  if (!replace) history.push(screen);
  screen = next;
  render();
}

function back(): void {
  const previous = history.pop();
  screen = previous ?? { name: "home" };
  render();
}

backButton.addEventListener("click", back);

/* ---------- rendering ---------- */

function render(): void {
  backButton.hidden = history.length === 0;
  // Navigation can change the query without the field knowing: a letter from
  // the alphabet strip, or Back. Keep the box showing what is on screen.
  if (input) {
    const shown = screen.name === "results" && !screen.query.startsWith("letter:")
      ? screen.query
      : screen.name === "home" ? "" : input.value;
    if (document.activeElement !== input) input.value = shown;
  }
  root.innerHTML = "";
  if (!dictionary) {
    root.append(element("div", { class: "loading" }, "Opening the encyclopaedia…"));
    return;
  }
  if (screen.name === "home") root.append(renderHome());
  else if (screen.name === "results") root.append(renderResults(screen.query));
  else root.append(renderEntry(screen.id, screen.query));
}

function renderHome(): HTMLElement {
  const wrap = element("div", { class: "wrap" });
  const hero = element("section", { class: "hero" });
  hero.append(
    element("h1", {}, "Mackey's Encyclopaedia of Freemasonry"),
    element("p", {}, `${dictionary!.size.toLocaleString()} articles from the revised edition of 1912, searchable offline.`),
  );
  wrap.append(hero, renderAlphabet());
  return wrap;
}

function renderAlphabet(): HTMLElement {
  const section = element("section", { class: "alphabet" });
  section.append(element("h2", { class: "sans" }, "Browse by letter"));

  const counts = dictionary!.letterCounts();
  const letters = Object.keys(counts).filter((key) => /^[A-Z]$/.test(key)).sort();
  const peak = Math.max(...letters.map((letter) => counts[letter]));
  const grid = element("div", { class: "letters" });

  for (const letter of letters) {
    const count = counts[letter];
    const button = element("button", {
      class: "letter",
      type: "button",
      // The bar is the information: how much of the book sits under this
      // letter. Announce the number rather than leaving it to the picture.
      "aria-label": `${letter}, ${count} entries`,
      title: `${count} entries`,
    });
    const bar = element("i");
    bar.style.height = `${Math.max(3, Math.round((count / peak) * 44))}px`;
    button.append(bar, element("b", {}, letter));
    button.addEventListener("click", () => go({ name: "results", query: `letter:${letter}` }));
    grid.append(button);
  }
  section.append(grid);
  return section;
}

function buildSearchBar(): void {
  const wrap = element("div", { class: "wrap" });
  const field = element("div", { class: "search-field" });

  input = element("input", {
    type: "search",
    placeholder: "Search 3,952 articles",
    autocapitalize: "none",
    autocorrect: "off",
    spellcheck: "false",
    role: "combobox",
    "aria-expanded": "false",
    "aria-controls": "suggest",
    "aria-autocomplete": "list",
    "aria-label": "Search the encyclopaedia",
  }) as HTMLInputElement;

  const clear = element("button", {
    class: "search-clear", type: "button", "aria-label": "Clear search",
  }, "\u00d7");
  clear.hidden = true;

  suggestPanel = element("div", { class: "suggest", id: "suggest", role: "listbox" });
  suggestPanel.hidden = true;

  input.addEventListener("input", () => {
    clear.hidden = input.value === "";
    showSuggestions(input.value);
  });

  input.addEventListener("keydown", (event) => {
    const key = (event as KeyboardEvent).key;
    if (key === "ArrowDown" || key === "ArrowUp") {
      if (suggestions.length === 0) return;
      event.preventDefault();
      const step = key === "ArrowDown" ? 1 : -1;
      activeSuggestion = (activeSuggestion + step + suggestions.length + 1) %
        (suggestions.length + 1) - (step === -1 && activeSuggestion === -1 ? 0 : 0);
      if (activeSuggestion > suggestions.length - 1) activeSuggestion = -1;
      if (activeSuggestion < -1) activeSuggestion = suggestions.length - 1;
      markActive();
    } else if (key === "Enter") {
      event.preventDefault();
      if (activeSuggestion >= 0 && suggestions[activeSuggestion]) {
        openEntry(suggestions[activeSuggestion].id, input.value.trim());
      } else {
        runSearch(input.value.trim());
      }
    } else if (key === "Escape") {
      hideSuggestions();
    }
  });

  input.addEventListener("blur", () => {
    // Late enough for a click on a suggestion to land first.
    setTimeout(hideSuggestions, 120);
  });

  input.addEventListener("focus", () => {
    if (input.value.trim()) showSuggestions(input.value);
  });

  clear.addEventListener("click", () => {
    input.value = "";
    clear.hidden = true;
    hideSuggestions();
    go({ name: "home" }, screen.name !== "home");
    input.focus();
  });

  field.append(input, clear);
  wrap.append(field, suggestPanel);
  searchbar.append(wrap);
}

/**
 * Headword matches, as the characters arrive.
 *
 * Headword search needs no index and answers in well under a millisecond, so
 * this runs on every keystroke without debouncing. Definitions are not
 * searched here: that would need the big index and would stall typing.
 */
function showSuggestions(raw: string): void {
  const query = raw.trim();
  activeSuggestion = -1;
  if (!dictionary || query.length < 1) {
    hideSuggestions();
    return;
  }

  suggestions = dictionary.suggest(query, 8);
  suggestPanel.innerHTML = "";

  if (suggestions.length === 0) {
    const near = dictionary.headwords.fuzzy(query, 4);
    if (near.length === 0) {
      hideSuggestions();
      return;
    }
    suggestions = near.flatMap((hit) => {
      const entry = dictionary!.entry(hit.id);
      return entry
        ? [{ id: hit.id, headword: entry.headword, letter: "", printedPage: entry.printedPage, band: Band.FuzzyHeadword, score: 0 }]
        : [];
    });
  }

  suggestions.forEach((result, position) => {
    const option = element("button", {
      class: "suggestion", type: "button", role: "option",
      id: `suggestion-${position}`, "aria-selected": "false",
    });
    option.append(markMatch(result.headword, query));
    if (result.band === Band.FuzzyHeadword) {
      option.append(element("em", {}, "closest match"));
    } else if (result.printedPage) {
      option.append(element("em", {}, `page ${result.printedPage}`));
    }
    option.addEventListener("mousedown", (event) => event.preventDefault());
    option.addEventListener("click", () => openEntry(result.id, query));
    suggestPanel.append(option);
  });

  const all = element("button", {
    class: "suggestion suggest-all", type: "button",
  }, `Search every article for \u201c${query}\u201d`);
  all.addEventListener("mousedown", (event) => event.preventDefault());
  all.addEventListener("click", () => runSearch(query));
  suggestPanel.append(all);

  suggestPanel.hidden = false;
  input.setAttribute("aria-expanded", "true");
}

/** Mark where the query falls inside the headword. */
function markMatch(headword: string, query: string): HTMLElement {
  const line = element("span");
  const at = headword.toLowerCase().indexOf(query.toLowerCase());
  if (at === -1) {
    line.textContent = headword;
    return line;
  }
  if (at > 0) line.append(headword.slice(0, at));
  line.append(element("mark", {}, headword.slice(at, at + query.length)));
  line.append(headword.slice(at + query.length));
  return line;
}

function markActive(): void {
  const options = suggestPanel.children;
  for (let i = 0; i < options.length; i++) {
    const option = options[i] as HTMLElement;
    const selected = i === activeSuggestion;
    option.setAttribute("aria-selected", selected ? "true" : "false");
  }
  input.setAttribute("aria-activedescendant",
    activeSuggestion >= 0 ? `suggestion-${activeSuggestion}` : "");
}

function hideSuggestions(): void {
  suggestions = [];
  activeSuggestion = -1;
  suggestPanel.hidden = true;
  suggestPanel.innerHTML = "";
  input.setAttribute("aria-expanded", "false");
}

function openEntry(id: number, query: string): void {
  hideSuggestions();
  input.blur();
  go({ name: "entry", id, query });
}

function runSearch(query: string): void {
  hideSuggestions();
  input.blur();
  if (!query) {
    go({ name: "home" }, screen.name !== "home");
    return;
  }
  go({ name: "results", query }, screen.name === "results");
}

function renderResults(query: string): HTMLElement {
  const wrap = element("div", { class: "wrap" });
  const results = query.startsWith("letter:")
    ? dictionary!.byLetter(query.slice(7))
    : dictionary!.search(query, { limit: 120 });

  if (results.length === 0) {
    wrap.append(emptyState(query));
    return wrap;
  }

  const heading = query.startsWith("letter:")
    ? `${results.length} entries under ${query.slice(7)}`
    : `${results.length} result${results.length === 1 ? "" : "s"} for “${query}”`;
  wrap.append(element("p", { class: "count" }, heading));

  if (!query.startsWith("letter:") && !dictionary!.isWarm) {
    wrap.append(element("p", { class: "warming" },
      "Searching headwords. Definitions are still loading…"));
  }

  let lastBand: number | null = null;
  for (const result of results) {
    if (!query.startsWith("letter:") && result.band !== lastBand) {
      wrap.append(element("p", { class: "band-label" }, BAND_LABEL[result.band]));
      lastBand = result.band;
    }
    wrap.append(resultRow(result, query));
  }
  return wrap;
}

function resultRow(result: Result, query: string): HTMLElement {
  const entry = dictionary!.entry(result.id);
  const button = element("button", { class: "result", type: "button" });
  const head = element("p", { class: "result-head" }, result.headword);
  if (result.printedPage) {
    head.append(element("span", { class: "result-page" }, `p. ${result.printedPage}`));
  }
  button.append(head);
  if (entry) {
    button.append(element("p", { class: "result-body" }, entry.body.slice(0, 180)));
  }
  button.addEventListener("click", () => go({ name: "entry", id: result.id, query }));
  return button;
}

function renderEntry(id: number, query: string): HTMLElement {
  const entry = dictionary!.entry(id);
  const wrap = element("div", { class: "wrap" });
  if (!entry) {
    wrap.append(element("p", { class: "empty" }, "That entry could not be found."));
    return wrap;
  }

  const article = element("article", { class: "entry" });
  article.append(element("h1", {}, entry.headword));

  const page = entry.printedPage
    ? `Page ${entry.printedPage} of the printed edition`
    : "Page number not recovered from the scan";
  article.append(element("p", { class: "entry-meta" }, page));

  if (entry.needsReview) {
    article.append(element("p", { class: "review-note" },
      "This entry was flagged during extraction. The wording may differ from the printed page."));
  }

  const body = element("div", { class: "entry-body" });
  const terms = query && !query.startsWith("letter:") ? query : "";
  for (const paragraph of splitParagraphs(entry.body)) {
    body.append(highlight(paragraph, terms));
  }
  article.append(body);

  const refs = dictionary!.referencesFrom(id);
  if (refs.length) {
    const section = element("section", { class: "refs" });
    section.append(element("h2", { class: "sans" }, "Mackey refers you to"));
    for (const ref of refs) {
      const button = element("button", { class: "ref", type: "button" }, ref.rawTarget);
      if (ref.toEntry === null) {
        button.disabled = true;
        button.title = "Not found in this edition";
      } else {
        button.addEventListener("click", () =>
          go({ name: "entry", id: ref.toEntry as number, query: "" }));
      }
      section.append(button);
    }
    article.append(section);
  }

  wrap.append(article);
  return wrap;
}

function emptyState(query: string): HTMLElement {
  const box = element("div", { class: "empty" });
  box.append(element("p", {}, `Nothing matches “${query}”.`));
  const suggestions = dictionary!.headwords.fuzzy(query, 5);
  if (suggestions.length) {
    box.append(element("p", {}, "Did you mean:"));
    for (const hit of suggestions) {
      const entry = dictionary!.entry(hit.id);
      if (!entry) continue;
      const button = element("button", { class: "ref", type: "button" }, entry.headword);
      button.addEventListener("click", () => go({ name: "entry", id: hit.id, query: "" }));
      box.append(button);
    }
  } else {
    box.append(element("p", {},
      "This is a Masonic encyclopaedia, so it covers ritual, history and symbolism rather than general English."));
  }
  return box;
}

/* ---------- text ---------- */

function splitParagraphs(body: string): string[] {
  // Mackey's articles arrive as one run of text. Long ones are easier to read
  // broken at sentence boundaries near a comfortable length.
  if (body.length < 700) return [body];
  const sentences = body.split(/(?<=\.)\s+(?=[A-Z])/);
  const paragraphs: string[] = [];
  let current = "";
  for (const sentence of sentences) {
    current = current ? `${current} ${sentence}` : sentence;
    if (current.length > 420) {
      paragraphs.push(current);
      current = "";
    }
  }
  if (current) paragraphs.push(current);
  return paragraphs;
}

function highlight(text: string, query: string): HTMLElement {
  const paragraph = element("p");
  const needle = query.trim().toLowerCase();
  if (!needle || needle.length < 2) {
    paragraph.textContent = text;
    return paragraph;
  }
  const haystack = text.toLowerCase();
  let from = 0;
  let found = false;
  for (;;) {
    const at = haystack.indexOf(needle, from);
    if (at === -1) break;
    found = true;
    if (at > from) paragraph.append(text.slice(from, at));
    paragraph.append(element("mark", {}, text.slice(at, at + needle.length)));
    from = at + needle.length;
  }
  if (!found) {
    paragraph.textContent = text;
    return paragraph;
  }
  if (from < text.length) paragraph.append(text.slice(from));
  return paragraph;
}

/* ---------- helpers ---------- */

function element(
  tag: string,
  attributes: Record<string, string> = {},
  text?: string,
): HTMLElement {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attributes)) {
    if (key === "value") (node as HTMLInputElement).value = value;
    else node.setAttribute(key, value);
  }
  if (text !== undefined) node.textContent = text;
  return node;
}

/* ---------- start ---------- */

async function start(): Promise<void> {
  try {
    const loaded = await loadDictionary("data");
    dictionary = loaded.dictionary;
    meta = loaded.meta;
    buildSearchBar();
    render();

    // Build the definition index once the first paint is done, then repeat the
    // current search so results fill out without the user doing anything.
    const warm = () => {
      dictionary!.warm();
      if (screen.name === "results") render();
    };
    if ("requestIdleCallback" in window) {
      (window as unknown as { requestIdleCallback: (fn: () => void) => void })
        .requestIdleCallback(warm);
    } else {
      setTimeout(warm, 200);
    }
  } catch (error) {
    root.innerHTML = "";
    root.append(element("div", { class: "wrap" },
      "The dictionary could not be loaded. Reload the page to try again."));
    console.error(error);
  }
}

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("sw.js").catch(() => {
      /* Offline support is a bonus; the app works without it. */
    });
  });
}

start();
