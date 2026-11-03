#!/usr/bin/env python3
"""
Ders Kitaplarında İçerik ve Tutarlılık Hatalarının Otomatik Tespiti
-------------------------------------------------------------------
Kullanım:
    python denetleyici.py kitap.pdf
    python denetleyici.py kitap.pdf --cikti rapor

Üç değerlendirme kriteri:
    1) ARGO / UYGUNSUZ İFADE  (TDK Güncel Türkçe Sözlük "argo/kaba" etiketi + argo_listesi.txt)
    2) YAZIM HATASI           (TDK Sözlük + TDK Yazım Kılavuzu + Zemberek;
                               büyük/küçük harf hataları da bu kritere girer)
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
import unicodedata
from collections import Counter
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


# İnternet ve e-posta adresleri kelime kelime denetlenmez. Aynı uzunlukta işaretle örtülür ki
# bulunan hataların konumu (bağlam) bozulmasın.
ADRES_RE = re.compile(r"(?:https?://|www\.)\S+|[\w.+-]+@[\w-]+(?:\.[\w-]+)+|\b[\w-]+(?:\.[\w-]+)*\.(?:com|net|org|edu|gov|tr|jpe?g|png|pdf|docx?|xlsx?|txt|html?)\b(?:/\S*)?|\bwww\s+\w+(?:\s+\w+){1,3}?\s+(?:tr|com|org|net)\b")


def adresleri_ort(metin: str) -> str:
    return ADRES_RE.sub(lambda m: "§" * len(m.group()), metin)


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
    adet: int = 1     # aynı kelime kitapta kaç kez geçti
    sayfalar: str = ""  # geçtiği sayfalar


def bulgulari_birlestir(bulgular) -> list:
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


def baglam_al(metin: str, bas: int, son: int, pay: int = 40) -> str:
    a, b = max(0, bas - pay), min(len(metin), son + pay)
    return ("…" if a > 0 else "") + metin[a:b].strip() + ("…" if b < len(metin) else "")


# ---------------------------------------------------------------------------
# 2) PDF'ten paragraf çıkarma
# ---------------------------------------------------------------------------
# Eski Türkçe yazı tiplerinde PDF'ten bozuk çıkan harfler. Bu harfler Türkçede kullanılmaz, o yüzden
# görüldüğü blokta düzeltilir: yÕldÕzÕdÕr -> yıldızıdır, úafak -> şafak, da÷ -> dağ, ølâhî -> İlâhî.
BOZUK_HARFLER = (str.maketrans({"Õ": "ı", "ú": "ş", "ù": "Ş", "÷": "ğ", "ø": "İ"}),
                 str.maketrans({"ý": "ı", "þ": "ş", "ð": "ğ", "Ý": "İ", "Þ": "Ş", "Ð": "Ğ"}))
BOZUK_RE = (re.compile(r"[Õúù÷ø]"), re.compile(r"[ýþðÝÞÐ]"))
HARF_DUZELT = str.maketrans({"\u00a0": " ", "\u2002": " ", "\u2003": " ", "\u2009": " ",
                             "ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl",
                             "\u2010": "-", "\u200b": None, "\u200c": None, "\ufeff": None})
BITTI_RE = re.compile(r"[.!?:;…][\"”’')\]]*$")
MADDE_ISARETI = "•›>▪◦‣●○■□\uf0b7\uf0a7\uf076\uf0d8"
MADDE_RE = re.compile(rf"^(?:[{MADDE_ISARETI}]|[–-]\s|\d+[.)]\s|[a-zA-Z]\)\s)")


def harfleri_duzelt(metin: str) -> str:
    metin = unicodedata.normalize("NFC", metin).translate(HARF_DUZELT)
    for kural, tablo in zip(BOZUK_RE, BOZUK_HARFLER):
        if kural.search(metin):
            metin = metin.translate(tablo)
    return metin


def blok_temizle(metin: str) -> str:
    """Satır sonu tirelemesini ve PDF'in satır sonlarında bıraktığı boşlukları temizler."""
    metin = re.sub(r"\u00ad[ \t]*\n\s*", "", metin).replace("\u00ad", "")
    metin = re.sub(r"-[ \t]*\n\s*(?=[a-zçğıöşü])", "", metin)   # satır sonu tireleme: "kita-\nplar"
    metin = re.sub(r"(?<=[A-ZÇĞİÖŞÜ])-[ \t]*\n\s*(?=[A-ZÇĞİÖŞÜ])", "", metin)   # başlıkta: "STRA-\nTEJİ"
    return re.sub(r"[ \t]*\n\s*", " ", metin).strip()


def blok_parcala(ham: str) -> list[str]:
    """Bir PDF bloğunu paragraflara böler. Madde işaretli satırlar ile noktasız kısa liste satırları
    birbirine eklenirse sonraki satırın ilk kelimesi yanlışlıkla "cümle ortası" sayılır.
    Madde işareti (›, •) cümlenin parçası olmadığı için silinir."""
    # Kalın görünsün diye iki kez basılmış şık harfleri PDF'ten "a.a." diye çıkar.
    ham = re.sub(r"(?<![^\W\d_])([a-zçğıöşü])\.\1\.", r"\1.", harfleri_duzelt(ham))
    satirlar = [s.strip() for s in ham.split("\n")]
    satirlar = [s for s in satirlar if s and not re.fullmatch(r"[\W_]+", s)]
    if not satirlar:
        return []
    en_uzun = max(map(len, satirlar))
    gruplar = [[satirlar[0]]]
    for satir in satirlar[1:]:
        onceki = gruplar[-1][-1]
        kisa_liste = (len(onceki) < max(en_uzun * 0.7, 45) and not onceki.endswith(("-", ",", "\u00ad"))
                      and not BITTI_RE.search(onceki) and satir[0].isupper())
        if MADDE_RE.match(satir) or kisa_liste:
            gruplar.append([satir])
        else:
            gruplar[-1].append(satir)
    return [re.sub(rf"^[{MADDE_ISARETI}]\s*", "", blok_temizle("\n".join(g))) for g in gruplar]


