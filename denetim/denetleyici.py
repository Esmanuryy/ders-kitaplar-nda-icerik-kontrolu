"""
Denetimin tamamını yöneten sınıf. Web sitesi (app.py) ve komut satırı (denetle.py) yalnızca bunu kullanır.

    d = Denetleyici()                       # sözlükleri bir kez yükler (birkaç saniye)
    sonuc = d.pdf_denetle("kitap.pdf")      # ya da d.metin_denetle("...")
    sonuc.bulgular, sonuc.ozel_adlar, sonuc.okunamayan_sayfalar
"""

import re
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from .buyuk_kucuk import harf_hatalari_bul
from .kelime import BUYUK_DENETIM_UZUNLUK, kelimeleri_denetle, tdk_adaylari
from .metin import HARFLER, KELIME_RE, KOD_RE, adresleri_ort, kelime_govdesi, tr_kucuk
from .noktalama import noktalama_bul
from .ozel_isim import ozel_isimleri_ayir
from .pdf import BOLUNME, SUSLU, metin_paragraflari, pdf_paragraflari
from .rapor import Bulgu, bulgulari_birlestir
from .sozluk import Sozluk, liste_oku, yanlis_sozlugu_oku
from .tdk import TDK, OnbellektenTDK, tdk_guvenilir_mi, toplu_sorgula

PROJE = Path(__file__).resolve().parent.parent
VERI = PROJE / "veri"

# Kelimelerinin bu kadarı hiçbir sözlükte yoksa paragrafın metni PDF'ten bozuk çıkmış (ya da Türkçe değil) sayılır.
OKUNAMAZ_ORANI = 0.25


@dataclass
class KelimeListeleri:
    argo: set
    yanlislar: dict
    ozel_isimler: frozenset
    izinli_kokler: tuple


@dataclass
class Sonuc:
    dosya_adi: str
    bulgular: list = field(default_factory=list)
    ozel_adlar: Counter = field(default_factory=Counter)
    okunamayan_sayfalar: list = field(default_factory=list)
    etkinlik_sayfalari: list = field(default_factory=list)   # etkinlik bölümü atlanan sayfalar
    sayfa_sayisi: int = 0
    paragraf_sayisi: int = 0
    tdk_durum: str = "kapali"    # kullanildi / kismen / ulasilamadi / beklenmeyen / kapali
    sure: float = 0.0

    def sayilar(self) -> dict:
        s = {"ARGO": 0, "YAZIM": 0, "NOKTALAMA": 0}
        for b in self.bulgular:
            s[b.kriter] += 1
        return s


