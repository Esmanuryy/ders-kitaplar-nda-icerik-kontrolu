"""
PDF'ten ve yapıştırılan metinden paragraf çıkarma.

PDF'teki metin ekranda görünenle her zaman aynı değildir. Bu modül şunları düzeltir:
  * bozuk yazı tiplerinden gelen harfler (yÕldÕz -> yıldız, teĢkil -> teşkil)
  * yan yana sütunların karışması ("oldu-" + "kişiye" = "oldukişiye")
  * satır sonu tirelemesi ("kita-" + "plar")
  * sayfa, sütun veya resim yüzünden bölünen cümleler
  * kenardaki dikey ve eğik süs yazıları
"""

import re
import unicodedata

import pymupdf

# Eski Türkçe yazı tiplerinde PDF'ten bozuk çıkan harfler. Bu harfler Türkçede kullanılmaz, o yüzden yalnızca
# görüldüğü blokta düzeltilir.
BOZUK_YAZI_TIPLERI = [
    (re.compile(r"[Õúù÷ø]"), str.maketrans({"Õ": "ı", "ú": "ş", "ù": "Ş", "÷": "ğ", "ø": "İ"})),
    (re.compile(r"[ýþðÝÞÐ]"), str.maketrans({"ý": "ı", "þ": "ş", "ð": "ğ", "Ý": "İ", "Þ": "Ş", "Ð": "Ğ"})),
    (re.compile(r"[ĢĠġ]"), str.maketrans({"Ģ": "ş", "Ġ": "İ", "ġ": "Ş"})),
]
HARF_DUZELT = str.maketrans({" ": " ", " ": " ", " ": " ", " ": " ",
                             "ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl",
                             "‐": "-", "‟": "'", "​": None, "‌": None, "﻿": None})
BITTI_RE = re.compile(r"[.!?:;…][\"”’')\]]*$")
MADDE_ISARETI = "•›>▪◦‣●○■□▶"
MADDE_RE = re.compile(rf"^(?:[{MADDE_ISARETI}]|[–-]\s|\d+[.)]\s|[a-zA-Z]\)\s)")
EN_FAZLA_BIRLESIK = 400        # yarım kalan tırnak/parantez için birleştirilecek en uzun paragraf
# Satır sonunda tireyle bölünmüş kelimenin bölündüğü yer. Burada birleştirilmez: "kita-plarını" birleşince
# doğru bir kelime olur, ama yan yana sütunlardan gelen "konul-kurallar" birleşince anlamsız bir kelime olur.
# Hangisi olduğuna Denetleyici sözlüğe bakarak karar verir (bolunmus_kelimeleri_birlestir).
BOLUNME = "\ue000"


# Etkinlik bölümünün başladığını gösteren satırlar. Etkinliklerde öğrenciden düzeltmesi istenen yanlışlar bilerek
# yazılır ("Aşağıdaki kelimelerin yanlışlarını bulunuz"); bu yüzden etkinlik bölümleri denetlenmeden atlanabilir.
ETKINLIK_RE = re.compile(
    r"^(?:\d+\.\s*)?ETK[İI]NL[İI]K\b"                          # 4. ETKİNLİK
    r"|^(?:\d+\.\s*)?Etkinlik\s*$"                              # Etkinlik (tek başına başlık)
    r"|^[a-zçğıöşü]\.[a-zçğıöşü]\.(?:\s|$)"                       # a.a. / b.b. etkinlik maddeleri
    r"|^(?:Sıra Sizde|Ölçme ve Değerlendirme|Ölçme Değerlendirme|Değerlendirme Soruları|Haydi Uygulayalım|Uygulayalım)"
    r"|^(?:ÖZ DEĞERLENDİRME ÖLÇEĞİ|Öz Değerlendirme Ölçeği|Akran Değerlendirme Formu|[A-ZÇĞİÖŞÜ /]+ ÖZ DEĞERLENDİRME ÖLÇEĞİ)")


def harfleri_duzelt(metin: str) -> str:
    metin = unicodedata.normalize("NFC", metin).translate(HARF_DUZELT)
    for kural, tablo in BOZUK_YAZI_TIPLERI:
        if kural.search(metin):
            metin = metin.translate(tablo)
    return metin


def blok_temizle(metin: str) -> str:
    """Satır sonu tirelemesini ve satır sonlarındaki boşlukları temizler."""
    metin = re.sub(r"­[ \t]*\n\s*", "", metin).replace("­", "")
    metin = re.sub(r"(?<=\w)-[ \t]*\n\s*(?:\d{1,3}\s+)?(?=[a-zçğıöşü])", BOLUNME, metin)   # kita-\nplar, pen- 2 cereden
    metin = re.sub(r"(?<=\w)(['’])[ \t]*\n\s*(?=[a-zçğıöşü])", r"\1", metin)                 # İzmir'\nde -> İzmir'de
    metin = re.sub(r"(?<=[A-ZÇĞİÖŞÜ])-[ \t]*\n\s*(?=[A-ZÇĞİÖŞÜ])", "", metin)     # STRA-\nTEJİ
    return re.sub(r"[ \t]*\n\s*", " ", metin).strip()


def blok_parcala(ham: str) -> list[str]:
    """Bir metin bloğunu paragraflara böler. Madde işaretli satırlar ve noktasız kısa liste satırları ayrı
    paragraf olur; yoksa sonraki satırın ilk kelimesi yanlışlıkla "cümle ortası" sayılırdı."""
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
        kisa_liste = (len(onceki) < max(en_uzun * 0.7, 45) and not onceki.endswith(("-", ",", "­"))
                      and not BITTI_RE.search(onceki) and satir[0].isupper())
        if MADDE_RE.match(satir) or kisa_liste:
            gruplar.append([satir])
        else:
            gruplar[-1].append(satir)
    return [re.sub(rf"^[{MADDE_ISARETI}]\s*", "", blok_temizle("\n".join(g))) for g in gruplar]


