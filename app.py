"""
Ders Kitabı Denetleyici - Web Arayüzü
-------------------------------------
Mevcut denetleyici.py ve tdk.py dosyalarına DOKUNMADAN, onların üstüne web sitesi ekler.
Çıktı dosyaları (rapor.csv, rapor.html) önceki biçimiyle aynıdır.

Çalıştırma:
    py -3.12 app.py
Sonra tarayıcıda aç:  http://127.0.0.1:5000

Büyük dosyalar: Yüklenebilecek en büyük PDF boyutu varsayılan olarak 500 MB'dır.
Değiştirmek için (Windows PowerShell):
    $env:DENETLEYICI_MAX_MB = "1000"
    py -3.12 app.py
"""

import os
import re
import tempfile
import threading
import time
import traceback
import uuid
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from pathlib import Path

from flask import Flask, abort, jsonify, render_template, request, send_file

import denetleyici as D          # mevcut denetim kodumuz
from tdk import TDK              # mevcut TDK modülümüz

KLASOR = D.KLASOR
MAX_PDF_MB = int(os.environ.get("DENETLEYICI_MAX_MB", "500"))   # yüklenebilecek en büyük PDF
MAX_METIN = 500_000              # yapıştırılabilecek en uzun metin (karakter)
MAX_GOSTERILEN_BULGU = 3000      # ekrana gönderilecek en çok bulgu (tamamı raporda)
MAX_SAKLANAN_RAPOR = 20          # bellekte tutulacak son rapor sayısı
MAX_SAKLANAN_IS = 30             # bellekte tutulacak son iş sayısı

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_PDF_MB * 1024 * 1024

# --- Program açılırken bir kez yüklenenler (Zemberek yüklemesi birkaç saniye sürer) ---
print("Zemberek yükleniyor… (birkaç saniye sürer)")
ARGO = D.liste_oku(KLASOR / "argo_listesi.txt")
YANLISLAR = D.yanlis_sozlugu_oku(KLASOR / "yaygin_yanlislar.txt")
OZEL = D.ozel_isimleri_oku(KLASOR / "ozel_isimler.txt")
DENETCI = D.YazimDenetcisi()

KILIT = threading.Lock()                         # aynı anda tek analiz çalışsın, diğerleri sırada beklesin
GECICI = Path(tempfile.mkdtemp(prefix="denetleyici_"))   # geçici dosyalar burada
RAPORLAR: "OrderedDict[str, dict]" = OrderedDict()
ISLER: "OrderedDict[str, dict]" = OrderedDict()
ID_BICIMI = re.compile(r"^[0-9a-f]{32}$")


class IsHatasi(Exception):
    """Kullanıcıya olduğu gibi gösterilecek hata mesajı."""


def hata(mesaj: str, kod: int = 400):
    return jsonify({"hata": mesaj}), kod


# ---------------------------------------------------------------------------
# Arka plan işleri ve ilerleme bilgisi
# ---------------------------------------------------------------------------
def is_olustur() -> str:
    is_id = uuid.uuid4().hex
    ISLER[is_id] = {"durum": "kuyrukta", "asama": "Sırada bekliyor…", "yuzde": 0, "sonuc": None, "hata": None}
    while len(ISLER) > MAX_SAKLANAN_IS:
        ISLER.popitem(last=False)
    return is_id


def guncelle(is_id: str, **bilgi):
    if is_id in ISLER:
        ISLER[is_id].update(bilgi)


def pdf_oku(yol: Path, ilerleme):
    """PDF'ten paragrafları çıkarır; sayfa sayısına göre ilerleme bildirir (%0-15)."""
    try:
        with D.pymupdf.open(str(yol)) as belge:
            if belge.needs_pass:
                raise IsHatasi("PDF şifreli. Şifresiz bir kopyasını yükleyin.")
            toplam = max(1, belge.page_count)
    except IsHatasi:
        raise
    except Exception:
        raise IsHatasi("PDF okunamadı. Dosya bozuk olabilir.")

    paragraflar, son_sayfa = [], 0
    try:
        for sayfa, par_no, metin in D.pdf_paragraflari(str(yol)):
            paragraflar.append((sayfa, par_no, metin))
            if sayfa != son_sayfa and (sayfa % 5 == 0 or sayfa == toplam):
                ilerleme(f"PDF'ten metin çıkarılıyor (sayfa {sayfa}/{toplam})", int(sayfa / toplam * 15))
            son_sayfa = sayfa
    except Exception:
        raise IsHatasi("PDF okunurken bir hata oluştu. Dosya bozuk olabilir.")
    if not paragraflar:
        raise IsHatasi("PDF'ten metin çıkarılamadı. Taranmış (resim) bir PDF olabilir; bunun için OCR gerekir.")
    return paragraflar


class OnbellektenTDK:
    """Ana denetim döngüsünde TDK'ye tekrar tekrar istek atmamak için sadece önbelleği okur."""

    def __init__(self, tdk):
        self.tdk = tdk

    def sozluk(self, kelime):
        return self.tdk.onbellek.get(f"gts:{kelime}")

    def sozluk_canli(self, kelime):
        return self.tdk.sozluk(kelime)               # öneri adaylarını doğrulamak için (az sayıda istek)

    def yazim_onerisi(self, kelime):
        return self.tdk.yazim_onerisi(kelime)


