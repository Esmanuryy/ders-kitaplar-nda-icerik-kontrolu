#!/usr/bin/env python3
"""
Ders Kitaplarında İçerik ve Tutarlılık Hatalarının Otomatik Tespiti
-------------------------------------------------------------------
Kullanım:
    python denetleyici.py kitap.pdf
    python denetleyici.py kitap.pdf --cikti rapor

Üç değerlendirme kriteri:
    1) ARGO / UYGUNSUZ İFADE  (TDK Güncel Türkçe Sözlük "argo/kaba" etiketi + argo_listesi.txt)
    2) YAZIM HATASI           (TDK Sözlük + TDK Yazım Kılavuzu + Zemberek)
    3) NOKTALAMA / TEKRAR     (TDK Yazım Kılavuzu'ndaki kurallara dayalı, kural tabanlı)

Çıktı: terminalde özet + CSV + HTML rapor (sayfa ve paragraf numarasıyla).
"""

import argparse
import csv
import html
import itertools
import logging
import re
import sys
from dataclasses import dataclass, asdict
from functools import lru_cache
from pathlib import Path

import pymupdf  # PyMuPDF
from zemberek import TurkishMorphology

from tdk import TDK

logging.disable(logging.INFO)  # Zemberek'in gereksiz log mesajlarını sustur

KLASOR = Path(__file__).parent

# ---------------------------------------------------------------------------
# 0) Yardımcı: Türkçe'ye uygun küçük harfe çevirme ve kelime ayırma
# ---------------------------------------------------------------------------
HARFLER = "A-Za-zÇĞİÖŞÜçğıöşüÂâÎîÛû"
KELIME_RE = re.compile(rf"[{HARFLER}]+(?:['’][{HARFLER}]+)?")
TR_ALFABE = "abcçdefgğhıijklmnoöprsştuüvyz"


def tr_kucuk(s: str) -> str:
    """'I'.lower() Türkçe'de 'i' verir ama doğrusu 'ı'. Bunu düzeltir."""
    return s.replace("İ", "i").replace("I", "ı").lower()


# ---------------------------------------------------------------------------
# 1) Bulgu (hata) kaydı
# ---------------------------------------------------------------------------
@dataclass
class Bulgu:
    sayfa: int
    paragraf: int
    kriter: str       # ARGO / YAZIM / NOKTALAMA
    kelime: str       # sorunlu kelime ya da ifade
    aciklama: str
    oneri: str
    baglam: str       # sorunlu kelimenin çevresindeki metin


def baglam_al(metin: str, bas: int, son: int, pay: int = 40) -> str:
    a, b = max(0, bas - pay), min(len(metin), son + pay)
    return ("…" if a > 0 else "") + metin[a:b].strip() + ("…" if b < len(metin) else "")


# ---------------------------------------------------------------------------
# 2) PDF'ten paragraf çıkarma
# ---------------------------------------------------------------------------
def pdf_paragraflari(yol: str):
    """Her sayfadan (sayfa_no, paragraf_no, metin) üretir."""
    belge = pymupdf.open(yol)
    for sayfa_no, sayfa in enumerate(belge, start=1):
        bloklar = sayfa.get_text("blocks")  # (x0, y0, x1, y1, metin, blok_no, tip)
        bloklar = [b for b in bloklar if b[6] == 0]       # 0 = metin bloğu (1 = resim)
        bloklar.sort(key=lambda b: (round(b[1]), b[0]))   # yukarıdan aşağı, soldan sağa
        par_no = 0
        for b in bloklar:
            metin = b[4]
            metin = re.sub(r"-\n(?=[a-zçğıöşü])", "", metin)  # satır sonu tireleme: "kita-\nplar"
            metin = metin.replace("\n", " ")
            if len(metin.strip()) < 3:
                continue
            par_no += 1
            yield sayfa_no, par_no, metin.strip()


