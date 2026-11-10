#!/usr/bin/env python3
"""
Komut satırından denetim.

    py -3.12 denetle.py kitap.pdf                  # TDK ile
    py -3.12 denetle.py kitap.pdf --cevrimdisi     # TDK'ye bağlanmadan
    py -3.12 denetle.py kitap.pdf --cikti sonuc    # sonuc.csv ve sonuc.html

Çıktı: terminalde özet, CSV ve HTML rapor.
"""

import argparse
import sys
from pathlib import Path

from denetim import Denetleyici, csv_yaz, html_yaz


def main():
    ap = argparse.ArgumentParser(description="Ders kitabı PDF denetleyici")
    ap.add_argument("pdf", help="Denetlenecek PDF dosyası")
    ap.add_argument("--cikti", default="rapor", help="Çıktı dosya adı öneki (varsayılan: rapor)")
    ap.add_argument("--cevrimdisi", action="store_true", help="TDK'ye bağlanma; yalnızca yerel sözlükleri kullan")
    ap.add_argument("--etkinlikleri-denetle", action="store_true",
                    help="Etkinlik bölümlerini de denetle (varsayılan: bilerek yanlış yazılmış alıştırmalar atlanır)")
    args = ap.parse_args()
    if not Path(args.pdf).exists():
        sys.exit(f"Dosya bulunamadı: {args.pdf}")

    print("Sözlükler yükleniyor…")
    denetleyici = Denetleyici()
    sonuc = denetleyici.pdf_denetle(args.pdf, tdk_kullan=not args.cevrimdisi, etkinlik_atla=not args.etkinlikleri_denetle,
                                    ilerleme=lambda asama, yuzde: print(f"\r%{yuzde:3d}  {asama:<60}", end=""))
    print()
    if not sonuc.paragraf_sayisi:
        sys.exit("PDF'ten metin çıkarılamadı. Taranmış (resim) bir PDF olabilir; bunun için OCR gerekir.")

    csv_yaz(sonuc.bulgular, f"{args.cikti}.csv")
    html_yaz(sonuc, f"{args.cikti}.html")
    sayilar = ", ".join(f"{k}: {v}" for k, v in sonuc.sayilar().items())
    print(f"\n{sonuc.sayfa_sayisi} sayfa, {sonuc.paragraf_sayisi} paragraf tarandı. {len(sonuc.bulgular)} bulgu ({sayilar}).")
    print(f"TDK: {sonuc.tdk_durum}   Süre: {sonuc.sure} sn")
    print("Ayrılan özel isimler: " + (", ".join(a for a, _ in sonuc.ozel_adlar.most_common(30)) or "yok"))
    if sonuc.etkinlik_sayfalari:
        print("Etkinlik bölümü atlanan sayfalar: " + ", ".join(map(str, sonuc.etkinlik_sayfalari)))
    if sonuc.okunamayan_sayfalar:
        print("Metni okunamayan sayfalar: " + ", ".join(map(str, sonuc.okunamayan_sayfalar)))
    print()
    for b in sonuc.bulgular:
        tekrar = f" ({b.adet} kez)" if b.adet > 1 else ""
        print(f"[Sayfa {b.sayfa}] {b.kriter:<9} '{b.kelime}'{tekrar} → {b.oneri}")
        print(f"      {b.aciklama}  |  {b.baglam}")
    print(f"\nRaporlar: {args.cikti}.csv ve {args.cikti}.html")


if __name__ == "__main__":
    main()
