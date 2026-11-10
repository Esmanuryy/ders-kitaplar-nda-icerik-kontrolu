"""
Kriter 3: Noktalama ve tekrar. TDK Yazım Kılavuzu'ndaki noktalama kurallarına dayalı, kural tabanlı denetim.
Her bulguda kuralın kısa açıklaması ve hatalı yerin düzeltilmiş hâli ("Doğrusu") verilir.
Fazladan boşluklar (PDF'te sayfa düzeninden de oluşabildiği için) hata sayılmaz.
"""

import re

from .metin import BUYUK_HARF, HARFLER, KELIME_RE, KUCUK_HARF, adresleri_ort, baglam_al, tr_kucuk
from .rapor import Bulgu

H = "A-Za-zÇĞİÖŞÜçğıöşüÂâÎîÛû"

# (kural, açıklama, düzeltme). Düzeltme, eşleşen parçanın doğru yazılışını verir.
KURALLAR = [
    (re.compile(rf"(?:(?<=[{H}]{{2}})|(?<=[{H}] )),(?=[{H}])|[;!?](?=[{H}])|(?<![\d\s]):(?=[{H}])"),
     "Virgül, noktalı virgül, iki nokta, soru ve ünlem işaretinden sonra bir boşluk bırakılır.",
     lambda s: s + " "),
    (re.compile(r"(?<=[a-zçğıöşü]{2})(?<!vb)(?<!vs)(?<!Prof)(?<!Doç)(?<!Yrd)(?<!Öğr)(?<!Arş)(?<!Uzm)\.(?=[A-ZÇĞİÖŞÜ]"
                r"|(?!(?:pdf|docx?|txt|html?|py|jpe?g|png|xlsx?|js|json|css|ts|java|cpp|xml|sql)\b)(?![a-zçğıöşü]+\()[a-zçğıöşü]{2})"),
     "Cümle sonundaki noktadan sonra bir boşluk bırakılır.",
     lambda s: ". "),
    (re.compile(r"(?<![.!?…])\.\.(?![.…])"),
     "İki nokta yan yana kullanılmaz. Ya tek nokta ya da üç nokta (…) kullanılır.",
     lambda s: "."),
    (re.compile(r"(?<!\.)\.{4}(?!\.)(?!\s*\d)"),
     "Üç noktadan fazla nokta kullanılmaz.",
     lambda s: "..."),
    (re.compile(r"[,;:][,;:.]"),
     "İki noktalama işareti yan yana kullanılmış; biri fazladır.",
     lambda s: s[-1] if s[-1] == "." else s[0]),
    (re.compile(r"!{2,}|\?{2,}"),
     "Ders kitabı dilinde ünlem ya da soru işareti tek kullanılır.",
     lambda s: s[0]),
    (re.compile(rf"(?<=[{H}]{{4}})\((?=[^)]*\s)"),
     "Açılan parantezden önce bir boşluk bırakılır.",
     lambda s: " ("),
    (re.compile(r"\)(?=[a-zçğıöşü]{3,})"),
     "Kapanan parantezden sonra bir boşluk bırakılır.",
     lambda s: ") "),
    (re.compile(r",(?=\s+(?:ve|veya)\b(?!\s*,))"),
     "\"ve\" ile \"veya\" bağlaçlarından önce virgül konmaz.",
     lambda s: ""),
    (re.compile(r"\b(\d+)(?=(?:lar|ler|da|de|ta|te|dan|den|tan|ten|ya|ye|yı|yi|yu|yü|nın|nin|nun|nün|ın|in|un|ün)\b)"),
     "Rakamla yazılan sayılara gelen ekler kesme işaretiyle ayrılır (1923'te, 1980'ler).",
     lambda s: s + "'"),
    (re.compile(r"(?<=\s)(?:m[iıuü](?:yim|yım|yum|yüm|sin|sın|sun|sün|yiz|yız|yuz|yüz|siniz|sınız|sunuz|sünüz|dir|dır|dur|dür)?)\.(?=\s|$)"),
     "Soru eki (mı, mi, mu, mü) içeren soru cümlesinin sonuna soru işareti konur.",
     lambda s: s[:-1] + "?"),
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


def cevre(metin: str, bas: int, son: int, ortasi: str) -> str:
    """Hatalı yeri, bitişik olduğu kelimelerle birlikte verir: yaşıyoruz.Sonra / silgi, ve"""
    sol = re.search(r"\S*$", metin[:bas]).group() or re.search(r"(?:\S*\s)?$", metin[:bas]).group()
    sag = re.match(r"\S*", metin[son:]).group() or re.match(r"(?:\s\S*)?", metin[son:]).group()
    return (sol[-30:] + ortasi + sag[:30]).strip()


def dogrusu(metin: str, bas: int, son: int, yeni: str) -> str:
    """Düzeltilmiş hâli: «yaşıyoruz. Sonra»"""
    return f"«{cevre(metin, bas, son, yeni)}»"


def noktalama_bul(sayfa, par_no, metin, sozluk) -> list[Bulgu]:
    if harf_harf_yazilmis(metin):
        return []
    bulgular = []
    # Boş parantez "(  )" noktalama alıştırmasıdır, hata değildir.
    tarama = re.sub(r"\(\s*\)", lambda m: "§" * len(m.group()), adresleri_ort(metin))

    def ekle(kelime, aciklama, oneri, bas, son):
        bulgular.append(Bulgu(sayfa, par_no, "NOKTALAMA", kelime, aciklama, oneri, baglam_al(metin, bas, son)))

    for kural, aciklama, duzelt in KURALLAR:
        for m in kural.finditer(tarama):
            ekle(cevre(metin, m.start(), m.end(), m.group()), aciklama,
                 "Doğrusu: " + dogrusu(metin, m.start(), m.end(), duzelt(m.group())), m.start(), m.end())

    # Açılıp kapanmayan parantez ve tırnak ("a)" gibi madde işaretleri yüzünden yalnızca açık kalan aranır)
    if tarama.count("(") + tarama.count("[") > tarama.count(")") + tarama.count("]"):   # (4,5] aralığı hata değil
        bas = tarama.rfind("(")
        ekle("(", "Açılan parantez kapatılmamış. Her açılan parantez kapatılmalıdır.",
             "Parantezin içindeki ifade bittiği yere ) koyun.", bas, bas + 1)
    # Birden çok paragraflık alıntı “… ile başlayıp …” ile biter; paragrafın başı ya da sonu tırnaksa hata sayılmaz.
    if (sum(tarama.count(t) for t in '"“”') % 2 and not re.match(r'^\W*[“"]', tarama)
            and not re.search(r'[”"]\W*$', tarama)):
        bas = max(tarama.rfind('"'), tarama.rfind("“"), tarama.rfind("”"))
        ekle(metin[bas], "Tırnak işareti açılmış ama kapatılmamış (ya da kapatılmış ama açılmamış).",
             "Alıntının başına ve sonuna tırnak koyun.", bas, bas + 1)

    # Cümle sonunda nokta yok. Yalnızca son cümle yüklemle bitiyorsa bildirilir: başlık, alt yazı, imza
    # ("Mehmet Âkif Ersoy") ve sayfa düzeni yüzünden kesilmiş cümleler ("sınır çizgisi") hata sayılmaz.
    son_cumle = KELIME_RE.findall(re.split(r"[.!?…]\s", tarama)[-1])
    buyuk = sum(1 for k in son_cumle if k[0].isupper())
    if (len(son_cumle) >= 6 and buyuk * 2 < len(son_cumle) and metin[-1].isalnum() and not ALT_YAZI_RE.match(metin)
            and sozluk.yuklem_olabilir_mi(tr_kucuk(son_cumle[-1]))):
        ekle(son_cumle[-1], "Cümle bitmiş ama sonuna nokta konmamış. Tamamlanmış cümlenin sonuna nokta konur.",
             "Doğrusu: " + dogrusu(metin, len(metin), len(metin), "."), len(metin) - len(son_cumle[-1]), len(metin))

    if metin.endswith(",") and len(son_cumle) >= 4 and sozluk.yuklem_olabilir_mi(tr_kucuk(son_cumle[-1])):
        ekle(son_cumle[-1] + ",", "Cümle virgülle bitmiş. Tamamlanmış cümlenin sonuna nokta konur.",
             "Doğrusu: " + dogrusu(metin, len(metin) - 1, len(metin), "."), len(metin) - 1, len(metin))

    # İki cümle arasında unutulan nokta: yüklemden sonra büyük harfle yeni cümle başlıyor (gitti Sonra)
    for m in re.finditer(rf"(?<![{HARFLER}])([{KUCUK_HARF}]{{3,}}) ([{BUYUK_HARF}][{KUCUK_HARF}]+)(?![{HARFLER}'’])", tarama):
        onceki, sonraki = m.group(1), tr_kucuk(m.group(2))
        if (not re.match(rf"[ ]+[{BUYUK_HARF}]", tarama[m.end():])       # Küçük Bey: çok kelimeli ad
                and sozluk.yuklem_olabilir_mi(onceki) and sozluk.gecerli_mi(sonraki)
                and sonraki not in ISIM_OLABILEN and not sozluk.ozel_isim_okunusu_var_mi(sonraki)):
            ekle(m.group(), "Bir cümle bitip yenisi başlamış ama araya nokta konmamış.",
                 f"Doğrusu: «{m.group(1)}. {m.group(2)}»", m.start(), m.end())

    # Arka arkaya tekrar eden kelime: "bu bu", "ve ve"
    kelimeler = list(KELIME_RE.finditer(tarama))
    for onceki, simdiki in zip(kelimeler, kelimeler[1:]):
        if (tr_kucuk(onceki.group()) == tr_kucuk(simdiki.group()) and len(onceki.group()) > 1
                and metin[onceki.end():simdiki.start()].strip() == ""
                and not ikileme_olabilir(tr_kucuk(onceki.group()), sozluk)):
            ekle(f"{onceki.group()} {simdiki.group()}", "Aynı kelime yanlışlıkla iki kez yazılmış.",
                 f"Doğrusu: «{onceki.group()}»", onceki.start(), simdiki.end())
    return bulgular
