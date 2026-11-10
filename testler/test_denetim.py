"""
Otomatik testler. Çalıştırma (proje klasöründe):

    py -3.12 -m unittest discover -s testler -v

Hatalı cümlelerdeki hataların bulunduğunu, doğru cümlelerde yanlış alarm çıkmadığını ve PDF okumanın
doğru çalıştığını kontrol eder. TDK'ye bağlanmaz.
"""

import sys
import tempfile
import unittest
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pymupdf  # noqa: E402

from denetim import Denetleyici  # noqa: E402
from denetim.pdf import pdf_paragraflari  # noqa: E402
from denetim.rapor import Bulgu, bulgulari_birlestir  # noqa: E402

D = None


def setUpModule():
    global D
    D = Denetleyici()                    # sözlükler bir kez yüklenir


def denetle(metin, tdk=None):
    return D.paragraf_denetle(1, 1, metin, tdk)


# (hatalı cümle, bulgunun içinde geçmesi gereken ifade)
HATALI = [
    ("Öğrenciler kitablarını okulda okudu.", "kitablarını"),
    ("Bu konu çok guzel anlatılmış.", "guzel"),
    ("Öğretmen dersde konuyu anlattı.", "dersde"),
    ("Çocuklar bahçede oynuyorlardı ve eğleniyolardı.", "eğleniyolardı"),
    ("Sınıfta öğrencilr sessizce oturdu.", "öğrencilr"),
    ("Yarın okula gelecekmisin diye sordu.", "gelecekmisin"),
    ("Bu cümle doğrumu acaba?", "doğrumu"),
    ("Herkez sınava hazırlandı.", "Herkez"),
    ("Sonra Öğrencilr sınıfa girdi.", "Öğrencilr"),
    ("BÖLÜM ÖZETİ VE YANLIZLIK", "YANLIZLIK"),
    ("KONU ANLATIMII", "ANLATIMII"),
    ("ahmet okula gitti.", "ahmet"),
    ("Dün mehmet bize geldi.", "mehmet"),
    ("Biz ankarada yaşıyoruz.", "ankarada"),
    ("Biz Ankarada yaşıyoruz.", "Ankarada"),
    ("Ali Türkiyede doğdu.", "Türkiyede"),
    ("Öğrenciler okul'da ders çalıştı.", "okul'da"),
    ("Savaş 1923te bitti.", "1923te"),
    ("Ders bitti.Sonra eve döndük.", ".S"),
    ("Kalem,silgi ve defter aldı.", ",s"),
    ("Kalem ,silgi aldı.", " ,"),
    ("Kalem, silgi, ve defter aldı.", ", ve"),
    ("Ders bitti..", ".."),
    ("Ders bitti....", "...."),
    ("Ne zaman geldin??", "??"),
    ("Bu konuyu anladın mı.", "mı."),
    ("Öğrenciler dün akşam kütüphanede uzun süre ders çalıştılar", "çalıştılar"),
    ("Öğrenciler ödevlerini yazdılar Bu konu çok önemlidir.", "yazdılar"),
    ("Kitap (yeni baskı önemli bir eserdir.", "("),
    ("Kitap( yeni baskı) önemli.", "( "),
    ("Kitap(yeni baskı) önemli.", "p("),
    ("Öğretmen \"Hoş geldiniz dedi.", '"'),
    ("Bu bu cümlede hata var.", "Bu bu"),
    ("Çocuk okula okula gitti.", "okula okula"),
    ("Bu konuda salak kişiler konuştu.", "salak"),
    ("Öğrenciler kanka gibi konuşmamalı.", "kanka"),
]

DOGRU = """Dünya'nın Güneş çevresindeki dönüşü bir yıl sürer. Ay ise Dünya'nın çevresinde döner.
Atatürk, 19 Mayıs 1919'da Samsun'a çıktı. Türkiye Cumhuriyeti 1923'te kuruldu.
Newton'un hareket yasaları fizik dersinde anlatılır. Isaac Newton bu yasaları yazmıştır.
Ahmet, Ayşe ve Mehmet okula birlikte gittiler. Öğretmenleri Deniz Hanım onları karşıladı.
Sonuç olarak 3,5 kg elma ve 2 km yol hesaplanır... Saat 10:30'da ders başlar.
Kitaba www.ornekkitap.com adresinden ulaşılabilir. Bilgi için ornek@ornekmail.com yazınız.
Yazar şöyle diyor: "Okumak insanı geliştirir." Bu cümle kitabın başındadır.
Aşağıdaki sorulardan hangisi doğrudur? Cevabınızı kısaca açıklayınız!
Ders Kitaplarında İçerik Denetimi
BÖLÜM 1: CANLILAR VE HAYAT
UNESCO ve NATO kısaltmaları büyük harfle yazılır. TDK'nin sözlüğünde pek çok kelime vardır.
Ankaralı öğrenciler Türkçe dersinde İngilizce kelimelerin yazımını öğrendi. Türkler Anadolu'ya geldi.
Prof. Dr. Ayşe Kaya bu konuda vb. pek çok örnek verdi. Karadeniz Bölgesi'nde yağış fazladır.
H2O suyun formülüdür. CO2 ise karbondioksittir. Bu bir x değişkenidir.
Geldi mi gelmedi mi belli değil, yine de bekledik. Sen de gel, ben de gelirim.
Bol bol pratik yap, yavaş yavaş ilerle ve koşa koşa gel. "Geldin mi?" diye sordu.
Milli Eğitim Bakanlığı kitapları ücretsiz dağıtmaktadır. Fransız İhtilali 1789'da oldu.
XIX. yüzyılda Osmanlıların ve Selçukluların tarihi incelendi. Bu, hükümet kararıdır.
Dr. Gülbike YILDIRIM ve Prof.Dr. Mutlu YILMAZ kitabı hazırladı. Kur'an ve şer'i hükümler anlatıldı.
Bu fonksiyon negatif olmayan bir sayı atar. Bir iple sallanabilirsiniz. Ama bu konu önemlidir.
Zekâ, yegâne ve şikâyet kelimeleri şapkalı yazılabilir. Konu  : Trafik kuralları
Fazladan  boşluklar hata sayılmaz . Kitap ( 2017 ) yılında basıldı.
Bir kaç kişi geldi ve hiç bir sorun çıkmadı. lhlamur ağacı çok güzel kokar.""".split("\n")


