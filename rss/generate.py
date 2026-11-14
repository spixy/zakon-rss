#!/usr/bin/env python3
"""Generuje RSS feedy noviel CZ a SK legislatívy z git histórie predpisov.

Zdroj: verejné git repozitáre s históriou predpisov (CC0), kde jeden commit = jedna
zmena predpisu, s dátumom účinnosti v traileri In-force. Pôvodné dáta: e-Sbírka a Slov-Lex.

Iba štandardná knižnica Pythonu a git. Repozitáre sa klonujú bez obsahu súborov
(--filter=tree:0), teda len commity, čo je pár desiatok MB.

Použitie:
    python rss/generate.py --cache .cache --out public [--days 90] [--base-url URL]
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html
import os
import re
import subprocess
import sys
from email.utils import format_datetime
from pathlib import Path
from xml.sax.saxutils import escape

COUNTRIES = {
    "cz": {
        "repo_env": "CZ_SOURCE_REPO",
        "home": "https://www.e-sbirka.cz",
        "title": "Novely české legislativy (Sbírka zákonů)",
        "description": "Změny zákonů a dalších předpisů ze Sbírky zákonů podle dne účinnosti. "
                       "Zdroj: e-Sbírka.",
        "language": "cs",
        # národné predpisy: autor je predpis (sb-YYYY-N@esbirka.invalid) alebo e-Sbírka
        "email": re.compile(r"@esbirka\.invalid$"),
        "kinds": {"", "law", "court"},  # bez opráv (correction)
        "official": "Oficiální text",
        "effective": "Účinnost od",
    },
    "sk": {
        "repo_env": "SK_SOURCE_REPO",
        "home": "https://www.slov-lex.sk",
        "title": "Novely slovenskej legislatívy (Zbierka zákonov)",
        "description": "Zmeny zákonov a ďalších predpisov zo Zbierky zákonov podľa dňa účinnosti. "
                       "Zdroj: Slov-Lex.",
        "language": "sk",
        "email": re.compile(r"@slov-lex\.invalid$"),
        "kinds": {"", "law", "court", "candidates", "unexplained", "baseline"},
        "official": "Oficiálny text",
        "effective": "Účinnosť od",
    },
}

SEP_FIELD = "\x1f"
SEP_REC = "\x1e"
TRAILER_LINE = re.compile(r"^[A-Za-z][A-Za-z0-9-]*: ")


def git(*args: str, cwd: Path | None = None) -> str:
    res = subprocess.run(["git", *args], cwd=cwd, capture_output=True,
                         encoding="utf-8", errors="replace")
    if res.returncode != 0:
        sys.exit(f"git {' '.join(args)} zlyhal:\n{res.stderr}")
    return res.stdout


def source_repo(code: str, cfg: dict) -> str:
    """Zdrojový repozitár ('vlastník/názov') z premennej prostredia, v Actions zo secrets."""
    repo = os.environ.get(cfg["repo_env"], "").strip()
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", repo):
        sys.exit(f"{code}: nastav premennú {cfg['repo_env']} na zdrojový repozitár vo tvare vlastník/názov")
    return repo


def sync_repo(code: str, repo: str, cache: Path) -> Path:
    """Naklonuje (iba commity) alebo aktualizuje vetvu main."""
    path = cache / f"{code}.git"
    url = f"https://github.com/{repo}.git"
    if not (path / "HEAD").exists():
        cache.mkdir(parents=True, exist_ok=True)
        git("clone", "-q", "--bare", "--single-branch", "--branch", "main",
            "--filter=tree:0", url, str(path))
    else:
        git("fetch", "-q", "origin", "+refs/heads/main:refs/heads/main", cwd=path)
    return path


def candidates(path: Path, cfg: dict, start: dt.date, end: dt.date) -> list[tuple[str, dt.date]]:
    """Rýchly prechod celou históriou: iba hash, e-mail autora, In-force, Kind."""
    fmt = SEP_FIELD.join([
        "%H", "%ae",
        "%(trailers:key=In-force,valueonly,separator=%x2C)",
        "%(trailers:key=Kind,valueonly,separator=%x2C)",
    ]) + SEP_REC
    out = git("log", "main", f"--format={fmt}", cwd=path)
    picked = []
    for rec in out.split(SEP_REC):
        rec = rec.strip("\n")
        if not rec:
            continue
        sha, email, in_force, kind = (rec.split(SEP_FIELD) + ["", "", "", ""])[:4]
        if not cfg["email"].search(email) or kind.strip() not in cfg["kinds"]:
            continue
        try:
            day = dt.date.fromisoformat(in_force.split(",")[0].strip())
        except ValueError:
            continue
        if start <= day <= end:
            picked.append((sha, day))
    return picked


def details(path: Path, shas: list[str]) -> dict[str, dict]:
    """Plné správy vybraných commitov jedným volaním gitu."""
    if not shas:
        return {}
    fmt = SEP_FIELD.join(["%H", "%an", "%cI", "%B"]) + SEP_REC
    res = subprocess.run(["git", "log", "--no-walk=unsorted", "--stdin", f"--format={fmt}"],
                         cwd=path, input="\n".join(shas), capture_output=True,
                         encoding="utf-8", errors="replace")
    if res.returncode != 0:
        sys.exit(res.stderr)
    info = {}
    for rec in res.stdout.split(SEP_REC):
        rec = rec.strip("\n")
        if not rec:
            continue
        sha, author, committed, body = rec.split(SEP_FIELD, 3)
        info[sha] = parse_message(body) | {"author": author, "committed": committed}
    return info


def parse_message(msg: str) -> dict:
    paras = [p.strip("\n") for p in re.split(r"\n\s*\n", msg.strip())]
    subject = paras[0].replace("\n", " ") if paras else ""
    trailers: dict[str, list[str]] = {}
    body = paras[1:]
    if body and all(TRAILER_LINE.match(l) for l in body[-1].splitlines()):
        for line in body.pop().splitlines():
            key, _, val = line.partition(": ")
            trailers.setdefault(key, []).append(val.strip())
    return {"subject": subject, "paragraphs": body, "trailers": trailers}


def shorten(text: str, limit: int = 220) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip(" ,;") + "…"


def title_for(c: dict, day: dt.date) -> str:
    """Nadpis, z ktorého je hneď jasné, o aký predpis ide."""
    subject, paras, author = c["subject"], c["paragraphs"], c["author"]
    first = paras[0].replace("\n", " ") if paras else ""
    # CZ: 1. odsek = "Vyhláška č. 214/2026 Sb.: Vyhláška, kterou se mění …" (plný názov)
    if first and first.startswith(author + ":"):
        return shorten(first)
    # SK baseline: "229/2011 Z. z.: znenie účinné od …" + 1. odsek = názov predpisu
    if "znenie účinné od" in subject and first:
        number = subject.split(":")[0]
        return shorten(f"{number}: {first.rstrip('.')} (znenie od {day.isoformat()})")
    return shorten(subject)


def linkify(text: str) -> str:
    esc = html.escape(text)
    return re.sub(r"(https?://[^\s<]+)", r'<a href="\1">\1</a>', esc)


def item_xml(code: str, cfg: dict, sha: str, day: dt.date, c: dict) -> str:
    t = c["trailers"]
    official = (t.get("Act") or t.get("Source") or t.get("Text-source") or [""])[0]
    official = official.split(" ")[0]
    link = official or cfg["home"]
    pub = dt.datetime.combine(day, dt.time(12, 0), tzinfo=dt.timezone(dt.timedelta(hours=1)))

    parts = [f"<p><strong>{cfg['effective']}: {day.isoformat()}</strong> · {html.escape(c['author'])}</p>"]
    for p in c["paragraphs"]:
        # zalomený text (pokračuje malým písmenom) spojiť, inak nový riadok
        p = re.sub(r"\n(?=[a-záäčďéíĺľňóôŕšťúýž(])", " ", p)
        parts.append(f"<p>{linkify(p).replace(chr(10), '<br>')}</p>")
    links = []
    if official:
        links.append(f'<a href="{html.escape(official)}">{cfg["official"]}</a>')
    for v in t.get("Version", []) + t.get("Text-source", []):
        links.append(f'<a href="{html.escape(v)}">{html.escape(v)}</a>')
    if links:
        parts.append("<p>" + " · ".join(links) + "</p>")

    cats = [k for k in t.get("Law-type", []) + t.get("Kind", []) if k]
    return "\n".join([
        "    <item>",
        f"      <title>{escape(title_for(c, day))}</title>",
        f"      <link>{escape(link)}</link>",
        f'      <guid isPermaLink="false">{code}-{hashlib.sha256(sha.encode()).hexdigest()[:20]}</guid>',
        f"      <pubDate>{format_datetime(pub)}</pubDate>",
        *[f"      <category>{escape(k)}</category>" for k in cats],
        f"      <description>{escape(''.join(parts))}</description>",
        "    </item>",
    ])


def feed_xml(code: str, cfg: dict, items: list[str], base_url: str, now: dt.datetime) -> str:
    self_url = f"{base_url.rstrip('/')}/{code}.xml" if base_url else f"{code}.xml"
    return "\n".join([
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">',
        "  <channel>",
        f"    <title>{escape(cfg['title'])}</title>",
        f"    <link>{cfg['home']}</link>",
        f"    <description>{escape(cfg['description'])}</description>",
        f"    <language>{cfg['language']}</language>",
        f"    <lastBuildDate>{format_datetime(now)}</lastBuildDate>",
        f'    <atom:link href="{escape(self_url)}" rel="self" type="application/rss+xml"/>',
        "    <ttl>720</ttl>",
        *items,
        "  </channel>",
        "</rss>",
        "",
    ])


def index_html(stats: dict, base_url: str, now: dt.datetime) -> str:
    rows = "".join(
        f'<li><a href="{c}.xml">{html.escape(COUNTRIES[c]["title"])}</a> – {n} položiek</li>'
        for c, n in stats.items())
    alts = "".join(
        f'<link rel="alternate" type="application/rss+xml" title="{html.escape(COUNTRIES[c]["title"])}" href="{c}.xml">'
        for c in stats)
    return f"""<!doctype html>
