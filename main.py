"""
Baigiamųjų darbų apimties skaičiuoklė.

Kiekvienam PDF aplanke:
  * suskaičiuoja visus puslapius;
  * suranda, kuriame puslapyje prasideda priedai („1 priedas“, „PRIEDAI“, „A priedas“, „Appendix 1“ …);
  * apskaičiuoja puslapius be priedų (= priedų pradžios puslapis − 1);
  * paima studento anotacijoje nurodytą apimtį („Darbo apimtis – 88 p. …“) ir paveikslų skaičių palyginimui.

Rezultatas: CSV failas (atsidaro Excel) ir, su --rename, pervadinti failai:
    Adam.Nekrašas.pdf  ->  Adam.Nekrašas__93.pdf
(skaičius po „__“ = puslapiai be priedų; Power Apps jį perskaito iš failo pavadinimo)

Naudojimas:
    pip install pypdfium2
    python thesis_pages.py "C:\\Moodle\\Baigiamieji"            # tik CSV ataskaita
    python thesis_pages.py "C:\\Moodle\\Baigiamieji" --rename   # + pervadina failus
"""
import csv
import re
import sys
import unicodedata
from pathlib import Path

import pypdfium2 as pdfium

# ---------------------------------------------------------------------------
# Priedų antraštės (tikrinamos tik pirmose puslapio eilutėse)
# ---------------------------------------------------------------------------
ANNEX_PATTERNS = [
    re.compile(r"^\s*(\d{1,2}|[A-Z]|[IVX]{1,4})\s*[-.]?\s*(asis\s+)?priedas\b", re.I),  # 1 priedas, A priedas, 1-asis priedas
    re.compile(r"^\s*priedas\s*(nr\.?\s*)?(\d{1,2}|[A-Z])\b", re.I),                    # Priedas Nr. 1, Priedas A
    re.compile(r"^\s*PRIEDAI\s*$"),                                                     # PRIEDAI (tik didžiosiomis)
    re.compile(r"^\s*(appendix|annex)\s*(no\.?\s*)?(\d{1,2}|[A-Z])\b", re.I),           # Appendix 1, Annex A
    re.compile(r"^\s*(APPENDICES|ANNEXES|APPENDIXES)\s*$"),
]
TOC_LINE = re.compile(r"(\.{4,}|…{2,}|\s\d{1,3}\s*$)")  # turinio eilutės: taškeliai arba puslapio nr. gale

# Anotacija: „Darbo apimtis – 88 p. teksto be priedų, 13 paveikslai, …“
VOLUME = re.compile(r"apimtis\s*[-–—:]?\s*(\d{1,3})\s*(p\.|psl|puslap)", re.I)
VOLUME_EN = re.compile(r"(\d{1,3})\s*pages", re.I)
FIGURES = re.compile(r"(\d{1,3})\s*(pav\.|paveiksl|figures?)", re.I)


def first_lines(text, n=3):
    lines = [l.strip() for l in (text or "").splitlines() if l.strip()]
    return lines[:n]


def is_annex_start(text):
    for line in first_lines(text):
        if TOC_LINE.search(line):
            continue
        if any(p.search(line) for p in ANNEX_PATTERNS):
            return True
    return False


SUFFIX = re.compile(r"__\d+$")


def clean_stem(path):
    # „Adam.Nekrašas__93“ -> „Adam.Nekrašas“ (nuimamas ankstesnis puslapių priedėlis)
    return SUFFIX.sub("", unicodedata.normalize("NFC", path.stem))


def name_from_file(path):
    # „Adam.Nekrašas.pdf“ -> „Adam Nekrašas“
    stem = clean_stem(path)
    return re.sub(r"[._]+", " ", stem).strip()


def analyse(path):
    row = {
        "Failas": path.name,
        "VardasPavarde": name_from_file(path),
        "VisoPsl": "",
        "PriedaiNuoPsl": "",
        "PslBePriedu": "",
        "AnotacijojePsl": "",
        "Paveikslu": "",
        "Pastaba": "",
    }
    try:
        pdf = pdfium.PdfDocument(str(path))
        text_of = lambda i: pdf[i].get_textpage().get_text_range().replace("\r", "")
        total = len(pdf)
        row["VisoPsl"] = total

        # anotacija — pirmuose 6 puslapiuose
        head = "\n".join(text_of(i) for i in range(min(6, total)))
        head_flat = re.sub(r"\s+", " ", head)
        m = VOLUME.search(head_flat) or VOLUME_EN.search(head_flat)
        if m:
            row["AnotacijojePsl"] = int(m.group(1))
            f = FIGURES.search(head_flat[m.start(): m.start() + 250])
            if f:
                row["Paveikslu"] = int(f.group(1))

        # priedų pradžia — ieškoma tik po pirmojo trečdalio (kad nepagautų turinio)
        start_from = max(5, total // 3)
        annex = next((i + 1 for i in range(start_from, total) if is_annex_start(text_of(i))), None)

        if annex:
            row["PriedaiNuoPsl"] = annex
            row["PslBePriedu"] = annex - 1
        else:
            row["PslBePriedu"] = total
            row["Pastaba"] = "Priedų nerasta (skaičiuojami visi puslapiai)"

        if row["AnotacijojePsl"] and abs(int(row["AnotacijojePsl"]) - int(row["PslBePriedu"])) > 3:
            note = f"Anotacijoje nurodyta {row['AnotacijojePsl']} p. — patikrinkite"
            row["Pastaba"] = (row["Pastaba"] + "; " if row["Pastaba"] else "") + note
        if not any(text_of(i).strip() for i in range(min(3, total))):
            row["Pastaba"] = "PDF be teksto (skenuotas?) — suskaičiuokite ranka"
        pdf.close()
    except Exception as e:  # sugadintas / užšifruotas PDF
        row["Pastaba"] = f"Klaida: {e}"
    return row


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    rename = "--rename" in sys.argv
    folder = Path(args[0])
    out = Path(args[1]) if len(args) > 1 else folder / "darbu_apimtis.csv"

    files = sorted(p for p in folder.rglob("*") if p.suffix.lower() == ".pdf")
    rows = []
    for p in files:
        r = analyse(p)
        if rename and r["PslBePriedu"] != "":
            target = p.with_name(f"{clean_stem(p)}__{r['PslBePriedu']}{p.suffix}")
            if target != p:
                if target.exists():
                    r["Pastaba"] = (r["Pastaba"] + "; " if r["Pastaba"] else "") + f"Nepervadinta: {target.name} jau yra"
                else:
                    p.rename(target)
                    r["Failas"] = target.name
        rows.append(r)
        print(f"{r['VardasPavarde']:<35} viso {r['VisoPsl']:>4} | be priedų {r['PslBePriedu']:>4} | anotacijoje {r['AnotacijojePsl'] or '-':>4}  {r['Pastaba']}")

    with open(out, "w", newline="", encoding="utf-8-sig") as fh:   # utf-8-sig -> Excel teisingai rodo lietuviškas raides
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()) if rows else ["Failas"], delimiter=";")
        w.writeheader()
        w.writerows(rows)
    print(f"\n{len(rows)} failų. Rezultatas: {out}")


if __name__ == "__main__":
    main()