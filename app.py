"""
Ders Kitabı Denetleyici - web sitesi

Çalıştırma:  Siteyi Ac.bat dosyasına çift tıklayın  ya da  py -3.12 app.py
Adres:       http://127.0.0.1:5000

En büyük PDF boyutu 500 MB'dır. Değiştirmek için (PowerShell):  $env:DENETLEYICI_MAX_MB = "1000"
"""

import os
import re
import tempfile
import threading
import traceback
import uuid
from collections import OrderedDict
from dataclasses import asdict
from pathlib import Path

import pymupdf
from flask import Flask, abort, jsonify, render_template, request, send_file

from denetim import Denetleyici, csv_yaz, html_yaz

MAX_PDF_MB = int(os.environ.get("DENETLEYICI_MAX_MB", "500"))
MAX_METIN = 500_000              # yapıştırılabilecek en uzun metin (karakter)
MAX_GOSTERILEN_BULGU = 3000      # ekrana gönderilecek en çok bulgu (tamamı indirilen raporda)
MAX_SAKLANAN = 20                # bellekte tutulacak son iş ve rapor sayısı
ID_BICIMI = re.compile(r"^[0-9a-f]{32}$")

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_PDF_MB * 1024 * 1024

print("Sözlükler yükleniyor… (yaklaşık 15 saniye sürer)")
DENETLEYICI = Denetleyici()
KILIT = threading.Lock()                                   # aynı anda tek denetim; diğerleri sırada bekler
GECICI = Path(tempfile.mkdtemp(prefix="denetleyici_"))
ISLER: "OrderedDict[str, dict]" = OrderedDict()


class KullaniciHatasi(Exception):
    """Kullanıcıya olduğu gibi gösterilecek hata."""


def hata(mesaj: str, kod: int = 400):
    return jsonify({"hata": mesaj}), kod


def pdf_kontrol(yol: Path):
    try:
        with pymupdf.open(str(yol)) as belge:
            if belge.needs_pass:
                raise KullaniciHatasi("PDF şifreli. Şifresiz bir kopyasını yükleyin.")
    except KullaniciHatasi:
        raise
    except Exception:
        raise KullaniciHatasi("PDF açılamadı. Dosya bozuk olabilir.")


def sonucu_hazirla(is_id: str, sonuc) -> dict:
    """Raporları diske yazar, siteye gönderilecek özeti hazırlar."""
    csv_yaz(sonuc.bulgular, GECICI / f"{is_id}.csv")
    html_yaz(sonuc, GECICI / f"{is_id}.html")
    return {
        "dosya": sonuc.dosya_adi,
        "sayfa_sayisi": sonuc.sayfa_sayisi,
        "paragraf_sayisi": sonuc.paragraf_sayisi,
        "sure": sonuc.sure,
        "tdk_durum": sonuc.tdk_durum,
        "sayilar": sonuc.sayilar(),
        "toplam_bulgu": len(sonuc.bulgular),
        "kesildi": len(sonuc.bulgular) > MAX_GOSTERILEN_BULGU,
        "ozel_isimler": sonuc.ozel_adlar.most_common(),
        "okunamayan_sayfalar": sonuc.okunamayan_sayfalar,
        "etkinlik_sayfalari": sonuc.etkinlik_sayfalari,
        "bulgular": [asdict(b) for b in sonuc.bulgular[:MAX_GOSTERILEN_BULGU]],
    }


