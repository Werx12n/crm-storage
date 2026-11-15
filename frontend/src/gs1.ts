// Розбір і перевірка штрихкодів GS1 на клієнті (контрольна цифра GTIN/SSCC, рядки з AI).

export type Gs1 = { gtin?: string; sscc?: string; batch?: string; expiry?: string; qty?: number; valid: boolean };

export function checkDigit(body: string): string {
  let sum = 0;
  for (let i = 0; i < body.length; i++) {
    const d = Number(body[body.length - 1 - i]);
    sum += d * (i % 2 === 0 ? 3 : 1);
  }
  return String((10 - (sum % 10)) % 10);
}

export const isGtin = (c: string) =>
  /^\d+$/.test(c) && [8, 12, 13, 14].includes(c.length) && checkDigit(c.slice(0, -1)) === c.slice(-1);

export const isSscc = (c: string) => /^\d{18}$/.test(c) && checkDigit(c.slice(0, -1)) === c.slice(-1);

const FIXED: Record<string, number> = { "00": 18, "01": 14, "02": 14, "11": 6, "13": 6, "15": 6, "17": 6 };
const VAR = new Set(["10", "21", "37"]);
const GS = "\x1d";

function yymmdd(v: string): string | undefined {
  if (!/^\d{6}$/.test(v)) return undefined;
  const y = 2000 + Number(v.slice(0, 2));
  const m = Number(v.slice(2, 4));
  let d = Number(v.slice(4, 6));
  if (d === 0) d = new Date(y, m, 0).getDate();
  return `${y}-${String(m).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
}

export function parseGs1(raw: string): Gs1 {
  let code = (raw ?? "").trim();
  for (const p of ["]C1", "]d2", "]Q3", "]e0"]) if (code.startsWith(p)) code = code.slice(p.length);
  const res: Gs1 = { valid: false };
  if (/^\d+$/.test(code) && [8, 12, 13, 14].includes(code.length)) {
    if (isGtin(code)) Object.assign(res, { gtin: code.padStart(14, "0"), valid: true });
    return res;
  }
  if (/^\d{18}$/.test(code)) {
    if (isSscc(code)) Object.assign(res, { sscc: code, valid: true });
    return res;
  }
  const el: Record<string, string> = {};
  if (code.startsWith("(")) {
    for (const m of code.matchAll(/\((\d{2,4})\)([^(]*)/g)) el[m[1]] = m[2].trim();
  } else {
    code = code.replace(/\|/g, GS);
    let i = 0;
    while (i < code.length) {
      const ai = code.slice(i, i + 2);
      i += 2;
      if (ai in FIXED) {
        el[ai] = code.slice(i, i + FIXED[ai]);
        i += FIXED[ai];
      } else if (VAR.has(ai)) {
        let end = code.indexOf(GS, i);
        if (end === -1) end = code.length;
        el[ai] = code.slice(i, end);
        i = end + 1;
      } else break;
      if (code[i] === GS) i++;
    }
  }
  const g = el["01"] ?? el["02"];
  if (g && isGtin(g)) res.gtin = g;
  if (el["00"] && isSscc(el["00"])) res.sscc = el["00"];
  if (el["10"]) res.batch = el["10"];
  if (el["17"]) res.expiry = yymmdd(el["17"]);
  if (el["37"] && /^\d+$/.test(el["37"])) res.qty = Number(el["37"]);
  res.valid = Boolean(res.gtin || res.sscc);
  return res;
}

/** Короткий опис результату для ТЗД. */
export function describe(raw: string): { ok: boolean | null; text: string } {
  if (!raw) return { ok: null, text: "" };
  const p = parseGs1(raw);
  if (/^\d+$/.test(raw.trim()) || raw.trim().startsWith("(") || raw.includes(GS)) {
    if (!p.valid) return { ok: false, text: "✗ Невірна контрольна цифра GS1" };
    const parts = [p.gtin && `GTIN ${p.gtin}`, p.sscc && `SSCC ${p.sscc}`, p.batch && `партія ${p.batch}`,
      p.expiry && `до ${p.expiry}`, p.qty && `${p.qty} од.`].filter(Boolean);
    return { ok: true, text: "✓ GS1: " + parts.join(", ") };
  }
  return { ok: null, text: "Код: " + raw.trim() };
}
