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

import { loadDictionary } from "../core/data/load.js";
import { stripMarkers } from "../core/normalise.js";
import * as reading from "./reading.js";
import * as gate from "./gate.js";
// Named `recents` because `history` is already the navigation stack here.
import * as recents from "./history.js";
                                                                         
import { Band, BAND_LABEL } from "../core/search/engine.js";

             
                    
                                      
                                                
                                    

let dictionary                    = null;
let meta              = null;
let screen         = { name: "home" };
let history           = [];

const root = document.getElementById("app")               ;
const backButton = document.getElementById("back")                     ;
const searchbar = document.getElementById("searchbar")               ;
const typeset = document.getElementById("typeset")                            ;

let preferences = reading.load();
let optionsPanel                     = null;

/*
  The search field is created once and never replaced.

  It used to be part of each screen, so every keystroke rebuilt the element
  being typed into: the caret jumped, and on a phone the keyboard closed and
  reopened. Keeping it outside the screens also means suggestions can appear
  under it without the screen behind them re-rendering.
*/
let input                  ;
let suggestPanel             ;
let suggestions           = [];
let activeSuggestion = -1;

function go(next        , replace = false)       {
  if (!replace) history.push(screen);
  screen = next;
  render();
}

function back()       {
  const previous = history.pop();
  screen = previous ?? { name: "home" };
  render();
}

backButton.addEventListener("click", back);

/* ---------- rendering ---------- */

function render()       {
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
  else if (screen.name === "pages") root.append(renderPages(screen.page));
  else root.append(renderEntry(screen.id, screen.query));
}

function renderHome()              {
  const wrap = element("div", { class: "wrap" });

  wrap.append(renderFrontPage());

  const recent = renderRecent();
  if (recent) wrap.append(recent);
  wrap.append(renderAlphabet());
  return wrap;
}

/**
 * The title page, redrawn.
 *
 * The scan of it was handsome but it was a photograph of paper: a fixed grey
 * image that had to be inverted at night and shipped 116 KB to say what the
 * app can set itself. Drawn in the app's own type and colour it scales, reads
 * correctly in both themes, and costs nothing.
 */
function renderFrontPage()              {
  const cover = element("section", { class: "cover" });
  const figure = element("figure");
  figure.append(element("img", {
    src: new URL("../img/title-page.png", import.meta.url).href,
    alt: "Title page: An Encyclop\u00e6dia of Freemasonry and Its Kindred "
       + "Sciences, by Albert G. Mackey, new and revised edition, 1914",
    width: "760",
    height: "1299",
  }));
  figure.append(element("figcaption", {},
    `${dictionary .size.toLocaleString()} articles, searchable offline`));
  cover.append(figure);

  const browse = element("button", { class: "browse", type: "button" },
    "Read the book page by page");
  browse.addEventListener("click", () => go({ name: "pages", page: firstPage() }));
  cover.append(browse);

  const about = element("button", { class: "about-link sans", type: "button" }, "About");
  about.addEventListener("click", openAbout);
  cover.append(about);
  return cover;
}

/* ---------- about ---------- */

const ABOUT_TEXT = [
  "Albert G. Mackey's An Encyclopaedia of Freemasonry and Its Kindred "
  + "Sciences, in the New and Revised Edition prepared by William J. Hughan "
  + "and Edward L. Hawkins and published by The Masonic History Company in "
  + "1914.",
  "The text was read from a scan of the printed book a page at a time, then "
  + "checked word by word against a second printing of the same edition. "
  + "Where the two disagreed, the page itself was read again and settled it.",
  "Compiled into a mobile application for the Brethren's reference by Arnie T.",
];

const DISCLAIMER = [
  "This application is provided free of charge for education and private "
  + "study. It may not be sold, licensed, or put to any commercial use, and "
  + "it may not be bundled with any product or service that is offered for "
  + "sale. The encyclopaedia itself is in the public domain, and this "
  + "compilation is shared in the same spirit: it must remain free to "
  + "everyone who receives it.",
  "The text is a transcription of a scanned book and may contain errors of "
  + "recognition. It carries no official standing, and it is neither "
  + "published nor endorsed by any Grand Lodge or other Masonic body. Where "
  + "accuracy matters, consult the printed edition.",
];

