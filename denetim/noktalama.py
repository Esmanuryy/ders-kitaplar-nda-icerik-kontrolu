"""
Kriter 3: Noktalama ve tekrar. TDK Yazım Kılavuzu'ndaki noktalama kurallarına dayalı, kural tabanlı denetim.
"""

import re

from .metin import BUYUK_HARF, HARFLER, KELIME_RE, KUCUK_HARF, adresleri_ort, baglam_al, tr_kucuk
from .rapor import Bulgu

H = "A-Za-zÇĞİÖŞÜçğıöşüÂâÎîÛû"
# (kural, açıklama, öneri). Her eşleşme bir bulgudur.
KURALLAR = [
    # Boşlukla hizalanmış etiketler ("Konu   : ...") ve alan adları (.eu) hata sayılmaz
    (re.compile(rf"(?<=[{H}])[ \t](?:[,;:!?]|\.(?![.{H}]))"),
     "Noktalama işaretinden önce boşluk", "Boşluğu silin"),
    (re.compile(rf"(?<=[{H}]{{2}}),[{H}]|[;!?][{H}]|(?<![\d\s]):[{H}]"),
     "Noktalama işaretinden sonra boşluk yok", "İşaretten sonra boşluk bırakın"),
    (re.compile(r"(?<=[a-zçğıöşü]{2})(?<!vb)(?<!vs)(?<!Prof)(?<!Doç)(?<!Yrd)(?<!Öğr)(?<!Arş)(?<!Uzm)\.(?:[A-ZÇĞİÖŞÜ]"
                r"|(?!(?:pdf|docx?|txt|html?|py|jpe?g|png|xlsx?|js|json|css|ts|java|cpp|xml|sql)\b)(?![a-zçğıöşü]+\()[a-zçğıöşü]{2})"),
     "Noktadan sonra boşluk yok", "Noktadan sonra boşluk bırakın"),
    (re.compile(r"(?<![.!?…])\.\.(?![.…])|(?<!\.)\.{4}(?!\.)(?!\s*\d)|[,;:][,;:.]"),
     "Tekrarlanan noktalama işareti", "Tek işaret veya üç nokta kullanın"),
    (re.compile(r"!{2,}|\?{2,}"), "Birden fazla ünlem/soru işareti", "Tek işaret kullanın (ders kitabı dili)"),
    (re.compile(r"\(\s|\s\)"), "Parantez içinde gereksiz boşluk", "Boşluğu silin"),
    (re.compile(rf"[{H}]{{4,}}\((?=[^)]*\s)"), "Parantezden önce boşluk yok", "Parantezden önce boşluk bırakın"),
    (re.compile(r"\)[a-zçğıöşü]{3,}"), "Parantezden sonra boşluk yok", "Parantezden sonra boşluk bırakın"),
    (re.compile(r",\s+(?:ve|veya)\b(?!\s*,)"), "\"ve/veya\" bağlacından önce virgül kullanılmaz", "Virgülü silin"),
    (re.compile(r"\b\d+(?:lar|ler|da|de|ta|te|dan|den|tan|ten|ya|ye|yı|yi|yu|yü|nın|nin|nun|nün|ın|in|un|ün)\b"),
     "Sayıya gelen ek kesme işaretiyle ayrılmalı", "Örnek: 1923'te, 1980'ler"),
    (re.compile(r"(?<=\s)m[iıuü](?:yim|yım|yum|yüm|sin|sın|sun|sün|yiz|yız|yuz|yüz|siniz|sınız|sunuz|sünüz|dir|dır|dur|dür)?\.(?=\s|$)"),
     "Soru ekinden sonra nokta kullanılmış", "Soru işareti (?) kullanın"),
]
# Bu kelimeler ikileme olamaz: "bu bu", "ve ve" kesin hatadır.
IKILEME_OLMAZ = frozenset("bu şu ve veya ile için gibi ama fakat ancak ki de da en".split())
# Bu sözlerle başlayan kısa alt yazılar cümle sayılmaz (nokta aranmaz)
ALT_YAZI_RE = re.compile(r"^(?:Şekil|Tablo|Resim|Grafik|Harita|Kaynak|Görsel|Fotoğraf|Ünite|Bölüm|Konu)\b", re.I)
# Hem özel isim hem sıradan kelime olabilenler: "gitti Deniz" iki cümle sayılmaz
ISIM_OLABILEN = frozenset("""deniz güneş dünya ay doğu batı kuzey güney aydın umut ümit sevgi yıldız gül çiçek ırmak kaya
    demir aslan arslan şahin tan bahar yaz nur can barış savaş onur başak ceren ela pınar özlem derya sibel gökhan
    yavuz bulut toprak çınar ocak şubat mart nisan mayıs haziran temmuz ağustos eylül ekim kasım aralık pazartesi salı
    çarşamba perşembe cuma cumartesi pazar cumhuriyet meclis devlet hanım bey efendi paşa sultan kaptan doktor bakan
    başbakan başkomutan harbiye gazi profesör öğretmen millî milli ulusal genel""".split())


