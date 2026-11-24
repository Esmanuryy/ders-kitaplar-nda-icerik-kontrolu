"""
Ders Kitabı Denetleyici - web sitesi

Çalıştırma:  Siteyi Ac.bat dosyasına çift tıklayın  ya da  py -3.12 app.py
Adres:       http://127.0.0.1:5000

En büyük PDF boyutu 500 MB'dır. Değiştirmek için (PowerShell):  $env:DENETLEYICI_MAX_MB = "1000"
"""

import atexit
import os
import re
import shutil
import tempfile
import threading
import traceback
import uuid
from collections import OrderedDict
from dataclasses import asdict
from pathlib import Path

import pymupdf
from flask import Flask, abort, jsonify, render_template, request, send_file

from denetim import Denetleyici, csv_yaz, degerlendir, html_yaz
from denetim.pdf import KITAP_TURLERI

MAX_PDF_MB = int(os.environ.get("DENETLEYICI_MAX_MB", "500"))
MAX_METIN = 500_000              # yapıştırılabilecek en uzun metin (karakter)
MAX_GOSTERILEN_BULGU = 3000      # ekrana gönderilecek en çok bulgu (tamamı indirilen raporda)
MAX_SAKLANAN = 20                # bellekte tutulacak son iş ve rapor sayısı
ID_BICIMI = re.compile(r"^[0-9a-f]{32}$")

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_PDF_MB * 1024 * 1024
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0          # tarayıcı stil ve betik dosyalarının eskisini kullanmasın
# Sayfadaki stil/betik adreslerine eklenir; dosyalar değişince tarayıcı yenisini indirir.
SURUM = str(int(max((Path(__file__).parent / "static" / f).stat().st_mtime for f in ("stil.css", "uygulama.js"))))

print("Sözlükler yükleniyor… (yaklaşık 15 saniye sürer)")
DENETLEYICI = Denetleyici()
KILIT = threading.Lock()                                   # aynı anda tek denetim; diğerleri sırada bekler
GECICI = Path(tempfile.mkdtemp(prefix="denetleyici_"))
atexit.register(shutil.rmtree, GECICI, ignore_errors=True)  # site kapanınca yüklenen PDF'ler ve raporlar silinir
ISLER: "OrderedDict[str, dict]" = OrderedDict()
PDFLER: dict = {}                # iş numarası -> denetlenen PDF (sayfa görüntüleyici için saklanır)


class KullaniciHatasi(Exception):
    """Kullanıcıya olduğu gibi gösterilecek hata."""


def hata(mesaj: str, kod: int = 400):
    return jsonify({"hata": mesaj}), kod


def pdf_kontrol(yol: Path):
    try:
        with pymupdf.open(str(yol)) as belge:
            if belge.needs_pass:
                raise KullaniciHatasi("PDF şifreli. Şifresiz bir kopyasını yükleyin.")
            return belge.page_count
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
        "degerlendirme": degerlendir(sonuc),
        "kitap_turu": KITAP_TURLERI[sonuc.kitap_turu],
        "bulgular": [asdict(b) for b in sonuc.bulgular[:MAX_GOSTERILEN_BULGU]],
    }


def calistir(is_id: str, tdk_kullan: bool, pdf_yolu: Path = None, metin: str = None, dosya_adi: str = "",
             etkinlik_atla: bool = True, kitap_turu: str = "sozel"):
    """Denetimi arka planda çalıştırır; site ilerlemeyi /durum adresinden izler."""
    def ilerleme(asama, yuzde):
        ISLER[is_id].update(asama=asama, yuzde=yuzde)

    try:
        with KILIT:
            ISLER[is_id].update(durum="calisiyor", asama="Başlıyor…", yuzde=1)
            if pdf_yolu:
                toplam_sayfa = pdf_kontrol(pdf_yolu)
                sonuc = DENETLEYICI.pdf_denetle(pdf_yolu, dosya_adi, tdk_kullan, ilerleme, etkinlik_atla, kitap_turu)
                if not sonuc.paragraf_sayisi:
                    raise KullaniciHatasi("PDF'te okunabilir metin yok. Taranmış (resim) bir PDF olabilir; "
                                          "bu tür dosyalar için önce OCR yapılması gerekir.")
            else:
                sonuc = DENETLEYICI.metin_denetle(metin, tdk_kullan, ilerleme, kitap_turu)
            ozet = sonucu_hazirla(is_id, sonuc)
            if pdf_yolu:
                PDFLER[is_id] = pdf_yolu                  # bulgunun sayfası sitede gösterilebilsin diye saklanır
                ozet.update(pdf=True, toplam_sayfa=toplam_sayfa)
            ISLER[is_id].update(durum="bitti", asama="Tamamlandı", yuzde=100, sonuc=ozet)
    except KullaniciHatasi as e:
        ISLER[is_id].update(durum="hata", hata=str(e))
    except Exception:
        traceback.print_exc()
        ISLER[is_id].update(durum="hata", hata="Denetim sırasında beklenmeyen bir hata oluştu. Siyah penceredeki mesaja bakın.")
    finally:
        if pdf_yolu and is_id not in PDFLER:
            pdf_yolu.unlink(missing_ok=True)              # hata olduysa PDF hemen silinir


