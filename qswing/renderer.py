# -*- coding: utf-8 -*-
"""qswing — Jinja2 → tek dosya HTML. Türkçe locale sayı biçimlendirme filtreleri."""
from __future__ import annotations
import os
from typing import Dict, Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape

TPL_DIR = os.path.join(os.path.dirname(__file__), "templates")


def _tr(s: str) -> str:
    """'1,234.56' → '1.234,56' (nokta↔virgül takası)."""
    return s.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def trnum(x: Optional[float], dec: int = 2, dash: str = "—") -> str:
    if x is None:
        return dash
    try:
        s = f"{float(x):,.{dec}f}"
    except (TypeError, ValueError):
        return dash
    return _tr(s)


def trsigned(x: Optional[float], dec: int = 2, dash: str = "—") -> str:
    if x is None:
        return dash
    s = trnum(abs(x), dec)
    return ("+" if x >= 0 else "−") + s


def trpct(x: Optional[float], dec: int = 1, dash: str = "—") -> str:
    if x is None:
        return dash
    return "%" + trnum(x, dec)


def trsignedpct(x: Optional[float], dec: int = 1, dash: str = "—") -> str:
    if x is None:
        return dash
    return ("+" if x >= 0 else "−") + "%" + trnum(abs(x), dec)


def trmoney_m(x: Optional[float], dec: int = 1, dash: str = "—") -> str:
    """Milyon $ — '$77,0M'."""
    if x is None:
        return dash
    return "$" + trnum(x, dec) + "M"


def trint(x: Optional[float], dash: str = "—") -> str:
    if x is None:
        return dash
    try:
        return _tr(f"{int(round(float(x))):,d}")
    except (TypeError, ValueError):
        return dash


def build_env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(TPL_DIR),
        autoescape=select_autoescape(["html", "xml"]),
        trim_blocks=True, lstrip_blocks=True,
    )
    env.filters.update(trnum=trnum, trsigned=trsigned, trpct=trpct,
                       trsignedpct=trsignedpct, trmoney_m=trmoney_m, trint=trint)
    return env


def render_to_string(context: Dict) -> str:
    """Raporu dosyaya yazmadan HTML string olarak döndür (sunucu/inline kullanım)."""
    env = build_env()
    return env.get_template("report.html.j2").render(**context)


def render(context: Dict, out_dir: str) -> str:
    env = build_env()
    tpl = env.get_template("report.html.j2")
    html = tpl.render(**context)
    os.makedirs(out_dir, exist_ok=True)
    fn = f"qswing_{context['ticker']}_{context['date']}.html"
    path = os.path.join(out_dir, fn)
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    return path


# net duruş sıralama önceliği: AL → İZLE → KAÇIN, sonra Aşama skoru azalan
_VORDER = {"AL": 0, "İZLE": 1, "KAÇIN": 2}


def render_index_to_string(summaries, date: str, failed=None) -> str:
    """Tarama index'ini HTML string döndür (dosyaya yazmaz; sunucu/inline kullanım)."""
    env = build_env()
    rows = sorted(summaries, key=lambda s: (_VORDER.get(s["verdict"]["label"], 3),
                                            -(s["stage"] or 0),
                                            -(s["rs_3m"] if s["rs_3m"] is not None else -999)))
    counts = {"AL": 0, "İZLE": 0, "KAÇIN": 0}
    for s in summaries:
        counts[s["verdict"]["label"]] = counts.get(s["verdict"]["label"], 0) + 1
    return env.get_template("index.html.j2").render(
        rows=rows, counts=counts, total=len(summaries), failed=failed or [], date=date)


def render_index(summaries, out_dir: str, date: str, failed=None) -> str:
    html = render_index_to_string(summaries, date, failed=failed)
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"qswing_index_{date}.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    return path