def ikileme_olabilir(kucuk, sozluk) -> bool:
    """bol bol, koşa koşa, meraklı meraklı doğrudur; "okula okula" gibi hâl ekli isim tekrarı değildir."""
    if kucuk in IKILEME_OLMAZ:
        return False
    return not all(re.search(r":(?:Dat|Loc|Abl|Acc|Gen)\b", c[3]) for c in sozluk.cozumler(kucuk))


def harf_harf_yazilmis(metin: str) -> bool:
    """Harita etiketi gibi harfleri aralıklı yazılmış metin: "K U Z E Y ( A R K T İ K )"."""
    parcalar = metin.split()
    return len(parcalar) >= 6 and sum(len(p) == 1 for p in parcalar) * 2 > len(parcalar)


def noktalama_bul(sayfa, par_no, metin, sozluk) -> list[Bulgu]:
    if harf_harf_yazilmis(metin):
        return []
    bulgular = []
    # Boş parantez "(  )" noktalama alıştırmasıdır, hata değildir.
    tarama = re.sub(r"\(\s*\)", lambda m: "§" * len(m.group()), adresleri_ort(metin))

    def ekle(kelime, aciklama, oneri, bas, son):
        bulgular.append(Bulgu(sayfa, par_no, "NOKTALAMA", kelime, aciklama, oneri, baglam_al(metin, bas, son)))

    for kural, aciklama, oneri in KURALLAR:
        for m in kural.finditer(tarama):
            ekle(m.group().strip() or "(boşluk)", aciklama, oneri, m.start(), m.end())

    # Açılıp kapanmayan parantez ve tırnak ("a)" gibi madde işaretleri yüzünden yalnızca açık kalan aranır)
    if tarama.count("(") + tarama.count("[") > tarama.count(")") + tarama.count("]"):   # (4,5] aralığı hata değil
        bas = tarama.rfind("(")
        ekle("(", "Açılan parantez kapatılmamış", "Parantezi kapatın", bas, bas + 1)
    # Birden çok paragraflık alıntı “… ile başlayıp …” ile biter; paragrafın başı ya da sonu tırnaksa hata sayılmaz.
    if sum(tarama.count(t) for t in '"“”') % 2 and not re.match(r'^\W*[“"]', tarama) and not re.search(r'[”"]\W*$', tarama):
        bas = max(tarama.rfind('"'), tarama.rfind("“"), tarama.rfind("”"))
        ekle(metin[bas], "Tırnak işareti açılmış ama kapatılmamış (ya da tersi)", "Tırnağı tamamlayın", bas, bas + 1)

    # Cümle sonunda nokta yok. Yalnızca son cümle yüklemle bitiyorsa bildirilir: başlık, alt yazı, imza
    # ("Mehmet Âkif Ersoy") ve sayfa düzeni yüzünden kesilmiş cümleler ("sınır çizgisi") hata sayılmaz.
    son_cumle = KELIME_RE.findall(re.split(r"[.!?…]\s", tarama)[-1])
    buyuk = sum(1 for k in son_cumle if k[0].isupper())
    if (len(son_cumle) >= 6 and buyuk * 2 < len(son_cumle) and metin[-1].isalnum() and not ALT_YAZI_RE.match(metin)
            and sozluk.yuklem_olabilir_mi(tr_kucuk(son_cumle[-1]))):
        ekle(son_cumle[-1], "Cümle sonunda noktalama işareti yok", "Cümlenin sonuna nokta koyun",
             len(metin) - len(son_cumle[-1]), len(metin))

    if metin.endswith(",") and len(son_cumle) >= 4 and sozluk.yuklem_olabilir_mi(tr_kucuk(son_cumle[-1])):
        ekle(",", "Cümle virgülle bitmiş", "Virgül yerine nokta koyun", len(metin) - 1, len(metin))

    # İki cümle arasında unutulan nokta: yüklemden sonra büyük harfle yeni cümle başlıyor (gitti Sonra)
    for m in re.finditer(rf"(?<![{HARFLER}])([{KUCUK_HARF}]{{3,}}) ([{BUYUK_HARF}][{KUCUK_HARF}]+)(?![{HARFLER}'’])", tarama):
        onceki, sonraki = m.group(1), tr_kucuk(m.group(2))
        if (not re.match(rf"[ ]+[{BUYUK_HARF}]", tarama[m.end():])       # Küçük Bey: çok kelimeli ad
                and sozluk.yuklem_olabilir_mi(onceki) and sozluk.gecerli_mi(sonraki)
                and sonraki not in ISIM_OLABILEN and not sozluk.ozel_isim_okunusu_var_mi(sonraki)):
            ekle(onceki, "İki cümle arasında nokta eksik", "Yüklemden sonra nokta koyun", m.start(), m.end())

    # Arka arkaya tekrar eden kelime: "bu bu", "ve ve"
    kelimeler = list(KELIME_RE.finditer(tarama))
    for onceki, simdiki in zip(kelimeler, kelimeler[1:]):
        if (tr_kucuk(onceki.group()) == tr_kucuk(simdiki.group()) and len(onceki.group()) > 1
                and metin[onceki.end():simdiki.start()].strip() == ""
                and not ikileme_olabilir(tr_kucuk(onceki.group()), sozluk)):
            ekle(f"{onceki.group()} {simdiki.group()}", "Kelime art arda tekrarlanmış", "Birini silin",
                 onceki.start(), simdiki.end())
    return bulgular