def sayfa_bloklari(sayfa) -> list[str]:
    """Sayfanın metnini okuma sırasıyla, kesintisiz metin parçaları olarak verir.
    PDF'te yan yana sütunların satırları karışık sırada gelebilir ("oldu-" + "kişiye" = "oldukişiye" gibi kelimeler
    oluşur). Bu yüzden her satır, hemen üstünde ve aynı yatay konumda olan satırın devamı sayılır.
    Kenardaki dikey ve eğik süs yazıları ("Materyalimi Seçiyorum") alınmaz."""
    bayrak = pymupdf.TEXTFLAGS_DICT & ~pymupdf.TEXT_PRESERVE_LIGATURES & ~pymupdf.TEXT_PRESERVE_IMAGES
    satirlar = []
    for blok in sayfa.get_text("dict", flags=bayrak)["blocks"]:
        for l in blok.get("lines", []):
            metin = "".join(s["text"] for s in l["spans"])
            if metin.strip() and abs(l["dir"][0]) >= 0.9995 and abs(l["dir"][1]) <= 0.03:
                satirlar.append((*l["bbox"], metin))
    satirlar.sort(key=lambda s: (round(s[1]), s[0]))

    parcalar = []                                     # her biri: {ilk y, ilk x, son satırın konumu, metin}
    for x0, y0, x1, y1, metin in satirlar:
        yukseklik = y1 - y0
        for p in reversed(parcalar):
            ayni_satir = abs(y0 - p["y0"]) < yukseklik * 0.5 and -2 <= x0 - p["x1"] < yukseklik
            alt_satir = (0 <= y0 - p["y1"] + yukseklik * 0.3 < yukseklik * 1.2
                         and min(x1, p["x1"]) - max(x0, p["x0"]) > 0.3 * min(x1 - x0, p["x1"] - p["x0"]))
            if ayni_satir or alt_satir:
                p["metin"] += (" " if ayni_satir else "\n") + metin
                p.update(x0=min(x0, p["x0"]) if ayni_satir else x0, y0=y0, x1=x1, y1=y1)
                break
        else:
            parcalar.append({"ilk": (round(y0), x0), "x0": x0, "y0": y0, "x1": x1, "y1": y1, "metin": metin})
    parcalar.sort(key=lambda p: p["ilk"])             # yukarıdan aşağı, soldan sağa
    return [p["metin"] for p in parcalar]


def yarim_kalmis_mi(metin: str) -> bool:
    return not BITTI_RE.search(metin) and not metin.isupper()


def pdf_paragraflari(yol: str):
    """Her sayfadan (sayfa_no, paragraf_no, metin) üretir. Sayfa, sütun veya resim yüzünden kesilen cümle
    sonraki parçada küçük harfle devam ediyorsa (arada başlık olsa bile) ikisi tek paragraf sayılır."""
    bekleyen = []                                         # son parçalar: sonradan devamı gelebilir
    with pymupdf.open(yol) as belge:
        for sayfa_no, sayfa in enumerate(belge, start=1):
            par_no = 0
            for metin in (m for blok in sayfa_bloklari(sayfa) for m in blok_parcala(blok)):
                if len(metin) < 3 or metin.isdigit():     # sayfa numarası gibi parçalar
                    continue
                if re.match(r"[a-zçğıöşü]", metin):
                    onceki = next((p for p in reversed(bekleyen) if yarim_kalmis_mi(p[2])), None)
                    if onceki:
                        ek = "" if onceki[2].endswith("-") else " "
                        onceki[2] = onceki[2].removesuffix("-") + ek + metin
                        continue
                # Tırnak açık kalmışsa sonraki parça aynı cümledir: "Mehmet ve / Dedesi" adlı metni
                if bekleyen and bekleyen[-1][2].count('"') % 2 and len(bekleyen[-1][2]) < 400:
                    bekleyen[-1][2] += (" / " if metin[0].isupper() else " ") + metin
                    continue
                par_no += 1
                bekleyen.append([sayfa_no, par_no, metin])
            while len(bekleyen) > 12:
                yield tuple(bekleyen.pop(0))
    yield from map(tuple, bekleyen)


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


def izinli_kokleri_oku(yol: Path) -> tuple:
    return tuple(liste_oku(yol)) if yol.exists() else ()


# Sözlüklerde bulunmayan ama doğru olan kelimelerin kökleri: bunlarla başlayan kelime yazım hatası sayılmaz.
IZINLI_KOKLER = izinli_kokleri_oku(KLASOR / "izinli_kelimeler.txt")


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
    def _cozumler(self, kelime: str) -> tuple:
        """Bilinen çözümlemeler: (madde, tür, alt tür, ayrıntılı çözüm)."""
        return tuple((a.item.lemma, str(a.item.primary_pos), str(a.item.secondary_pos), a.format_string())
                     for a in self.morfoloji.analyze(kelime).analysis_results
                     if str(a.item.primary_pos) != "PrimaryPos.Unknown")

    def sozluk_maddeleri(self, kelime: str) -> tuple[str, ...]:
        """Çekimli kelimenin sözlük maddelerini verir: gidiyoruz -> gitmek, kitapları -> kitap."""
        return tuple(dict.fromkeys(tr_kucuk(c[0]) for c in self._cozumler(kelime)))

    def gecerli_mi(self, kelime: str) -> bool:
        return bool(self._cozumler(kelime))

    def ozel_isim_mi(self, kelime: str) -> bool:
        """Kelime sözlükte yalnızca özel isim olarak mı geçiyor? (Ayşe, Ankara gibi)"""
        cozumler = self._cozumler(kelime)
        return bool(cozumler) and all(c[2] == "SecondaryPos.ProperNoun" for c in cozumler)

    def yuklem_olabilir_mi(self, kelime: str) -> bool:
        """Kelime cümleyi bitirecek çekimde mi? gitti, okuyunuz, eserdir, var. Ama oyun, kurarak, edinme,
        özellikleri değil: yalın isim olabilen ya da zaman/kişi eki taşımayan kelime cümleyi bitirmeyebilir."""
        if kelime in ("var", "yok", "değil"):
            return True
        cozumler = self._cozumler(kelime)
        if any(tr_kucuk(c[0]) == kelime for c in cozumler):
            return False
        return any(":Cop" in c[3] or (c[1] == "PrimaryPos.Verb" and "→" not in c[3] and re.search(
            r"[+:](?:Past|Narr|Prog1|Prog2|Aor|Fut|Cond|Neces|Opt)\b|Imp\+\w+:A2pl", c[3])) for c in cozumler)

    def sozluk_disi_serbest_mi(self, kelime: str) -> bool:
        """TDK'de madde olmayan ama doğru sayılan biçimler: soru eki (mı, misin) ve kısaltmalar (km, kg)."""
        return any(c[1] == "PrimaryPos.Question" or c[2] == "SecondaryPos.Abbreviation"
                   for c in self._cozumler(kelime))

    def kesmesiz_ozel_isim(self, kelime: str) -> str | None:
        """Hâl eki kesmeyle ayrılmamış özel ismin doğrusunu verir: ankarada -> Ankara'da.
        Millet ve dil adları kesme almaz (TDK): Türkçede, Türkleri."""
        if not self.ozel_isim_mi(kelime) or kelime in self.sozluk_maddeleri(kelime):
            return None
        for madde, _, _, cozum in self._cozumler(kelime):
            kok = tr_kucuk(madde)
            if ("→" not in cozum and re.search(r":(Dat|Loc|Abl|Acc|Gen)\b", cozum)
                    and kok not in KESMESIZ_ADLAR and not kok.endswith(("çe", "ça", "ce", "ca"))
                    and kelime.startswith(kok)):
                return f"{madde}'{kelime[len(kok):]}"
        return None

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

        # (b) Tek harflik düzenlemeler (silme, ekleme, değiştirme, yer değiştirme).
        #     Çok uzun bilinmeyen kelimelerde aranmaz: her aday çözümlendiği için çok yavaştır.
        if not adaylar and 4 <= len(kelime) <= 16:
            bolumler = [(kelime[:i], kelime[i:]) for i in range(len(kelime) + 1)]
            silme = [s + k[1:] for s, k in bolumler if k]
            yer = [s + k[1] + k[0] + k[2:] for s, k in bolumler if len(k) > 1]
            degis = [s + h + k[1:] for s, k in bolumler if k for h in TR_ALFABE]
            ekle = [s + h + k for s, k in bolumler for h in TR_ALFABE]
            for aday in dict.fromkeys(silme + yer + degis + ekle):
                if aday != kelime and self.gecerli_mi(aday):
                    adaylar.append(aday)
                    if len(adaylar) >= 6:
                        break
        return tuple(adaylar[:12])      # TDK ile elenip en iyi 3'ü gösterilir