def tdk_toplu_sorgu(tdk, paragraflar, ilerleme):
    """Kitaptaki tüm benzersiz kelimeleri TDK'den paralel çeker. Döndürür: (cevapsız kalan oran, kelime kümesi)."""
    gerekli = D.tdk_aday_kelimeler(paragraflar, DENETCI)
    eksik = [k for k in sorted(gerekli) if f"gts:{k}" not in tdk.onbellek]
    if not eksik:
        return 0.0, gerekli

    def cevapsiz_orani():
        return sum(1 for k in gerekli if f"gts:{k}" not in tdk.onbellek) / max(1, len(gerekli))

    if not tdk.baglanti_dene():               # TDK cevap vermiyor: önbellektekilerle devam et, boşuna bekleme
        return cevapsiz_orani(), gerekli

    kalan = eksik
    bitti = 0
    with ThreadPoolExecutor(max_workers=tdk.calisan) as havuz:
        gelecekler = [havuz.submit(tdk.sozluk, k) for k in kalan]
        for _ in as_completed(gelecekler):
            bitti += 1
            if bitti % 25 == 0 or bitti == len(kalan):
                ilerleme(f"TDK sözlüğü sorgulanıyor ({bitti}/{len(eksik)} kelime)",
                         15 + int(45 * bitti / max(1, len(kalan))))
            if bitti % 200 == 0:              # TDK yarıda kesilirse alınan cevaplar kaybolmasın
                tdk.kaydet()
            if tdk.kapali:                    # TDK yanıt vermiyor: kalan istekleri iptal et
                havuz.shutdown(wait=False, cancel_futures=True)
                break
    tdk.kaydet()
    return cevapsiz_orani(), gerekli


def analiz_et(paragraflar, dosya_adi: str, tdk_kullan: bool, ilerleme):
    """Paragrafları üç kritere göre denetler, raporları üretir, JSON'a hazır sözlük döndürür."""
    basla = time.time()
    tdk, tdk_durum, denetim_basi = None, "kapali", 20

    if tdk_kullan:
        gercek = TDK(KLASOR / "tdk_onbellek.json")
        ilerleme("TDK sözlüğü hazırlanıyor…", 15)
        cevapsiz, gerekli = tdk_toplu_sorgu(gercek, paragraflar, ilerleme)
        if cevapsiz >= 1.0:
            tdk_durum = "ulasilamadi"         # hiç cevap yok: yedek yola geç
        elif not D.tdk_guvenilir_mi(gercek, gerekli):
            tdk_durum = "beklenmeyen"         # TDK cevapları beklenen biçimde değil: yedek yola geç
        else:
            # Cevabı olmayan kelimeler tek tek Zemberek ve yerel listelerle denetlenir.
            tdk, tdk_durum = OnbellektenTDK(gercek), "kismen" if cevapsiz > 0.05 else "kullanildi"
        denetim_basi = 60

    toplam = len(paragraflar)
    ilerleme("Özel isimler ayrılıyor…", denetim_basi)
    ozel_adlar = D.ozel_isimleri_ayir(paragraflar, DENETCI)
    belge_ozel = frozenset(ozel_adlar)
    bulgular = []
    for i, (sayfa, par_no, metin) in enumerate(paragraflar, start=1):
        bulgular.extend(D.paragraf_denetle(sayfa, par_no, metin, ARGO, YANLISLAR, DENETCI, tdk, OZEL, belge_ozel))
        if i % 50 == 0 or i == toplam:
            ilerleme(f"Metin denetleniyor (paragraf {i}/{toplam})", denetim_basi + int((95 - denetim_basi) * i / toplam))

    bulgular = D.bulgulari_birlestir(bulgular)
    ilerleme("Rapor hazırlanıyor…", 96)
    rapor_id = uuid.uuid4().hex
    csv_yolu = GECICI / f"{rapor_id}.csv"
    html_yolu = GECICI / f"{rapor_id}.html"
    D.csv_yaz(bulgular, csv_yolu)
    D.html_yaz(bulgular, html_yolu, dosya_adi, toplam, ozel_adlar)
    RAPORLAR[rapor_id] = {"csv": csv_yolu, "html": html_yolu}
    while len(RAPORLAR) > MAX_SAKLANAN_RAPOR:               # eski raporları temizle
        _, eski = RAPORLAR.popitem(last=False)
        for yol in eski.values():
            yol.unlink(missing_ok=True)

    sayilar = {"ARGO": 0, "YAZIM": 0, "NOKTALAMA": 0}
    for b in bulgular:
        sayilar[b.kriter] = sayilar.get(b.kriter, 0) + 1

    return {
        "id": rapor_id,
        "dosya": dosya_adi,
        "sayfa_sayisi": len({p[0] for p in paragraflar}),
        "paragraf_sayisi": toplam,
        "sure": round(time.time() - basla, 1),
        "tdk_durum": tdk_durum,
        "sayilar": sayilar,
        "toplam_bulgu": len(bulgular),
        "ozel_isimler": ozel_adlar.most_common(),
        "kesildi": len(bulgular) > MAX_GOSTERILEN_BULGU,
        "bulgular": [asdict(b) for b in bulgular[:MAX_GOSTERILEN_BULGU]],
    }


