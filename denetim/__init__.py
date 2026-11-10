"""
Ders Kitaplarında İçerik ve Tutarlılık Hatalarının Otomatik Tespiti

Modüller:
    metin.py         Türkçe harf ve kelime yardımcıları
    pdf.py           PDF'ten ve metinden paragraf çıkarma
    sozluk.py        Zemberek + Hunspell sözlükleri ve kelime listeleri
    tdk.py           TDK sözlük istemcisi (önbellekli)
    kelime.py        Kriter 1 ve 2: argo ve yazım
    buyuk_kucuk.py   Büyük / küçük harf hataları
    noktalama.py     Kriter 3: noktalama ve tekrar
    ozel_isim.py     Özel isimleri ayırma
    rapor.py         Bulgu kaydı, CSV ve HTML rapor
    denetleyici.py   Hepsini birleştiren Denetleyici sınıfı
"""

from .denetleyici import Denetleyici, Sonuc
from .rapor import Bulgu, csv_yaz, html_yaz

__all__ = ["Denetleyici", "Sonuc", "Bulgu", "csv_yaz", "html_yaz"]
