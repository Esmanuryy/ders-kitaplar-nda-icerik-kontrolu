# Ders Kitaplarında İçerik ve Tutarlılık Hatalarının Otomatik Tespiti

Yazılım Geliştirme I dersi dönem projesi.

PDF formatındaki ders kitaplarından metin çıkarır ve üç kritere göre olası hataları bulur.
Bulunan her hata için sayfa ve paragraf numarası gösterilir.

## Kriterler
1. **Argo / uygunsuz ifade:** TDK Güncel Türkçe Sözlük'teki "argo/kaba" etiketi ve `argo_listesi.txt`
2. **Yazım hatası:** TDK Sözlük, TDK Yazım Kılavuzu, Zemberek, `yaygin_yanlislar.txt` ve büyük/küçük harf kuralları (cümle başı, özel isimler, kelime ortasında büyük harf)
3. **Noktalama / tekrar:** TDK Yazım Kılavuzu kurallarına dayalı kural tabanlı denetim

Her kelime tek tek taranır; anlamına bakılmaz, yazılışı ve sözlük kaydı incelenir. Özel isimler ayrılır ve yazım hatası sayılmaz (`Newton'un`, `Ankara`, metinde tekrar eden `Pisagor`); listeleri site ve HTML raporda gösterilir. Kod ve formül satırları denetlenmez.

## Kurulum
Python 3.12 gerekir (Zemberek yeni Python sürümleriyle uyumsuzdur).

```
py -3.12 -m pip install -r requirements.txt
```

## Web sitesi (arayüz)
En kolay yol: `Siteyi Ac.bat` dosyasına (ya da masaüstündeki kısayola) çift tıkla. Site başlar ve tarayıcıda kendiliğinden açılır; kapatmak için açılan siyah pencereyi kapat.

Komut satırından açmak için:
```
py -3.12 app.py
```
Sonra tarayıcıda `http://127.0.0.1:5000` adresini aç. PDF yükle veya metin yapıştır, sonuçları filtrele, CSV/HTML olarak indir. Uygulama PDF dosyaları için sabit bir boyut sınırı koymaz; sunucu, disk alanı veya bağlantı kısıtları yine geçerli olabilir.

## Komut satırı kullanımı
```
py -3.12 ornek_pdf_olustur.py          # deneme PDF'i üretir (isteğe bağlı)
py -3.12 denetleyici.py ornek.pdf      # denetler
py -3.12 denetleyici.py kitap.pdf --cevrimdisi   # TDK'siz çalıştırır
```
Çıktı: `rapor.csv` ve `rapor.html`

## Dosyalar
| Dosya | Açıklama |
|---|---|
| `denetleyici.py` | Ana program |
| `app.py` | Web sitesi sunucusu (Flask) |
| `templates/index.html` | Web sitesinin sayfası |
| `tdk.py` | TDK sözlük servisi istemcisi (önbellek ve hata yönetimiyle) |
| `argo_listesi.txt` | Argo ve uygunsuz kelime listesi |
| `yaygin_yanlislar.txt` | Sık yapılan yazım hataları |
| `sozluk/` | Türkçe Hunspell sözlüğü (yazım denetiminin ana kaynağı) |
| `izinli_kelimeler.txt` | Sözlükte olmayan ama doğru kelimeler (hata sayılmaz) |
| `ozel_isimler.txt` | Büyük harfle başlaması gereken özel isimler (ankara → Ankara) |
| `ornek_pdf_olustur.py` | Hatalı örnek PDF üretir |
| `Siteyi Ac.bat` | Çift tıklayınca siteyi başlatıp tarayıcıda açar |

## Durum
- [x] PDF'ten metin çıkarma, üç kriter, rapor çıktısı
- [x] TDK modülü (ilk sürüm)
- [ ] TDK verisinin gerçek verilerle doğrulanması
- [x] Web arayüzü (ilk sürüm)

## Geliştirici
Esmanur Yılmaz - 24130781
