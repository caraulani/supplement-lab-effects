"""Fetch open-access full text from Europe PMC and save XML plus a plain-text rendering.

Usage: python3 -I scripts/fetch_fulltext.py PMC1234567 [PMC...]

Writes ../_raw/europepmc/<PMCID>.xml and <PMCID>.txt (a sibling folder of the repository).
The .txt keeps section titles, paragraphs, figure/table captions and table rows
(cells joined by " | "), so table values can be located by row.
Standard library only. The downloaded XML is treated as data, never executed.
"""
from __future__ import annotations

import pathlib
import html.parser
import re
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET

RAW = pathlib.Path(__file__).resolve().parent.parent.parent / "_raw" / "europepmc"
URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML"
UA = "LifeFrom-open-build/1.0 (dataset build script)"


def _text(el: ET.Element) -> str:
    return re.sub(r"\s+", " ", "".join(el.itertext())).strip()


def render(xml_bytes: bytes) -> str:
    root = ET.fromstring(xml_bytes)
    out: list[str] = []

    front = root.find("front")
    if front is not None:
        t = front.find(".//article-title")
        if t is not None:
            out.append("TITLE: " + _text(t))
        doi = front.find(".//article-id[@pub-id-type='doi']")
        if doi is not None:
            out.append("DOI: " + _text(doi))
        ab = front.find(".//abstract")
        if ab is not None:
            out.append("\n== ABSTRACT ==")
            for p in ab.iter():
                if p.tag in ("title",):
                    out.append("[" + _text(p) + "]")
                elif p.tag == "p":
                    out.append(_text(p))

    def walk(el: ET.Element, depth: int = 0) -> None:
        for child in el:
            tag = child.tag
            if tag == "sec":
                t = child.find("title")
                if t is not None:
                    out.append("\n" + "#" * (depth + 2) + " " + _text(t))
                walk(child, depth + 1)
            elif tag == "p":
                # paragraphs may embed tables/figures; render text without them first
                inner_tables = child.findall(".//table-wrap")
                if inner_tables:
                    out.append(_text_excluding(child))
                    for tw in inner_tables:
                        render_table(tw)
                else:
                    out.append(_text(child))
            elif tag == "table-wrap":
                render_table(child)
            elif tag == "fig":
                lab = child.find("label")
                cap = child.find("caption")
                out.append(
                    "\nFIGURE " + (_text(lab) if lab is not None else "")
                    + ": " + (_text(cap) if cap is not None else "")
                )
            elif tag in ("title",):
                continue
            else:
                walk(child, depth)

    def render_table(tw: ET.Element) -> None:
        lab = tw.find("label")
        cap = tw.find("caption")
        out.append(
            "\nTABLE " + (_text(lab) if lab is not None else "")
            + ": " + (_text(cap) if cap is not None else "")
        )
        for tr in tw.iter("tr"):
            cells = [_text(c) for c in tr if c.tag in ("td", "th")]
            out.append(" | ".join(cells))
        foot = tw.find("table-wrap-foot")
        if foot is not None:
            out.append("TABLE FOOTNOTE: " + _text(foot))
        out.append("END TABLE")

    body = root.find("body")
    if body is not None:
        out.append("\n== BODY ==")
        walk(body)
    back = root.find("back")
    if back is not None:
        for tw in back.iter("table-wrap"):
            render_table(tw)
    return "\n".join(out) + "\n"


def _text_excluding(p: ET.Element) -> str:
    parts = [p.text or ""]
    for c in p:
        if c.tag != "table-wrap":
            parts.append("".join(c.itertext()))
        parts.append(c.tail or "")
    return re.sub(r"\s+", " ", "".join(parts)).strip()


PMC_HTML = "https://pmc.ncbi.nlm.nih.gov/articles/{pmcid}/"
# Articles whose full text Europe PMC does not serve as XML (publisher restriction) but which
# PubMed Central shows as a free public web page. Rendered from that page instead.
HTML_ONLY = {"PMC5818818", "PMC3069236", "PMC11254377", "PMC5134919", "PMC7467599", "PMC6818550"}


class _HTMLText(html.parser.HTMLParser):
    BLOCK = {"p", "h1", "h2", "h3", "h4", "tr", "li", "caption", "figcaption", "div", "section"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.lines: list[str] = []
        self.cur: list[str] = []
        self.cells: list[str] | None = None
        self.skip = 0
        self.meta: dict[str, str] = {}

    def flush(self) -> None:
        t = re.sub(r"\s+", " ", "".join(self.cur)).strip()
        if t:
            self.lines.append(t)
        self.cur = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "meta" and a.get("name", "").startswith("citation_") and a.get("name") not in self.meta:
            self.meta[a["name"]] = a.get("content", "")
        if tag in ("script", "style", "nav", "header", "footer"):
            self.skip += 1
        if self.skip:
            return
        if tag == "tr":
            self.flush()
            self.cells = []
        elif tag in ("td", "th") and self.cells is not None:
            self.cur = []
        elif tag in ("table",):
            self.flush()
            self.lines.append("TABLE START")
        elif tag in self.BLOCK:
            self.flush()
            if tag in ("h2", "h3", "h4"):
                self.cur.append("## ")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "nav", "header", "footer"):
            self.skip = max(0, self.skip - 1)
            return
        if self.skip:
            return
        if tag in ("td", "th") and self.cells is not None:
            self.cells.append(re.sub(r"\s+", " ", "".join(self.cur)).strip())
            self.cur = []
        elif tag == "tr" and self.cells is not None:
            self.lines.append(" | ".join(self.cells))
            self.cells = None
            self.cur = []
        elif tag == "table":
            self.flush()
            self.lines.append("END TABLE")
        elif tag in self.BLOCK:
            self.flush()

    def handle_data(self, data):
        if not self.skip:
            self.cur.append(data)


def render_html(raw: str) -> str:
    p = _HTMLText()
    p.feed(raw)
    p.flush()
    head = [
        "TITLE: " + p.meta.get("citation_title", ""),
        "DOI: " + p.meta.get("citation_doi", ""),
        "SOURCE: PubMed Central public web page (Europe PMC XML not available for this article)",
    ]
    return "\n".join(head + p.lines) + "\n"


def fetch(pmcid: str, force: bool = False) -> pathlib.Path:
    RAW.mkdir(parents=True, exist_ok=True)
    xml_path = RAW / f"{pmcid}.xml"
    txt_path = RAW / f"{pmcid}.txt"
    if pmcid in HTML_ONLY:
        html_path = RAW / f"{pmcid}.html"
        if force or not html_path.exists():
            req = urllib.request.Request(PMC_HTML.format(pmcid=pmcid),
                                         headers={"User-Agent": "Mozilla/5.0 " + UA})
            with urllib.request.urlopen(req, timeout=60) as r:
                html_path.write_bytes(r.read())
        txt_path.write_text(render_html(html_path.read_text(encoding="utf-8")), encoding="utf-8")
        return txt_path
    if force or not xml_path.exists():
        req = urllib.request.Request(URL.format(pmcid=pmcid), headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=60) as r:
            data = r.read()
        if not data.strip().startswith(b"<"):
            raise RuntimeError(f"{pmcid}: no XML returned")
        xml_path.write_bytes(data)
        time.sleep(0.3)
    txt_path.write_text(render(xml_path.read_bytes()), encoding="utf-8")
    return txt_path


if __name__ == "__main__":
    for pid in sys.argv[1:]:
        try:
            p = fetch(pid.strip())
            print(f"ok {pid} -> {p} ({p.stat().st_size} bytes)")
        except Exception as e:  # noqa: BLE001
            print(f"FAIL {pid}: {e}")