def is_baslat(**kwargs):
    is_id = uuid.uuid4().hex
    ISLER[is_id] = {"durum": "kuyrukta", "asama": "Sırada bekliyor…", "yuzde": 0, "sonuc": None, "hata": None}
    while len(ISLER) > MAX_SAKLANAN:                       # eski işleri ve raporlarını temizle
        eski, _ = ISLER.popitem(last=False)
        for uzanti in ("csv", "html"):
            (GECICI / f"{eski}.{uzanti}").unlink(missing_ok=True)
        eski_pdf = PDFLER.pop(eski, None)               # eski işlerin PDF'leri silinir
        if eski_pdf:
            eski_pdf.unlink(missing_ok=True)
    threading.Thread(target=calistir, args=(is_id,), kwargs=kwargs, daemon=True).start()
    return jsonify({"is_id": is_id})


@app.get("/")
def ana_sayfa():
    return render_template("index.html", max_mb=MAX_PDF_MB, surum=SURUM)


@app.post("/denetle/pdf")
def denetle_pdf():
    dosya = request.files.get("pdf")
    tur = request.form.get("tur", "")                    # kitap türü seçilmeden PDF kabul edilmez
    if tur not in KITAP_TURLERI:
        return hata("Lütfen kitap türünü seçin (sözel ya da sayısal).")
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
                     etkinlik_atla=request.form.get("etkinlik") != "0", kitap_turu=tur)


@app.post("/denetle/metin")
def denetle_metin():
    veri = request.get_json(silent=True) or {}
    metin = str(veri.get("metin", "")).strip()
    if len(metin) < 3:
        return hata("Lütfen denetlenecek bir metin yazın.")
    if len(metin) > MAX_METIN:
        return hata(f"Metin çok uzun (en fazla {MAX_METIN:,} karakter).".replace(",", "."))
    tur = str(veri.get("tur", ""))
    if tur not in KITAP_TURLERI:
        return hata("Lütfen kitap türünü seçin (sözel ya da sayısal).")
    return is_baslat(tdk_kullan=bool(veri.get("tdk")), metin=metin, kitap_turu=tur)


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


def isin_pdfi(is_id) -> Path:
    yol = PDFLER.get(is_id) if ID_BICIMI.match(is_id) else None
    if not yol or not yol.exists():
        abort(404)
    return yol


@app.get("/sayfa/<is_id>/<int:no>")
def sayfa_resmi(is_id, no):
    """Kitabın bir sayfasını resim olarak verir. ?k=kelime verilirse kelime sayfada sarıyla işaretlenir."""
    kelime = request.args.get("k", "").strip()[:80]
    with pymupdf.open(str(isin_pdfi(is_id))) as belge:
        if not 1 <= no <= belge.page_count:
            abort(404)
        sayfa = belge[no - 1]
        bulunan = []
        if kelime:
            # Önce kelimenin tamamı, bulunamazsa içindeki en uzun kelime aranır (noktalama bulgularında "gitti.Sonra").
            adaylar = [kelime] + sorted(re.findall(r"[^\W\d_]{3,}", kelime), key=len, reverse=True)
            for aday in adaylar:
                bulunan = sayfa.search_for(aday, quads=True)
                if bulunan:
                    break
            for dortgen in bulunan:
                isaret = sayfa.add_highlight_annot(dortgen)
                isaret.set_colors(stroke=(1, 0.82, 0.1))
                isaret.update()
        sayfa_yuksekligi = sayfa.rect.height
        resim = sayfa.get_pixmap(matrix=pymupdf.Matrix(1.7, 1.7), annots=True).tobytes("png")
    cevap = app.response_class(resim, mimetype="image/png")
    cevap.headers["X-Isaretlenen"] = str(len(bulunan))
    if bulunan:                                          # ilk işaretin sayfadaki yüksekliği (0-1): site oraya kaydırır
        cevap.headers["X-Konum"] = f"{bulunan[0].rect.y0 / sayfa_yuksekligi:.4f}"
    cevap.headers["Cache-Control"] = "private, max-age=600"
    return cevap


@app.get("/pdf/<is_id>")
def pdf_dosyasi(is_id):
    """Denetlenen PDF'i tarayıcıda açar (#page=N ile istenen sayfaya gidilir)."""
    return send_file(isin_pdfi(is_id), mimetype="application/pdf", download_name="kitap.pdf")


@app.errorhandler(413)
def cok_buyuk(_):
    return hata(f"Dosya çok büyük (en fazla {MAX_PDF_MB} MB).", 413)


if __name__ == "__main__":
    print("\nSite hazır → http://127.0.0.1:5000   (kapatmak için bu pencereyi kapatın)\n")
    # 127.0.0.1: site yalnızca bu bilgisayardan açılır, ağdaki başkaları erişemez.
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)