# ---------------------------------------------------------------------------
# 5) Kriter 3: Noktalama / tekrar kuralları
# ---------------------------------------------------------------------------
NOKTALAMA_KURALLARI = [
    (re.compile(r"(?<=[A-Za-zÇĞİÖŞÜçğıöşüÂâÎîÛû])\s+(?:[,;:!?]|\.(?!\.))"), "Noktalama işaretinden önce boşluk", "Boşluğu silin"),
    (re.compile(r"(?<=[A-Za-zÇĞİÖŞÜçğıöşü]{2}),[A-Za-zÇĞİÖŞÜçğıöşü]|[;!?][A-Za-zÇĞİÖŞÜçğıöşü]|(?<!\d):[A-Za-zÇĞİÖŞÜçğıöşü]"), "Noktalama işaretinden sonra boşluk yok", "İşaretten sonra boşluk bırakın"),
    (re.compile(r"(?<=[a-zçğıöşü]{2})(?<!vb)(?<!vs)\.(?:[A-ZÇĞİÖŞÜ]|(?!(?:pdf|docx?|txt|html?|py|jpe?g|png|xlsx?|js|json|css|ts|java|cpp|xml|sql)\b)(?![a-zçğıöşü]+\()[a-zçğıöşü]{2})"),
     "Noktadan sonra boşluk yok", "Noktadan sonra boşluk bırakın"),
    (re.compile(r"(?<![.!?])\.\.(?!\.)|(?<!\.)\.{4}(?!\.)(?!\s*\d)|[,;:][,;:.]"), "Tekrarlanan noktalama işareti", "Tek işaret veya üç nokta kullanın"),
    (re.compile(r"!{2,}|\?{2,}"), "Birden fazla ünlem/soru işareti", "Tek işaret kullanın (ders kitabı dili)"),
    (re.compile(r"\(\s|\s\)"), "Parantez içi gereksiz boşluk", "Boşluğu silin"),
    (re.compile(r"[A-Za-zÇĞİÖŞÜçğıöşü]{4,}\((?=[^)]*\s)"), "Parantezden önce boşluk yok", "Parantezden önce boşluk bırakın"),
    (re.compile(r"\)[a-zçğıöşü]{3,}"), "Parantezden sonra boşluk yok", "Parantezden sonra boşluk bırakın"),
    (re.compile(r",\s+(?:ve|veya)\b(?!\s*,)"), "\"ve/veya\" bağlacından önce virgül kullanılmaz", "Virgülü silin"),
    (re.compile(r"^[,;:!?]"), "Paragraf noktalama işaretiyle başlıyor", "İşareti silin"),
    (re.compile(r"\b\d+(?:lar|ler|da|de|ta|te|dan|den|tan|ten|ya|ye|yı|yi|yu|yü|nın|nin|nun|nün|ın|in|un|ün)\b"),
     "Sayıya gelen ek kesme işaretiyle ayrılmalı", "Örnek: 1923'te, 1980'ler"),
    (re.compile(r"(?<=\s)m[iıuü](?:yim|yım|yum|yüm|sin|sın|sun|sün|yiz|yız|yuz|yüz|siniz|sınız|sunuz|sünüz|dir|dır|dur|dür)?\.(?=\s|$)"),
     "Soru ekinden sonra nokta kullanılmış", "Soru işareti (?) kullanın"),
]
# Kod ve formül satırları Türkçe cümle değildir: yazım ve noktalama açısından denetlenmez.
KOD_RE = re.compile(r"[{}]|=>|==|\(\)|^\s*//|\)\s*;\s*$|\bconst\b")
# Bu kelimeler ikileme olamaz: "bu bu", "ve ve" kesin hatadır.
IKILEME_OLMAZ = frozenset("bu şu ve veya ile için gibi ama fakat ancak ki de da en".split())
# Bu sözlerle başlayan kısa alt yazılar cümle sayılmaz (nokta aranmaz)
ALT_YAZI_RE = re.compile(r"^(?:Şekil|Tablo|Resim|Grafik|Harita|Kaynak|Görsel|Fotoğraf|Ünite|Bölüm|Konu)\b", re.I)


# ---------------------------------------------------------------------------
# Büyük / küçük harf kontrolü (TDK Yazım Kılavuzu: "Büyük harflerin kullanıldığı yerler")
# ---------------------------------------------------------------------------
KUCUK_HARF = "a-zçğıöşü"
BUYUK_HARF = "A-ZÇĞİÖŞÜ"
# Noktadan sonra küçük harf gelmesi normal olan kısaltmalar (vb. vs. bkz. gibi)
KISALTMALAR = {"vb", "vs", "vd", "bkz", "örn", "ör", "sf", "s", "no", "dr", "prof", "doç", "yy",
               "mö", "ms", "mah", "cad", "sok", "tel", "yak", "krş", "bk", "çev", "hz", "sn",
               "dk", "çev", "ed", "yay", "bs", "ss", "md", "fak", "müh", "uzm", "yrd", "öğr"}


def tr_buyuk_ilk(s: str) -> str:
    """İlk harfi Türkçe kurallarıyla büyütür: istanbul -> İstanbul, ışık -> Işık."""
    if not s:
        return s
    ilk = {"i": "İ", "ı": "I"}.get(s[0], s[0].upper())
    return ilk + s[1:]


# Hem özel isim hem de sıradan kelime olabilenler: cümle ortasında büyük harfle yazılsalar da hata sayılmaz.
ISIM_OLABILEN = frozenset("""deniz güneş dünya ay doğu batı kuzey güney aydın umut ümit sevgi yıldız gül çiçek ırmak kaya
    demir aslan arslan şahin tan bahar yaz nur can barış savaş onur başak ceren ela pınar özlem derya sibel gökhan
    yavuz bulut toprak çınar ocak şubat mart nisan mayıs haziran temmuz ağustos eylül ekim kasım aralık pazartesi salı
    çarşamba perşembe cuma cumartesi pazar cumhuriyet meclis devlet hanım bey efendi paşa sultan kaptan doktor bakan
    başbakan başkomutan harbiye gazi profesör öğretmen millî milli ulusal genel""".split())
# "Siz anlatınız!" dedim. / "Ne zaman?" diye sordu: bu kelimelerle cümle devam eder.
DEME_KELIMELERI = frozenset("diye dedi dedim dedik dediler sordu sordum sorduk söyledi bağırdı".split())
# Bu adlara gelen ekler kesme işaretiyle ayrılmaz (TDK).
KESMESIZ_ADLAR = frozenset("""türk alman fransız ingiliz arap rus yunan ermeni kürt japon italyan ispanyol
    macar bulgar sırp hırvat moğol tatar acem amerikan""".split())