class Denetleyici:
    def __init__(self, veri_klasoru: Path = VERI):
        self.veri_klasoru = veri_klasoru
        self.sozluk = Sozluk(PROJE / "sozluk" / "tr_TR")
        self.listeler = KelimeListeleri(
            argo=liste_oku(veri_klasoru / "argo_listesi.txt"),
            yanlislar=yanlis_sozlugu_oku(veri_klasoru / "yaygin_yanlislar.txt"),
            ozel_isimler=frozenset(liste_oku(veri_klasoru / "ozel_isimler.txt")),
            izinli_kokler=tuple(liste_oku(veri_klasoru / "izinli_kelimeler.txt")),
        )

    # ------------------------------------------------------------------
    def bolunmus_kelimeleri_birlestir(self, metin: str) -> str:
        """Satır sonunda tireyle bölünmüş kelimeyi birleştirir: kita- / plarını -> kitaplarını.
        İki parça da kendi başına kelimeyse ve birleşince anlamsız oluyorsa (yan yana sütunlardan gelen
        "konul" + "kurallar", "okuma" + "yazma") birleştirilmez; her kelime kendi başına denetlenir."""
        def karar(m):
            sol, sag = m.group(1), m.group(2)
            if self.sozluk.dogru_yazilmis_mi(tr_kucuk(sol + sag)):
                return sol + sag
            if self.sozluk.dogru_yazilmis_mi(tr_kucuk(sol)) and self.sozluk.dogru_yazilmis_mi(tr_kucuk(sag)):
                return f"{sol}-{sag}"
            return sol + sag
        metin = re.sub(rf"([{HARFLER}]+){BOLUNME}([{HARFLER}]+)", karar, metin).replace(BOLUNME, "")

        # Satır başında numara olan metinlerde (şiir, okuma metni) bölünen kelime: "pen- 2 cereden" -> "pencereden".
        # Yalnızca birleşince doğru bir kelime oluyorsa birleştirilir; "okuma- yazma" olduğu gibi kalır.
        def satir_numarali(m):
            birlesik = m.group(1) + m.group(3)
            return birlesik if self.sozluk.dogru_yazilmis_mi(tr_kucuk(birlesik)) else m.group(0)
        return re.sub(rf"([{HARFLER}]+)- (\d{{1,3}} )?([a-zçğıöşü]+)", satir_numarali, metin)

    def suslu_basliklari_ayikla(self, paragraflar) -> list:
        """Harf harf yazılmış süslü başlıklar (OYUN DÜNYASI) bütün kelimeleri sözlükte bulunursa denetlenir.
        Harfleri eksik ya da karışık okunduysa ("REN EÇRME") yanlış hata üretmemesi için atlanır."""
        sonuc = []
        for s, n, m in paragraflar:
            if SUSLU in m:
                kelimeler = [tr_kucuk(k) for k in KELIME_RE.findall(m.replace(SUSLU, ""))]
                if not all(len(k) < 2 or self.sozluk.dogru_yazilmis_mi(kelime_govdesi(k)) for k in kelimeler):
                    continue
                m = m.replace(SUSLU, "")
            sonuc.append((s, n, m))
        return sonuc

    def paragraf_denetle(self, sayfa, par_no, metin, tdk=None, belge_ozel=frozenset()) -> list[Bulgu]:
        """Bir paragrafı üç kritere göre denetler: argo, yazım (büyük/küçük harf dahil), noktalama."""
        if KOD_RE.search(metin):                     # kod ve formül satırları denetlenmez
            return []
        bulgular = kelimeleri_denetle(sayfa, par_no, metin, self.listeler, self.sozluk, tdk, belge_ozel)
        gorulen = {(b.kelime, b.baglam) for b in bulgular}
        bulgular += [b for b in harf_hatalari_bul(sayfa, par_no, metin, self.listeler.ozel_isimler, self.sozluk)
                     if (b.kelime, b.baglam) not in gorulen]
        bulgular += noktalama_bul(sayfa, par_no, metin, self.sozluk)
        return bulgular

    def okunamaz_mi(self, metin: str) -> bool:
        """PDF'ten bozuk çıkan metin (yldzdr gibi harfleri kaybolmuş) ya da Türkçe olmayan paragraf."""
        kelimeler = [tr_kucuk(k) for k in KELIME_RE.findall(adresleri_ort(metin)) if len(k) >= 3 and not k.isupper()]
        if len(kelimeler) < 8:
            return False
        bilinmeyen = sum(1 for k in kelimeler if not self.sozluk.dogru_yazilmis_mi(kelime_govdesi(k)))
        return bilinmeyen / len(kelimeler) >= OKUNAMAZ_ORANI

    # ------------------------------------------------------------------
    def tdk_hazirla(self, paragraflar, ilerleme=None):
        """Kitaptaki kelimeleri TDK'ye toplu sorar. Döndürür: (denetimde kullanılacak TDK nesnesi ya da None, durum)."""
        gercek = TDK(self.veri_klasoru / "tdk_onbellek.json")
        kelimeler = set()
        for _, _, metin in paragraflar:
            for m in KELIME_RE.finditer(adresleri_ort(metin)):
                govde = kelime_govdesi(m.group())
                if len(govde) >= 2 and (not govde.isupper() or len(govde) >= BUYUK_DENETIM_UZUNLUK):
                    kelimeler.update(tdk_adaylari(tr_kucuk(govde), self.sozluk))
        cevapsiz = toplu_sorgula(gercek, kelimeler, ilerleme)
        if cevapsiz >= 1.0:
            return None, "ulasilamadi"
        if not tdk_guvenilir_mi(gercek, kelimeler):
            return None, "beklenmeyen"
        return OnbellektenTDK(gercek), ("kismen" if cevapsiz > 0.05 else "kullanildi")

    def denetle(self, paragraflar, dosya_adi, tdk_kullan=True, ilerleme=None) -> Sonuc:
        """Paragrafların tamamını denetler. ilerleme(aşama, yüzde) ile durum bildirilir."""
        basla = time.time()
        ilerleme = ilerleme or (lambda asama, yuzde: None)
        paragraflar = self.suslu_basliklari_ayikla(
            [(s, n, self.bolunmus_kelimeleri_birlestir(m)) for s, n, m in paragraflar])
        sonuc = Sonuc(dosya_adi, sayfa_sayisi=len({p[0] for p in paragraflar}), paragraf_sayisi=len(paragraflar))

        tdk = None
        if tdk_kullan:
            ilerleme("TDK sözlüğü hazırlanıyor…", 20)
            tdk, sonuc.tdk_durum = self.tdk_hazirla(
                paragraflar, lambda bitti, toplam: ilerleme(f"TDK sözlüğü sorgulanıyor ({bitti}/{toplam} kelime)",
                                                           20 + int(40 * bitti / toplam)))
        ilerleme("Özel isimler ayrılıyor…", 60)
        sonuc.ozel_adlar = ozel_isimleri_ayir(paragraflar, self.sozluk, self.listeler.izinli_kokler)
        belge_ozel = frozenset(sonuc.ozel_adlar)

        ham, okunamayan = [], []
        for i, (sayfa, par_no, metin) in enumerate(paragraflar, start=1):
            if self.okunamaz_mi(metin):
                okunamayan.append(sayfa)
            else:
                ham += self.paragraf_denetle(sayfa, par_no, metin, tdk, belge_ozel)
            if i % 50 == 0 or i == len(paragraflar):
                ilerleme(f"Metin denetleniyor (paragraf {i}/{len(paragraflar)})", 62 + int(36 * i / len(paragraflar)))
        sonuc.bulgular = bulgulari_birlestir(ham)
        sonuc.okunamayan_sayfalar = sorted(set(okunamayan))
        sonuc.sure = round(time.time() - basla, 1)
        return sonuc

    def pdf_denetle(self, yol, dosya_adi=None, tdk_kullan=True, ilerleme=None, etkinlik_atla=True) -> Sonuc:
        """etkinlik_atla: kitaptaki etkinlik bölümleri (bilerek yanlış yazılmış alıştırmalar) denetlenmez."""
        ilerleme = ilerleme or (lambda asama, yuzde: None)
        atlanan = []
        paragraflar = list(pdf_paragraflari(str(yol), lambda s, t: ilerleme(
            f"PDF'ten metin çıkarılıyor (sayfa {s}/{t})", int(18 * s / t)), etkinlik_atla, atlanan))
        sonuc = self.denetle(paragraflar, dosya_adi or Path(yol).name, tdk_kullan, ilerleme)
        sonuc.etkinlik_sayfalari = atlanan
        return sonuc

    def metin_denetle(self, metin, tdk_kullan=True, ilerleme=None) -> Sonuc:
        return self.denetle(metin_paragraflari(metin), "Yapıştırılan metin", tdk_kullan, ilerleme)
