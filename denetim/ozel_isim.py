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
    if kendi_buyuk and not once.group(2) and not once.group(1).isupper():
        return True                                                    # Ali BAYANDUR: ad + büyük harfli soyad
    onceki = tr_kucuk(once.group(1))
    if once.group(2):
        return onceki in KISALTMALAR                                   # Dr. Gülbike, Prof. Ayşe
    return not cumle_basi_mi(metin, once.start(1)) or sozluk.ozel_isim_mi(onceki) or not sozluk.gecerli_mi(onceki)


# Özel isimden sonra gelen ve onun ne olduğunu söyleyen kelimeler: Kuşar şehri, Isık halkı, Kadırkan ormanı
AD_TURU_RE = re.compile(
    r"\s+(?:şehr|kent|köy|kasaba|orman|nehr|ırmağ|çay|dağ|tepe|göl|deniz|körfez|boğaz|kanal|ada|yarımada|vadi|ova|"
    r"bölge|ülke|eyalet|kavm|halk|oymağ|devlet|hanedan|beylik|imparatorluğ|sistem|koleksiyon|teşkilat|vakf|cami|"
    r"medrese|saray|kale|köprü|hamam|türbe|külliye|antlaşma|savaş|muharebe|isyan|destan|yazıt|gazete|dergi|macun|"
    r"şirket|fabrika|şehir)(?:l[ae]r)?(?:s?[ıiuü])(?:n[ıiuü]n|nd[ae]n?|n[ae]|n[ıiuü])?\b")
_B = BUYUK_HARF


def ozel_ad_baglami_mi(metin: str, m) -> bool:
    """Sözlükte olmayan büyük harfli kelimenin bir ad olduğunu gösteren bağlamlar (anlamına bakılmaz, yalnızca
    çevresindeki yazıya bakılır):
      * yabancı ad ve okunuşu:            Weser (Viza), Kiel (Kiıl), Sorbonne'da (Sorbon)
      * rakamlı kod:                       Kovid-19, Senitel-2
      * Osmanlıca tamlama:                 Mekteb-i Tıbbiyye-i Şahane, Kitâb-ı Bahriyye, Bacıyan-ı Rum
      * büyük harfli adlardan oluşan liste: Serez, Ferye, Üsküp / Riyad–Cidde–Dammam
      * adın türünü söyleyen kelime:       Kuşar şehri, Isık halkı, Pençik sistemi
      * şapkalı Arapça-Farsça ad:          Levnî, Harirî"""
    once, sonra = metin[:m.start()], metin[m.end():]
    kelime = m.group()
    if re.match(rf"\s*\(\s*[{_B}][^()]{{0,30}}\)", sonra) or re.search(rf"[{_B}][^\s()]*\s*\(\s*$", once):
        return True
    if re.match(r"-\d", sonra) or re.match(rf"-[{_B}]", sonra):
        return True                                                    # Kovid-19, KABARDİN-BALKARYA
    if (re.search(rf"[{_B}][{HARFLER}]+ $", once) and re.match(rf" [{_B}][{HARFLER}]", sonra)
            and not cumle_basi_mi(metin, re.search(rf"[{_B}][{HARFLER}]+ $", once).start())):
        return True                                                    # Tarım Makinaları Bilimi Dergisi
    if re.match(r"-[ıiuü]\b", sonra) or re.search(r"-[ıiuü]\s+$", once):
        return True
    liste_once = re.search(rf"(?:^|[\s(–—-])([{_B}][{HARFLER}’']+)\s*(?:,|–|—|-|\bve\b|\bile\b)\s*$", once)
    liste_sonra = re.match(rf"\s*(?:,|–|—|-|\bve\b|\bile\b)\s*[{_B}][{HARFLER}]", sonra)
    if liste_once and not cumle_basi_mi(metin, liste_once.start(1)) or (liste_sonra and liste_once):
        return True
    if liste_sonra and re.match(rf"\s*(?:,|–|—)\s*[{_B}][{HARFLER}]+\s*(?:,|–|—)", sonra):
        return True                                                    # Kıtay, Tatabı, ... (liste başı)
    if AD_TURU_RE.match(sonra):
        return True
    return bool(re.search(r"[âîû]", kelime)) and not cumle_basi_mi(metin, m.start())


def unlu_uyumu_bozuk_mu(isim: str, ek: str) -> bool:
    """Ankara'de: ismin son ünlüsü kalın, ekin ilk ünlüsü ince (ya da tersi). Refi'i, Ahmet'e uyumludur."""
    isim_unlu = re.findall(r"[aıoueiöüâîû]", tr_kucuk(isim))
    ek_unlu = re.findall(r"[aıoueiöü]", tr_kucuk(ek))
    if not isim_unlu or not ek_unlu:
        return False
    kalin = lambda u: u in "aıouâû"
    return kalin(isim_unlu[-1]) != kalin(ek_unlu[0])


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