/** The about panel, as a dialog over the page. */
function openAbout()       {
  const overlay = element("div", { class: "modal" });
  const card = element("div", {
    class: "modal-card", role: "dialog", "aria-modal": "true",
    "aria-labelledby": "about-title",
  });

  card.append(element("h2", { class: "sans", id: "about-title" }, "About"));
  for (const paragraph of ABOUT_TEXT) card.append(element("p", {}, paragraph));

  card.append(element("h3", { class: "sans" }, "Disclaimer"));
  for (const paragraph of DISCLAIMER) {
    card.append(element("p", { class: "fine" }, paragraph));
  }

  const close = element("button", { class: "close sans", type: "button" }, "Close");
  const dismiss = ()       => {
    overlay.remove();
    document.removeEventListener("keydown", onKey);
  };
  // Named rather than inline so the same reference can be removed again:
  // an anonymous listener here would outlive every panel ever opened.
  function onKey(event               )       {
    if (event.key === "Escape") dismiss();
  }
  close.addEventListener("click", dismiss);
  overlay.addEventListener("click", (event       ) => {
    if (event.target === overlay) dismiss();
  });
  document.addEventListener("keydown", onKey);

  card.append(close);
  overlay.append(card);
  document.body.append(overlay);
  close.focus();
}

/* ---------- page by page ---------- */

let pageNumbers           = [];

/** Every printed page that has an entry beginning on it, in order. */
function pages()           {
  if (pageNumbers.length === 0) {
    const found = new Set        ();
    for (const row of dictionary .headwords.rows) {
      const page = row[4];
      if (page > 0) found.add(page);
    }
    pageNumbers = [...found].sort((a, b) => a - b);
  }
  return pageNumbers;
}

function firstPage()         {
  return pages()[0] ?? 1;
}

function stepPage(from        , direction        )                {
  const all = pages();
  const at = all.indexOf(from);
  if (at === -1) {
    // Not a page that starts an entry: move to the nearest one that does.
    const next = direction === 1
      ? all.find((page) => page > from)
      : [...all].reverse().find((page) => page < from);
    return next ?? null;
  }
  return all[at + direction] ?? null;
}

function renderPages(page        )              {
  const wrap = element("div", { class: "wrap" });
  const all = pages();
  const position = all.indexOf(page);

  const bar = element("div", { class: "pagebar" });
  const previous = element("button", { class: "pagestep", type: "button" },
    "\u2190 Previous");
  const next = element("button", { class: "pagestep", type: "button" },
    "Next \u2192");
  const back = stepPage(page, -1);
  const forward = stepPage(page, 1);
  previous.disabled = back === null;
  next.disabled = forward === null;
  previous.addEventListener("click", () => {
    if (back !== null) go({ name: "pages", page: back }, true);
  });
  next.addEventListener("click", () => {
    if (forward !== null) go({ name: "pages", page: forward }, true);
  });

  const label = element("span", { class: "pagelabel" },
    `Page ${page}` + (position >= 0 ? ` of ${all[all.length - 1]}` : ""));
  bar.append(previous, label, next);
  wrap.append(bar);

  const entries = dictionary .byPage(page);
  if (entries.length === 0) {
    wrap.append(element("p", { class: "empty" },
      "No article begins on this page."));
  }
  for (const result of entries) {
    wrap.append(resultRow(result, ""));
  }

  const jump = element("div", { class: "pagejump" });
  const field = element("input", {
    type: "number", min: String(all[0] ?? 1), max: String(all[all.length - 1] ?? 1),
    value: String(page), "aria-label": "Go to printed page",
  })                    ;
  const goButton = element("button", { class: "pagestep", type: "button" }, "Go");
  const jumpTo = () => {
    const wanted = Number(field.value);
    if (!Number.isFinite(wanted)) return;
    const nearest = all.includes(wanted)
      ? wanted
      : all.reduce((best, candidate) =>
          Math.abs(candidate - wanted) < Math.abs(best - wanted) ? candidate : best,
          all[0]);
    go({ name: "pages", page: nearest }, true);
  };
  goButton.addEventListener("click", jumpTo);
  field.addEventListener("keydown", (event) => {
    if ((event                 ).key === "Enter") jumpTo();
  });
  jump.append(element("span", { class: "sans" }, "Go to page"), field, goButton);
  wrap.append(jump);
  return wrap;
}

function renderRecent()                     {
  const visits = recents.load().filter((visit) => dictionary .entry(visit.id));
  if (visits.length === 0) return null;

  const section = element("section", { class: "recent" });
  section.append(element("h2", { class: "sans" }, "Recently viewed"));
  for (const visit of visits.slice(0, 8)) {
    const button = element("button", { class: "recent-item", type: "button" });
    button.append(document.createTextNode(visit.headword));
    button.append(element("em", {}, recents.when(visit.at)));
    button.addEventListener("click", () => go({ name: "entry", id: visit.id, query: "" }));
    section.append(button);
  }
  const clear = element("button", { class: "recent-clear", type: "button" },
    "Clear history");
  clear.addEventListener("click", () => {
    recents.clear();
    render();
  });
  section.append(clear);
  return section;
}

