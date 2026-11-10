"""
Sözlükler: Zemberek (kelimenin kökü, eki, türü ve özel isim olup olmadığı) ve Hunspell Türkçe sözlüğü
(kelimenin doğru yazılıp yazılmadığı). Ayrıca proje klasöründeki kelime listeleri burada okunur.
"""

import itertools
import logging
import re
from functools import lru_cache
from pathlib import Path

from spylls.hunspell import Dictionary
from zemberek import TurkishMorphology

from .metin import TR_ALFABE, tr_kucuk

logging.disable(logging.INFO)  # Zemberek'in gereksiz log mesajlarını sustur

SAPKASIZ = str.maketrans("âîûÂÎÛ", "aiuAIU")
# Millet ve dil adlarına gelen ekler kesme işaretiyle ayrılmaz (TDK): Türkçede, Türkleri
KESMESIZ_ADLAR = frozenset("""türk alman fransız ingiliz arap rus yunan ermeni kürt japon italyan ispanyol
    macar bulgar sırp hırvat moğol tatar acem amerikan""".split())


def liste_oku(yol: Path) -> set[str]:
    """Her satırda bir kelime olan listeyi okur. # ile başlayan satırlar açıklamadır."""
    if not yol.exists():
        return set()
    return {tr_kucuk(s.strip()) for s in yol.read_text(encoding="utf-8").splitlines()
            if s.strip() and not s.strip().startswith("#")}


def yanlis_sozlugu_oku(yol: Path) -> dict[str, str]:
    """yanlış=doğru biçimindeki satırları okur."""
    sozluk = {}
    for satir in liste_oku(yol):
        if "=" in satir:
            yanlis, dogru = satir.split("=", 1)
            sozluk[yanlis.strip()] = dogru.strip()
    return sozluk


