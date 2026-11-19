/**
 * The door.
 *
 * A challenge before the book opens: "Who comes here?", answered with a word.
 *
 * It is worth being plain about what this is and is not. The application is a
 * static site, so this file is downloaded by whoever asks for it, and the
 * whole encyclopaedia sits beside it in data/entries.json, reachable by
 * typing its address. Anyone who wants the text without answering can have
 * it. This is a doorkeeper's question, not a lock: it sets the manner of
 * entry, and it keeps the book from opening by accident in front of someone
 * it was not meant for.
 *
 * Because of that the word is not in the source in plain sight. What is
 * stored is a digest of it, which is obscurity rather than security -- a
 * short word can be found by trying words against the digest -- but it does
 * mean the answer is not sitting in the repository to be read at a glance.
 *
 * Four wrong answers close the door for twenty seconds. The count and the
 * closing time are kept in storage, so reloading the page does not reopen it.
 *
 * The question is asked once per installation, not once per opening. A copy
 * installed on a phone asks on its first run and then opens straight into the
 * book, which is what being admitted means: the Brother is known to this
 * copy from then on. Another device, another browser, or site data cleared,
 * and it asks again, because that is a different copy.
 */

const ATTEMPTS_KEY = "am-door-tries";
const UNTIL_KEY = "am-door-until";
const PASSED_KEY = "am-door-passed";

const LIMIT = 4;
const WAIT_MS = 20_000;

/** The expected answer, as a digest. See the note above on what that is for. */
const EXPECTED = "39f791e9-7b4c07ed";

/**
 * A small, stable digest. Deliberately not Web Crypto: subtle.crypto needs a
 * secure context, and the one-file copy of this application is opened from a
 * folder, where there is none. A cryptographic hash would buy nothing here
 * anyway, for the reasons in the note above.
 */
export function digest(word        )         {
  const salted = `tyler:${word}:1914`;
  let a = 0x811c9dc5;
  let b = 0x01000193;
  for (let i = 0; i < salted.length; i++) {
    const code = salted.charCodeAt(i);
    a = Math.imul(a ^ code, 0x01000193) >>> 0;
    b = Math.imul(b + code + i, 0x85ebca6b) >>> 0;
    b = ((b << 13) | (b >>> 19)) >>> 0;
  }
  return `${a.toString(16).padStart(8, "0")}-${b.toString(16).padStart(8, "0")}`;
}

export function admits(word        )          {
  return digest(word.trim()) === EXPECTED;
}

/* ---------- how many have been turned away ---------- */

function read(key        )         {
  try {
    return Number(localStorage.getItem(key)) || 0;
  } catch {
    return 0;
  }
}

function readText(key        )         {
  try {
    return localStorage.getItem(key) ?? "";
  } catch {
    return "";
  }
}

function writeText(key        , value        )       {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* A door that cannot remember is still a door. */
  }
}

function write(key        , value        )       {
  try {
    localStorage.setItem(key, String(value));
  } catch {
    /* A door that cannot remember is still a door. */
  }
}

/** Milliseconds left to wait, or 0. */
export function closedFor(now = Date.now())         {
  return Math.max(0, read(UNTIL_KEY) - now);
}

/** Record a wrong answer; returns the wait it earned, in milliseconds. */
export function refuse(now = Date.now())         {
  const tries = read(ATTEMPTS_KEY) + 1;
  if (tries < LIMIT) {
    write(ATTEMPTS_KEY, tries);
    return 0;
  }
  write(ATTEMPTS_KEY, 0);
  write(UNTIL_KEY, now + WAIT_MS);
  return WAIT_MS;
}

export function admitted()       {
  write(ATTEMPTS_KEY, 0);
  write(UNTIL_KEY, 0);
  // What is remembered is which word was given, not merely that one was. So
  // changing the word asks every installation again, which is the whole point
  // of changing it -- otherwise a copy admitted under the old word would go
  // on opening for ever.
  writeText(PASSED_KEY, EXPECTED);
}

/** Whether this installation has been admitted under the word now in force. */
export function admittedBefore()          {
  return readText(PASSED_KEY) === EXPECTED;
}

/** Ask again on this installation. Nothing calls this yet; it is the way back. */
export function forget()       {
  writeText(PASSED_KEY, "");
}

export function triesLeft()         {
  return Math.max(0, LIMIT - read(ATTEMPTS_KEY));
}

/* ---------- the door itself ---------- */

/**
 * Show the challenge. `onOpen` is called once the word is right.
 *
 * The book is loading behind this, so answering correctly opens it at once
 * rather than starting the wait then.
 */
export function guard(root             , onOpen            )       {
  const make = (tag        , cls         , text         )              => {
    const node = document.createElement(tag);
    if (cls) node.setAttribute("class", cls);
    if (text !== undefined) node.textContent = text;
    return node;
  };

  document.body.classList.add("shut");
  const panel = make("div", "door");
  const challenge = make("p", "challenge", "Who comes here?");

  const form = make("form", "door-form");
  const label = make("label", "visually-hidden", "The word");
  label.setAttribute("for", "door-word");
  const field = make("input", "door-word")                    ;
  field.setAttribute("id", "door-word");
  field.setAttribute("type", "password");
  field.setAttribute("autocomplete", "off");
  field.setAttribute("autocapitalize", "none");
  field.setAttribute("spellcheck", "false");
  field.setAttribute("aria-describedby", "door-note");

  const enter = make("button", "door-enter sans", "Enter");
  enter.setAttribute("type", "submit");

  const note = make("p", "door-note sans");
  note.setAttribute("id", "door-note");
  note.setAttribute("role", "status");

  form.append(label, field, enter);
  panel.append(challenge, form, note);
  root.replaceChildren(panel);
  field.focus();

  let ticking                                            ;

  const closeFor = (ms        )       => {
    field.disabled = true;
    enter.disabled = true;
    const until = Date.now() + ms;
    const tick = ()       => {
      const left = Math.ceil((until - Date.now()) / 1000);
      if (left > 0) {
        note.textContent = `The door is closed. ${left} second${left === 1 ? "" : "s"}.`;
        return;
      }
      if (ticking) clearInterval(ticking);
      field.disabled = false;
      enter.disabled = false;
      note.textContent = "";
      field.focus();
    };
    tick();
    ticking = setInterval(tick, 250);
  };

  const waiting = closedFor();
  if (waiting > 0) closeFor(waiting);

  form.addEventListener("submit", (event       ) => {
    event.preventDefault();
    if (field.disabled) return;
    if (admits(field.value)) {
      admitted();
      if (ticking) clearInterval(ticking);
      document.body.classList.remove("shut");
      onOpen();
      return;
    }
    field.value = "";
    const wait = refuse();
    if (wait > 0) {
      closeFor(wait);
    } else {
      const left = triesLeft();
      note.textContent = left === 1
        ? "Not the word. One more attempt."
        : `Not the word. ${left} attempts remain.`;
      field.focus();
    }
  });
}