def ozel_isimleri_oku(yol: Path) -> frozenset:
    return frozenset(liste_oku(yol)) if yol.exists() else frozenset()


def cumle_mi(parca: str, denetci) -> bool:
    """Parça, ilk . ! ? işaretine kadar gerçek bir cümle mi? Kelime listeleri ve sayfa düzeninden kopan
    parçalar elenir: en az 3 kelime olmalı ve son kelimesi yüklem olabilmeli."""
    kelimeler = KELIME_RE.findall(re.split(r"[.!?…]", parca, maxsplit=1)[0])
    return len(kelimeler) >= 3 and denetci.yuklem_olabilir_mi(tr_kucuk(kelimeler[-1]))


def harf_hatalari_bul(sayfa, par_no, metin, ozel_isimler, denetci):
    """Büyük/küçük harf hatalarını bulur. Hatalar YAZIM kriteri altında raporlanır."""
    bulgular, isaretli = [], set()
    tarama = adresleri_ort(metin)

    def ekle(bas, son, kelime, aciklama, oneri):
        if bas in isaretli:
            return
        isaretli.add(bas)
        bulgular.append(Bulgu(sayfa, par_no, "YAZIM", kelime, aciklama, oneri, baglam_al(metin, bas, son)))

    # 1) Paragraf küçük harfle başlıyor. "a) ...", "1. ..." gibi madde işaretleri atlanır.
    #    Kelime listeleri ve yarım parçalar elenir: tam bir cümle olmalı.
    m = re.match(rf"^[\s—–-]*([{KUCUK_HARF}][{HARFLER}]*)(.?)", tarama)   # rakamla başlayan paragraf kontrol edilmez
    if (m and not (len(m.group(1)) == 1 and m.group(2) in (")", "."))
            and cumle_mi(tarama, denetci)):
        ekle(m.start(1), m.end(1), m.group(1), "Büyük/küçük harf hatası: cümle küçük harfle başlamış",
             tr_buyuk_ilk(m.group(1)))

    # 2) Cümle sonu işaretinden (. ! ?) sonra küçük harfle başlayan kelime
    for m in re.finditer(rf"(\S*)([.!?])([\"”’')\]]*)\s+[\"“‘'(\[]?([{KUCUK_HARF}][{HARFLER}]*)", tarama):
        onceki, isaret, kapanis, kelime = m.group(1), m.group(2), m.group(3), m.group(4)
        if kapanis or len(kelime) == 1 or kelime in DEME_KELIMELERI or "=" in onceki:   # "Geldin mi?" diye sordu.  /  b) şıkkı  /  3=? işlemi
            continue
        if not cumle_mi(tarama[m.start(4):], denetci):
            continue                                            # sonrası cümle değil, kelime listesi
        if isaret == "." and (onceki.endswith(".") or onceki.endswith("…")):
            continue                                            # üç nokta: cümle devam edebilir
        temiz = re.sub(r"\W", "", onceki)
        if isaret == "." and (temiz.isdigit() or len(temiz) <= 1 or tr_kucuk(temiz) in KISALTMALAR):
            continue                                            # "3. madde", "a. şık", "vb. kelime"
        ekle(m.start(4), m.end(4), kelime, "Büyük/küçük harf hatası: cümle küçük harfle başlamış",
             tr_buyuk_ilk(kelime))

    for m in KELIME_RE.finditer(tarama):
        if kelime_parcasi(tarama, m):
            continue
        govde = re.split(r"['’]", m.group())[0]
        # 3) Özel isim küçük harfle yazılmış (ankara, türkiye, ingilizce ...)
        if govde == tr_kucuk(govde) and govde in ozel_isimler:
            ekle(m.start(), m.start() + len(govde), govde,
                 "Büyük/küçük harf hatası: özel isim büyük harfle başlamalı", tr_buyuk_ilk(govde))
            continue
        # 4) Kelimenin ortasında yanlış büyük harf (oKul, kitapLar, OkUl). Teknik terimleri
        #    (getElementById gibi) yanlış işaretlememek için sadece sözlükte bulunan kelimelere bakılır.
        kucuk = tr_kucuk(govde)
        # 3b) Cümle ortasında tek başına, gereksiz büyük harfle yazılmış sıradan kelime (Okula).
        #     Başlıklar ve çok kelimeli özel adlar elenir: yanındaki kelimeler de büyük harfliyse bakılmaz.
        if (govde == m.group() and len(govde) >= 3 and not govde.isupper() and govde[0].isupper()
                and not cumle_basi_mi(tarama, m.start()) and kucuk not in ISIM_OLABILEN
                and denetci.gecerli_mi(kucuk)
                and not any(c[2] == "SecondaryPos.ProperNoun" for c in denetci._cozumler(kucuk))):
            once = re.search(rf"([{HARFLER}]+)[ ]+$", tarama[:m.start()])
            sonra = re.match(rf"[ ]+([{HARFLER}]+)", tarama[m.end():])
            if (once and sonra and once.group(1)[0].islower() and sonra.group(1)[0].islower()
                    and sonra.group(1) not in ("ve", "veya", "ile")):
                ekle(m.start(), m.end(), govde, "Büyük/küçük harf hatası: cümle ortasında gereksiz büyük harf",
                     kucuk)
                continue
        if len(govde) >= 3 and denetci.gecerli_mi(kucuk) and not denetci.ozel_isim_mi(kucuk):   # JavaScript, MySQL
            if re.match(rf"^[{KUCUK_HARF}]+[{BUYUK_HARF}]", govde):
                ekle(m.start(), m.start() + len(govde), govde,
                     "Büyük/küçük harf hatası: kelimenin ortasında büyük harf var", kucuk)
            elif re.match(rf"^[{BUYUK_HARF}][{KUCUK_HARF}]+[{BUYUK_HARF}]", govde):
                ekle(m.start(), m.start() + len(govde), govde,
                     "Büyük/küçük harf hatası: kelimenin ortasında büyük harf var", tr_buyuk_ilk(kucuk))
    return bulgular


def ikileme_olabilir(kucuk, denetci) -> bool:
    """bol bol, koşa koşa, meraklı meraklı doğrudur; "okula okula" gibi hâl ekli isim tekrarı değildir."""
    if kucuk in IKILEME_OLMAZ:
        return False
    return not all(re.search(r":(?:Dat|Loc|Abl|Acc|Gen)\b", c[3]) for c in denetci._cozumler(kucuk))