# ---------------------------------------------------------------------------
# 3) Kriter 1: Argo / uygunsuz ifade
# ---------------------------------------------------------------------------
def liste_oku(yol: Path) -> set[str]:
    kelimeler = set()
    for satir in yol.read_text(encoding="utf-8").splitlines():
        satir = satir.strip()
        if satir and not satir.startswith("#"):
            kelimeler.add(tr_kucuk(satir))
    return kelimeler


def yanlis_sozlugu_oku(yol: Path) -> dict[str, str]:
    sozluk = {}
    for satir in yol.read_text(encoding="utf-8").splitlines():
        satir = satir.strip()
        if satir and not satir.startswith("#") and "=" in satir:
            yanlis, dogru = satir.split("=", 1)
            sozluk[tr_kucuk(yanlis.strip())] = dogru.strip()
    return sozluk


# ---------------------------------------------------------------------------
# 4) Kriter 2: Yazım denetimi (Zemberek)
# ---------------------------------------------------------------------------
class YazimDenetcisi:
    def __init__(self):
        self.morfoloji = TurkishMorphology.create_with_defaults()

    @lru_cache(maxsize=50000)
    def kok(self, kelime: str) -> str | None:
        """Kelime Türkçe'de geçerliyse kökünü, değilse None döner."""
        sonuc = self.morfoloji.analyze(kelime)
        for a in sonuc.analysis_results:
            if str(a.item.primary_pos) != "PrimaryPos.Unknown":
                return a.get_stem()
        return None

    @lru_cache(maxsize=50000)
    def sozluk_maddeleri(self, kelime: str) -> tuple[str, ...]:
        """Çekimli kelimenin sözlük maddelerini verir: gidiyoruz -> gitmek, kitapları -> kitap."""
        maddeler = []
        for a in self.morfoloji.analyze(kelime).analysis_results:
            if str(a.item.primary_pos) != "PrimaryPos.Unknown":
                maddeler.append(tr_kucuk(a.item.lemma))
        return tuple(dict.fromkeys(maddeler))

    def gecerli_mi(self, kelime: str) -> bool:
        return self.kok(kelime) is not None

    @lru_cache(maxsize=20000)
    def oneriler(self, kelime: str) -> tuple[str, ...]:
        """Hatalı kelime için olası düzeltmeler üretir."""
        adaylar = []

        # (a) Türkçe karakter eksikliği: guzel -> güzel, ogrenci -> öğrenci
        esle = {"c": "cç", "g": "gğ", "i": "iı", "o": "oö", "s": "sş", "u": "uü"}
        secenekler = [esle.get(h, h) for h in kelime]
        if sum(len(s) > 1 for s in secenekler) <= 6:
            for kombinasyon in itertools.product(*secenekler):
                aday = "".join(kombinasyon)
                if aday != kelime and self.gecerli_mi(aday):
                    adaylar.append(aday)

        # (b) Tek harflik düzenlemeler (silme, ekleme, değiştirme, yer değiştirme)
        if not adaylar and len(kelime) >= 4:
            bolumler = [(kelime[:i], kelime[i:]) for i in range(len(kelime) + 1)]
            silme = [s + k[1:] for s, k in bolumler if k]
            yer = [s + k[1] + k[0] + k[2:] for s, k in bolumler if len(k) > 1]
            degis = [s + h + k[1:] for s, k in bolumler if k for h in TR_ALFABE]
            ekle = [s + h + k for s, k in bolumler for h in TR_ALFABE]
            for aday in dict.fromkeys(silme + yer + degis + ekle):
                if aday != kelime and self.gecerli_mi(aday):
                    adaylar.append(aday)
        return tuple(adaylar[:3])


