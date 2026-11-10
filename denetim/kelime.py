"""
Kriter 1 (argo) ve kriter 2 (yazım): metindeki her kelime tek tek incelenir. Anlama bakılmaz; kelimenin
yazılışı, sözlük kaydı ve TDK'deki etiketi kullanılır.
"""

import re

from .metin import (BIRIMLER, HARFLER, KAYNAKCA_RE, KELIME_RE, UZATMA_RE, BUYUK_HARF, adresleri_ort, baglam_al,
                    cumle_basi_mi, kelime_govdesi, kelime_parcasi, tr_buyuk, tr_buyuk_ilk, tr_kucuk)
from .ozel_isim import ad_soyad_icinde_mi
from .rapor import Bulgu

BUYUK_DENETIM_UZUNLUK = 6   # tamamı büyük harfli kelimelerde bundan kısası kısaltma sayılır (NATO, TBMM)
# Kesme işaretiyle yazılan eski ve Arapça kökenli kelimeler (okul'da gibi hata sayılmaz)
KESMELI_KELIMELER = frozenset("""san'at kur'an şe'ir te'lif mes'ul cür'et ma'lum şer'i şer'î sür'at va'd i'tibar
    i'timad i'timâd mes'ele te'sis def'a an'ane ka'be""".split())


def tdk_adaylari(kucuk: str, sozluk) -> tuple[str, ...]:
    """TDK'de aranacak madde başları. Çekimli kelime TDK'de bulunmaz: gidiyoruz -> gitmek, kitapları -> kitap."""
    return sozluk.maddeler(kucuk) or (kucuk,)


def yazim_onerileri(kucuk, sozluk, tdk) -> list[str]:
    """Önce TDK Yazım Kılavuzu'nun önerisi, sonra (TDK ulaşılabiliyorsa onda doğrulanan) sözlük önerileri."""
    oneriler, canli = [], None
    if tdk:
        oneriler += tdk.yazim_onerisi(kucuk)
        canli = getattr(tdk, "sozluk_canli", tdk.sozluk)
    adaylar = [c for c in sozluk.oneriler(kucuk) if not sozluk.ozel_isim_mi(c)]
    if canli:
        cevaplar = [canli(tdk_adaylari(c, sozluk)[0]) for c in adaylar]
        if all(c is not None for c in cevaplar):
            adaylar = [c for c, r in zip(adaylar, cevaplar) if r["var"]]
    return list(dict.fromkeys(oneriler + adaylar[:3]))