def noktalama_bul(sayfa, par_no, metin, denetci):
    bulgular = []
    # Boş parantez "(  )" noktalama alıştırmasıdır, hata değildir.
    tarama = re.sub(r"\(\s*\)", lambda m: "§" * len(m.group()), adresleri_ort(metin))

    def ekle(kelime, aciklama, oneri, bas, son):
        bulgular.append(Bulgu(sayfa, par_no, "NOKTALAMA", kelime, aciklama, oneri, baglam_al(metin, bas, son)))

    for kural, aciklama, oneri in NOKTALAMA_KURALLARI:
        for m in kural.finditer(tarama):
            ekle(m.group().strip() or "(boşluk)", aciklama, oneri, m.start(), m.end())

    # Açılıp kapanmayan parantez ve tırnak ("a)" gibi madde işaretleri yüzünden sadece açık kalan aranır)
    if tarama.count("(") + tarama.count("[") > tarama.count(")") + tarama.count("]"):   # (4,5] aralığı hata değil
        bas = tarama.rfind("(")
        ekle("(", "Açılan parantez kapatılmamış", "Parantezi kapatın", bas, bas + 1)
    if sum(tarama.count(t) for t in '"“”') % 2:
        bas = max(tarama.rfind('"'), tarama.rfind("“"), tarama.rfind("”"))
        ekle(metin[bas], "Tırnak işareti açılmış ama kapatılmamış (ya da tersi)", "Tırnağı tamamlayın", bas, bas + 1)

    # Cümle sonunda nokta yok. Yalnızca son cümle yüklemle bitiyorsa bildirilir: başlık, alt yazı, imza ("Mehmet Âkif
    # Ersoy") ve sayfa düzeni yüzünden kesilmiş cümleler ("sınır çizgisi") hata sayılmaz.
    son_cumle = KELIME_RE.findall(re.split(r"[.!?…]\s", tarama)[-1])
    buyuk = sum(1 for k in son_cumle if k[0].isupper())
    if (len(son_cumle) >= 6 and buyuk * 2 < len(son_cumle) and metin[-1].isalnum() and not ALT_YAZI_RE.match(metin)
            and denetci.yuklem_olabilir_mi(tr_kucuk(son_cumle[-1]))):
        ekle(son_cumle[-1], "Cümle sonunda noktalama işareti yok", "Cümlenin sonuna nokta koyun",
             len(metin) - len(son_cumle[-1]), len(metin))

    # Arka arkaya tekrar eden kelime: "bu bu", "ve ve"
    kelimeler = list(KELIME_RE.finditer(tarama))
    for onceki, simdiki in zip(kelimeler, kelimeler[1:]):
        if (tr_kucuk(onceki.group()) == tr_kucuk(simdiki.group()) and len(onceki.group()) > 1
                and not ikileme_olabilir(tr_kucuk(onceki.group()), denetci)):
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
KESMELI_KELIMELER = frozenset({"san'at", "kur'an", "şe'ir", "te'lif", "mes'ul", "cür'et", "ma'lum"})
BUYUK_DENETIM_UZUNLUK = 6   # tamamı büyük harfli kelimelerde bundan kısası kısaltma sayılır (NATO, TBMM)


def kelime_govdesi(ham: str) -> str:
    """"PDF’den" gibi kesme işaretli yapılarda sadece kelime gövdesini al."""
    return re.split(r"['’]", ham)[0]


def tdk_adaylari(kucuk: str, denetci) -> tuple[str, ...]:
    """TDK'de aranacak madde başları. Çekimli kelime TDK'de bulunmaz, o yüzden önce
    Zemberek ile sözlük maddesine çeviririz: gidiyoruz -> gitmek, kitapları -> kitap."""
    return denetci.sozluk_maddeleri(kucuk) or (kucuk,)


def tdk_aday_kelimeler(paragraflar, denetci) -> set:
    """Kitaptaki tüm kelimelerin TDK'de aranacak madde başlarını (benzersiz) toplar."""
    gerekli = set()
    for _, _, metin in paragraflar:
        for m in KELIME_RE.finditer(adresleri_ort(metin)):
            govde = kelime_govdesi(m.group())
            if len(govde) >= 2 and (not govde.isupper() or len(govde) >= BUYUK_DENETIM_UZUNLUK):
                gerekli.update(tdk_adaylari(tr_kucuk(govde), denetci))
    return gerekli


def cumle_basi_mi(metin: str, konum: int) -> bool:
    """Kelime cümlenin ilk kelimesi mi? (paragraf başı, . ! ? : sonrası, madde işareti ya da tırnak açılışı)"""
    return re.search(r"(^[\W\d]*|^[a-zA-Z][.)]\s+|[.!?:…/][\"”’')\]]*\s+[\"“‘'(\[]*)$", metin[:konum]) is not None


def kelime_parcasi(metin: str, m) -> bool:
    """Tek başına kelime olmayan parçalar: CO2, 1923te, 0'dan, P(A)'yı, "Rafadan Tayfa"nın, -mış, Korku-suz-luk."""
    bas, son = m.start(), m.end()
    if bas > 0 and metin[bas - 1] == "-":
        return True
    if bas >= 2 and metin[bas - 1] in "'’\"”" and (metin[bas - 2].isalnum() or metin[bas - 2] in ")]%"):
        return True
    return (bas > 0 and metin[bas - 1].isdigit()) or (son < len(metin) and metin[son].isdigit())


def ad_soyad_icinde_mi(metin: str, m, denetci) -> bool:
    """Dr. Gülbike YILDIRIM, Vedat Ersin CEVİZ-Zekican YARDIMCI: büyük harfli komşusu olan bilinmeyen kelime addır.
    Cümlenin ilk kelimesi komşu sayılmaz ("Sonra Öğrencilr" ad değildir); başlıktaki büyük harfli kelimeler
    birbirine komşu sayılmaz ("KONU ANLATIMII" ad değildir)."""
    kendi_buyuk = kelime_govdesi(m.group()).isupper()
    if re.match(rf",\s+[{BUYUK_HARF}]\.", metin[m.end():]):   # kaynakça: ZORLUTUNA, H. N.
        return True
    sonra = re.match(rf"[ -]+([{HARFLER}]+)", metin[m.end():])
    if sonra and sonra.group(1)[0].isupper() and not (kendi_buyuk and sonra.group(1).isupper()):
        return True
    once = re.search(rf"([{HARFLER}]+)(\.?)[ -]+$", metin[:m.start()])
    if not once or not once.group(1)[0].isupper() or (kendi_buyuk and once.group(1).isupper()):
        return False
    onceki = tr_kucuk(once.group(1))
    if once.group(2):
        return onceki in KISALTMALAR                      # Dr. Gülbike, Prof. Ayşe
    return not cumle_basi_mi(metin, once.start(1)) or denetci.ozel_isim_mi(onceki) or not denetci.gecerli_mi(onceki)


