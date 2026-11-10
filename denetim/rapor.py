"""Bulgu kaydı, tekrar eden bulguların birleştirilmesi ve CSV / HTML rapor."""

import csv
import html
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from .metin import tr_kucuk

KRITER_ADLARI = {"ARGO": "Argo / uygunsuz", "YAZIM": "Yazım", "NOKTALAMA": "Noktalama"}


@dataclass
class Bulgu:
    sayfa: int
    paragraf: int
    kriter: str          # ARGO / YAZIM / NOKTALAMA
    kelime: str          # sorunlu kelime ya da ifade
    aciklama: str
    oneri: str
    baglam: str          # sorunlu yerin çevresindeki metin
    adet: int = 1        # aynı bulgu kaç kez geçti
    sayfalar: str = ""   # geçtiği sayfalar


def bulgulari_birlestir(bulgular) -> list[Bulgu]:
    """Aynı kelime bir kez listelenir; kaç kez ve hangi sayfalarda geçtiği yazılır.
    Noktalama hataları her yerde ayrı düzeltildiği için yalnızca birebir aynı olanlar birleştirilir."""
    gruplar = {}
    for b in bulgular:
        anahtar = (b.kriter, tr_kucuk(b.kelime)) if b.kriter != "NOKTALAMA" else (b.kriter, b.aciklama, b.kelime, b.baglam)
        gruplar.setdefault(anahtar, []).append(b)
    sonuc = []
    for grup in gruplar.values():
        ilk = grup[0]
        sayfalar = dict.fromkeys(b.sayfa for b in grup)
        sonuc.append(Bulgu(ilk.sayfa, ilk.paragraf, ilk.kriter, ilk.kelime, ilk.aciklama, ilk.oneri, ilk.baglam,
                           len(grup), ", ".join(map(str, sayfalar))))
    return sonuc


def csv_yaz(bulgular, yol):
    with open(yol, "w", newline="", encoding="utf-8-sig") as f:   # utf-8-sig: Excel Türkçe karakterleri doğru açar
        yazici = csv.DictWriter(f, fieldnames=[a.name for a in fields(Bulgu)])
        yazici.writeheader()
        yazici.writerows(asdict(b) for b in bulgular)


def html_yaz(sonuc, yol):
    """Yazdırılabilir, tek dosyalık HTML rapor."""
    e = html.escape
    satirlar = "".join(
        f"<tr class='{b.kriter.lower()}'><td>{b.sayfa}</td><td>{KRITER_ADLARI[b.kriter]}</td><td><b>{e(b.kelime)}</b></td>"
        f"<td>{e(b.aciklama)}</td><td>{e(b.oneri)}</td><td>{b.adet}</td><td>{e(b.sayfalar)}</td><td>{e(b.baglam)}</td></tr>"
        for b in sonuc.bulgular)
    sayilar = " · ".join(f"{KRITER_ADLARI[k]}: {v}" for k, v in sonuc.sayilar().items())
    ozel = ", ".join(f"{e(a)} ({n})" for a, n in sonuc.ozel_adlar.most_common()) or "yok"
    okunamayan = ", ".join(map(str, sonuc.okunamayan_sayfalar)) or "yok"
    etkinlik = ", ".join(map(str, sonuc.etkinlik_sayfalari)) or "yok"
    Path(yol).write_text(f"""<!DOCTYPE html><html lang="tr"><head><meta charset="utf-8"><title>Denetim Raporu</title>
<style>
body{{font-family:Arial,sans-serif;margin:28px;color:#1c1c1c}}h1{{font-size:22px;margin:0 0 4px;border-top:6px solid #dc0d15;padding-top:14px}}
p{{margin:4px 0;font-size:14px}}table{{border-collapse:collapse;width:100%;margin-top:16px}}
td,th{{border:1px solid #d9d9d9;padding:6px 8px;font-size:13px;vertical-align:top;text-align:left}}th{{background:#dc0d15;color:#fff}}
tr.argo td:nth-child(2){{color:#b30a11;font-weight:bold}}tr.yazim td:nth-child(2){{color:#8a5300;font-weight:bold}}
@media print{{body{{margin:0}}th{{-webkit-print-color-adjust:exact;print-color-adjust:exact}}}}
</style></head><body>
<h1>Ders Kitabı Denetim Raporu</h1>
<p><b>Dosya:</b> {e(sonuc.dosya_adi)} — {sonuc.sayfa_sayisi} sayfa, {sonuc.paragraf_sayisi} paragraf</p>
<p><b>Bulgu:</b> {len(sonuc.bulgular)} ({sayilar})</p>
<p><b>Ayrılan özel isimler (hata sayılmadı):</b> {ozel}</p>
<p><b>Etkinlik bölümü atlanan sayfalar (bilerek yanlış yazılmış alıştırmalar):</b> {etkinlik}</p>
<p><b>Metni okunamayan sayfalar (denetlenmedi):</b> {okunamayan}</p>
<table><tr><th>Sayfa</th><th>Tür</th><th>Kelime</th><th>Açıklama</th><th>Öneri</th><th>Tekrar</th><th>Geçtiği sayfalar</th><th>Bağlam</th></tr>
{satirlar}</table></body></html>""", encoding="utf-8")
