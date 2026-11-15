"""Друк етикеток і документів: штрихкод GS1-128 (Code 128C + FNC1) у SVG та HTML-шаблон."""
from html import escape

_PATTERNS = (
    "212222 222122 222221 121223 121322 131222 122213 122312 132212 221213 221312 231212 112232 "
    "122132 122231 113222 123122 123221 223211 221132 221231 213212 223112 312131 311222 321122 "
    "321221 312212 322112 322211 212123 212321 232121 111323 131123 131321 112313 132113 132311 "
    "211313 231113 231311 112133 112331 132131 113123 113321 133121 313121 211331 231131 213113 "
    "213311 213131 311123 311321 331121 312113 312311 332111 314111 221411 431111 111224 111422 "
    "121124 121421 141122 141221 112214 112412 122114 122411 142112 142211 241211 221114 413111 "
    "241112 134111 111242 121142 121241 114212 124112 124211 411212 421112 421211 212141 214121 "
    "412121 111143 111341 131141 114113 114311 411113 411311 113141 114131 311141 411131 211412 "
    "211214 211232 2331112"
).split()
START_C, FNC1, STOP = 105, 102, 106


def gs1_128_svg(digits: str, height: int = 70, module: int = 2) -> str:
    """Числовий GS1-128 (наприклад, AI 00 + SSCC) як SVG."""
    if len(digits) % 2:
        digits = "0" + digits
    codes = [START_C, FNC1] + [int(digits[i:i + 2]) for i in range(0, len(digits), 2)]
    checksum = (codes[0] + sum(c * i for i, c in enumerate(codes[1:], start=1))) % 103
    codes += [checksum, STOP]
    x, rects = 10 * module, []
    for c in codes:
        for i, w in enumerate(_PATTERNS[c]):
            w = int(w) * module
            if i % 2 == 0:
                rects.append(f'<rect x="{x}" y="0" width="{w}" height="{height}"/>')
            x += w
    width = x + 10 * module
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
            f'viewBox="0 0 {width} {height}"><rect width="100%" height="100%" fill="#fff"/>'
            f'<g fill="#000">{"".join(rects)}</g></svg>')


def label_html(sscc: str, rows: list[tuple[str, str]], title: str = "Етикетка вантажної одиниці (SSCC)") -> str:
    trs = "".join(f"<tr><th>{escape(k)}</th><td>{escape(str(v))}</td></tr>" for k, v in rows)
    return f"""<!doctype html><html lang="uk"><head><meta charset="utf-8"><title>{escape(title)}</title>
<style>body{{font-family:Arial,sans-serif;margin:16px}}.l{{border:2px solid #000;padding:12px;width:420px}}
th{{text-align:left;padding-right:12px}}h2{{margin:0 0 8px}}.hr{{font-family:monospace;font-size:18px}}</style>
</head><body onload="window.print&&setTimeout(()=>window.print(),300)"><div class="l"><h2>{escape(title)}</h2>
<table>{trs}</table><div style="margin-top:10px">{gs1_128_svg("00" + sscc)}</div>
<div class="hr">(00) {escape(sscc)}</div></div></body></html>"""


def document_html(title: str, header: list[tuple[str, str]], columns: list[str], rows: list[list],
                  footer: str = "", barcode: str | None = None) -> str:
    head = "".join(f"<tr><th>{escape(k)}</th><td>{escape(str(v))}</td></tr>" for k, v in header)
    ths = "".join(f"<th>{escape(c)}</th>" for c in columns)
    trs = "".join("<tr>" + "".join(f"<td>{escape(str(v))}</td>" for v in r) + "</tr>" for r in rows)
    bc = f'<div>{gs1_128_svg("00" + barcode)}<div>(00) {escape(barcode)}</div></div>' if barcode else ""
    return f"""<!doctype html><html lang="uk"><head><meta charset="utf-8"><title>{escape(title)}</title>
<style>body{{font-family:Arial,sans-serif;margin:24px}}table{{border-collapse:collapse}}
.g td,.g th{{border:1px solid #333;padding:4px 8px}}.h th{{text-align:left;padding-right:12px}}</style></head>
<body><h2>{escape(title)}</h2><table class="h">{head}</table>{bc}<br><table class="g"><tr>{ths}</tr>{trs}</table>
<p>{escape(footer)}</p><button onclick="window.print()">Друк</button></body></html>"""
