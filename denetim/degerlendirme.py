"""
Denetim sonucunun değerlendirmesi: kitabın hata oranı, kalite puanı ve kısa bir yorum.

Oran, programın bulduğu hataların denetlenen kelime sayısına bölünmesiyle bulunur. Program emin olmadığı yeri hata
saymadığı için gerçek hata sayısı biraz daha fazla olabilir; bu not değerlendirmede de yazılır.
"""

KRITER_ADLARI = {"ARGO": "argo / uygunsuz ifade", "YAZIM": "yazım", "NOKTALAMA": "noktalama"}

# 1000 kelimedeki hata sayısına göre seviyeler: (en fazla, kod, ad, yorum)
SEVIYELER = [
    (0.0, "temiz", "Hata bulunamadı", "Denetlenen bölümlerde argo, yazım ya da noktalama hatası bulunamadı."),
    (0.5, "cok_iyi", "Çok iyi", "Hata çok az. Kitap dil ve yazım bakımından büyük ölçüde temiz."),
    (2.0, "iyi", "İyi", "Az sayıda hata var. Listelenen yerler düzeltildiğinde kitap temiz olur."),
    (5.0, "orta", "Orta", "Hatalar dikkat çekecek kadar sık. Kitabın gözden geçirilmesi önerilir."),
    (float("inf"), "zayif", "Zayıf", "Hata sayısı yüksek. Kitabın baştan sona dil ve yazım denetiminden geçirilmesi gerekir."),
]


def binde(sayi: int, kelime: int) -> float:
    """1000 kelimedeki sayı."""
    return round(sayi * 1000 / kelime, 2) if kelime else 0.0


def degerlendir(sonuc) -> dict:
    """Sonuç için hata oranlarını, 100 üzerinden kalite puanını, seviyeyi ve yorumu verir."""
    kelime = sonuc.kelime_sayisi
    gecis = {k: 0 for k in KRITER_ADLARI}               # her hatanın kitapta kaç kez geçtiği sayılır
    for b in sonuc.bulgular:
        gecis[b.kriter] += b.adet
    toplam = sum(gecis.values())
    oran = binde(toplam, kelime)

    kod, ad, yorum = next((k, a, y) for sinir, k, a, y in SEVIYELER if oran <= sinir)
    # Puan: 1000 kelimede her hata 10 puan düşürür; ders kitabında hiç olmaması gereken argo ayrıca 10 puan düşürür.
    puan = max(0, round(100 - oran * 10 - gecis["ARGO"] * 10))
    uyarilar = []
    if gecis["ARGO"]:
        uyarilar.append(f"Kitapta {gecis['ARGO']} yerde argo ya da uygunsuz ifade var. Ders kitabında hiç olmamalı; "
                        "önce bunlar düzeltilmeli.")
        if kod in ("temiz", "cok_iyi", "iyi"):          # argo varsa değerlendirme en fazla "Orta" olur
            kod, ad = "orta", "Orta"
            yorum = "Hata az olsa da argo ifade bulunduğu için kitabın gözden geçirilmesi gerekir."
    if toplam:
        en_cok = max(gecis, key=gecis.get)
        uyarilar.append(f"En çok {KRITER_ADLARI[en_cok]} hatası var ({gecis[en_cok]} yerde).")

    return {
        "kelime": kelime,
        "sayfa": sonuc.sayfa_sayisi,
        "hata": toplam,                                  # hataların kitapta geçtiği toplam yer sayısı
        "farkli_hata": len(sonuc.bulgular),
        "binde": oran,                                   # 1000 kelimede hata
        "dogru_yuzde": round(100 - toplam * 100 / kelime, 2) if kelime else 100.0,
        "sayfa_basina": round(toplam / sonuc.sayfa_sayisi, 2) if sonuc.sayfa_sayisi else 0.0,
        "turler": {k: {"hata": v, "binde": binde(v, kelime)} for k, v in gecis.items()},
        "puan": puan,
        "seviye": kod,
        "seviye_adi": ad,
        "yorum": yorum,
        "uyarilar": uyarilar,
        "not": "Oran, programın bulduğu hatalara göre hesaplanır. Program emin olmadığı yeri hata saymaz ve "
               "atlanan etkinlik bölümleri hesaba katılmaz; gerçek hata sayısı biraz daha fazla olabilir.",
    }


def sayi_yaz(x, basamak=2) -> str:
    """Türkçe sayı yazımı: 42.310 / 0,45"""
    if isinstance(x, int) or float(x).is_integer():
        return f"{int(x):,}".replace(",", ".")
    return f"{x:,.{basamak}f}".replace(",", "X").replace(".", ",").replace("X", ".").rstrip("0").rstrip(",")
