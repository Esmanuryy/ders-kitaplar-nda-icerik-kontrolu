"""
Kriter 1 (argo) ve kriter 2 (yazım): metindeki her kelime tek tek incelenir. Anlama bakılmaz; kelimenin
yazılışı, sözlük kaydı ve TDK'deki etiketi kullanılır.
"""

import re

from .metin import (BIRIMLER, KAYNAKCA_RE, KELIME_RE, UZATMA_RE, BUYUK_HARF, adresleri_ort, baglam_al,
                    cumle_basi_mi, kelime_govdesi, kelime_parcasi, tr_buyuk, tr_buyuk_ilk, tr_kucuk)
from .ozel_isim import ad_soyad_icinde_mi, ozel_ad_baglami_mi, unlu_uyumu_bozuk_mu
from .rapor import Bulgu

BUYUK_DENETIM_UZUNLUK = 6   # tamamı büyük harfli kelimelerde bundan kısası kısaltma sayılır (NATO, TBMM)
ARGO_ONERI = "Yerine resmî ve ders kitabına uygun bir söz kullanın."
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


TR_HARFLER = "abcçdefgğhıijklmnoöprsştuüvyz"
TERIM_ACIKLAMA_RE = re.compile(r"[’']\s*\(|\s+\(|\s+(?:denilen|denen|denir|denmektedir|adı verilen|adını alan|olarak adlandırılan|adlı)\b")
UNLULER, UNSUZLER = "aeıioöuü", "bcçdfghjklmnprsştvyz"
# Kesme işaretiyle ayrılan yaygın ekler. Bunların dışında kalan kesmeler (sür’atle, şer’iye, beyne’l) eski yazımdır.
YAYGIN_EKLER = frozenset("""a e ya ye ı i u ü yı yi yu yü ın in un ün nın nin nun nün da de ta te dan den tan ten
    la le yla yle lar ler dır dir dur dür tır tir tur tür ki daki deki taki teki dı di du dü ydı ydi ydu ydü""".split())
# Türkçede yazarken sık karıştırılan harfler: noktasız/şapkasız yazım ve sert-yumuşak ünsüzler (kitablar, guzel)
KARISAN_HARFLER = [set(c) for c in ("ıi", "oö", "uü", "sş", "cç", "gğk", "bp", "dt", "aâ", "iî", "uû")]


def yazim_hatasina_benzer(kelime: str, oneri: str) -> bool:
    """Kelime, önerilen kelimenin yazım hatasıyla oluşmuş hâline benziyor mu? Bir harf eksik/fazla
    (Öğrencilr), iki harfin yeri değişmiş ya da sık karıştırılan bir harf yanlış yazılmışsa (Kitablar) evet.
    İlk harfi farklı ya da alakasız bir harf değişmişse (Köçürme / Göçürme, Köpürme) özel isim sayılır."""
    a, b = tr_kucuk(kelime), tr_kucuk(oneri)
    if abs(len(a) - len(b)) == 1:
        kisa, uzun = (a, b) if len(a) < len(b) else (b, a)
        return any(uzun[:i] + uzun[i + 1:] == kisa for i in range(1, len(uzun)))
    if len(a) != len(b):
        return False
    farklar = [i for i in range(len(a)) if a[i] != b[i]]
    if len(farklar) == 2 and farklar[1] == farklar[0] + 1 and farklar[0] > 0:
        return a[farklar[0]] == b[farklar[1]] and a[farklar[1]] == b[farklar[0]]          # harflerin yeri değişmiş
    return (len(farklar) == 1 and farklar[0] > 0
            and any(a[farklar[0]] in k and b[farklar[0]] in k for k in KARISAN_HARFLER))


def degisken_mi(tarama, m, kucuk, sozluk) -> bool:
    """Matematikteki değişkenler ve onlara gelen ekler: x, xa, xn, ab, mx, "a nın" (a'nın)."""
    if sozluk.gecerli_mi(kucuk):
        return False
    if len(kucuk) <= 2 or (len(kucuk) <= 3 and re.search(r"[xqw]", kucuk)):
        return True
    return len(kucuk) <= 4 and bool(re.search(r"(?:^|[\s(])[a-zA-Z]\s+$", tarama[:m.start()]))


