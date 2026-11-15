"""Розбір і генерація штрихкодів GS1 (GTIN, GS1-128 / DataMatrix, SSCC)."""
import calendar
import re
from datetime import date

GS = "\x1d"
_FIXED = {"00": 18, "01": 14, "02": 14, "11": 6, "13": 6, "15": 6, "17": 6}
_VARIABLE = {"10", "21", "37"}


def check_digit(body: str) -> str:
    total = 0
    for i, ch in enumerate(reversed(body)):
        total += int(ch) * (3 if i % 2 == 0 else 1)
    return str((10 - total % 10) % 10)


def is_valid_gtin(code: str) -> bool:
    return bool(code) and code.isdigit() and len(code) in (8, 12, 13, 14) \
        and check_digit(code[:-1]) == code[-1]


def normalize_gtin(code: str) -> str:
    return code.zfill(14)


def is_valid_sscc(code: str) -> bool:
    return bool(code) and code.isdigit() and len(code) == 18 and check_digit(code[:-1]) == code[-1]


def make_sscc(company_prefix: str, serial: int, extension: str = "0") -> str:
    body_len = 17 - len(extension) - len(company_prefix)
    body = f"{extension}{company_prefix}{str(serial).zfill(body_len)[-body_len:]}"
    return body + check_digit(body)


def make_gtin13(prefix: str, item: int) -> str:
    body = f"{prefix}{str(item).zfill(12 - len(prefix))}"
    return body + check_digit(body)


def parse_date(yymmdd: str) -> date:
    yy, mm, dd = int(yymmdd[:2]), int(yymmdd[2:4]), int(yymmdd[4:6])
    year = 2000 + yy
    if dd == 0:
        dd = calendar.monthrange(year, mm)[1]
    return date(year, mm, dd)


class ScanResult(dict):
    """{'gtin', 'batch', 'expiry', 'sscc', 'qty', 'raw'}."""


def parse(raw: str) -> ScanResult:
    """Розбирає скан: GTIN-8/12/13/14, SSCC-18 або рядок елементів GS1 з AI.

    Формати: "(01)04820000000017(10)L1(17)271231" або без дужок з роздільником GS (\x1d) чи "|".
    """
    code = (raw or "").strip()
    for prefix in ("]C1", "]d2", "]Q3", "]e0"):
        if code.startswith(prefix):
            code = code[len(prefix):]
    res = ScanResult(gtin=None, batch=None, expiry=None, sscc=None, qty=None, raw=raw)
    if not code:
        return res
    if code.isdigit() and len(code) in (8, 12, 13, 14):
        if is_valid_gtin(code):
            res["gtin"] = normalize_gtin(code)
        return res
    if code.isdigit() and len(code) == 18:
        if is_valid_sscc(code):
            res["sscc"] = code
        return res
    elements: dict[str, str] = {}
    if code.startswith("("):
        for ai, val in re.findall(r"\((\d{2,4})\)([^(]*)", code):
            elements[ai] = val.strip()
    else:
        code = code.replace("|", GS)
        i = 0
        while i < len(code):
            ai = code[i:i + 2]
            i += 2
            if ai in _FIXED:
                elements[ai] = code[i:i + _FIXED[ai]]
                i += _FIXED[ai]
            elif ai in _VARIABLE:
                end = code.find(GS, i)
                end = len(code) if end == -1 else end
                elements[ai] = code[i:end]
                i = end + 1
            else:
                break  # невідомий AI — припиняємо розбір
            if i < len(code) and code[i] == GS:
                i += 1
    gtin = elements.get("01") or elements.get("02")
    if gtin and is_valid_gtin(gtin):
        res["gtin"] = gtin
    if "00" in elements and is_valid_sscc(elements["00"]):
        res["sscc"] = elements["00"]
    if "10" in elements:
        res["batch"] = elements["10"]
    if "17" in elements:
        try:
            res["expiry"] = parse_date(elements["17"])
        except ValueError:
            pass
    if "37" in elements and elements["37"].isdigit():
        res["qty"] = int(elements["37"])
    return res