# ---------------------------------------------------------------------------
# 5) Kriter 3: Noktalama / tekrar kuralları
# ---------------------------------------------------------------------------
NOKTALAMA_KURALLARI = [
    (re.compile(r"\S {2,}\S"), "Birden fazla boşluk", "Tek boşluk kullanın"),
    (re.compile(r"\s+[,.;:!?](?!\.)"), "Noktalama işaretinden önce boşluk", "Boşluğu silin"),
    (re.compile(r"[,;:!?][A-Za-zÇĞİÖŞÜçğıöşü]"), "Noktalama işaretinden sonra boşluk yok", "İşaretten sonra boşluk bırakın"),
    (re.compile(r"[.,;:]{2,}(?<!\.\.\.)"), "Tekrarlanan noktalama işareti", "Tek işaret kullanın"),
    (re.compile(r"[!?]{2,}"), "Birden fazla ünlem/soru işareti", "Tek işaret kullanın (ders kitabı dili)"),
    (re.compile(r"\(\s|\s\)"), "Parantez içi gereksiz boşluk", "Boşluğu silin"),
]


def noktalama_bul(sayfa, par_no, metin):
    bulgular = []
    for kural, aciklama, oneri in NOKTALAMA_KURALLARI:
        for m in kural.finditer(metin):
            bulgular.append(Bulgu(sayfa, par_no, "NOKTALAMA", m.group().strip() or "(boşluk)",
                                  aciklama, oneri, baglam_al(metin, m.start(), m.end())))
    # Arka arkaya tekrar eden kelime: "bu bu", "ve ve"
    kelimeler = list(KELIME_RE.finditer(metin))
    for onceki, simdiki in zip(kelimeler, kelimeler[1:]):
        if tr_kucuk(onceki.group()) == tr_kucuk(simdiki.group()) and len(onceki.group()) > 1:
            araya_giren = metin[onceki.end():simdiki.start()]
            if araya_giren.strip() == "":
                bulgular.append(Bulgu(sayfa, par_no, "NOKTALAMA",
                                      f"{onceki.group()} {simdiki.group()}",
                                      "Kelime art arda tekrarlanmış", "Birini silin",
                                      baglam_al(metin, onceki.start(), simdiki.end())))
    return bulgular


# ---------------------------------------------------------------------------
# 6) Bir paragrafı üç kritere göre denetle
# ---------------------------------------------------------------------------
def kelime_govdesi(ham: str) -> str:
    """"PDF’den" gibi kesme işaretli yapılarda sadece kelime gövdesini al."""
    return re.split(r"['’]", ham)[0]


def tdk_adaylari(kucuk: str, denetci) -> tuple[str, ...]:
    """TDK'de aranacak madde başları. Çekimli kelime TDK'de bulunmaz, o yüzden önce
    Zemberek ile sözlük maddesine çeviririz: gidiyoruz -> gitmek, kitapları -> kitap."""
    return denetci.sozluk_maddeleri(kucuk) or (kucuk,)


def tdk_on_yukleme(paragraflar, denetci, tdk):
    """Kitaptaki tüm benzersiz kelimeleri bulup TDK'den toplu (paralel) çeker."""
    gerekli = set()
    for _, _, metin in paragraflar:
        for m in KELIME_RE.finditer(metin):
            govde = kelime_govdesi(m.group())
            if len(govde) >= 2 and not govde.isupper():
                gerekli.update(tdk_adaylari(tr_kucuk(govde), denetci))
    tdk.on_yukle(sorted(gerekli))


