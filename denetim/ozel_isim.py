"""
Özel isimleri ayırma. Anlama bakılmaz; kelimenin yazılışına, sözlük kaydına ve yanındaki kelimelere bakılır.
Ayrılan özel isimler yazım hatası sayılmaz ve sitede ayrı listelenir.
"""

import re
from collections import Counter

from .metin import (BUYUK_HARF, HARFLER, KELIME_RE, KISALTMALAR, UZATMA_RE, adresleri_ort, cumle_basi_mi,
                    kelime_govdesi, kelime_parcasi, tr_kucuk)


def ad_soyad_icinde_mi(metin: str, m, sozluk) -> bool:
    """Dr. Gülbike YILDIRIM, Vedat Ersin CEVİZ: büyük harfli komşusu olan bilinmeyen kelime addır.
    Cümlenin ilk kelimesi komşu sayılmaz ("Sonra Öğrencilr" ad değildir); başlıktaki büyük harfli kelimeler
    birbirine komşu sayılmaz ("KONU ANLATIMII" ad değildir)."""
    kendi_buyuk = kelime_govdesi(m.group()).isupper()
    if re.match(rf",\s+[{BUYUK_HARF}]\.", metin[m.end():]):          # kaynakça: ZORLUTUNA, H. N.
        return True
    sonra = re.match(rf"[ -]+([{HARFLER}]+)", metin[m.end():])
    if sonra and sonra.group(1)[0].isupper() and not (kendi_buyuk and sonra.group(1).isupper()):
        return True
    once = re.search(rf"([{HARFLER}]+)(\.?)[ -]+$", metin[:m.start()])
    if not once or not once.group(1)[0].isupper() or (kendi_buyuk and once.group(1).isupper()):
        return False
    onceki = tr_kucuk(once.group(1))
    if once.group(2):
        return onceki in KISALTMALAR                                   # Dr. Gülbike, Prof. Ayşe
    return not cumle_basi_mi(metin, once.start(1)) or sozluk.ozel_isim_mi(onceki) or not sozluk.gecerli_mi(onceki)


def ozel_isimleri_ayir(paragraflar, sozluk, izinli_kokler=()) -> Counter:
    """Metindeki özel isimleri ayırır. Döndürür: {özel isim: geçme sayısı}.
      * Newton'un     -> büyük harf ve kesme işareti
      * Ankara, Ayşe  -> sözlükte yalnızca özel isim olarak kayıtlı
      * Gülbike       -> büyük harfli bir ad ya da unvanla yan yana (Dr. Gülbike YILDIRIM)
      * Pisagor       -> cümle ortasında büyük harfli, sözlükte yok ve metinde en az iki kez geçiyor
    """
    sayac, supheli = Counter(), Counter()
    for _, _, metin in paragraflar:
        tarama = adresleri_ort(metin)
        for m in KELIME_RE.finditer(tarama):
            govde = kelime_govdesi(m.group())
            if (len(govde) < 2 or govde.isupper() or not govde[0].isupper() or kelime_parcasi(tarama, m)
                    or re.search(rf"[{BUYUK_HARF}]", govde[1:])):
                continue
            kucuk = tr_kucuk(govde)
            if kucuk.startswith(izinli_kokler) or UZATMA_RE.search(kucuk):
                continue
            if sozluk.ozel_isim_mi(kucuk):
                # Türkiye "Türki+ye" diye de çözümlenir: en uzun madde başı alınır
                sayac[max((c[0] for c in sozluk.cozumler(kucuk)), key=len)] += 1
            elif govde != m.group():
                # Sözlük'ü gibi sıradan kelimeler listelenmez; Samsun'a gibi özel ad okunuşu olanlar listelenir
                if not sozluk.gecerli_mi(kucuk) or sozluk.ozel_isim_okunusu_var_mi(kucuk):
                    sayac[govde] += 1
            elif not sozluk.gecerli_mi(kucuk) and ad_soyad_icinde_mi(tarama, m, sozluk):
                sayac[govde] += 1
            elif not sozluk.gecerli_mi(kucuk) and not cumle_basi_mi(tarama, m.start()):
                supheli[govde] += 1
    for ad, adet in supheli.items():
        if adet >= 2 or ad in sayac or not sozluk.oneriler(tr_kucuk(ad)):
            sayac[ad] += adet
    return sayac
