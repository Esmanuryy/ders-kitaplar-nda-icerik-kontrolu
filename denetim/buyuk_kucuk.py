"""
Büyük / küçük harf hataları (TDK Yazım Kılavuzu: "Büyük harflerin kullanıldığı yerler").
Bu hatalar raporda YAZIM kriteri altında gösterilir.
"""

import re

from .metin import (BUYUK_HARF, HARFLER, KELIME_RE, KISALTMALAR, KUCUK_HARF, ROMA_RAKAMI_RE, adresleri_ort,
                    baglam_al, kelime_parcasi, tr_buyuk_ilk, tr_kucuk)
from .rapor import Bulgu

# "Siz anlatınız!" dedim. / "Ne zaman?" diye sordu: bu kelimelerle cümle devam eder.
DEME_KELIMELERI = frozenset("diye dedi dedim dedik dediler sordu sordum sorduk söyledi bağırdı".split())


def cumle_mi(parca: str, sozluk) -> bool:
    """Parça, ilk . ! ? işaretine kadar gerçek bir cümle mi? Kelime listeleri ve sayfa düzeninden kopan
    parçalar elenir: en az 3 kelime olmalı ve son kelimesi yüklem olabilmeli."""
    kelimeler = KELIME_RE.findall(re.split(r"[.!?…]", parca, maxsplit=1)[0])
    return len(kelimeler) >= 3 and sozluk.yuklem_olabilir_mi(tr_kucuk(kelimeler[-1]))


def buyuk_i_olabilir(kelime: str, sozluk) -> bool:
    """PDF'te büyük I harfi küçük L gibi çıkabilir: "lhlamur" aslında "Ihlamur"dur."""
    return kelime[:1] == "l" and sozluk.dogru_yazilmis_mi("ı" + tr_kucuk(kelime[1:]))


def harf_hatalari_bul(sayfa, par_no, metin, ozel_isimler, sozluk) -> list[Bulgu]:
    bulgular, isaretli = [], set()
    tarama = adresleri_ort(metin)

    def ekle(bas, son, kelime, aciklama, oneri):
        if bas not in isaretli:
            isaretli.add(bas)
            bulgular.append(Bulgu(sayfa, par_no, "YAZIM", kelime, aciklama, oneri, baglam_al(metin, bas, son)))

    # 1) Paragraf küçük harfle başlıyor. "a) ...", "1. ..." gibi madde işaretleri ve kelime listeleri atlanır.
    m = re.match(rf"^[\s—–-]*([{KUCUK_HARF}][{HARFLER}]*)(.?)", tarama)
    if (m and not (len(m.group(1)) == 1 and m.group(2) in (")", ".")) and cumle_mi(tarama, sozluk)
            and not buyuk_i_olabilir(m.group(1), sozluk)):
        ekle(m.start(1), m.end(1), m.group(1), "Cümleler büyük harfle başlar.", tr_buyuk_ilk(m.group(1)))

    # 2) Cümle sonu işaretinden (. ! ?) sonra küçük harfle başlayan cümle
    for m in re.finditer(rf"(\S*)([.!?])([\"”’')\]]*)\s+[\"“‘'(\[]?([{KUCUK_HARF}][{HARFLER}]*)", tarama):
        onceki, isaret, kapanis, kelime = m.group(1), m.group(2), m.group(3), m.group(4)
        if (kapanis or len(kelime) == 1 or kelime in DEME_KELIMELERI or "=" in onceki
                or buyuk_i_olabilir(kelime, sozluk)):
            continue                                            # "Geldin mi?" diye sordu / b) şıkkı / 3=? işlemi
        if not cumle_mi(tarama[m.start(4):], sozluk):
            continue                                            # sonrası cümle değil, kelime listesi
        if isaret == "." and (onceki.endswith(".") or onceki.endswith("…")):
            continue                                            # üç nokta: cümle devam edebilir
        temiz = re.sub(r"\W", "", onceki)
        if isaret == "." and (temiz.isdigit() or len(temiz) <= 1 or tr_kucuk(temiz) in KISALTMALAR
                              or ROMA_RAKAMI_RE.match(temiz)):
            continue                                            # 3. madde, a. şık, vb. kelime, XIX. yüzyıl
        ekle(m.start(4), m.end(4), kelime, "Noktadan, soru ya da ünlem işaretinden sonra yeni cümle büyük harfle başlar.",
            tr_buyuk_ilk(kelime))

    for m in KELIME_RE.finditer(tarama):
        if kelime_parcasi(tarama, m):
            continue
        govde = re.split(r"['’]", m.group())[0]
        kucuk = tr_kucuk(govde)
        # 3) Özel isim küçük harfle yazılmış (ankara, türkiye, ingilizce)
        if govde == kucuk and govde in ozel_isimler:
            ekle(m.start(), m.start() + len(govde), govde, "Özel isimler (kişi, yer, ülke, dil adları) büyük harfle başlar.",
                 tr_buyuk_ilk(govde))
            continue
        # 4) Kelimenin ortasında yanlış büyük harf (oKul, kitapLar). JavaScript gibi özel adlar ve MySQL gibi
        #    birden çok büyük harfli kısaltmalar elenir.
        if (len(govde) >= 3 and sozluk.gecerli_mi(kucuk) and not sozluk.ozel_isim_mi(kucuk)
                and len(re.findall(rf"[{BUYUK_HARF}]", govde[1:])) == 1):
            if re.match(rf"^[{KUCUK_HARF}]+[{BUYUK_HARF}]", govde):
                ekle(m.start(), m.start() + len(govde), govde, "Kelimenin ortasında büyük harf kullanılmaz.",
                     kucuk)
            elif re.match(rf"^[{BUYUK_HARF}][{KUCUK_HARF}]+[{BUYUK_HARF}]", govde):
                ekle(m.start(), m.start() + len(govde), govde, "Kelimenin ortasında büyük harf kullanılmaz.",
                     tr_buyuk_ilk(kucuk))
    return bulgular