def ozel_isimleri_ayir(paragraflar, denetci) -> Counter:
    """Metindeki özel isimleri kelime kelime tarayarak ayırır; anlamına bakılmaz, yalnızca yazılış ve sözlük:
      * Newton'un     -> büyük harf + kesme işareti
      * Ankara, Ayşe  -> Zemberek'te yalnızca özel isim olarak kayıtlı
      * Pisagor       -> cümle ortasında büyük harfli, sözlükte yok ve metinde en az iki kez geçiyor
                         (ya da yazım hatasına benzemiyor)
    Döndürür: {özel isim: geçme sayısı}."""
    sayac, supheli = Counter(), Counter()
    for _, _, metin in paragraflar:
        tarama = adresleri_ort(metin)
        for m in KELIME_RE.finditer(tarama):
            govde = kelime_govdesi(m.group())
            if (len(govde) < 2 or govde.isupper() or not govde[0].isupper() or kelime_parcasi(tarama, m)
                    or re.search(rf"[{BUYUK_HARF}]", govde[1:])):
                continue
            kucuk = tr_kucuk(govde)
            if kucuk.startswith(IZINLI_KOKLER) or UZATMA_RE.search(kucuk):
                continue
            if denetci.ozel_isim_mi(kucuk):
                # Türkiye "Türki+ye" diye de çözümlenir: en uzun madde başı alınır
                sayac[max((c[0] for c in denetci._cozumler(kucuk)), key=len)] += 1
            elif govde != m.group():
                # Sözlük'ü gibi sıradan kelimeler listelenmez; Samsun'a gibi özel ad okunuşu olanlar listelenir
                if not denetci.gecerli_mi(kucuk) or any(c[2] == "SecondaryPos.ProperNoun" for c in denetci._cozumler(kucuk)):
                    sayac[govde] += 1
            elif not denetci.gecerli_mi(kucuk) and ad_soyad_icinde_mi(tarama, m, denetci):
                sayac[govde] += 1
            elif not denetci.gecerli_mi(kucuk) and not cumle_basi_mi(tarama, m.start()):
                supheli[govde] += 1
    for ad, adet in supheli.items():
        if adet >= 2 or ad in sayac or not denetci.oneriler(tr_kucuk(ad)):
            sayac[ad] += adet
    return sayac


def tdk_on_yukleme(paragraflar, denetci, tdk) -> set:
    """Kitaptaki tüm benzersiz kelimeleri bulup TDK'den toplu (paralel) çeker."""
    gerekli = tdk_aday_kelimeler(paragraflar, denetci)
    tdk.on_yukle(sorted(gerekli))
    return gerekli


# TDK'nin cevapları bozuksa (site değişmiş, yanlış yanıt vb.) bütün kelimeler "hatalı" çıkmasın diye
# her çalıştırmada bu çok yaygın kelimelerin TDK'de bulunup bulunmadığına bakılır.
KANARYA_KELIMELER = ("okul", "kitap", "ders", "insan")


def tdk_guvenilir_mi(tdk, adaylar) -> bool:
    """TDK cevapları beklenen biçimde mi? Değilse TDK'ye dayalı katı denetim yapılmaz."""
    cevaplar = [tdk.onbellek.get(f"gts:{k}") for k in adaylar]
    cevaplar = [c for c in cevaplar if c]
    if len(cevaplar) >= 50 and sum(1 for c in cevaplar if not c["var"]) / len(cevaplar) > 0.35:
        return False                                     # kelimelerin çoğu "yok" çıktı: şüpheli
    kanarya = [c for c in map(tdk.sozluk, KANARYA_KELIMELER) if c is not None]   # TDK kapalıysa önbellekte olanlar
    return not kanarya or sum(1 for c in kanarya if c["var"]) >= min(3, len(kanarya))


UZATMA_RE = re.compile(rf"([{HARFLER}])\1\1")   # bilerek uzatılmış söyleyiş


def yazim_onerileri(kucuk, denetci, tdk) -> list[str]:
    """Hatalı kelime için önce TDK Yazım Kılavuzu'nu, sonra TDK'de doğrulanan Zemberek önerilerini verir."""
    oneriler, canli = [], None
    if tdk:
        oneriler += tdk.yazim_onerisi(kucuk)                 # TDK Yazım Kılavuzu
        canli = getattr(tdk, "sozluk_canli", tdk.sozluk)
    adaylar_oneri = [c for c in denetci.oneriler(kucuk) if not denetci.ozel_isim_mi(c)]
    if canli:                                                # TDK'de gerçekten var olanları seç
        cevaplar = [canli(tdk_adaylari(c, denetci)[0]) for c in adaylar_oneri]
        if all(c is not None for c in cevaplar):             # TDK cevap verdiyse sadece doğrulananlar
            adaylar_oneri = [c for c, r in zip(adaylar_oneri, cevaplar) if r["var"]]
    return list(dict.fromkeys(oneriler + adaylar_oneri[:3]))


