"""
Etiketten für Brother P-touch-Bandgeräte.

- .lbx-Dateien für den P-touch Editor (Aufbau 1:1 nach einer mit P-touch Editor 6.12 gespeicherten
  Vorlage: nativer QR-Code links, rechts drei Zeilen Artikel / interne Nummer / Firma)
- PDF mit einer Seite pro Etikett in Bandgröße, druckbar direkt über den Brother-Druckertreiber

Maße in Punkt (1 pt = 1/72 Zoll). Bandbreiten, Ränder und Formatcodes laut P-touch Editor.
"""
import functools
import io
import zipfile
from xml.sax.saxutils import escape

from django.utils import timezone

PT_PER_MM = 72 / 25.4

TAPES = {
    "24": {"label": "24 mm", "width": 68.0, "margin": 8.4, "format": 261, "band": 51.2, "cell": "2pt"},
    "18": {"label": "18 mm", "width": 51.2, "margin": 3.2, "format": 260, "band": 44.8, "cell": "1.6pt"},
    "12": {"label": "12 mm", "width": 33.6, "margin": 2.8, "format": 259, "band": 28.0, "cell": "1.2pt"},
}
DEFAULT_TAPE = "24"

PRINTER_ID = "30256"
PRINTER_NAME = "Brother PT-P710BT"

NS = (
    'xmlns:pt="http://schemas.brother.info/ptouch/2007/lbx/main" '
    'xmlns:style="http://schemas.brother.info/ptouch/2007/lbx/style" '
    'xmlns:text="http://schemas.brother.info/ptouch/2007/lbx/text" '
    'xmlns:draw="http://schemas.brother.info/ptouch/2007/lbx/draw" '
    'xmlns:image="http://schemas.brother.info/ptouch/2007/lbx/image" '
    'xmlns:barcode="http://schemas.brother.info/ptouch/2007/lbx/barcode" '
    'xmlns:database="http://schemas.brother.info/ptouch/2007/lbx/database" '
    'xmlns:table="http://schemas.brother.info/ptouch/2007/lbx/table" '
    'xmlns:cable="http://schemas.brother.info/ptouch/2007/lbx/cable"'
)


def _pt(value):
    return f"{round(value, 1):g}pt"


def layout(tape=DEFAULT_TAPE):
    """Geometrie eines Etiketts; für 24 mm identisch mit der P-touch-Vorlage."""
    t = TAPES.get(tape, TAPES[DEFAULT_TAPE])
    scale = t["band"] / 51.2
    edge = 5.6                       # Rand am Bandanfang/-ende
    qr = t["band"] - 1.2             # QR-Code quadratisch über die bedruckbare Höhe
    text_x = edge + qr + 4.2
    text_w = 83.0
    length = text_x + text_w + 1.2 + edge
    line_h = 16.7 * scale
    lines = [
        {"y": t["margin"] + off * scale, "h": line_h, "size": size * scale, "org": org * scale, "weight": weight}
        for off, size, org, weight in [(0, 13.7, 14, 700), (17.3, 12, 12, 400), (34.5, 12, 12, 400)]
    ]
    return {**t, "edge": edge, "qr": qr, "text_x": text_x, "text_w": text_w, "length": length, "lines": lines,
            "length_mm": length / PT_PER_MM, "width_mm": t["width"] / PT_PER_MM}


def _font(size, weight):
    return (f'<text:ptFontInfo><text:logFont name="Calibri" width="0" italic="false" weight="{weight}" charSet="0" '
            f'pitchAndFamily="34"/><text:fontExt effect="NOEFFECT" underline="0" strikeout="0" size="{_pt(size)}" '
            f'orgSize="28.8pt" textColor="#000000" textPrintColorNumber="1"/></text:ptFontInfo>')


def _style(x, y, w, h, name, pen="NULL"):
    return (f'<pt:objectStyle x="{_pt(x)}" y="{_pt(y)}" width="{_pt(w)}" height="{_pt(h)}" backColor="#FFFFFF" '
            f'backPrintColorNumber="0" ropMode="COPYPEN" angle="0" anchor="TOPLEFT" flip="NONE">'
            f'<pt:pen style="{pen}" widthX="0.5pt" widthY="0.5pt" color="#000000" printColorNumber="1"/>'
            f'<pt:brush style="NULL" color="#000000" printColorNumber="1" id="0"/>'
            f'<pt:expanded objectName="{name}" ID="0" lock="0" templateMergeTarget="LABELLIST" '
            f'templateMergeType="NONE" templateMergeID="0" allowOutOfBoundsTransfer="false" linkStatus="NONE" '
            f'linkID="0"/></pt:objectStyle>')