def arka_plan(is_id: str, kaynak, dosya_adi: str, tdk_kullan: bool, pdf_yolu: Path = None):
    """Analizi ayrı bir iş parçacığında çalıştırır; site ilerlemeyi /durum adresinden izler."""
    def ilerleme(asama, yuzde):
        guncelle(is_id, asama=asama, yuzde=yuzde)

    try:
        with KILIT:                                             # aynı anda tek analiz
            guncelle(is_id, durum="calisiyor", asama="Başlıyor…", yuzde=1)
            paragraflar = pdf_oku(pdf_yolu, ilerleme) if pdf_yolu else kaynak
            sonuc = analiz_et(paragraflar, dosya_adi, tdk_kullan, ilerleme)
        guncelle(is_id, durum="bitti", asama="Tamamlandı", yuzde=100, sonuc=sonuc)
    except IsHatasi as e:
        guncelle(is_id, durum="hata", hata=str(e))
    except Exception:
        traceback.print_exc()
        guncelle(is_id, durum="hata", hata="Analiz sırasında beklenmeyen bir hata oluştu. Terminaldeki mesajı kontrol edin.")
    finally:
        if pdf_yolu:
            pdf_yolu.unlink(missing_ok=True)                    # yüklenen PDF'i saklamayız


def isi_baslat(**kwargs):
    is_id = is_olustur()
    threading.Thread(target=arka_plan, args=(is_id,), kwargs=kwargs, daemon=True).start()
    return jsonify({"is_id": is_id})


# ---------------------------------------------------------------------------
# Sayfalar
# ---------------------------------------------------------------------------
@app.get("/")
def ana_sayfa():
    return render_template("index.html", max_mb=MAX_PDF_MB)


@app.post("/analiz")
def analiz_pdf():
    dosya = request.files.get("pdf")
    if not dosya or not dosya.filename:
        return hata("Lütfen bir PDF dosyası seçin.")
    if not dosya.filename.lower().endswith(".pdf"):
        return hata("Yalnızca PDF dosyaları yüklenebilir.")
    tdk_kullan = request.form.get("tdk") == "1"

    yol = GECICI / f"{uuid.uuid4().hex}.pdf"       # kullanıcı dosya adı yola karışmaz
    dosya.save(yol)
    with open(yol, "rb") as f:
        if f.read(5) != b"%PDF-":
            yol.unlink(missing_ok=True)
            return hata("Bu dosya geçerli bir PDF gibi görünmüyor.")
    return isi_baslat(kaynak=None, dosya_adi=Path(dosya.filename).name, tdk_kullan=tdk_kullan, pdf_yolu=yol)


@app.post("/analiz-metin")
def analiz_metin():
    veri = request.get_json(silent=True) or {}
    metin = str(veri.get("metin", "")).strip()
    if not metin:
        return hata("Lütfen denetlenecek bir metin yazın.")
    if len(metin) > MAX_METIN:
        return hata(f"Metin çok uzun (en fazla {MAX_METIN:,} karakter).".replace(",", "."))
    parcalar = [s for p in re.split(r"\n\s*\n", metin) for s in D.blok_parcala(p)]   # kelime aralarındaki çift boşluk korunur
    paragraflar = [(1, i, p) for i, p in enumerate((p for p in parcalar if len(p) >= 3), start=1)]
    if not paragraflar:
        return hata("Metin çok kısa.")
    return isi_baslat(kaynak=paragraflar, dosya_adi="Yapıştırılan metin", tdk_kullan=bool(veri.get("tdk")))


@app.get("/durum/<is_id>")
def durum(is_id):
    if not ID_BICIMI.match(is_id) or is_id not in ISLER:
        return hata("Bu işlem bulunamadı. Sunucu yeniden başlatılmış olabilir; dosyayı tekrar yükleyin.", 404)
    return jsonify(ISLER[is_id])


@app.get("/indir/<rapor_id>/<tur>")
def indir(rapor_id, tur):
    if not ID_BICIMI.match(rapor_id) or tur not in ("csv", "html"):
        abort(404)
    rapor = RAPORLAR.get(rapor_id)
    if not rapor or not rapor[tur].exists():
        abort(404)
    return send_file(rapor[tur], as_attachment=True, download_name=f"rapor.{tur}")


@app.errorhandler(413)
def cok_buyuk(_):
    return hata(f"Dosya çok büyük (en fazla {MAX_PDF_MB} MB).", 413)


if __name__ == "__main__":
    print(f"\nSite hazır → tarayıcıda şu adresi açın:  http://127.0.0.1:5000   (en büyük PDF: {MAX_PDF_MB} MB)")
    print("(Kapatmak için bu pencerede Ctrl + C)\n")
    # host=127.0.0.1: site yalnızca bu bilgisayardan açılır, ağdaki başkaları erişemez.
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)