class Sozluk:
    """Zemberek ve Hunspell'i bir arada kullanır. Açılışı birkaç saniye sürdüğü için program başında bir kez
    oluşturulur; sorgu sonuçları bellekte tutulur."""

    def __init__(self, hunspell_yolu: Path):
        self.morfoloji = TurkishMorphology.create_with_defaults()
        self.hunspell = Dictionary.from_files(str(hunspell_yolu))

    @lru_cache(maxsize=100000)
    def sozlukte_var_mi(self, kelime: str) -> bool:
        """Hunspell Türkçe sözlüğüne göre kelime doğru yazılmış mı? Şapkalı yazımlar şapkasız da aranır."""
        return self.hunspell.lookup(kelime) or self.hunspell.lookup(kelime.translate(SAPKASIZ))

    @lru_cache(maxsize=100000)
    def cozumler(self, kelime: str) -> tuple:
        """Zemberek'in bildiği çözümlemeler: (madde, tür, alt tür, ayrıntılı çözüm)."""
        return tuple((a.item.lemma, str(a.item.primary_pos), str(a.item.secondary_pos), a.format_string())
                     for a in self.morfoloji.analyze(kelime).analysis_results
                     if str(a.item.primary_pos) != "PrimaryPos.Unknown")

    def gecerli_mi(self, kelime: str) -> bool:
        """Zemberek kelimeyi çözümleyebiliyor mu?"""
        return bool(self.cozumler(kelime))

    def maddeler(self, kelime: str) -> tuple[str, ...]:
        """Çekimli kelimenin sözlük maddeleri: gidiyoruz -> gitmek, kitapları -> kitap."""
        return tuple(dict.fromkeys(tr_kucuk(c[0]) for c in self.cozumler(kelime)))

    def ozel_isim_mi(self, kelime: str) -> bool:
        """Kelime yalnızca özel isim olarak mı biliniyor? (Ayşe, Ankara)"""
        c = self.cozumler(kelime)
        return bool(c) and all(x[2] == "SecondaryPos.ProperNoun" for x in c)

    def ozel_isim_okunusu_var_mi(self, kelime: str) -> bool:
        return any(x[2] == "SecondaryPos.ProperNoun" for x in self.cozumler(kelime))

    def dogru_yazilmis_mi(self, kelime: str) -> bool:
        """Yazım kararı: Hunspell'de varsa ya da Zemberek onu sıradan bir kelime olarak çözümleyebiliyorsa doğrudur."""
        return self.sozlukte_var_mi(kelime) or (self.gecerli_mi(kelime) and not self.ozel_isim_mi(kelime))

    def serbest_mi(self, kelime: str) -> bool:
        """Sözlükte madde olmayan ama doğru biçimler: soru eki (mı, misin) ve kısaltmalar."""
        return any(x[1] == "PrimaryPos.Question" or x[2] == "SecondaryPos.Abbreviation" for x in self.cozumler(kelime))

    def yuklem_olabilir_mi(self, kelime: str) -> bool:
        """Kelime cümleyi bitirecek çekimde mi? gitti, okuyunuz, eserdir, var. Ama oyun, kurarak, edinme,
        sağlamaya değil: yalın isim olabilen ya da zaman/kişi eki taşımayan kelime cümleyi bitirmeyebilir."""
        if kelime in ("var", "yok", "değil"):
            return True
        c = self.cozumler(kelime)
        if any(tr_kucuk(x[0]) == kelime or x[1] == "PrimaryPos.Pronoun" for x in c):
            return False
        for _, tur, _, cozum in c:
            if ":Cop" in cozum:
                return True
            if (tur == "PrimaryPos.Verb" and not re.search(r"→(?:Noun|Adj|Adv)", cozum)
                    and not re.search(r":Neg\+\w*:?Opt", cozum)
                    and re.search(r"[+:](?:Past|Narr|Prog1|Prog2|Aor|Fut|Cond|Neces|Opt)\b|Imp\+\w+:A2pl", cozum)):
                return True
        return False

    def kesmesiz_ozel_isim(self, kelime: str) -> str | None:
        """Hâl eki kesmeyle ayrılmamış özel ismin doğrusu: ankarada -> Ankara'da. Çoğul eki (Osmanlıların),
        millet ve dil adları (Türkçede) kesme almaz; sözlükte olduğu gibi geçen adlar (Hollanda) da atlanır."""
        if not self.ozel_isim_mi(kelime) or kelime in self.maddeler(kelime):
            return None
        if self.hunspell.lookup(kelime[:1].upper() + kelime[1:]):
            return None
        for madde, _, _, cozum in self.cozumler(kelime):
            kok = tr_kucuk(madde)
            ek = kelime[len(kok):]
            if ("→" not in cozum and re.search(r":(Dat|Loc|Abl|Acc|Gen)\b", cozum) and kelime.startswith(kok)
                    and kok not in KESMESIZ_ADLAR and not kok.endswith(("çe", "ça", "ce", "ca"))
                    and not ek.startswith(("lar", "ler"))):
                return f"{madde}'{ek}"
        return None

    @lru_cache(maxsize=20000)
    def oneriler(self, kelime: str) -> tuple[str, ...]:
        """Hatalı kelime için sözlükte bulunan düzeltme adayları."""
        adaylar = []
        # (a) Türkçe karakter eksikliği: guzel -> güzel, ogrenci -> öğrenci
        esle = {"c": "cç", "g": "gğ", "i": "iı", "o": "oö", "s": "sş", "u": "uü"}
        secenekler = [esle.get(h, h) for h in kelime]
        if sum(len(s) > 1 for s in secenekler) <= 6:
            for kombinasyon in itertools.product(*secenekler):
                aday = "".join(kombinasyon)
                if aday != kelime and self.sozlukte_var_mi(aday):
                    adaylar.append(aday)
        # (b) Tek harflik düzenlemeler: silme, yer değiştirme, değiştirme, ekleme
        if not adaylar and 4 <= len(kelime) <= 16:
            bolumler = [(kelime[:i], kelime[i:]) for i in range(len(kelime) + 1)]
            silme = [s + k[1:] for s, k in bolumler if k]
            yer = [s + k[1] + k[0] + k[2:] for s, k in bolumler if len(k) > 1]
            degis = [s + h + k[1:] for s, k in bolumler if k for h in TR_ALFABE]
            ekle = [s + h + k for s, k in bolumler for h in TR_ALFABE]
            for aday in dict.fromkeys(silme + yer + degis + ekle):
                if aday != kelime and self.sozlukte_var_mi(aday):
                    adaylar.append(aday)
                    if len(adaylar) >= 6:
                        break
        return tuple(adaylar)