def _clean(value):
    return " ".join(str(value or "").split())


def _text_object(n, x, line, width, value):
    value = _clean(value)
    char_len = len(value.encode("utf-16-le")) // 2  # P-touch zählt UTF-16-Einheiten
    font = _font(line["size"], line["weight"])
    items = f'<text:stringItem charLen="{char_len}">{font}</text:stringItem>' if char_len else ""
    return (f'<text:text>{_style(x, line["y"], width, line["h"], f"Text{n}")}{font}'
            f'<text:textControl control="LONGTEXTFIXED" clipFrame="false" aspectNormal="true" shrink="true" '
            f'autoLF="true" avoidImage="false"/>'
            f'<text:textAlign horizontalAlignment="LEFT" verticalAlignment="CENTER" inLineAlignment="BASELINE"/>'
            f'<text:textStyle vertical="false" nullBlock="false" charSpace="0" lineSpace="0" '
            f'orgPoint="{_pt(line["org"])}" combinedChars="false"/>'
            f'<text:transferSettings editOnPrintFormat="" editOnPrintOrder="0"/>'
            f'<pt:data>{escape(value)}</pt:data>{items}</text:text>')


def _qr_object(n, geo, data):
    return (f'<barcode:barcode>{_style(geo["edge"], geo["margin"], geo["qr"], geo["qr"], f"Barcode{n}", "INSIDEFRAME")}'
            f'<barcode:barcodeStyle protocol="QRCODE" lengths="48" zeroFill="false" barWidth="1.2pt" barRatio="1:3" '
            f'humanReadable="true" humanReadableAlignment="LEFT" checkDigit="false" autoLengths="true" margin="true" '
            f'sameLengthBar="false" bearerBar="false"/>'
            f'<barcode:qrcodeStyle model="2" eccLevel="15%" cellSize="{geo["cell"]}" mbcs="auto" joint="1" '
            f'version="auto"/><pt:data>{escape(_clean(data))}</pt:data></barcode:barcode>')


def label_xml(lines, qr_data, tape=DEFAULT_TAPE):
    geo = layout(tape)
    texts = "".join(_text_object(i + 2, geo["text_x"], geo["lines"][i], geo["text_w"], (list(lines) + ["", "", ""])[i])
                    for i in range(3))
    band_x, band_w = geo["edge"], geo["length"] - 2 * geo["edge"]
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<pt:document {NS} version="1.10" generator="P-touch Editor 6.12.1.0 Windows">'
        '<pt:body currentSheet="Blatt 1" direction="LTR"><style:sheet name="Blatt 1">'
        f'<style:paper media="0" width="{_pt(geo["width"])}" height="{_pt(geo["length"])}" '
        f'marginLeft="{_pt(geo["margin"])}" marginTop="5.6pt" marginRight="{_pt(geo["margin"])}" marginBottom="5.6pt" '
        f'orientation="landscape" autoLength="false" monochromeDisplay="true" printColorDisplay="false" '
        f'printColorsID="0" paperColor="#FFFFFF" paperInk="#000000" split="1" format="{geo["format"]}" '
        f'backgroundTheme="0" printerID="{PRINTER_ID}" printerName="{PRINTER_NAME}"/>'
        '<style:cutLine regularCut="0pt" freeCut=""/>'
        f'<style:backGround x="{_pt(band_x)}" y="{_pt(geo["margin"])}" width="{_pt(band_w)}" height="{_pt(geo["band"])}" '
        'brushStyle="NULL" brushId="0" userPattern="NONE" userPatternId="0" color="#000000" printColorNumber="1" '
        'backColor="#FFFFFF" backPrintColorNumber="0"/>'
        f'<pt:objects>{texts}{_qr_object(5, geo, qr_data)}</pt:objects>'
        '</style:sheet></pt:body></pt:document>\n'
    )


