/**
 * Split helpers for the shared-expense form.
 *
 * The server does the real arithmetic. These only power the live "do the amounts add up?"
 * check on an exact split, in whole minor units so no floating-point error creeps in.
 */

/** Minor-unit digits of a currency: 2 for rupees, 0 for yen. */
export function minorExponent(currency: string): number {
  try {
    return new Intl.NumberFormat("en", { style: "currency", currency }).resolvedOptions().maximumFractionDigits ?? 2;
  } catch {
    return 2;
  }
}

/** "1,250.5" in INR is 125050; null when the text is not an amount that fits the currency. */
export function parseMinor(text: string, currency: string): number | null {
  const cleaned = text.replace(/,/g, "").trim();
  const exponent = minorExponent(currency);
  const match = /^(\d*)(?:\.(\d*))?$/.exec(cleaned);
  if (!match || (match[1] === "" && !match[2])) return null;
  const fraction = match[2] ?? "";
  if (fraction.length > exponent) return null;
  const minor = Number(`${match[1] || "0"}${fraction.padEnd(exponent, "0")}`);
  return Number.isSafeInteger(minor) ? minor : null;
}

/** How an exact split stands against the total, in minor units. */
export interface ExactCheck {
  /** What the entered amounts add up to (blank or invalid entries count as zero). */
  enteredMinor: number;
  /** Total minus entered: positive means money is still unassigned, negative means too much. */
  differenceMinor: number;
  /** True when every amount is a valid positive amount and they sum to the total. */
  addsUp: boolean;
}

export function checkExactSplit(totalText: string, amountTexts: string[], currency: string): ExactCheck {
  const total = parseMinor(totalText, currency) ?? 0;
  const parsed = amountTexts.map((text) => parseMinor(text, currency));
  const enteredMinor = parsed.reduce<number>((sum, minor) => sum + (minor ?? 0), 0);
  const everyAmountIsValid = parsed.every((minor) => minor !== null && minor > 0);
  return {
    enteredMinor,
    differenceMinor: total - enteredMinor,
    addsUp: total > 0 && everyAmountIsValid && enteredMinor === total,
  };
}

/** A minor-unit amount as plain text for the user: 50 in INR is "0.50". */
export function minorToText(minor: number, currency: string): string {
  const exponent = minorExponent(currency);
  const sign = minor < 0 ? "-" : "";
  const digits = String(Math.abs(minor)).padStart(exponent + 1, "0");
  return exponent === 0 ? `${sign}${digits}` : `${sign}${digits.slice(0, -exponent)}.${digits.slice(-exponent)}`;
}
