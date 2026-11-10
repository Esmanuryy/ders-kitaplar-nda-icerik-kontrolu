"""
Türkçe metin yardımcıları: harf dönüşümleri, kelime bulma ve kelimenin cümledeki yeri.
Diğer bütün modüller bunları kullanır.
"""

import re

HARFLER = "A-Za-zÇĞİÖŞÜçğıöşüÂâÎîÛû"
KUCUK_HARF = "a-zçğıöşü"
BUYUK_HARF = "A-ZÇĞİÖŞÜ"
TR_ALFABE = "abcçdefgğhıijklmnoöprsştuüvyz"

# Bir kelime ve varsa kesme işaretinden sonra gelen eki: Ankara'da, PDF’den
KELIME_RE = re.compile(rf"[{HARFLER}]+(?:['’][{HARFLER}]+)?")
# Bilerek uzatılmış söyleyiş: İnanılmaaaaaz, çooook
UZATMA_RE = re.compile(rf"([{HARFLER}])\1\1")
# İnternet, e-posta adresleri ve dosya adları kelime kelime denetlenmez.
ADRES_RE = re.compile(
    r"(?:https?://\s*|www\.)\S+"
    r"|[\w.+-]+@[\w-]+(?:\.[\w-]+)+"
    r"|\b[\w-]+(?:\.[\w-]+)*\.(?:com|net|org|edu|gov|tr|jpe?g|png|pdf|docx?|xlsx?|txt|html?)\b(?:/\S*)?"
    r"|\bwww\s+\w+(?:\s+\w+){1,3}?\s+(?:tr|com|org|net)\b")
# Kod ve formül satırları Türkçe cümle değildir.
KOD_RE = re.compile(r"[{}]|=>|==|\(\)|^\s*//|\)\s*;\s*$|\bconst\b")
# Kaynakça satırı: "ZORLUTUNA, H. N. (2010). Benim Küçük Dostlarım..."
KAYNAKCA_RE = re.compile(r"\(\d{4}[a-z]?\)\.|\bs\. \d+|\bpp?\. \d+|\bdoi\b|https?://", re.I)
ROMA_RAKAMI_RE = re.compile(r"^[IVXLCDM]+$")

# Noktadan sonra küçük harf gelmesi normal olan kısaltmalar
KISALTMALAR = frozenset("""vb vs vd bkz örn ör sf s no dr prof doç yy mö ms mah cad sok tel yak krş bk çev hz sn dk ed
    yay bs ss md fak müh uzm yrd öğr arş""".split())
# Ölçü birimleri: sözlükte yoktur ama yazım hatası değildir
BIRIMLER = frozenset("km cm mm kg mg ml lt kcal cal kwh mw kw mhz ghz gb mb kb tb ha da".split())


def tr_kucuk(s: str) -> str:
    """'I'.lower() Türkçede 'i' verir ama doğrusu 'ı'. Bunu düzeltir."""
    return s.replace("İ", "i").replace("I", "ı").lower()


def tr_buyuk(s: str) -> str:
    return s.replace("i", "İ").replace("ı", "I").upper()


def tr_buyuk_ilk(s: str) -> str:
    """İlk harfi Türkçe kurallarıyla büyütür: istanbul -> İstanbul, ışık -> Işık."""
    if not s:
        return s
    return {"i": "İ", "ı": "I"}.get(s[0], s[0].upper()) + s[1:]


def adresleri_ort(metin: str) -> str:
    """Adresleri aynı uzunlukta işaretle örter; böylece bulunan hataların konumu (bağlam) bozulmaz."""
    return ADRES_RE.sub(lambda m: "§" * len(m.group()), metin)


def kelime_govdesi(ham: str) -> str:
    """Kesme işaretli kelimenin gövdesi: Ankara'da -> Ankara"""
    return re.split(r"['’]", ham)[0]


def baglam_al(metin: str, bas: int, son: int, pay: int = 40) -> str:
    """Hatalı kelimenin çevresindeki metin (rapor ve sitede gösterilir)."""
    a, b = max(0, bas - pay), min(len(metin), son + pay)
    return ("…" if a > 0 else "") + metin[a:b].strip() + ("…" if b < len(metin) else "")


def kelime_parcasi(metin: str, m) -> bool:
    """Tek başına kelime olmayan parçalar: CO2, 1923te, 0'dan, P(A)'yı, "Rafadan Tayfa"nın, -mış,
    Korku-suz-luk, aylik_ucret, café."""
    bas, son = m.start(), m.end()
    if bas > 0 and (metin[bas - 1] in "-_" or metin[bas - 1].isalpha()):
        return True
    if son < len(metin) and (metin[son] == "_" or metin[son].isalpha()):
        return True
    if bas >= 2 and metin[bas - 1] in "'’\"”" and (metin[bas - 2].isalnum() or metin[bas - 2] in ")]%"):
        return True
    return (bas > 0 and metin[bas - 1].isdigit()) or (son < len(metin) and metin[son].isdigit())


def cumle_basi_mi(metin: str, konum: int) -> bool:
    """Kelime cümlenin ilk kelimesi mi? (paragraf başı, . ! ? : sonrası, madde işareti ya da tırnak açılışı)"""
    return re.search(r"(^[\W\d]*|^[a-zA-Z][.)]\s+|[.!?:…/][\"”’')\]]*\s+[\"“‘'(\[]*)$", metin[:konum]) is not None