def paragraf_denetle(sayfa, par_no, metin, argo, yanlislar, denetci, tdk=None, ozel_isimler=frozenset(),
                     belge_ozel=frozenset()):
    """belge_ozel: ozel_isimleri_ayir() ile metnin tamamından bulunan özel isimler (yazım hatası sayılmaz)."""
    bulgular = []
    if KOD_RE.search(metin):
        return bulgular
    tarama = adresleri_ort(metin)

    # Ayrı yazılmaması gereken ifadeler: "bir kaç" -> "birkaç" (yaygin_yanlislar.txt içinde boşluklu satırlar)
    kucuk_metin = tr_kucuk(tarama)
    for yanlis, dogru in yanlislar.items():
        if " " in yanlis and yanlis in kucuk_metin:
            for m in re.finditer(rf"(?<![{HARFLER}]){re.escape(yanlis)}(?![{HARFLER}])", kucuk_metin):
                ham = metin[m.start():m.end()]
                bulgular.append(Bulgu(sayfa, par_no, "YAZIM", ham, "Sık yapılan yazım yanlışı",
                                      tr_buyuk_ilk(dogru) if ham[0].isupper() else dogru,
                                      baglam_al(metin, m.start(), m.end())))

    for m in KELIME_RE.finditer(tarama):
        if kelime_parcasi(tarama, m):
            continue
        govde = kelime_govdesi(m.group())
        kucuk = tr_kucuk(govde)
        ctx = baglam_al(metin, m.start(), m.end())
        adaylar = tdk_adaylari(kucuk, denetci)
        # Kelimenin kendisi zaten bir sözlük maddesiyse (ama, yazım, ...) yalnızca kendisine bakılır.
        # Yoksa "ama" kelimesi "am + a" diye de çözümlendiği için yanlışlıkla argo sayılırdı.
        bakilacak = (kucuk,) if kucuk in adaylar else adaylar

        # --- Kriter 1: Argo ---
        # (a) TDK Güncel Türkçe Sözlük'te "argo" / "kaba" etiketli mi?
        if tdk:
            tdk_argo = next((tdk.sozluk(a) for a in bakilacak
                             if (tdk.sozluk(a) or {}).get("argo")), None)
            # "sayı atar" atmak, "bir iple" ip kelimesidir. Anlama bakılmadığı için kelimenin argo olmayan
            # bir okunuşu varsa argo sayılmaz; yalnızca bütün okunuşları argoysa bildirilir.
            okunuslar = [b for b in map(tdk.sozluk, adaylar) if b and b["var"]]
            if tdk_argo and not all(b["argo"] for b in okunuslar):
                tdk_argo = None
            if tdk_argo:
                bulgular.append(Bulgu(sayfa, par_no, "ARGO", govde,
                                      "TDK Güncel Türkçe Sözlük'te argo/kaba olarak işaretli: "
                                      + tdk_argo["argo_anlam"],
                                      "Ders kitabına uygun resmî bir ifade kullanın", ctx))
                continue
        # (b) Kendi listemiz (TDK'de olmayan güncel argo ve gündelik dil için)
        if kucuk in argo or any(a in argo for a in bakilacak):
            bulgular.append(Bulgu(sayfa, par_no, "ARGO", govde,
                                  "Argo / uygunsuz ya da gündelik konuşma dili (argo_listesi.txt)",
                                  "Ders kitabına uygun resmî bir ifade kullanın", ctx))
            continue

        # --- Kriter 2: Yazım ---
        # (a) Sık yapılan yazım yanlışları. Çekimli hâlleri de yakalar: yanlızca -> yalnızca, herşeyi -> her şeyi
        dogru = yanlislar.get(kucuk)
        if dogru is None:
            for a in adaylar:
                if a in yanlislar and kucuk.startswith(a):
                    dogru = yanlislar[a] + kucuk[len(a):]
                    break
        if dogru is not None:
            if govde.isupper():
                dogru = dogru.replace("i", "İ").replace("ı", "I").upper()
            elif govde[:1].isupper():
                dogru = tr_buyuk_ilk(dogru)
            bulgular.append(Bulgu(sayfa, par_no, "YAZIM", govde, "Sık yapılan yazım yanlışı", dogru, ctx))
            continue

        if len(govde) < 2:
            continue
        tamami_buyuk = govde.isupper()
        if tamami_buyuk and len(govde) < BUYUK_DENETIM_UZUNLUK:      # kısaltma: PDF, TDK, NATO
            continue
        if kucuk.startswith(IZINLI_KOKLER) or UZATMA_RE.search(kucuk):
            continue                                                 # izinli_kelimeler.txt / İnanılmaaaaaz, çooook
        kesmeli = govde != m.group()
        kesmeli_tam = tr_kucuk(m.group())
        cumle_basi = cumle_basi_mi(tarama, m.start())
        buyuk_baslar = govde[0].isupper() and not tamami_buyuk

        # --- Özel isimler: anlama bakılmaz, kelimenin yazılışı ve sözlük kaydı incelenir ---
        if tamami_buyuk and (kesmeli or denetci.gecerli_mi(kucuk)):
            continue                                                 # TÜRKİYE'DE, BÖLÜM: doğru
        if buyuk_baslar and kesmeli:
            # Ankara'de: özel isim doğru ama kesmeden sonraki ek ünlü uyumuna aykırı
            if denetci.ozel_isim_mi(kucuk) and not denetci.gecerli_mi(kesmeli_tam):
                bulgular.append(Bulgu(sayfa, par_no, "YAZIM", m.group(),
                                      "Özel isme gelen ek yanlış yazılmış", "Eki ünlü uyumuna göre düzeltin", ctx))
            continue                                                 # Newton'un: özel isim
        if buyuk_baslar and denetci.ozel_isim_mi(kucuk):
            dogrusu = denetci.kesmesiz_ozel_isim(kucuk)
            # Fevziye Lisesi, Halide Nusret: sonraki kelime de büyük harfliyse çok kelimeli addır, ek aranmaz.
            if dogrusu and not re.match(rf"[ ]+[{BUYUK_HARF}]", tarama[m.end():]):
                bulgular.append(Bulgu(sayfa, par_no, "YAZIM", govde,
                                      "Özel isme gelen ek kesme işaretiyle ayrılmalı", dogrusu, ctx))
            continue                                                 # Ankara, Ayşe: özel isim
        if buyuk_baslar and govde in belge_ozel:
            continue                                                 # metinde özel isim olarak tespit edildi
        if (buyuk_baslar or tamami_buyuk) and not denetci.gecerli_mi(kucuk) and ad_soyad_icinde_mi(tarama, m, denetci):
            continue                                                 # Dr. Gülbike YILDIRIM

        # (b) Sözlük denetimi: TDK asıl kaynaktır. Zemberek'in sözlüğü çok geniş olduğu için
        #     yanlış yazılmış bazı kelimeleri (yanlız, herşey gibi) "geçerli" sayabilir; bu yüzden
        #     TDK ulaşılabiliyorsa onun "bulunamadı" cevabına güveniriz.
        zemberek_biliyor = denetci.gecerli_mi(kucuk)
        tdk_bilgileri = [tdk.sozluk(a) for a in adaylar] if tdk else []
        tdk_ulasilamadi = (not tdk) or any(b is None for b in tdk_bilgileri)
        tdk_biliyor = any(b and b["var"] for b in tdk_bilgileri)

        # okul'da: özel isim olmayan kelimeye gelen ek kesmeyle ayrılmaz
        if (kesmeli and not buyuk_baslar and (zemberek_biliyor or tdk_biliyor)
                and not denetci.ozel_isim_mi(kucuk) and not denetci.sozluk_disi_serbest_mi(kucuk)
                and kesmeli_tam not in KESMELI_KELIMELER):
            bulgular.append(Bulgu(sayfa, par_no, "YAZIM", m.group(),
                                  "Özel isim olmayan kelimeye gelen ek kesme işaretiyle ayrılmaz",
                                  m.group().replace("'", "").replace("’", ""), ctx))
            continue

        if kesmeli and not buyuk_baslar and not (zemberek_biliyor or tdk_biliyor):
            continue                                                 # framework'tür: kesmeyle yazılmış yabancı terim
        if not buyuk_baslar and not tamami_buyuk and not zemberek_biliyor and tr_buyuk_ilk(kucuk) in belge_ozel:
            continue                                                 # cache: metinde Cache olarak da geçiyor

        # ahmet, ankarada: özel isim küçük harfle yazılmış (kitablarını gibi yazım hatası da olabilir)
        listede = kucuk not in ozel_isimler and any(a in ozel_isimler for a in adaylar)
        if (not tamami_buyuk and not buyuk_baslar and denetci.ozel_isim_mi(kucuk)
                and (not tdk_biliyor or listede)):
            oneriler = [denetci.kesmesiz_ozel_isim(kucuk) or tr_buyuk_ilk(kucuk)] + yazim_onerileri(
                kucuk, denetci, None if tdk_ulasilamadi else tdk)
            bulgular.append(Bulgu(sayfa, par_no, "YAZIM", govde,
                                  "Özel isim küçük harfle yazılmış ya da kelimede yazım hatası var",
                                  ", ".join(dict.fromkeys(oneriler)), ctx))
            continue
        if denetci.sozluk_disi_serbest_mi(kucuk):
            continue                                                 # mı, misin, km, kg

        if tdk_ulasilamadi:
            hatali = not zemberek_biliyor
            aciklama = "Sözlükte bulunamadı (TDK kullanılmadı) – olası yazım hatası"
        elif tdk_biliyor:
            hatali, aciklama = False, ""
        else:
            # Zemberek biliyorsa hata sayılmaz: TDK çekimli kelimeleri ve bazı türemişleri (idi, gruplayınız) madde
            # olarak içermez. Sözlükte geçerli sayılan yanlışlar (yanlız, herşey) yaygin_yanlislar.txt ile yakalanır.
            hatali, aciklama = not zemberek_biliyor, "Sözlükte bulunamadı – olası yazım hatası"

        if hatali:
            oneriler = yazim_onerileri(kucuk, denetci, None if tdk_ulasilamadi else tdk)
            # Cümle ortasında büyük harfli ya da tamamı büyük harfli bilinmeyen kelime özel isim/kısaltma olabilir:
            # yalnızca bilinen bir kelimeye çok benziyorsa (Öğrencilr -> öğrenciler) bildirilir.
            if tamami_buyuk or (buyuk_baslar and not cumle_basi):
                if not oneriler or tarama[m.start() - 1:m.start()] in ('"', "“"):   # "Mankala" adıyla anılan oyun
                    continue
                aciklama = "Olası yazım hatası (özel isim değilse)"
            elif buyuk_baslar:
                aciklama = "Sözlükte bulunamadı – yazım hatası ya da özel isim"
            if tamami_buyuk:
                oneriler = [o.replace("i", "İ").replace("ı", "I").upper() for o in oneriler]
            elif buyuk_baslar:
                oneriler = [tr_buyuk_ilk(o) for o in oneriler]
            bulgular.append(Bulgu(sayfa, par_no, "YAZIM", govde, aciklama, ", ".join(oneriler) or "Öneri bulunamadı", ctx))

    # --- Kriter 2 (devam): Büyük / küçük harf hataları ---
    gorulen = {(b.kelime, b.baglam) for b in bulgular}
    bulgular.extend(b for b in harf_hatalari_bul(sayfa, par_no, metin, ozel_isimler, denetci)
                    if (b.kelime, b.baglam) not in gorulen)

    # --- Kriter 3: Noktalama / tekrar (TDK Yazım Kılavuzu kurallarına göre) ---
    bulgular.extend(noktalama_bul(sayfa, par_no, metin, denetci))
    return bulgular