def calistir(is_id: str, tdk_kullan: bool, pdf_yolu: Path = None, metin: str = None, dosya_adi: str = "",
             etkinlik_atla: bool = True):
    """Denetimi arka planda çalıştırır; site ilerlemeyi /durum adresinden izler."""
    def ilerleme(asama, yuzde):
        ISLER[is_id].update(asama=asama, yuzde=yuzde)

    try:
        with KILIT:
            ISLER[is_id].update(durum="calisiyor", asama="Başlıyor…", yuzde=1)
            if pdf_yolu:
                pdf_kontrol(pdf_yolu)
                sonuc = DENETLEYICI.pdf_denetle(pdf_yolu, dosya_adi, tdk_kullan, ilerleme, etkinlik_atla)
                if not sonuc.paragraf_sayisi:
                    raise KullaniciHatasi("PDF'te okunabilir metin yok. Taranmış (resim) bir PDF olabilir; "
                                          "bu tür dosyalar için önce OCR yapılması gerekir.")
            else:
                sonuc = DENETLEYICI.metin_denetle(metin, tdk_kullan, ilerleme)
            ISLER[is_id].update(durum="bitti", asama="Tamamlandı", yuzde=100, sonuc=sonucu_hazirla(is_id, sonuc))
    except KullaniciHatasi as e:
        ISLER[is_id].update(durum="hata", hata=str(e))
    except Exception:
        traceback.print_exc()
        ISLER[is_id].update(durum="hata", hata="Denetim sırasında beklenmeyen bir hata oluştu. Siyah penceredeki mesaja bakın.")
    finally:
        if pdf_yolu:
            pdf_yolu.unlink(missing_ok=True)              # yüklenen PDF saklanmaz


def is_baslat(**kwargs):
    is_id = uuid.uuid4().hex
    ISLER[is_id] = {"durum": "kuyrukta", "asama": "Sırada bekliyor…", "yuzde": 0, "sonuc": None, "hata": None}
    while len(ISLER) > MAX_SAKLANAN:                       # eski işleri ve raporlarını temizle
        eski, _ = ISLER.popitem(last=False)
        for uzanti in ("csv", "html"):
            (GECICI / f"{eski}.{uzanti}").unlink(missing_ok=True)
    threading.Thread(target=calistir, args=(is_id,), kwargs=kwargs, daemon=True).start()
    return jsonify({"is_id": is_id})


@app.get("/")
def ana_sayfa():
    return render_template("index.html", max_mb=MAX_PDF_MB)


@app.post("/denetle/pdf")
def denetle_pdf():
    dosya = request.files.get("pdf")
    if not dosya or not dosya.filename:
        return hata("Lütfen bir PDF dosyası seçin.")
    if not dosya.filename.lower().endswith(".pdf"):
        return hata("Yalnızca PDF dosyaları yüklenebilir.")
    yol = GECICI / f"{uuid.uuid4().hex}.pdf"               # kullanıcının dosya adı dosya yoluna karışmaz
    dosya.save(yol)
    with open(yol, "rb") as f:
        if f.read(5) != b"%PDF-":
            yol.unlink(missing_ok=True)
            return hata("Bu dosya geçerli bir PDF gibi görünmüyor.")
    return is_baslat(tdk_kullan=request.form.get("tdk") == "1", pdf_yolu=yol, dosya_adi=Path(dosya.filename).name,
                     etkinlik_atla=request.form.get("etkinlik") != "0")


@app.post("/denetle/metin")
def denetle_metin():
    veri = request.get_json(silent=True) or {}
    metin = str(veri.get("metin", "")).strip()
    if len(metin) < 3:
        return hata("Lütfen denetlenecek bir metin yazın.")
    if len(metin) > MAX_METIN:
        return hata(f"Metin çok uzun (en fazla {MAX_METIN:,} karakter).".replace(",", "."))
    return is_baslat(tdk_kullan=bool(veri.get("tdk")), metin=metin)


@app.get("/durum/<is_id>")
def durum(is_id):
    if not ID_BICIMI.match(is_id) or is_id not in ISLER:
        return hata("Bu işlem bulunamadı. Site yeniden başlatılmış olabilir; dosyayı tekrar yükleyin.", 404)
    return jsonify(ISLER[is_id])


@app.get("/indir/<is_id>/<tur>")
def indir(is_id, tur):
    yol = GECICI / f"{is_id}.{tur}"
    if not ID_BICIMI.match(is_id) or tur not in ("csv", "html") or not yol.exists():
        abort(404)
    return send_file(yol, as_attachment=True, download_name=f"denetim_raporu.{tur}")


@app.errorhandler(413)
def cok_buyuk(_):
    return hata(f"Dosya çok büyük (en fazla {MAX_PDF_MB} MB).", 413)


if __name__ == "__main__":
    print("\nSite hazır → http://127.0.0.1:5000   (kapatmak için bu pencereyi kapatın)\n")
    # 127.0.0.1: site yalnızca bu bilgisayardan açılır, ağdaki başkaları erişemez.
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)
