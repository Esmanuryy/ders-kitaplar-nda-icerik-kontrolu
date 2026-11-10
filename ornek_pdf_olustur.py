"""
Sunum ve deneme için içinde bilerek hata bırakılmış iki sayfalık bir PDF üretir: ornek_kitap.pdf

    py -3.12 ornek_pdf_olustur.py
"""

from pathlib import Path

import pymupdf

YAZI_TIPI = "C:/Windows/Fonts/arial.ttf"   # Türkçe karakterli bir yazı tipi (Mac/Linux'ta yolunu değiştirin)

SAYFALAR = [
    ("1. ÜNİTE: OKUMA KÜLTÜRÜ", [
        "Kitap okumak insanın hayal dünyasını geliştirir. Herşey kitaplarla başlar ve guzel alışkanlıklar kazandırır.",
        "Biz Ankarada yaşıyoruz.Her hafta kütüphaneye gidip bir kaç kitap alıyoruz. Kütüphanede sessiz olmak önemlidir.",
        "Öğretmenimiz dün bize bir hikâye okudu ve herkez dikkatle dinledi. Hikâyede Ali'nin salak bir şaka yaptığı anlatılıyordu.",
        "Sınıfımızda kalem,silgi, ve defter her zaman hazır bulunur.. Bu kuralı hepimiz biliyoruz.",
    ]),
    ("2. ÜNİTE: TARİHİMİZ", [
        "Mustafa Kemal Atatürk 19 Mayıs 1919'da Samsun'a çıktı. Kurtuluş Savaşı 1923te sona erdi.",
        "Bu konuyu anladın mı. Öğrenciler ödevlerini dikkatle yazdılar Sonra öğretmenlerine teslim ettiler.",
        "Newton'un yasaları fizik dersinde, Pisagor bağıntısı ise matematik dersinde öğretilir. Pisagor eski bir matematikçidir.",
        "Kitabın yeni baskısı (2024 yılında yayımlandı önemli değişiklikler içeriyor.",
    ]),
]


def olustur(yol: Path):
    belge = pymupdf.open()
    for baslik, paragraflar in SAYFALAR:
        sayfa = belge.new_page()
        sayfa.insert_font(fontname="tr", fontfile=YAZI_TIPI)
        sayfa.insert_text((50, 70), baslik, fontname="tr", fontsize=15)
        y = 105
        for p in paragraflar:
            kutu = pymupdf.Rect(50, y, 545, y + 90)
            sayfa.insert_textbox(kutu, p, fontname="tr", fontsize=11.5)
            y += 75
    belge.save(yol)


if __name__ == "__main__":
    hedef = Path(__file__).parent / "ornek_kitap.pdf"
    olustur(hedef)
    print(f"Oluşturuldu: {hedef}")