def paragraf_denetle(sayfa, par_no, metin, argo, yanlislar, denetci, tdk=None):
    bulgular = []
    for m in KELIME_RE.finditer(metin):
        govde = kelime_govdesi(m.group())
        kucuk = tr_kucuk(govde)
        ctx = baglam_al(metin, m.start(), m.end())
        adaylar = tdk_adaylari(kucuk, denetci)

        # --- Kriter 1: Argo ---
        # (a) TDK Güncel Türkçe Sözlük'te "argo" / "kaba" etiketli mi?
        if tdk:
            tdk_argo = next((tdk.sozluk(a) for a in adaylar
                             if (tdk.sozluk(a) or {}).get("argo")), None)
            if tdk_argo:
                bulgular.append(Bulgu(sayfa, par_no, "ARGO", govde,
                                      "TDK Güncel Türkçe Sözlük'te argo/kaba olarak işaretli: "
                                      + tdk_argo["argo_anlam"],
                                      "Ders kitabına uygun resmî bir ifade kullanın", ctx))
                continue
        # (b) Kendi listemiz (TDK'de olmayan güncel argo ve gündelik dil için)
        if kucuk in argo or any(a in argo for a in adaylar):
            bulgular.append(Bulgu(sayfa, par_no, "ARGO", govde,
                                  "Argo / uygunsuz ya da gündelik konuşma dili (argo_listesi.txt)",
                                  "Ders kitabına uygun resmî bir ifade kullanın", ctx))
            continue

        # --- Kriter 2: Yazım ---
        if kucuk in yanlislar:
            bulgular.append(Bulgu(sayfa, par_no, "YAZIM", govde,
                                  "Sık yapılan yazım yanlışı", yanlislar[kucuk], ctx))
            continue

        # Atlanacaklar: tek harf, tamamı büyük harf (kısaltma: PDF, TDK), cümle ortasındaki
        # büyük harfle başlayan kelimeler (özel isim olma ihtimali yüksek)
        if len(govde) < 2 or govde.isupper():
            continue
        cumle_basi = re.search(r"(^|[.!?]\s+)$", metin[:m.start()]) is not None
        if govde[0].isupper() and not cumle_basi:
            continue

        zemberek_biliyor = denetci.gecerli_mi(kucuk)
        tdk_bilgileri = [tdk.sozluk(a) for a in adaylar] if tdk else []
        tdk_ulasilamadi = (not tdk) or any(b is None for b in tdk_bilgileri)
        tdk_biliyor = any(b and b["var"] for b in tdk_bilgileri)

        if tdk_ulasilamadi:
            hatali, kaynak = (not zemberek_biliyor), "Zemberek (TDK'ye ulaşılamadı)"
        else:
            # TDK'de yoksa VE Zemberek de tanımıyorsa hata say (özel isim/terim yanlış alarmını azaltır)
            hatali, kaynak = (not tdk_biliyor and not zemberek_biliyor), "TDK ve Zemberek"

        if hatali:
            oneriler = []
            if tdk and not tdk_ulasilamadi:
                oneriler += tdk.yazim_onerisi(kucuk)          # TDK Yazım Kılavuzu
            oneriler += list(denetci.oneriler(kucuk))          # Zemberek tabanlı öneri
            oner = ", ".join(dict.fromkeys(oneriler)) or "Öneri bulunamadı"
            bulgular.append(Bulgu(sayfa, par_no, "YAZIM", govde,
                                  f"Sözlükte bulunamadı ({kaynak}) – olası yazım hatası", oner, ctx))

    # --- Kriter 3: Noktalama / tekrar (TDK Yazım Kılavuzu kurallarına göre) ---
    bulgular.extend(noktalama_bul(sayfa, par_no, metin))
    return bulgular


# ---------------------------------------------------------------------------
# 7) Raporlama
# ---------------------------------------------------------------------------
def csv_yaz(bulgular, yol):
    with open(yol, "w", newline="", encoding="utf-8-sig") as f:  # utf-8-sig: Excel Türkçe açar
        yazici = csv.DictWriter(f, fieldnames=list(Bulgu.__dataclass_fields__))
        yazici.writeheader()
        yazici.writerows(asdict(b) for b in bulgular)