def alinti_icinde_mi(metin: str, konum: int) -> bool:
    """Konum tırnak içinde mi? Alıntılar eserin aslındaki yazımla aktarılır ("olub", "tesbit", "münasibdir");
    bu yüzden alıntıdaki kelimelerin yazımı hata sayılmaz."""
    once = metin[:konum]
    if once.count("“") > once.count("”") or once.count('"') % 2:
        return True
    acilis = once.rfind("‘")
    return acilis >= 0 and not re.search(r"’(?![a-zçğıöşüâîû])", once[acilis:])


def kelimeleri_denetle(sayfa, par_no, metin, veri, sozluk, tdk=None, belge_ozel=frozenset(), matematik=False,
                       pdf=False) -> list[Bulgu]:
    """veri: Denetleyici'nin kelime listeleri (argo, yanlislar, ozel_isimler, izinli_kokler)."""
    bulgular = []
    tarama = adresleri_ort(metin)
    kaynakca = bool(KAYNAKCA_RE.search(metin))      # kaynakçada yabancı ad ve başlıklar olur: yazımına bakılmaz

    def bulgu(kriter, kelime, aciklama, oneri, m):
        bulgular.append(Bulgu(sayfa, par_no, kriter, kelime, aciklama, oneri, baglam_al(metin, m.start(), m.end())))

    # Her kelime kendi başına ele alınır; kelimeler birleştirilip anlam aranmaz.
    for m in KELIME_RE.finditer(tarama):
        if kelime_parcasi(tarama, m):
            continue
        govde = kelime_govdesi(m.group())
        kucuk = tr_kucuk(govde)
        adaylar = tdk_adaylari(kucuk, sozluk)
        # Kelimenin kendisi bir sözlük maddesiyse yalnızca kendisine bakılır: "ama", "am + a" diye de çözümlenir.
        bakilacak = (kucuk,) if kucuk in adaylar else adaylar

        # --- Kriter 1: Argo ---
        # PDF'te bölünen kelimenin parçası argo bir kelimeye denk gelebilir ("kul-lan" -> "lan"): kısa olanlar atlanır.
        if pdf and len(kucuk) <= 3:
            kopmus_parca = True
        else:
            kopmus_parca = False
        if tdk and not kopmus_parca:
            tdk_argo = next((tdk.sozluk(a) for a in bakilacak if (tdk.sozluk(a) or {}).get("argo")), None)
            # "sayı atar" atmak, "bir iple" ip kelimesidir: argo olmayan bir okunuşu varsa argo sayılmaz.
            okunuslar = [b for b in map(tdk.sozluk, adaylar) if b and b["var"]]
            if tdk_argo and all(b["argo"] for b in okunuslar):
                bulgu("ARGO", govde, f"“{govde}” TDK Güncel Türkçe Sözlük'te argo ya da kaba söz olarak geçiyor "
                      f"(anlamı: {tdk_argo['argo_anlam']}). Ders kitabında kullanılmamalı.", ARGO_ONERI, m)
                continue
        if not kopmus_parca and (kucuk in veri.argo or any(a in veri.argo for a in bakilacak)):
            bulgu("ARGO", govde, f"“{govde}” argo, kaba ya da gündelik konuşma diline ait bir söz. "
                  "Ders kitabında kullanılmamalı.", ARGO_ONERI, m)
            continue

        # --- Kriter 2: Yazım ---
        # Künyedeki büyük harfli soyadlar (Ali HEMDE, Ali BAYANDUR) yazım yanlışı sayılmaz.
        if (govde.isupper() and len(govde) >= 2 and not sozluk.gecerli_mi(kucuk)
                and ad_soyad_icinde_mi(tarama, m, sozluk)):
            continue
        # (a) Sık yapılan yanlışlar; çekimli hâlleri de yakalanır: yanlızca -> yalnızca, herşeyi -> her şeyi
        dogru = veri.yanlislar.get(kucuk)
        if dogru is None:
            dogru = next((veri.yanlislar[a] + kucuk[len(a):] for a in adaylar
                          if a in veri.yanlislar and kucuk.startswith(a)), None)
        if dogru is not None and govde[0].isupper() and ozel_ad_baglami_mi(tarama, m):
            dogru = None                                                  # Tarım Makinaları Dergisi: kurum adı
        if dogru is not None:
            dogru = tr_buyuk(dogru) if govde.isupper() else tr_buyuk_ilk(dogru) if govde[0].isupper() else dogru
            bulgu("YAZIM", govde, f"“{govde}” sık yapılan bir yazım yanlışı.", dogru, m)
            continue

        # (b) Denetlenmeyenler
        tamami_buyuk = govde.isupper()
        if (len(govde) < 2 or kaynakca or kucuk in BIRIMLER or kucuk.startswith(veri.izinli_kokler)
                or UZATMA_RE.search(kucuk)                                        # İnanılmaaaaz
                or degisken_mi(tarama, m, kucuk, sozluk)                           # xa, xn, a nın
                or (tamami_buyuk and len(govde) < BUYUK_DENETIM_UZUNLUK)):        # PDF, TDK, NATO
            continue
        if not tamami_buyuk and re.search(rf"[{BUYUK_HARF}]", govde[1:]) and not sozluk.sozlukte_var_mi(kucuk):
            continue                                                              # iOS, bölümNo, KWrite
        kesmeli = govde != m.group()
        kesmeli_tam = tr_kucuk(m.group()).replace("’", "'")
        buyuk_baslar = govde[0].isupper() and not tamami_buyuk
        if tamami_buyuk and (kesmeli or sozluk.gecerli_mi(kucuk) or sozluk.gecerli_mi(tr_kucuk(govde.replace("I", "İ")))):
            continue                                       # TÜRKİYE'DE, BÖLÜM; STRATEJIK: PDF'te İ harfi I çıkmış

        # (c) Özel isimler
        if buyuk_baslar and kesmeli:
            # Ankara'de: özel isim doğru ama kesmeden sonraki ek ünlü uyumuna aykırı
            ek = re.split(r"['’]", m.group(), maxsplit=1)[-1]
            if (sozluk.ozel_isim_mi(kucuk) and not re.search(r"[qwx]", kucuk) and not sozluk.gecerli_mi(kesmeli_tam)
                    and unlu_uyumu_bozuk_mu(govde, ek) and not ozel_ad_baglami_mi(tarama, m)):
                bulgu("YAZIM", m.group(), "Özel isme gelen ek, ismin son hecesine uymuyor (ünlü uyumu bozuk).",
                      "Eki ünlü uyumuna göre düzeltin (Ankara'da, Ahmet'e gibi).", m)
            continue                                                              # Newton'un
        if buyuk_baslar and sozluk.ozel_isim_mi(kucuk):
            dogrusu = sozluk.kesmesiz_ozel_isim(kucuk)
            listedeki = any(a in veri.ozel_isimler for a in adaylar) or kucuk in veri.ozel_isimler
            if dogrusu and listedeki and not re.match(rf"[ ]+[{BUYUK_HARF}]", tarama[m.end():]):   # Fevziye Lisesi
                bulgu("YAZIM", govde, "Özel isimlere gelen ekler kesme işaretiyle ayrılır.", dogrusu, m)
            continue                                                              # Ankara, Ayşe
        if buyuk_baslar and govde in belge_ozel:
            continue                                                              # metinde özel isim olarak ayrıldı
        if (buyuk_baslar or tamami_buyuk) and not sozluk.sozlukte_var_mi(kucuk) and ozel_ad_baglami_mi(tarama, m):
            continue                                                              # Weser (Viza), Kuşar şehri
        if (buyuk_baslar or tamami_buyuk) and not sozluk.sozlukte_var_mi(kucuk) and ad_soyad_icinde_mi(tarama, m, sozluk):
            continue                                                              # Dr. Gülbike YILDIRIM

        # Alıntıdaki ve şapkalı eski yazımlı kelimeler (nasîb, kirâmım) eserin aslındaki gibi aktarılır.
        if alinti_icinde_mi(tarama, m.start()) or re.search("[âîû\u0302]", kucuk):
            if not sozluk.dogru_yazilmis_mi(kucuk):
                continue
        # İki ünsüzle başlayan (mlay, grid, drone) ya da q, w, x içeren küçük harfli kelime Türkçe değildir ya da
        # PDF'te bölünmüş bir parçadır; yazımına bakılmaz.
        if (not buyuk_baslar and not tamami_buyuk and not sozluk.dogru_yazilmis_mi(kucuk)
                and (re.match(rf"[{UNSUZLER}]{{2}}", kucuk) or re.search(r"[qwx]", kucuk))):
            continue
        # Hemen ardından açıklaması gelen kelime bilerek kullanılmış bir terimdir: "sıçgan (sıçan)", "toygun denilen",
        # "salyane adı verilen". Kitap bu kelimeyi tanıtıyordur; yazım hatası sayılmaz.
        if not sozluk.dogru_yazilmis_mi(kucuk) and TERIM_ACIKLAMA_RE.match(tarama[m.end():]):
            continue

        # (d) Sözlük kararı. TDK asıl kaynaktır; ulaşılamazsa Hunspell ve Zemberek kullanılır.
        tdk_bilgileri = [tdk.sozluk(a) for a in adaylar] if tdk else []
        tdk_ulasilamadi = (not tdk) or any(b is None for b in tdk_bilgileri)
        tdk_biliyor = any(b and b["var"] for b in tdk_bilgileri)
        bilinen = sozluk.gecerli_mi(kucuk) or tdk_biliyor

        if kesmeli and not buyuk_baslar:
            # okul'da: özel isim olmayan kelimeye gelen ek kesmeyle ayrılmaz. Sözlükte olmayan yabancı terim
            # (framework'tür) ve eski yazımlar (şer'i, san'at) atlanır.
            ek = re.split(r"['’]", m.group(), maxsplit=1)[-1]
            if (bilinen and not sozluk.ozel_isim_mi(kucuk) and not sozluk.serbest_mi(kucuk)
                    and kesmeli_tam not in KESMELI_KELIMELER and tr_kucuk(ek) in YAYGIN_EKLER
                    and not alinti_icinde_mi(tarama, m.start()) and not re.search(r"[âîû]", kesmeli_tam)
                    and not re.search(r"-\s*$", tarama[:m.start()])):
                bulgu("YAZIM", m.group(), "Kesme işareti yalnızca özel isimlere gelen ekleri ayırır; bu kelime özel isim değil.",
                      m.group().replace("'", "").replace("’", ""), m)
            continue
        if not buyuk_baslar and not tamami_buyuk and not sozluk.gecerli_mi(kucuk) and tr_buyuk_ilk(kucuk) in belge_ozel:
            continue                                                              # cache: metinde Cache olarak da geçiyor

        # Baş harfi kopmuş kelime parçası: "erçek" (süslü büyük G ayrı yazılmış), "rütebilmeniz". Başına tek bir harf
        # eklenince doğru bir kelime oluyorsa kelime PDF'te bölünmüştür; hata sayılmaz.
        if (not buyuk_baslar and not tamami_buyuk and len(kucuk) >= 3
                and not sozluk.dogru_yazilmis_mi(kucuk)
                and (any(sozluk.gecerli_mi(h + kucuk) for h in TR_HARFLER)
                     or any(sozluk.gecerli_mi(u + s + kucuk) for u in UNSUZLER for s in UNLULER))):
            continue                                                  # lenek (ge-lenek), şullar (ko-şullar)

        # ahmet, ankarada: özel isim küçük harfle yazılmış (kitablarını gibi yazım hatası da olabilir)
        # Yalnızca veri/ozel_isimler.txt listesindeki adlar için bildirilir; sözlükte özel isim olarak da geçen
        # sıradan kelimeler (grid, drone, mehir, yörük) hata sayılmaz.
        listede = kucuk in veri.ozel_isimler or any(a in veri.ozel_isimler for a in adaylar)
        if not tamami_buyuk and not buyuk_baslar and listede and sozluk.ozel_isim_mi(kucuk):
            oneriler = [sozluk.kesmesiz_ozel_isim(kucuk) or tr_buyuk_ilk(kucuk)]
            oneriler += yazim_onerileri(kucuk, sozluk, None if tdk_ulasilamadi else tdk)
            bulgu("YAZIM", govde, f"“{govde}” bir özel isme benziyor; özel isimler büyük harfle başlar. "
                  "Özel isim değilse kelime yanlış yazılmış olabilir.",
                  ", ".join(dict.fromkeys(oneriler)), m)
            continue
        if sozluk.serbest_mi(kucuk) or tdk_biliyor or sozluk.dogru_yazilmis_mi(kucuk):
            continue                                                              # mı, misin, km; doğru kelime

        # lhlamur: PDF'te büyük I harfi küçük L gibi çıkabilir (Ihlamur). "ı" ile okununca doğruysa hata değildir.
        if kucuk[0] == "l" and sozluk.dogru_yazilmis_mi("ı" + kucuk[1:]):
            continue

        # Türkçede hiçbir kelime ğ ile başlamaz: "ğundan" satırda bölünmüş bir kelimenin parçasıdır.
        if kucuk[0] == "ğ":
            continue

        oneriler = yazim_onerileri(kucuk, sozluk, None if tdk_ulasilamadi else tdk)
        aciklama = f"“{govde}” Türkçe sözlükte bulunamadı; yanlış yazılmış olabilir."
        # Emin olunmayan kelime hata sayılmaz: sözlükte olmayan bir kelime ancak bilinen bir kelimenin yazım hatasına
        # benziyorsa (guzel -> güzel, öğrencilr -> öğrenciler) bildirilir. Hiçbir kelimeye benzemeyen kelime terim,
        # eski kelime, yabancı ad ya da PDF'ten bozuk çıkmış bir parçadır; hata uydurulmaz.
        oneriler = [o for o in oneriler if yazim_hatasina_benzer(govde, o)]
        if not oneriler:
            continue
        if tamami_buyuk or (buyuk_baslar and not cumle_basi_mi(tarama, m.start())):
            # Cümle ortasında büyük harfli bilinmeyen kelime özel isim ya da kısaltma olabilir: yalnızca bilinen bir
            # kelimeye çok benziyorsa (Öğrencilr -> öğrenciler) bildirilir. Tırnak içindeki adlar atlanır.
            # Ad gibi duran kelime (Köçürme, Gümüştepe) bir yazım hatasına benzemiyorsa özel isim sayılır.
            if tarama[m.start() - 1:m.start()] in ('"', "“"):
                continue
            aciklama = f"“{govde}” sözlükte yok ama bilinen bir kelimeye çok benziyor. Özel isim değilse yanlış yazılmış."
        elif buyuk_baslar:
            # Cümle başında büyük harfle başlayan, sözlükteki hiçbir kelimeye benzemeyen kelime özel isimdir
            # (Fahrünnisa). Bilinen bir kelimeye benziyorsa (Herkez, Guzel) yazım hatası olarak bildirilir.
            aciklama = f"“{govde}” Türkçe sözlükte bulunamadı; yanlış yazılmış ya da bir özel isim olabilir."
        if tamami_buyuk:
            oneriler = [tr_buyuk(o) for o in oneriler]
        elif buyuk_baslar:
            oneriler = [tr_buyuk_ilk(o) for o in oneriler]
        bulgu("YAZIM", govde, aciklama, ", ".join(oneriler), m)
    return bulgular
