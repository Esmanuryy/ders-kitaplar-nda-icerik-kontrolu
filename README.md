# Ders Kitabı Denetleyici

Ders kitaplarında içerik ve tutarlılık hatalarının otomatik tespiti. Yazılım Geliştirme I dersi dönem projesi.

PDF formatındaki bir ders kitabını okur. Argo ifadeleri, yazım hatalarını ve noktalama hatalarını sayfa numarası, açıklama ve düzeltme önerisiyle listeler.

## Neleri bulur?

| Kriter | Nasıl bakılır | Örnek |
|---|---|---|
| **Argo / uygunsuz ifade** | TDK Güncel Türkçe Sözlük'teki "argo" ve "kaba" etiketleri, argo listesi | salak, kanka |
| **Yazım** | Hunspell Türkçe sözlüğü, Zemberek, TDK, sık yapılan yanlışlar listesi | guzel → güzel, herkez → herkes, yanlız → yalnız |
| **Büyük/küçük harf, kesme işareti** | Yazım kuralları | ankarada → Ankara'da, okul'da → okulda |
| **Noktalama** | TDK Yazım Kılavuzu'na dayalı kurallar | gitti.Sonra, kalem ,silgi, anladın mı. |

- Her kelime tek tek taranır. Anlamına bakılmaz; kelimenin yazılışına ve sözlük kaydına bakılır.
- Özel isimler (Newton, Ankara, Dr. Gülbike YILDIRIM) ayrılır, hata sayılmaz ve ayrı listelenir.
- Aynı hata kitapta defalarca geçse de bir kez listelenir; kaç kez ve hangi sayfalarda geçtiği yazılır.

## Kurulum

Python 3.12 gerekir (Zemberek yeni Python sürümleriyle uyumsuzdur).

```
py -3.12 -m pip install -r requirements.txt
```

## Kullanım

**Web sitesi:** `Siteyi Ac.bat` dosyasına (ya da masaüstündeki kısayola) çift tıklayın. Site açılır ve tarayıcıda kendiliğinden gösterilir. Kapatmak için siyah pencereyi kapatın.

Komut satırından açmak için:
```
py -3.12 app.py
```
Adres: `http://127.0.0.1:5000`

**Komut satırı:**
```
py -3.12 denetle.py kitap.pdf                 # TDK ile
py -3.12 denetle.py kitap.pdf --cevrimdisi    # TDK'ye bağlanmadan
```
Çıktı: `rapor.csv` ve `rapor.html`

**Örnek PDF:** `ornek_kitap.pdf` içinde bilerek bırakılmış hatalar var. Yeniden üretmek için: `py -3.12 ornek_pdf_olustur.py`

## Proje yapısı

```
app.py                  Web sitesi (Flask)
denetle.py              Komut satırı
denetim/                Denetim kodu
  denetleyici.py          Hepsini birleştiren Denetleyici sınıfı
  pdf.py                  PDF'ten paragraf çıkarma (bozuk harf, sütun, tireleme düzeltmeleri)
  kelime.py               Argo ve yazım denetimi
  buyuk_kucuk.py          Büyük / küçük harf hataları
  noktalama.py            Noktalama ve tekrar kuralları
  ozel_isim.py            Özel isimleri ayırma
  sozluk.py               Zemberek ve Hunspell
  tdk.py                  TDK sözlük istemcisi (önbellekli)
  metin.py                Türkçe harf ve kelime yardımcıları
  rapor.py                Bulgu kaydı, CSV ve HTML rapor
veri/                   Kelime listeleri
  argo_listesi.txt        Argo ve uygunsuz kelimeler
  yaygin_yanlislar.txt    Sık yapılan yazım yanlışları (yanlış=doğru)
  ozel_isimler.txt        Büyük harfle başlaması gereken özel isimler
  izinli_kelimeler.txt    Sözlükte olmayan ama doğru kelimeler
sozluk/                 Türkçe Hunspell sözlüğü
templates/, static/     Sitenin sayfası, görünümü ve davranışı
testler/                Otomatik testler
```

## Testler

```
py -3.12 -m unittest discover -s testler -v
```
Hatalı cümlelerde hatanın bulunduğunu, doğru cümlelerde yanlış alarm çıkmadığını ve PDF okumanın doğru çalıştığını kontrol eder.

## Bilinen sınırlar

- Her kelime kendi başına denetlenir; kelimeler birleştirilip anlam aranmaz. Bu yüzden anlam gerektiren hatalar ("bende geldim", "bir kaç" yerine "birkaç") bulunamaz.
- Fazladan boşluklar hata sayılmaz.
- Sözlükte olmayan terimler ve eski kelimeler ("yakantop", "gulam") yazım hatası olarak işaretlenebilir. TDK açıkken bu durum azalır. Doğru olduğu bilinen kelimeler `veri/izinli_kelimeler.txt` dosyasına eklenebilir.
- Metni PDF'ten bozuk çıkan paragraflar denetlenmez; site bu sayfaları ayrıca bildirir.
- Taranmış (resim) PDF'ler okunamaz; önce OCR gerekir.
- TDK sitesi yoğun istekte cevap vermeyebilir. Cevaplar `veri/tdk_onbellek.json` dosyasına kaydedilir; aynı kitabın ikinci taraması çok daha hızlıdır.

## Kaynaklar

- Türkçe Hunspell sözlüğü: [tdd-ai/hunspell-tr](https://github.com/tdd-ai/hunspell-tr) (MPL-2.0, `sozluk/LICENSE`)
- Argo listesinin bir bölümü: [ooguz/turkce-kufur-karaliste](https://github.com/ooguz/turkce-kufur-karaliste) (CC BY-SA 4.0)
- Zemberek (zemberek-python), PyMuPDF, spylls, Flask, TDK sözlük servisi (sozluk.gov.tr)

## Geliştirici

Esmanur Yılmaz - 24130781