function renderAlphabet()              {
  const section = element("section", { class: "alphabet" });
  section.append(element("h2", { class: "sans" }, "Browse by letter"));

  const counts = dictionary .letterCounts();
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

function buildSearchBar()       {
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
  })                    ;

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
    const key = (event                 ).key;
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
function showSuggestions(raw        )       {
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
      const entry = dictionary .entry(hit.id);
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
function markMatch(headword        , query        )              {
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

function markActive()       {
  const options = suggestPanel.children;
  for (let i = 0; i < options.length; i++) {
    const option = options[i]               ;
    const selected = i === activeSuggestion;
    option.setAttribute("aria-selected", selected ? "true" : "false");
  }
  input.setAttribute("aria-activedescendant",
    activeSuggestion >= 0 ? `suggestion-${activeSuggestion}` : "");
}

function hideSuggestions()       {
  suggestions = [];
  activeSuggestion = -1;
  suggestPanel.hidden = true;
  suggestPanel.innerHTML = "";
  input.setAttribute("aria-expanded", "false");
}

function openEntry(id        , query        )       {
  hideSuggestions();
  input.blur();
  go({ name: "entry", id, query });
}

function runSearch(query        )       {
  hideSuggestions();
  input.blur();
  if (!query) {
    go({ name: "home" }, screen.name !== "home");
    return;
  }
  go({ name: "results", query }, screen.name === "results");
}

function renderResults(query        )              {
  const wrap = element("div", { class: "wrap" });
  const results = query.startsWith("letter:")
    ? dictionary .byLetter(query.slice(7))
    : dictionary .search(query, { limit: 120 });

  if (results.length === 0) {
    wrap.append(emptyState(query));
    return wrap;
  }

  const heading = query.startsWith("letter:")
    ? `${results.length} entries under ${query.slice(7)}`
    : `${results.length} result${results.length === 1 ? "" : "s"} for “${query}”`;
  wrap.append(element("p", { class: "count" }, heading));

  if (!query.startsWith("letter:") && !dictionary .isWarm) {
    wrap.append(element("p", { class: "warming" },
      "Searching headwords. Definitions are still loading…"));
  }

  let lastBand                = null;
  for (const result of results) {
    if (!query.startsWith("letter:") && result.band !== lastBand) {
      wrap.append(element("p", { class: "band-label" }, BAND_LABEL[result.band]));
      lastBand = result.band;
    }
    wrap.append(resultRow(result, query));
  }
  return wrap;
}

function resultRow(result        , query        )              {
  const entry = dictionary .entry(result.id);
  const button = element("button", { class: "result", type: "button" });
  const head = element("p", { class: "result-head" }, result.headword);
  if (result.printedPage) {
    head.append(element("span", { class: "result-page" }, `p. ${result.printedPage}`));
  }
  button.append(head);
  if (entry) {
    button.append(element("p", { class: "result-body" },
      stripMarkers(entry.body).slice(0, 180)));
  }
  button.addEventListener("click", () => go({ name: "entry", id: result.id, query }));
  return button;
}

function renderEntry(id        , query        )              {
  const entry = dictionary .entry(id);
  if (entry) recents.record(id, entry.headword);
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
  if (entry.body.trim()) {
    for (const paragraph of splitParagraphs(entry.body)) {
      body.append(renderParagraph(paragraph, terms));
    }
  } else {
    // A dozen headwords came through the scan with no text under them. A
    // blank page reads as a broken app; saying so, and saying where to look
    // instead, reads as a book with a gap in it, which is what this is.
    body.append(element("p", { class: "empty" },
      entry.printedPage
        ? `The text of this article was not recovered from the scan. It is on page ${entry.printedPage} of the printed edition.`
        : "The text of this article was not recovered from the scan."));
  }
  article.append(body);

  const refs = dictionary .referencesFrom(id);
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
          go({ name: "entry", id: ref.toEntry          , query: "" }));
      }
      section.append(button);
    }
    article.append(section);
  }

  wrap.append(article);
  return wrap;
}