def sayfa_bloklari(sayfa, etkinlik_atla=False) -> tuple[list[str], bool]:
    """Sayfanın metnini okuma sırasıyla verir. Her satır, hemen üstünde ve aynı yatay konumda olan satırın
    devamı sayılır; böylece yan yana sütunlar karışmaz. Eğik ve dikey yazılar alınmaz."""
    bayrak = pymupdf.TEXTFLAGS_DICT & ~pymupdf.TEXT_PRESERVE_LIGATURES & ~pymupdf.TEXT_PRESERVE_IMAGES
    satirlar = []
    for blok in sayfa.get_text("dict", flags=bayrak)["blocks"]:
        for l in blok.get("lines", []):
            metin = "".join(s["text"] for s in l["spans"])
            if metin.strip() and abs(l["dir"][0]) >= 0.9995 and abs(l["dir"][1]) <= 0.03:
                satirlar.append((*l["bbox"], metin))
    satirlar.sort(key=lambda s: (round(s[1]), s[0]))

    # Etkinlik başlığı varsa, başlığın olduğu yerden sayfa sonuna kadar olan metin alınmaz.
    etkinlik_y = None
    if etkinlik_atla:
        etkinlik_y = next((s[1] for s in satirlar if ETKINLIK_RE.search(s[4].strip())), None)
        if etkinlik_y is not None:
            satirlar = [s for s in satirlar if s[1] < etkinlik_y - 3]

    parcalar = []
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
    parcalar.sort(key=lambda p: p["ilk"])
    return [p["metin"] for p in parcalar], etkinlik_y is not None


def _yarim_kalmis(metin: str) -> bool:
    return not BITTI_RE.search(metin) and not metin.isupper()


def _acik_kalmis(metin: str) -> bool:
    """Tırnak ya da parantez açılmış ama kapanmamış mı? (sayfa düzeni yüzünden bölünmüş olabilir)"""
    tirnak = metin.count('"') % 2 or metin.count("“") > metin.count("”")
    return len(metin) < EN_FAZLA_BIRLESIK and (tirnak or metin.count("(") > metin.count(")"))


def paragraflari_birlestir(parcalar):
    """(sayfa, metin) parçalarından (sayfa, paragraf_no, metin) üretir. Bölünmüş cümleleri birleştirir:
    küçük harfle devam eden parça son yarım paragrafa, açık kalan tırnak/parantezin devamı öncekine eklenir."""
    bekleyen, son_sayfa, par_no = [], None, 0
    for sayfa_no, metin in parcalar:
        if sayfa_no != son_sayfa:
            son_sayfa, par_no = sayfa_no, 0
            while len(bekleyen) > 12:
                yield tuple(bekleyen.pop(0))
        if len(metin) < 3 or metin.isdigit():                 # sayfa numarası gibi parçalar
            continue
        if re.match(r"[a-zçğıöşü]", metin):
            onceki = next((p for p in reversed(bekleyen) if _yarim_kalmis(p[2])), None)
            if onceki:
                if onceki[2].endswith("-") and onceki[2][-2:-1].isalpha():
                    onceki[2] = onceki[2][:-1] + BOLUNME + metin          # sayfa/sütun sonunda bölünen kelime
                elif onceki[2].endswith(("'", "’")):
                    onceki[2] += metin                                     # İzmir' + de
                else:
                    onceki[2] += " " + metin
                continue
        if bekleyen and _acik_kalmis(bekleyen[-1][2]):
            bekleyen[-1][2] += (" / " if metin[0].isupper() else " ") + metin
            continue
        par_no += 1
        bekleyen.append([sayfa_no, par_no, metin])
    yield from map(tuple, bekleyen)


def pdf_parcalari(yol: str, ilerleme=None, etkinlik_atla=False, atlanan=None):
    """PDF'teki her metin parçasını (sayfa_no, metin) olarak verir. etkinlik_atla açıksa etkinlik bölümleri alınmaz
    ve bu sayfaların numaraları atlanan listesine eklenir."""
    with pymupdf.open(yol) as belge:
        toplam = belge.page_count
        for sayfa_no, sayfa in enumerate(belge, start=1):
            bloklar, etkinlik_var = sayfa_bloklari(sayfa, etkinlik_atla)
            if etkinlik_var and atlanan is not None:
                atlanan.append(sayfa_no)
            for blok in bloklar:
                for metin in blok_parcala(blok):
                    yield sayfa_no, metin
            if ilerleme and (sayfa_no % 5 == 0 or sayfa_no == toplam):
                ilerleme(sayfa_no, toplam)


def pdf_paragraflari(yol: str, ilerleme=None, etkinlik_atla=False, atlanan=None):
    """PDF'teki paragrafları (sayfa_no, paragraf_no, metin) olarak verir."""
    return paragraflari_birlestir(pdf_parcalari(yol, ilerleme, etkinlik_atla, atlanan))


def metin_paragraflari(metin: str) -> list:
    """Yapıştırılan metni paragraflara böler (boş satır yeni paragraf demektir). Hepsi 1. sayfa sayılır."""
    parcalar = [(1, p) for blok in re.split(r"\n\s*\n", metin) for p in blok_parcala(blok)]
    return list(paragraflari_birlestir(parcalar))
