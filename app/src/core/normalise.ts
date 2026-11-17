/**
 * Normalisation rules, shared with the extraction pipeline.
 *
 * CRITICAL: this must behave identically to pipeline/parse/normalise.py.
 * A query normalised differently from the stored text matches nothing, and it
 * presents as a broken search engine rather than a broken string function.
 *
 * Both implementations are tested against pipeline/tests/normalise_fixtures.json.
 * Change a rule here and you must change it there, then regenerate.
 */

// Letters that carry no combining mark and must be mapped explicitly.
const EXPLICIT: ReadonlyMap<string, string> = new Map([
  ["ß", "ss"],
  ["æ", "ae"], ["Æ", "ae"],
  ["œ", "oe"], ["Œ", "oe"],
  ["ø", "o"], ["Ø", "o"],
  ["đ", "d"], ["Đ", "d"],
  ["þ", "th"], ["Þ", "th"],
]);

// Python's \w is [letters, digits, underscore] under re.UNICODE. JavaScript's
// \w is ASCII-only, so the class is spelled out to keep the two in step.
const WORD = "\\p{L}\\p{N}_";
const COMBINING = /\p{M}/gu;
const INNER_HYPHEN = new RegExp(`(?<=[${WORD}])-(?=[${WORD}])`, "gu");
const INNER_APOSTROPHE = new RegExp(`(?<=[${WORD}])['’](?=[${WORD}])`, "gu");
const NON_WORD = new RegExp(`[^${WORD}\\s\\u0000\\u0001]`, "gu");
const WHITESPACE = /\s+/gu;
const LETTER = /\p{L}/u;

const HYPHEN_MARK = "\u0000";
const APOSTROPHE_MARK = "\u0001";

/** Maçon to Macon, Thébäische to Thebaische. */
export function stripDiacritics(text: string): string {
  const withoutMarks = text.normalize("NFD").replace(COMBINING, "");
  let out = "";
  for (const character of withoutMarks) {
    out += EXPLICIT.get(character) ?? character;
  }
  return out.normalize("NFC");
}

/**
 * The canonical form used for matching, in both engines.
 *
 * Lowercase, diacritics removed, inner hyphens and apostrophes kept, all other
 * punctuation dropped, whitespace collapsed.
 *
 *   normalise("Babylon, Red Cross of.")  ->  "babylon red cross of"
 *   normalise("Rose-Croix")              ->  "rose-croix"
 *   normalise("Mason's Word")            ->  "mason's word"
 */
export function normalise(text: string): string {
  if (!text) return "";
  let out = stripDiacritics(text).toLowerCase();
  out = out.replace(INNER_HYPHEN, HYPHEN_MARK);
  out = out.replace(INNER_APOSTROPHE, APOSTROPHE_MARK);
  out = out.replace(NON_WORD, " ");
  out = out.split(HYPHEN_MARK).join("-").split(APOSTROPHE_MARK).join("'");
  return out.replace(WHITESPACE, " ").trim();
}

/**
 * Ordering key: like normalise(), but hyphens and apostrophes also go, so
 * "Rose-Croix" and "Rose Croix" sort together.
 */
export function sortKey(text: string): string {
  const plain = normalise(text).split("-").join(" ").split("'").join(" ");
  return plain.replace(WHITESPACE, " ").trim();
}

/** The A–Z bucket for the index. Non-alphabetic headwords bucket as '#'. */
export function firstLetter(text: string): string {
  const key = sortKey(text);
  const first = key.charAt(0);
  return first && LETTER.test(first) ? first.toUpperCase() : "#";
}