<html lang="sk"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Novely zákonov CZ/SK</title>{alts}
<style>body{{font-family:system-ui,sans-serif;max-width:40rem;margin:2rem auto;padding:0 1rem;line-height:1.5}}</style>
</head><body>
<h1>Novely zákonov – RSS</h1>
<ul>{rows}</ul>
<p>Aktualizované {now.strftime('%Y-%m-%d %H:%M')} UTC. Dáta: e-Sbírka (Ministerstvo vnitra ČR)
a Slov-Lex (Ministerstvo spravodlivosti SR). Právne záväzný je len text vyhlásený v Zbierke / Sbírce.</p>
</body></html>
"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cache", type=Path, default=Path(".cache"), help="adresár pre klony")
    ap.add_argument("--out", type=Path, default=Path("public"), help="výstupný adresár")
    ap.add_argument("--days", type=int, default=90, help="koľko dní dozadu podľa účinnosti")
    ap.add_argument("--ahead", type=int, default=365, help="koľko dní dopredu (už vyhlásené, ešte neúčinné)")
    ap.add_argument("--max-items", type=int, default=300)
    ap.add_argument("--base-url", default=os.environ.get("FEED_BASE_URL", ""))
    ap.add_argument("--only", choices=sorted(COUNTRIES), action="append", help="len vybraná krajina")
    args = ap.parse_args()

    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    today = now.date()
    start, end = today - dt.timedelta(days=args.days), today + dt.timedelta(days=args.ahead)
    args.out.mkdir(parents=True, exist_ok=True)

    stats = {}
    for code in args.only or list(COUNTRIES):
        cfg = COUNTRIES[code]
        path = sync_repo(code, source_repo(code, cfg), args.cache)
        picked = candidates(path, cfg, start, end)
        info = details(path, [s for s, _ in picked])
        # najnovšia účinnosť hore; pri rovnakom dni neskôr zaznamenaný commit hore
        picked.sort(key=lambda x: (x[1], info[x[0]]["committed"]), reverse=True)
        picked = picked[: args.max_items]
        items = [item_xml(code, cfg, sha, day, info[sha]) for sha, day in picked]
        (args.out / f"{code}.xml").write_text(feed_xml(code, cfg, items, args.base_url, now), encoding="utf-8")
        stats[code] = len(items)
        print(f"{code}: {len(items)} items ({start} .. {end})")

    (args.out / "index.html").write_text(index_html(stats, args.base_url, now), encoding="utf-8")


if __name__ == "__main__":
    main()
