"""
TDK (Türk Dil Kurumu) sözlük istemcisi  —  https://sozluk.gov.tr

Kullandığımız iki uç nokta:
    GTS   (Güncel Türkçe Sözlük) : https://sozluk.gov.tr/gts?ara=KELİME
    YAZIM (Yazım Kılavuzu)       : https://sozluk.gov.tr/yazim?ara=KELİME

Özellikler:
  * Aynı kelimeyi iki kez sormaz (bellek + diskte tdk_onbellek.json).
  * Ağ hatası olursa "bilinmiyor" döner; program yanlışlıkla hata üretmez.
  * Çok sayıda kelimeyi paralel (thread) sorgulayabilir.

NOT: TDK'nin JSON alan adları site güncellenince değişebilir. Bir şey çalışmazsa:
        python tdk.py kelime
     komutu ham cevabı ekrana basar; alan adlarını oradan kontrol edebilirsin.
"""

import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

GTS_URL = "https://sozluk.gov.tr/gts"
YAZIM_URL = "https://sozluk.gov.tr/yazim"

# TDK'de bir anlamın "özellik" etiketinde bu ifadeler geçiyorsa uygunsuz say.
ARGO_ETIKETLERI = ("argo", "kaba")


class TDK:
    def __init__(self, onbellek_yolu: Path, calisan: int = 8, bekleme: float = 0.05):
        self.yol = Path(onbellek_yolu)
        self.calisan = calisan
        self.bekleme = bekleme
        self.kilit = threading.Lock()
        self.oturum = requests.Session()
        self.oturum.headers.update({
            "User-Agent": "Mozilla/5.0 (ders-kitabi-denetleyici; ogrenci projesi)",
            "Accept": "application/json",
        })
        self.onbellek: dict = {}
        self.hata_sayisi = 0
        self.ust_uste_hata = 0
        self.kapali = False   # üst üste hata olursa True: artık istek atmayız
        if self.yol.exists():
            try:
                self.onbellek = json.loads(self.yol.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                self.onbellek = {}

    # ------------------------------------------------------------------
    # Ham istek
    # ------------------------------------------------------------------
    def _getir(self, url: str, kelime: str):
        """(durum, veri) döner. durum: 'ok' | 'yok' | 'hata'."""
        if self.kapali:
            return "hata", None
        for deneme in range(2):
            try:
                r = self.oturum.get(url, params={"ara": kelime}, timeout=5)
                if r.status_code != 200:
                    raise requests.RequestException(f"HTTP {r.status_code}")
                veri = r.json()
                # TDK, bulunamayan kelimede {"error": "Sonuç bulunamadı"} döndürür
                self.ust_uste_hata = 0
                if isinstance(veri, dict) and "error" in veri:
                    return "yok", None
                if not veri:
                    return "yok", None
                return "ok", veri
            except (requests.RequestException, ValueError):
                time.sleep(0.5 * (deneme + 1))
        self.hata_sayisi += 1
        self.ust_uste_hata += 1
        if self.ust_uste_hata >= 3:
            self.kapali = True
            print("UYARI: TDK'ye ulaşılamıyor; bu çalıştırmada TDK devre dışı bırakıldı.")
        return "hata", None

    # ------------------------------------------------------------------
    # Güncel Türkçe Sözlük: kelime var mı, argo/kaba mı?
    # ------------------------------------------------------------------
    @staticmethod
    def _etiketler(anlam: dict) -> list[str]:
        et = []
        for o in anlam.get("ozelliklerListe", []) or []:
            for alan in ("tam_adi", "kisa_adi"):
                if o.get(alan):
                    et.append(str(o[alan]).lower())
        return et

    def sozluk(self, kelime: str) -> dict | None:
        """
        Dönen sözlük:
            {"var": bool, "argo": bool, "argo_anlam": str, "ilk_anlam": str}
        TDK'ye ulaşılamazsa None döner (bilinmiyor).
        """
        anahtar = f"gts:{kelime}"
        with self.kilit:
            if anahtar in self.onbellek:
                return self.onbellek[anahtar]

        time.sleep(self.bekleme)
        durum, veri = self._getir(GTS_URL, kelime)
        if durum == "hata":
            return None
        if durum == "yok":
            sonuc = {"var": False, "argo": False, "argo_anlam": "", "ilk_anlam": ""}
        else:
            # Gelen maddeler arasından kelimenin kendisiyle birebir eşleşenleri al
            maddeler = [m for m in veri if str(m.get("madde", "")).lower().split(" ")[0] == kelime.lower()
                        or str(m.get("madde", "")).lower() == kelime.lower()] or veri
            anlamlar = []
            for m in maddeler:
                for a in m.get("anlamlarListe", []) or []:
                    anlamlar.append(a)
            isaretli = [a for a in anlamlar
                        if any(e in et for et in self._etiketler(a) for e in ARGO_ETIKETLERI)]
            # Yanlış alarmı azaltmak için: ilk anlam argo/kaba ise veya
            # anlamların yarıdan fazlası argo/kaba ise "argo" say.
            ilk_isaretli = bool(anlamlar) and anlamlar[0] in isaretli
            argo = bool(isaretli) and (ilk_isaretli or len(isaretli) * 2 > len(anlamlar))
            sonuc = {
                "var": True,
                "argo": argo,
                "argo_anlam": (isaretli[0].get("anlam", "") if isaretli else "")[:120],
                "ilk_anlam": (anlamlar[0].get("anlam", "") if anlamlar else "")[:120],
            }
        with self.kilit:
            self.onbellek[anahtar] = sonuc
        return sonuc

    # ------------------------------------------------------------------
    # Yazım Kılavuzu: doğru yazılışı öner
    # ------------------------------------------------------------------
    def yazim_onerisi(self, kelime: str) -> list[str]:
        anahtar = f"yazim:{kelime}"
        with self.kilit:
            if anahtar in self.onbellek:
                return self.onbellek[anahtar]
        durum, veri = self._getir(YAZIM_URL, kelime)
        if durum == "hata":
            return []
        oneriler = []
        if durum == "ok":
            for m in veri:
                sozu = m.get("sozu") or m.get("madde")
                if sozu and sozu.lower() != kelime.lower():
                    oneriler.append(sozu)
        oneriler = oneriler[:3]
        with self.kilit:
            self.onbellek[anahtar] = oneriler
        return oneriler

    # ------------------------------------------------------------------
    # Toplu ön yükleme ve kaydetme
    # ------------------------------------------------------------------
    def on_yukle(self, kelimeler, ilerleme=True):
        """Önbellekte olmayan kelimeleri paralel olarak TDK'den çeker."""
        eksik = [k for k in dict.fromkeys(kelimeler) if f"gts:{k}" not in self.onbellek]
        if not eksik:
            return
        # Önce tek kelimeyle bağlantıyı dene; olmuyorsa toplu sorguya hiç girme
        self.sozluk(eksik[0])
        if self.kapali or self.ust_uste_hata:
            return
        if ilerleme:
            print(f"TDK'den {len(eksik)} kelime sorgulanıyor (bir kez yapılır, sonra önbellekten okunur)…")
        with ThreadPoolExecutor(max_workers=self.calisan) as havuz:
            list(havuz.map(self.sozluk, eksik))
        self.kaydet()

    def kaydet(self):
        with self.kilit:
            self.yol.write_text(json.dumps(self.onbellek, ensure_ascii=False, indent=0), encoding="utf-8")


# Komut satırından deneme:  python tdk.py salak
if __name__ == "__main__":
    kelime = sys.argv[1] if len(sys.argv) > 1 else "okul"
    t = TDK(Path("tdk_onbellek_deneme.json"))
    for ad, url in (("GTS", GTS_URL), ("YAZIM", YAZIM_URL)):
        durum, veri = t._getir(url, kelime)
        print(f"--- {ad} ({durum}) ---")
        print(json.dumps(veri, ensure_ascii=False, indent=2)[:2500])
    print("--- Bizim yorumumuz ---")
    print(t.sozluk(kelime))