def html_yaz(bulgular, yol, pdf_adi, toplam_par):
    renk = {"ARGO": "#fde2e2", "YAZIM": "#fff3cd", "NOKTALAMA": "#e2ecfd"}
    sayac = {}
    for b in bulgular:
        sayac[b.kriter] = sayac.get(b.kriter, 0) + 1
    satirlar = "".join(
        f"<tr style='background:{renk[b.kriter]}'><td>{b.sayfa}</td><td>{b.paragraf}</td>"
        f"<td>{b.kriter}</td><td><b>{html.escape(b.kelime)}</b></td>"
        f"<td>{html.escape(b.aciklama)}</td><td>{html.escape(b.oneri)}</td>"
        f"<td>{html.escape(b.baglam)}</td></tr>"
        for b in bulgular
    )
    ozet = " | ".join(f"{k}: {v}" for k, v in sorted(sayac.items())) or "Hata bulunamadı"
    Path(yol).write_text(f"""<!DOCTYPE html><html lang="tr"><head><meta charset="utf-8">
<title>Denetim Raporu</title>
<style>body{{font-family:Arial,sans-serif;margin:24px}}table{{border-collapse:collapse;width:100%}}
td,th{{border:1px solid #bbb;padding:6px;font-size:14px;vertical-align:top}}th{{background:#333;color:#fff}}</style>
</head><body><h2>Ders Kitabı Denetim Raporu</h2>
<p>Dosya: <b>{html.escape(pdf_adi)}</b> — {toplam_par} paragraf tarandı — {len(bulgular)} bulgu ({ozet})</p>
<table><tr><th>Sayfa</th><th>Paragraf</th><th>Kriter</th><th>Kelime</th><th>Açıklama</th><th>Öneri</th><th>Bağlam</th></tr>
{satirlar}</table></body></html>""", encoding="utf-8")


# ---------------------------------------------------------------------------
# 8) Ana akış
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Ders kitabı PDF denetleyici")
    ap.add_argument("pdf", help="Denetlenecek PDF dosyası")
    ap.add_argument("--cikti", default="rapor", help="Çıktı dosya adı öneki (varsayılan: rapor)")
    ap.add_argument("--cevrimdisi", action="store_true",
                    help="TDK'ye bağlanma; sadece Zemberek ve yerel listeleri kullan")
    args = ap.parse_args()

    if not Path(args.pdf).exists():
        sys.exit(f"Dosya bulunamadı: {args.pdf}")

    argo = liste_oku(KLASOR / "argo_listesi.txt")
    yanlislar = yanlis_sozlugu_oku(KLASOR / "yaygin_yanlislar.txt")
    print("Zemberek yükleniyor…")
    denetci = YazimDenetcisi()

    paragraflar = list(pdf_paragraflari(args.pdf))
    toplam = len(paragraflar)
    if toplam == 0:
        sys.exit("PDF'ten metin çıkarılamadı. Taranmış (resim) bir PDF olabilir; OCR gerekir.")

    tdk = None
    if not args.cevrimdisi:
        tdk = TDK(KLASOR / "tdk_onbellek.json")
        tdk_on_yukleme(paragraflar, denetci, tdk)
        if tdk.hata_sayisi:
            print(f"UYARI: TDK'ye {tdk.hata_sayisi} istek ulaşamadı (internet/engel?). "
                  "Bu kelimeler için sadece Zemberek kullanıldı.")

    bulgular = []
    for sayfa, par_no, metin in paragraflar:
        bulgular.extend(paragraf_denetle(sayfa, par_no, metin, argo, yanlislar, denetci, tdk))
    if tdk:
        tdk.kaydet()

    csv_yaz(bulgular, f"{args.cikti}.csv")
    html_yaz(bulgular, f"{args.cikti}.html", Path(args.pdf).name, toplam)

    print(f"\n{toplam} paragraf tarandı, {len(bulgular)} bulgu var.\n")
    for b in bulgular:
        print(f"[Sayfa {b.sayfa}, Paragraf {b.paragraf}] {b.kriter:<9} '{b.kelime}' → {b.oneri}")
        print(f"      {b.aciklama}  |  {b.baglam}")
    print(f"\nRaporlar: {args.cikti}.csv  ve  {args.cikti}.html")


if __name__ == "__main__":
    main()
