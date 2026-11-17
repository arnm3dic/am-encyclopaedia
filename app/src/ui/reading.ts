/**
 * Reading options: text size, and a reading mode that clears the apparatus.
 *
 * This is a book, and most of the time spent in it is spent reading one
 * article rather than searching. Reading mode narrows the measure, enlarges
 * the type and puts the search bar away; the preference is remembered.
 *
 * Storage is wrapped: a page in a sandboxed frame can throw on localStorage
 * rather than simply returning nothing, and losing a font-size preference is
 * not worth breaking the page over.
 */

const KEY = "am-reading";

export type Size = "s" | "m" | "l" | "xl";

export type Preferences = {
  size: Size;
  reading: boolean;
};

const SIZES: Size[] = ["s", "m", "l", "xl"];
const SIZE_LABEL: Record<Size, string> = { s: "A", m: "A", l: "A", xl: "A" };
const SIZE_NAME: Record<Size, string> = {
  s: "Small", m: "Default", l: "Large", xl: "Largest",
};

export function load(): Preferences {
  const fallback: Preferences = { size: "m", reading: false };
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return fallback;
    const parsed = JSON.parse(raw) as Partial<Preferences>;
    return {
      size: SIZES.includes(parsed.size as Size) ? (parsed.size as Size) : "m",
      reading: parsed.reading === true,
    };
  } catch {
    return fallback;
  }
}

export function save(preferences: Preferences): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(preferences));
  } catch {
    /* A preference that cannot be stored is not worth an error. */
  }
}

export function apply(preferences: Preferences): void {
  const classes = document.body.classList;
  for (const size of SIZES) classes.remove(`size-${size}`);
  classes.add(`size-${preferences.size}`);
  classes.toggle("reading", preferences.reading);
}

/**
 * Build the options panel.
 *
 * `onChange` is called after each change so the caller can re-render: reading
 * mode hides the search bar, and the screen underneath needs to know.
 */
export function buildPanel(
  preferences: Preferences,
  onChange: (next: Preferences) => void,
): HTMLElement {
  const panel = document.createElement("div");
  panel.className = "options";
  panel.id = "reading-options";
  panel.hidden = true;

  const wrap = document.createElement("div");
  wrap.className = "wrap";

  // Text size
  const sizeRow = document.createElement("div");
  sizeRow.className = "option-row";
  const sizeLabel = document.createElement("span");
  sizeLabel.textContent = "Text size";
  const steps = document.createElement("div");
  steps.className = "steps";
  steps.setAttribute("role", "group");
  steps.setAttribute("aria-label", "Text size");

  const buttons = new Map<Size, HTMLButtonElement>();
  for (const size of SIZES) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = SIZE_LABEL[size];
    button.setAttribute("aria-label", SIZE_NAME[size]);
    button.style.fontSize = { s: "0.8rem", m: "0.95rem", l: "1.1rem", xl: "1.3rem" }[size];
    button.setAttribute("aria-pressed", String(preferences.size === size));
    button.addEventListener("click", () => {
      preferences.size = size;
      for (const [key, other] of buttons) {
        other.setAttribute("aria-pressed", String(key === size));
      }
      apply(preferences);
      save(preferences);
      onChange(preferences);
    });
    buttons.set(size, button);
    steps.append(button);
  }
  sizeRow.append(sizeLabel, steps);

  // Reading mode
  const modeRow = document.createElement("div");
  modeRow.className = "option-row";
  const modeLabel = document.createElement("span");
  modeLabel.textContent = "Reading mode hides the search bar and widens the leading";
  // Wrapped so it takes the same framing as the size steps.
  const group = document.createElement("div");
  group.className = "steps";
  const inner = document.createElement("button");
  inner.type = "button";
  inner.textContent = preferences.reading ? "On" : "Off";
  inner.setAttribute("aria-pressed", String(preferences.reading));
  inner.addEventListener("click", () => {
    preferences.reading = !preferences.reading;
    inner.textContent = preferences.reading ? "On" : "Off";
    inner.setAttribute("aria-pressed", String(preferences.reading));
    apply(preferences);
    save(preferences);
    onChange(preferences);
  });
  group.append(inner);
  modeRow.append(modeLabel, group);

  wrap.append(sizeRow, modeRow);
  panel.append(wrap);
  return panel;
}