function emptyState(query        )              {
  const box = element("div", { class: "empty" });
  box.append(element("p", {}, `Nothing matches “${query}”.`));
  const suggestions = dictionary .headwords.fuzzy(query, 5);
  if (suggestions.length) {
    box.append(element("p", {}, "Did you mean:"));
    for (const hit of suggestions) {
      const entry = dictionary .entry(hit.id);
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

/* ---------- reading options ---------- */

function buildReadingOptions()       {
  if (!typeset) return;
  optionsPanel = reading.buildPanel(preferences, () => render());
  searchbar.parentElement?.insertBefore(optionsPanel, searchbar.nextSibling);

  typeset.addEventListener("click", () => {
    if (!optionsPanel) return;
    const open = optionsPanel.hidden;
    optionsPanel.hidden = !open;
    typeset.setAttribute("aria-expanded", String(open));
  });
}

/* ---------- text ---------- */

const ITALIC_OPEN = "\u0002";
const ITALIC_CLOSE = "\u0003";

function splitParagraphs(body        )           {
  carriedItalic = false;
  // Mackey's articles arrive as one run of text. Long ones are easier to read
  // broken at sentence boundaries near a comfortable length.
  if (body.length < 700) return [body];
  const sentences = body.split(/(?<=\.)\s+(?=[A-Z])/);
  const paragraphs           = [];
  let current = "";
  for (const sentence of sentences) {
    current = current ? `${current} ${sentence}` : sentence;
    if (current.length > 420) {
      paragraphs.push(current);
      current = "";
    }
  }
  if (current) paragraphs.push(current);
  return paragraphs.map(balanceMarkers);
}

/**
 * Keep each paragraph's italic markers balanced.
 *
 * A long entry is broken into paragraphs at sentence boundaries, and a run of
 * italics can span one of those breaks. Left alone the first paragraph never
 * closes and the second never opens, so the italics simply vanish from the
 * rest of the entry.
 */
let carriedItalic = false;

function balanceMarkers(paragraph        )         {
  let text = paragraph;
  if (carriedItalic) text = ITALIC_OPEN + text;
  let open = carriedItalic;
  for (const character of paragraph) {
    if (character === ITALIC_OPEN) open = true;
    else if (character === ITALIC_CLOSE) open = false;
  }
  carriedItalic = open;
  if (open) text += ITALIC_CLOSE;
  return text;
}

/**
 * Render one paragraph, turning italic markers into emphasis and marking the
 * search term.
 *
 * Mackey italicises foreign terms, book titles and the target of every
 * cross-reference, and that distinction is part of what the entry says.
 */
function renderParagraph(text        , query        )              {
  const paragraph = element("p");
  for (const [chunk, italic] of splitItalics(text)) {
    const host = italic ? element("em") : paragraph;
    fillWithHighlights(host, chunk, query);
    if (italic) paragraph.append(host);
  }
  return paragraph;
}

/** Split marked text into runs, each flagged italic or not. */
function splitItalics(text        )                           {
  const runs                           = [];
  let buffer = "";
  let italic = false;
  for (const character of text) {
    if (character === "\u0002" || character === "\u0003") {
      const wanted = character === "\u0002";
      if (wanted !== italic) {
        if (buffer) runs.push([buffer, italic]);
        buffer = "";
        italic = wanted;
      }
      continue;
    }
    buffer += character;
  }
  if (buffer) runs.push([buffer, italic]);
  return runs;
}

function fillWithHighlights(host             , text        , query        )       {
  const needle = query.trim().toLowerCase();
  if (!needle || needle.length < 2) {
    host.append(text);
    return;
  }
  const haystack = text.toLowerCase();
  let from = 0;
  for (;;) {
    const at = haystack.indexOf(needle, from);
    if (at === -1) break;
    if (at > from) host.append(text.slice(from, at));
    host.append(element("mark", {}, text.slice(at, at + needle.length)));
    from = at + needle.length;
  }
  if (from < text.length) host.append(text.slice(from));
}

/* ---------- helpers ---------- */

function element(
  tag        ,
  attributes                         = {},
  text         ,
)              {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attributes)) {
    if (key === "value") (node                    ).value = value;
    else node.setAttribute(key, value);
  }
  if (text !== undefined) node.textContent = text;
  return node;
}

/* ---------- start ---------- */

async function start()                {
  try {
    // The book loads while the door is shut, so answering opens it at once
    // instead of starting a five-megabyte wait at that moment.
    const loading = loadDictionary();
    // Once per installation, not once per opening: a copy that has been
    // admitted opens into the book.
    if (!gate.admittedBefore()) {
      await new Promise      ((open) => gate.guard(root, open));
    }

    const loaded = await loading;
    dictionary = loaded.dictionary;
    meta = loaded.meta;
    buildSearchBar();
    buildReadingOptions();
    reading.apply(preferences);
    render();

    // Build the definition index once the first paint is done, then repeat the
    // current search so results fill out without the user doing anything.
    const warm = () => {
      dictionary .warm();
      if (screen.name === "results") render();
    };
    if ("requestIdleCallback" in window) {
      (window                                                                )
        .requestIdleCallback(warm);
    } else {
      setTimeout(warm, 200);
    }
  } catch (error) {
    root.innerHTML = "";
    const box = element("div", { class: "wrap empty" });
    box.append(element("p", {}, "The dictionary could not be loaded."));
    box.append(element("p", { class: "sans" }, String(
      error instanceof Error ? error.message : error)));
    root.append(box);
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