def prop_xml():
    now = timezone.now().strftime("%Y-%m-%dT%H:%M:%SZ")
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<meta:properties xmlns:meta="http://schemas.brother.info/ptouch/2007/lbx/meta" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/">'
        '<meta:appName>P-touch Editor 6.12.1.0 Windows</meta:appName><dc:title></dc:title><dc:subject></dc:subject>'
        '<dc:creator>JobForge</dc:creator><meta:keyword></meta:keyword><dc:description></dc:description>'
        f'<meta:template></meta:template><dcterms:created>{now}</dcterms:created>'
        f'<dcterms:modified>{now}</dcterms:modified><meta:lastPrinted></meta:lastPrinted>'
        '<meta:modifiedBy></meta:modifiedBy><meta:revision>1</meta:revision><meta:editTime>0</meta:editTime>'
        '<meta:numPages>1</meta:numPages><meta:numWords>0</meta:numWords><meta:numChars>0</meta:numChars>'
        '<meta:security>0</meta:security><meta:transferScript></meta:transferScript></meta:properties>\n'
    )


def build_lbx(lines, qr_data, tape=DEFAULT_TAPE):
    """Eine .lbx-Datei (ZIP mit label.xml und prop.xml) als Bytes."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("label.xml", label_xml(lines, qr_data, tape).encode("utf-8"))
        z.writestr("prop.xml", prop_xml().encode("utf-8"))
    return buf.getvalue()


def safe_filename(value):
    keep = "".join(c if c.isalnum() or c in "-_." else "_" for c in str(value))
    return keep.strip("._") or "etikett"


def build_lbx_zip(items, tape=DEFAULT_TAPE):
    """Mehrere Etiketten als ZIP mit je einer .lbx-Datei."""
    buf = io.BytesIO()
    used = set()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for item in items:
            name = safe_filename(item["code"])
            candidate, n = name, 2
            while candidate in used:
                candidate, n = f"{name}_{n}", n + 1
            used.add(candidate)
            z.writestr(f"{candidate}.lbx", build_lbx(item["lines"], item["code"], tape))
    return buf.getvalue()


def _split_two(text):
    """Text an dem Leerzeichen trennen, das die Zeilen am gleichmäßigsten aufteilt."""
    spaces = [i for i, c in enumerate(text) if c == " "]
    if not spaces:
        mid = len(text) // 2
        return [text[:mid], text[mid:]]
    i = min(spaces, key=lambda s: abs(s - len(text) / 2))
    return [text[:i], text[i + 1:]]


def pdf_lines(lines, geo):
    """Textzeilen für die PDF-Ausgabe. Zu lange Texte werden verkleinert und – wenn das besser lesbar ist –
    auf zwei Zeilen umbrochen (wie „Verkleinern“/Zeilenumbruch im P-touch Editor)."""
    out = []
    avail = geo["text_w"] * 0.96
    for text, line in zip((list(lines) + ["", "", ""])[:3], geo["lines"]):
        text = _clean(text)
        bold = line["weight"] >= 600
        size, parts = line["size"], [text]
        width = text_width_per_pt(text, bold)
        if text and width * size > avail:
            size = avail / width
            two = _split_two(text)
            two_size = min(line["h"] / 2.15, avail / max(text_width_per_pt(p, bold) for p in two))
            if two_size > size * 1.15:
                size, parts = two_size, two
            size = max(size, 3.5)
        out.append({"text": text, "parts": parts, "size": size, "weight": line["weight"], "y": line["y"],
                    "h": line["h"]})
    return out


FONT_FILES = {
    True: ["Carlito-Bold.ttf", "calibrib.ttf", "LiberationSans-Bold.ttf", "DejaVuSans-Bold.ttf"],
    False: ["Carlito-Regular.ttf", "calibri.ttf", "LiberationSans-Regular.ttf", "DejaVuSans.ttf"],
}


@functools.lru_cache(maxsize=4)
def _measure_font(bold):
    from PIL import ImageFont

    for name in FONT_FILES[bold]:
        try:
            return ImageFont.truetype(name, 100)
        except OSError:
            continue
    return None


def text_width_per_pt(text, bold=False):
    """Breite des Textes in pt je 1 pt Schriftgröße – gemessen mit Calibri/Carlito, sonst geschätzt."""
    if not text:
        return 0.0
    font = _measure_font(bold)
    if font is None:
        return len(text) * (0.62 if bold else 0.56)
    return font.getlength(text) / 100