class SahteTDK:
    """TDK'nin argo etiketlerini taklit eder (testte internete bağlanılmaz)."""

    def __init__(self, argo):
        self.argo = set(argo)

    def sozluk(self, kelime):
        return {"var": True, "argo": kelime in self.argo, "argo_anlam": "argo anlam", "ilk_anlam": ""}

    def yazim_onerisi(self, kelime):
        return []


class HataBulma(unittest.TestCase):
    def test_hatali_cumleler(self):
        for metin, beklenen in HATALI:
            with self.subTest(metin=metin):
                bulgular = denetle(metin)
                self.assertTrue(any(beklenen.strip() in b.kelime or (beklenen in b.baglam and b.kriter == "NOKTALAMA")
                                    for b in bulgular), f"Bulunamadı: {beklenen!r} -> {[b.kelime for b in bulgular]}")

    def test_dogru_cumlelerde_yanlis_alarm_yok(self):
        for metin in DOGRU:
            with self.subTest(metin=metin):
                self.assertEqual([(b.kelime, b.aciklama) for b in denetle(metin)], [])

    def test_argo_tdk_etiketi(self):
        self.assertTrue(any(b.kriter == "ARGO" for b in denetle("Bu salak öğrenciler konuştu.", SahteTDK({"salak"}))))
        # "atar" TDK'de argo etiketli ama atmak fiilinin çekimi olarak da okunabilir: argo sayılmaz
        self.assertFalse(any(b.kriter == "ARGO" for b in denetle("Fonksiyon bir sayı atar.", SahteTDK({"atar"}))))
        self.assertFalse(any(b.kriter == "ARGO" for b in denetle("Bir iple oynadık.", SahteTDK({"iplemek"}))))


class PdfOkuma(unittest.TestCase):
    def test_tireleme_ve_liste(self):
        with tempfile.TemporaryDirectory() as klasor:
            yol = Path(klasor) / "deneme.pdf"
            belge = pymupdf.open()
            sayfa = belge.new_page()
            sayfa.insert_font(fontname="tr", fontfile="C:/Windows/Fonts/arial.ttf")
            y = 60
            for satir in ["Öğrenciler kita-", "plarını okudu ve çok sevindi.", "", "Kullanıcıdan veri almak",
                          "Veriyi işlemek"]:
                if satir:
                    sayfa.insert_text((50, y), satir, fontname="tr", fontsize=11)
                y += 15 if satir else 30
            belge.save(yol)
            belge.close()
            metinler = [p[2] for p in pdf_paragraflari(str(yol))]
        self.assertIn("Öğrenciler kitaplarını okudu ve çok sevindi.", metinler)
        self.assertIn("Veriyi işlemek", metinler)


class BolunmusKelime(unittest.TestCase):
    def test_tireyle_bolunen_kelime_birlesir(self):
        sonuc = D.metin_denetle("Öğrenciler kita-\nplarını okudu. Biz İzmir'\nde yaşıyoruz. Okuma-\nyazma öğrendik.", False)
        self.assertEqual([b.kelime for b in sonuc.bulgular], [])

    def test_sutunlardan_gelen_parcalar_ayri_kelime_kalir(self):
        self.assertEqual(D.bolunmus_kelimeleri_birlestir("eksiksiz konulkurallar başka"), "eksiksiz konul-kurallar başka")
        self.assertEqual(D.bolunmus_kelimeleri_birlestir("kitaplarını"), "kitaplarını")


class Birlestirme(unittest.TestCase):
    def test_ayni_kelime_tek_bulgu(self):
        b = [Bulgu(s, 1, "YAZIM", "guzel", "a", "güzel", "") for s in (3, 3, 7)]
        sonuc = bulgulari_birlestir(b)
        self.assertEqual(len(sonuc), 1)
        self.assertEqual((sonuc[0].adet, sonuc[0].sayfalar), (3, "3, 7"))


if __name__ == "__main__":
    unittest.main()
