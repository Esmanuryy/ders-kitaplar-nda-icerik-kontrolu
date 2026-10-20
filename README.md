# Ders Kitaplarında İçerik ve Tutarlılık Hatalarının Otomatik Tespiti

Yazılım Geliştirme I dersi dönem projesi.

PDF formatındaki ders kitaplarından metin çıkarır ve üç kritere göre olası hataları bulur.
Bulunan her hata için sayfa ve paragraf numarası gösterilir.

## Kriterler
1. **Argo / uygunsuz ifade:** TDK Güncel Türkçe Sözlük'teki "argo/kaba" etiketi ve `argo_listesi.txt`
2. **Yazım hatası:** TDK Sözlük, TDK Yazım Kılavuzu, Zemberek ve `yaygin_yanlislar.txt`
3. **Noktalama / tekrar:** TDK Yazım Kılavuzu kurallarına dayalı kural tabanlı denetim

## Kurulum
Python 3.12 gerekir (Zemberek yeni Python sürümleriyle uyumsuzdur).

```
py -3.12 -m pip install -r requirements.txt
```

## Kullanım
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
| `tdk.py` | TDK sözlük servisi istemcisi (önbellek ve hata yönetimiyle) |
| `argo_listesi.txt` | Argo ve uygunsuz kelime listesi |
| `yaygin_yanlislar.txt` | Sık yapılan yazım hataları |
| `ornek_pdf_olustur.py` | Hatalı örnek PDF üretir |

## Durum
- [x] PDF'ten metin çıkarma, üç kriter, rapor çıktısı
- [x] TDK modülü (ilk sürüm)
- [ ] TDK verisinin gerçek verilerle doğrulanması
- [ ] Arayüz

## Geliştirici
Esmanur Yılmaz - 24130721