def kelimeleri_denetle(sayfa, par_no, metin, veri, sozluk, tdk=None, belge_ozel=frozenset()) -> list[Bulgu]:
    """veri: Denetleyici'nin kelime listeleri (argo, yanlislar, ozel_isimler, izinli_kokler)."""
    bulgular = []
    tarama = adresleri_ort(metin)
    kaynakca = bool(KAYNAKCA_RE.search(metin))      # kaynakçada yabancı ad ve başlıklar olur: yazımına bakılmaz

    def bulgu(kriter, kelime, aciklama, oneri, m):
        bulgular.append(Bulgu(sayfa, par_no, kriter, kelime, aciklama, oneri, baglam_al(metin, m.start(), m.end())))

    # Ayrı yazılmaması gereken ifadeler: "bir kaç" -> "birkaç" (yaygin_yanlislar.txt içindeki boşluklu satırlar)
    kucuk_metin = tr_kucuk(tarama)
    for yanlis, dogru in veri.yanlislar.items():
        if " " in yanlis and yanlis in kucuk_metin:
            for m in re.finditer(rf"(?<![{HARFLER}]){re.escape(yanlis)}(?![{HARFLER}])", kucuk_metin):
                ham = metin[m.start():m.end()]
                bulgu("YAZIM", ham, "Sık yapılan yazım yanlışı", tr_buyuk_ilk(dogru) if ham[0].isupper() else dogru, m)

    for m in KELIME_RE.finditer(tarama):
        if kelime_parcasi(tarama, m):
            continue
        govde = kelime_govdesi(m.group())
        kucuk = tr_kucuk(govde)
        adaylar = tdk_adaylari(kucuk, sozluk)
        # Kelimenin kendisi bir sözlük maddesiyse yalnızca kendisine bakılır: "ama", "am + a" diye de çözümlenir.
        bakilacak = (kucuk,) if kucuk in adaylar else adaylar

        # --- Kriter 1: Argo ---
        if tdk:
            tdk_argo = next((tdk.sozluk(a) for a in bakilacak if (tdk.sozluk(a) or {}).get("argo")), None)
            # "sayı atar" atmak, "bir iple" ip kelimesidir: argo olmayan bir okunuşu varsa argo sayılmaz.
            okunuslar = [b for b in map(tdk.sozluk, adaylar) if b and b["var"]]
            if tdk_argo and all(b["argo"] for b in okunuslar):
                bulgu("ARGO", govde, "TDK Güncel Türkçe Sözlük'te argo/kaba olarak işaretli: " + tdk_argo["argo_anlam"],
                      "Ders kitabına uygun resmî bir ifade kullanın", m)
                continue
        if kucuk in veri.argo or any(a in veri.argo for a in bakilacak):
            bulgu("ARGO", govde, "Argo, kaba ya da gündelik konuşma dili (argo_listesi.txt)",
                  "Ders kitabına uygun resmî bir ifade kullanın", m)
            continue

        # --- Kriter 2: Yazım ---
        # (a) Sık yapılan yanlışlar; çekimli hâlleri de yakalanır: yanlızca -> yalnızca, herşeyi -> her şeyi
        dogru = veri.yanlislar.get(kucuk)
        if dogru is None:
            dogru = next((veri.yanlislar[a] + kucuk[len(a):] for a in adaylar
                          if a in veri.yanlislar and kucuk.startswith(a)), None)
        if dogru is not None:
            dogru = tr_buyuk(dogru) if govde.isupper() else tr_buyuk_ilk(dogru) if govde[0].isupper() else dogru
            bulgu("YAZIM", govde, "Sık yapılan yazım yanlışı", dogru, m)
            continue

        # (b) Denetlenmeyenler
        tamami_buyuk = govde.isupper()
        if (len(govde) < 2 or kaynakca or kucuk in BIRIMLER or kucuk.startswith(veri.izinli_kokler)
                or UZATMA_RE.search(kucuk)                                        # İnanılmaaaaz
                or (tamami_buyuk and len(govde) < BUYUK_DENETIM_UZUNLUK)):        # PDF, TDK, NATO
            continue
        if not tamami_buyuk and re.search(rf"[{BUYUK_HARF}]", govde[1:]) and not sozluk.sozlukte_var_mi(kucuk):
            continue                                                              # iOS, bölümNo, KWrite
        kesmeli = govde != m.group()
        kesmeli_tam = tr_kucuk(m.group()).replace("’", "'")
        buyuk_baslar = govde[0].isupper() and not tamami_buyuk
        if tamami_buyuk and (kesmeli or sozluk.gecerli_mi(kucuk)):
            continue                                                              # TÜRKİYE'DE, BÖLÜM

        # (c) Özel isimler
        if buyuk_baslar and kesmeli:
            # Ankara'de: özel isim doğru ama kesmeden sonraki ek ünlü uyumuna aykırı
            if sozluk.ozel_isim_mi(kucuk) and not re.search(r"[qwx]", kucuk) and not sozluk.gecerli_mi(kesmeli_tam):
                bulgu("YAZIM", m.group(), "Özel isme gelen ek yanlış yazılmış", "Eki ünlü uyumuna göre düzeltin", m)
            continue                                                              # Newton'un
        if buyuk_baslar and sozluk.ozel_isim_mi(kucuk):
            dogrusu = sozluk.kesmesiz_ozel_isim(kucuk)
            if dogrusu and not re.match(rf"[ ]+[{BUYUK_HARF}]", tarama[m.end():]):   # Fevziye Lisesi: çok kelimeli ad
                bulgu("YAZIM", govde, "Özel isme gelen ek kesme işaretiyle ayrılmalı", dogrusu, m)
            continue                                                              # Ankara, Ayşe
        if buyuk_baslar and govde in belge_ozel:
            continue                                                              # metinde özel isim olarak ayrıldı
        if (buyuk_baslar or tamami_buyuk) and not sozluk.sozlukte_var_mi(kucuk) and ad_soyad_icinde_mi(tarama, m, sozluk):
            continue                                                              # Dr. Gülbike YILDIRIM

        # (d) Sözlük kararı. TDK asıl kaynaktır; ulaşılamazsa Hunspell ve Zemberek kullanılır.
        tdk_bilgileri = [tdk.sozluk(a) for a in adaylar] if tdk else []
        tdk_ulasilamadi = (not tdk) or any(b is None for b in tdk_bilgileri)
        tdk_biliyor = any(b and b["var"] for b in tdk_bilgileri)
        bilinen = sozluk.gecerli_mi(kucuk) or tdk_biliyor

        if kesmeli and not buyuk_baslar:
            # okul'da: özel isim olmayan kelimeye gelen ek kesmeyle ayrılmaz. Sözlükte olmayan yabancı terim
            # (framework'tür) ve eski yazımlar (şer'i, san'at) atlanır.
            if (bilinen and not sozluk.ozel_isim_mi(kucuk) and not sozluk.serbest_mi(kucuk)
                    and kesmeli_tam not in KESMELI_KELIMELER):
                bulgu("YAZIM", m.group(), "Özel isim olmayan kelimeye gelen ek kesme işaretiyle ayrılmaz",
                      m.group().replace("'", "").replace("’", ""), m)
            continue
        if not buyuk_baslar and not tamami_buyuk and not sozluk.gecerli_mi(kucuk) and tr_buyuk_ilk(kucuk) in belge_ozel:
            continue                                                              # cache: metinde Cache olarak da geçiyor

        # ahmet, ankarada: özel isim küçük harfle yazılmış (kitablarını gibi yazım hatası da olabilir)
        listede = kucuk not in veri.ozel_isimler and any(a in veri.ozel_isimler for a in adaylar)
        if (not tamami_buyuk and not buyuk_baslar and sozluk.ozel_isim_mi(kucuk)
                and (not tdk_biliyor or listede)):
            oneriler = [sozluk.kesmesiz_ozel_isim(kucuk) or tr_buyuk_ilk(kucuk)]
            oneriler += yazim_onerileri(kucuk, sozluk, None if tdk_ulasilamadi else tdk)
            bulgu("YAZIM", govde, "Özel isim küçük harfle yazılmış ya da kelimede yazım hatası var",
                  ", ".join(dict.fromkeys(oneriler)), m)
            continue
        if sozluk.serbest_mi(kucuk) or tdk_biliyor or sozluk.dogru_yazilmis_mi(kucuk):
            continue                                                              # mı, misin, km; doğru kelime

        oneriler = yazim_onerileri(kucuk, sozluk, None if tdk_ulasilamadi else tdk)
        aciklama = "Sözlükte bulunamadı – olası yazım hatası"
        if tamami_buyuk or (buyuk_baslar and not cumle_basi_mi(tarama, m.start())):
            # Cümle ortasında büyük harfli bilinmeyen kelime özel isim ya da kısaltma olabilir: yalnızca bilinen bir
            # kelimeye çok benziyorsa (Öğrencilr -> öğrenciler) bildirilir. Tırnak içindeki adlar atlanır.
            if not oneriler or tarama[m.start() - 1:m.start()] in ('"', "“"):
                continue
            aciklama = "Olası yazım hatası (özel isim değilse)"
        elif buyuk_baslar:
            aciklama = "Sözlükte bulunamadı – yazım hatası ya da özel isim"
        if tamami_buyuk:
            oneriler = [tr_buyuk(o) for o in oneriler]
        elif buyuk_baslar:
            oneriler = [tr_buyuk_ilk(o) for o in oneriler]
        bulgu("YAZIM", govde, aciklama, ", ".join(oneriler) or "Öneri bulunamadı", m)
    return bulgular