# ---------------------------------------------------------------------------
# 7) Raporlama
# ---------------------------------------------------------------------------
def csv_yaz(bulgular, yol):
    with open(yol, "w", newline="", encoding="utf-8-sig") as f:  # utf-8-sig: Excel Türkçe açar
        yazici = csv.DictWriter(f, fieldnames=list(Bulgu.__dataclass_fields__))
        yazici.writeheader()
        yazici.writerows(asdict(b) for b in bulgular)


def html_yaz(bulgular, yol, pdf_adi, toplam_par, ozel_adlar=None):
    renk = {"ARGO": "#fde2e2", "YAZIM": "#fff3cd", "NOKTALAMA": "#e2ecfd"}
    sayac = {}
    for b in bulgular:
        sayac[b.kriter] = sayac.get(b.kriter, 0) + 1
    satirlar = "".join(
        f"<tr style='background:{renk[b.kriter]}'><td>{b.sayfa}</td><td>{b.paragraf}</td>"
        f"<td>{b.kriter}</td><td><b>{html.escape(b.kelime)}</b></td>"
        f"<td>{html.escape(b.aciklama)}</td><td>{html.escape(b.oneri)}</td>"
        f"<td>{b.adet}</td><td>{html.escape(b.sayfalar)}</td>"
        f"<td>{html.escape(b.baglam)}</td></tr>"
        for b in bulgular
    )
    ozet = " | ".join(f"{k}: {v}" for k, v in sorted(sayac.items())) or "Hata bulunamadı"
    ozel_satir = ""
    if ozel_adlar:
        liste = ", ".join(f"{html.escape(ad)} ({adet})" for ad, adet in ozel_adlar.most_common())
        ozel_satir = f"<p><b>Ayrılan özel isimler (yazım hatası sayılmadı):</b> {liste}</p>"
    Path(yol).write_text(f"""<!DOCTYPE html><html lang="tr"><head><meta charset="utf-8">
<title>Denetim Raporu</title>
<style>body{{font-family:Arial,sans-serif;margin:24px}}table{{border-collapse:collapse;width:100%}}
td,th{{border:1px solid #bbb;padding:6px;font-size:14px;vertical-align:top}}th{{background:#dc0d15;color:#fff}}</style>
</head><body><h2>Ders Kitabı Denetim Raporu</h2>
<p>Dosya: <b>{html.escape(pdf_adi)}</b> — {toplam_par} paragraf tarandı — {len(bulgular)} bulgu ({ozet})</p>{ozel_satir}
<table><tr><th>Sayfa</th><th>Paragraf</th><th>Kriter</th><th>Kelime</th><th>Açıklama</th><th>Öneri</th><th>Tekrar</th><th>Geçtiği sayfalar</th><th>Bağlam</th></tr>
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
    ozel = ozel_isimleri_oku(KLASOR / "ozel_isimler.txt")
    print("Zemberek yükleniyor…")
    denetci = YazimDenetcisi()

    paragraflar = list(pdf_paragraflari(args.pdf))
    toplam = len(paragraflar)
    if toplam == 0:
        sys.exit("PDF'ten metin çıkarılamadı. Taranmış (resim) bir PDF olabilir; OCR gerekir.")

    tdk = None
    if not args.cevrimdisi:
        tdk = TDK(KLASOR / "tdk_onbellek.json")
        adaylar = tdk_on_yukleme(paragraflar, denetci, tdk)
        if not tdk_guvenilir_mi(tdk, adaylar):
            print("UYARI: TDK'den beklenmeyen cevaplar geldi; TDK bu çalıştırmada kullanılmayacak.")
            tdk = None
        elif tdk.hata_sayisi:
            print(f"UYARI: TDK'ye {tdk.hata_sayisi} istek ulaşamadı (internet/engel?). Önbellekte cevabı olan "
                  "kelimelerde TDK, diğerlerinde Zemberek ve yerel listeler kullanılıyor.")

    ozel_adlar = ozel_isimleri_ayir(paragraflar, denetci)
    belge_ozel = frozenset(ozel_adlar)
    bulgular = []
    for sayfa, par_no, metin in paragraflar:
        bulgular.extend(paragraf_denetle(sayfa, par_no, metin, argo, yanlislar, denetci, tdk, ozel, belge_ozel))
    bulgular = bulgulari_birlestir(bulgular)
    if tdk:
        tdk.kaydet()

    csv_yaz(bulgular, f"{args.cikti}.csv")
    html_yaz(bulgular, f"{args.cikti}.html", Path(args.pdf).name, toplam, ozel_adlar)

    print(f"\n{toplam} paragraf tarandı, {len(bulgular)} bulgu var.")
    print("Ayrılan özel isimler: " + (", ".join(ad for ad, _ in ozel_adlar.most_common()) or "yok") + "\n")
    for b in bulgular:
        print(f"[Sayfa {b.sayfa}, Paragraf {b.paragraf}] {b.kriter:<9} '{b.kelime}' → {b.oneri}")
        print(f"      {b.aciklama}  |  {b.baglam}")
    print(f"\nRaporlar: {args.cikti}.csv  ve  {args.cikti}.html")


if __name__ == "__main__":
    main()