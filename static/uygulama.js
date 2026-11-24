// Ders Kitabı Denetleyici - sayfa davranışı
(function () {
  "use strict";
  const $ = (s) => document.querySelector(s);
  const KRITER = {
    ARGO: { ad: "Argo / uygunsuz", sinif: "argo" },
    YAZIM: { ad: "Yazım", sinif: "yazim" },
    NOKTALAMA: { ad: "Noktalama", sinif: "nokta" },
  };
  const TDK_MESAJ = {
    kullanildi: ["bilgi", "TDK sözlüğü kullanıldı."],
    kismen: ["dikkat", "TDK bazı kelimelere cevap vermedi. Bu kelimeler bilgisayardaki sözlükle denetlendi."],
    ulasilamadi: ["dikkat", "TDK'ye ulaşılamadı. Denetim bilgisayardaki sözlük ve listelerle yapıldı."],
    beklenmeyen: ["dikkat", "TDK'den beklenmeyen cevaplar geldi. Denetim bilgisayardaki sözlük ve listelerle yapıldı."],
    kapali: ["bilgi", "TDK kapalıydı. Denetim bilgisayardaki sözlük ve listelerle yapıldı."],
  };
  const ORNEK_METIN =
    "Bu konu çok guzel anlatılmış. Herkez sınava hazırlandı ve yanlız kalmadı.\n\n" +
    "Biz Ankarada yaşıyoruz.Sonra okula gittik. Kalem,silgi, ve defter aldık..\n\n" +
    "Bu konuyu anladın mı. Öğrenciler kütüphanede uzun süre ders çalıştılar\n\n" +
    "Bu salak şaka herkesi güldürdü!! Newton'un yasaları ve Pisagor bağıntısı çok önemlidir. Pisagor bir matematikçidir.";
  const SAYFA_BOYUTU = 50;

  let pdfDosya = null, sonuc = null, filtre = "HEPSI", arama = "", siralama = "sayfa", gosterilen = SAYFA_BOYUTU;
  let sureSayaci = null;

  function el(etiket, sinif, metin) {
    const e = document.createElement(etiket);
    if (sinif) e.className = sinif;
    if (metin !== undefined) e.textContent = metin;
    return e;
  }

  // ---------------- Giriş ----------------
  function pdfSekmesi() { return $("#sekme-pdf").getAttribute("aria-selected") === "true"; }

  function sekmeSec(pdf) {
    $("#sekme-pdf").setAttribute("aria-selected", pdf);
    $("#sekme-metin").setAttribute("aria-selected", !pdf);
    $("#sekme-pdf").tabIndex = pdf ? 0 : -1;
    $("#sekme-metin").tabIndex = pdf ? -1 : 0;
    $("#panel-pdf").classList.toggle("gizli", !pdf);
    $("#panel-metin").classList.toggle("gizli", pdf);
    $("#etkinlik-secenek").classList.toggle("gizli", !pdf);
    dugmeDurumu();
  }

  function kitapTuru() {
    const secili = document.querySelector('input[name="tur"]:checked');
    return secili ? secili.value : null;
  }

  function dugmeDurumu() {
    const tur = kitapTuru();
    // Kitap türü seçilmeden PDF yüklenemez ve denetim başlatılamaz.
    $("#pdf-girdi").disabled = !tur;
    $("#yukle").classList.toggle("kapali", !tur);
    $("#yukle").setAttribute("aria-disabled", String(!tur));
    $("#tur-uyari").classList.toggle("gizli", !!tur);
    $("#denetle-btn").disabled = !tur || (pdfSekmesi() ? !pdfDosya : $("#metin-girdi").value.trim().length < 3);
  }

  function dosyaSec(dosya) {
    hataGizle();
    if (dosya && !kitapTuru()) {
      hataGoster("PDF yüklemeden önce kitap türünü seçin (sözel ya da sayısal).");
      $(".tur-sec").scrollIntoView({ behavior: "smooth", block: "center" });
      dosya = null;
    }
    if (dosya && !dosya.name.toLowerCase().endsWith(".pdf")) {
      hataGoster("Yalnızca PDF dosyaları yüklenebilir.");
      dosya = null;
    }
    pdfDosya = dosya || null;
    $("#secili").classList.toggle("gizli", !pdfDosya);
    if (pdfDosya) $("#secili-ad").textContent = pdfDosya.name + " · " + (pdfDosya.size / 1048576).toFixed(1).replace(".", ",") + " MB";
    dugmeDurumu();
  }

  function hataGoster(m) { const h = $("#hata"); h.textContent = m; h.classList.remove("gizli"); }
  function hataGizle() { $("#hata").classList.add("gizli"); }

  // ---------------- Bekleme ekranı ----------------
  function bekle(acik) {
    $("#bekle").classList.toggle("acik", acik);
    clearInterval(sureSayaci);
    if (acik) {
      const bas = Date.now();
      ilerleme("Hazırlanıyor…", 0);
      $("#bekle-sure").textContent = "0 sn";
      sureSayaci = setInterval(() => { $("#bekle-sure").textContent = Math.round((Date.now() - bas) / 1000) + " sn"; }, 1000);
    }
  }

  function ilerleme(asama, yuzde) {
    $("#bekle-asama").textContent = asama;
    $("#bekle-yuzde").textContent = "%" + yuzde;
    $("#bekle-cubuk").style.width = yuzde + "%";
  }

  // ---------------- Sunucuyla konuşma ----------------
  function gonder(url, govde, json) {
    // XMLHttpRequest: büyük PDF yüklenirken yükleme yüzdesi gösterilebilsin diye
    return new Promise((coz, reddet) => {
      const x = new XMLHttpRequest();
      x.open("POST", url);
      if (json) x.setRequestHeader("Content-Type", "application/json");
      x.upload.onprogress = (e) => { if (e.lengthComputable) ilerleme("Dosya yükleniyor…", Math.round(e.loaded / e.total * 100)); };
      x.onload = () => {
        let veri = {};
        try { veri = JSON.parse(x.responseText); } catch (_) { /* boş cevap */ }
        if (x.status >= 200 && x.status < 300) coz(veri); else reddet(new Error(veri.hata || "İstek başarısız oldu."));
      };
      x.onerror = () => reddet(new TypeError("ağ"));
      x.send(json ? JSON.stringify(govde) : govde);
    });
  }

  async function isiIzle(isId) {
    for (;;) {
      await new Promise((r) => setTimeout(r, 700));
      const r = await fetch("/durum/" + isId);
      const d = await r.json();
      if (!r.ok) throw new Error(d.hata || "Durum alınamadı.");
      ilerleme(d.asama, d.yuzde);
      if (d.durum === "bitti") return d.sonuc;
      if (d.durum === "hata") throw new Error(d.hata);
    }
  }

  async function denetle() {
    hataGizle();
    bekle(true);
    try {
      const tdk = $("#tdk-sec").checked;
      let is;
      if (pdfSekmesi()) {
        const f = new FormData();
        f.append("pdf", pdfDosya);
        f.append("tdk", tdk ? "1" : "0");
        f.append("etkinlik", $("#etkinlik-sec").checked ? "1" : "0");
        f.append("tur", kitapTuru());
        is = await gonder("/denetle/pdf", f, false);
      } else {
        is = await gonder("/denetle/metin", { metin: $("#metin-girdi").value, tdk, tur: kitapTuru() }, true);
      }
      sonuc = await isiIzle(is.is_id);
      sonuc.id = is.is_id;
      filtre = "HEPSI"; arama = ""; $("#ara").value = ""; gosterilen = SAYFA_BOYUTU;
      sonuclariGoster();
    } catch (e) {
      hataGoster(e instanceof TypeError
        ? "Site şu anda kapalı. Masaüstündeki Ders Kitabı Denetleyici kısayoluna çift tıklayın, sonra yeniden deneyin."
        : e.message);
    } finally {
      bekle(false);
      dugmeDurumu();
    }
  }

  // ---------------- Sonuçlar ----------------
  function vurgula(hedef, metin, kelime) {
    const i = kelime ? metin.toLocaleLowerCase("tr").indexOf(kelime.toLocaleLowerCase("tr")) : -1;
    if (i < 0) { hedef.textContent = metin; return; }
    hedef.append(metin.slice(0, i), el("mark", null, metin.slice(i, i + kelime.length)), metin.slice(i + kelime.length));
  }

  // Sayfa numarası: PDF denetlendiyse tıklanınca kitabın o sayfası açılır.
  function sayfaDugmesi(no, b, metin) {
    if (!sonuc.pdf) return el("span", null, metin);
    const d = el("button", "sayfa-btn", metin);
    d.type = "button";
    d.title = "Kitabın " + no + ". sayfasını aç";
    d.addEventListener("click", () => sayfaAc(Number(no), b));
    return d;
  }

  function kartYap(b) {
    const k = KRITER[b.kriter];
    const kart = el("article", "bulgu " + k.sinif);
    const ust = el("div", "bulgu-ust");
    ust.append(el("span", "rozet " + k.sinif, k.ad), sayfaDugmesi(b.sayfa, b, "Sayfa " + b.sayfa));
    if (b.adet > 1) {
      const tekrar = el("span", "tekrar", b.adet + " kez geçiyor: ");
      String(b.sayfalar).split(",").map((s) => s.trim()).filter(Boolean).forEach((s, i) => {
        if (i) tekrar.append(", ");
        tekrar.append(sayfaDugmesi(s, b, s));
      });
      ust.append(tekrar);
    }
    const govde = el("div", "bulgu-govde");
    const sol = el("div");
    sol.append(el("div", "kelime", b.kelime));
    const sag = el("div");
    const neden = el("p", "neden");
    neden.append(el("b", null, "Neden hata?"), b.aciklama);
    const oneri = el("p", "oneri");
    let etiket = "Öneri:", deger = b.oneri;
    if (deger.startsWith("Doğrusu: ")) { etiket = "Doğrusu:"; deger = deger.slice(9); }
    else if (b.kriter === "YAZIM" && !/[.;]$/.test(deger)) etiket = deger.includes(",") ? "Doğru yazılışı şunlardan biri olabilir:" : "Doğru yazılışı:";
    oneri.append(el("b", null, etiket), deger);
    sag.append(neden, oneri);
    const baglam = el("p", "baglam");
    vurgula(baglam, b.baglam, b.kelime);
    govde.append(sol, sag, baglam);
    kart.append(ust, govde);
    return kart;
  }

  function suzulmus() {
    const a = arama.toLocaleLowerCase("tr");
    const sira = { ARGO: 0, YAZIM: 1, NOKTALAMA: 2 };
    const l = sonuc.bulgular.filter((b) => (filtre === "HEPSI" || b.kriter === filtre)
      && (!a || (b.kelime + " " + b.baglam + " " + b.aciklama).toLocaleLowerCase("tr").includes(a)));
    if (siralama === "tekrar") l.sort((x, y) => y.adet - x.adet || x.sayfa - y.sayfa);
    else if (siralama === "tur") l.sort((x, y) => sira[x.kriter] - sira[y.kriter] || x.sayfa - y.sayfa);
    else l.sort((x, y) => x.sayfa - y.sayfa || x.paragraf - y.paragraf);
    return l;
  }

  function listeyiCiz() {
    const l = suzulmus(), liste = $("#liste");
    liste.replaceChildren();
    if (!l.length) {
      liste.append(el("p", "bos", sonuc.bulgular.length ? "Bu süzgece uyan bulgu yok." : "Hiç hata bulunamadı."));
    } else {
      l.slice(0, gosterilen).forEach((b) => liste.append(kartYap(b)));
    }
    $("#daha").classList.toggle("gizli", l.length <= gosterilen);
    $("#daha-btn").textContent = "Daha fazla göster (" + (l.length - gosterilen) + " bulgu daha)";
  }

  function filtreleriCiz() {
    const kutu = $("#filtreler");
    kutu.replaceChildren();
    const s = sonuc.sayilar;
    [["HEPSI", "Tümü", sonuc.bulgular.length], ["ARGO", "Argo", s.ARGO], ["YAZIM", "Yazım", s.YAZIM], ["NOKTALAMA", "Noktalama", s.NOKTALAMA]]
      .forEach(([kod, ad, sayi]) => {
        const d = el("button", "filtre", ad + " (" + sayi + ")");
        d.type = "button";
        d.setAttribute("aria-pressed", filtre === kod);
        d.addEventListener("click", () => { filtre = kod; gosterilen = SAYFA_BOYUTU; filtreleriCiz(); listeyiCiz(); });
        kutu.append(d);
      });
  }

  function bildirim(tur, metin) {
    const d = el("div", "uyari " + tur, metin);
    $("#bildirimler").append(d);
  }

  function sonuclariGoster() {
    const s = sonuc;
    $("#sonuc-baslik").textContent = s.dosya;
    const meta = $("#sonuc-meta");
    meta.replaceChildren();
    [s.kitap_turu, s.sayfa_sayisi + " sayfa", s.paragraf_sayisi + " paragraf",
      String(s.sure).replace(".", ",") + " saniye"].forEach((m) => meta.append(el("li", null, m)));

    const ozet = $("#ozet");
    ozet.replaceChildren();
    [["toplam", s.toplam_bulgu, "toplam bulgu"], ["argo", s.sayilar.ARGO, "argo / uygunsuz"],
      ["yazim", s.sayilar.YAZIM, "yazım"], ["nokta", s.sayilar.NOKTALAMA, "noktalama"],
      ["ozel", s.ozel_isimler.length, "ayrılan özel isim"]].forEach(([sinif, sayi, ad]) => {
      const k = el("div", sinif);
      k.append(el("b", null, String(sayi)), el("span", null, ad));
      ozet.append(k);
    });

    degerlendirmeyiCiz(s.degerlendirme);

    $("#bildirimler").replaceChildren();
    const [tur, mesaj] = TDK_MESAJ[s.tdk_durum] || TDK_MESAJ.kapali;
    bildirim(tur, mesaj);
    if (s.etkinlik_sayfalari && s.etkinlik_sayfalari.length) {
      bildirim("bilgi", "Etkinlik ve çalışma bölümleri denetlenmedi (" + s.etkinlik_sayfalari.length + " sayfa). Bu bölümlerdeki yanlışlar öğrenci bulsun diye bilerek yazılır. Sayfalar: "
        + s.etkinlik_sayfalari.join(", ") + ".");
    }
    if (s.okunamayan_sayfalar.length) {
      bildirim("dikkat", "Şu sayfalarda bazı paragrafların metni PDF'ten bozuk çıktı ya da Türkçe değil; bu paragraflar denetlenmedi: sayfa "
        + s.okunamayan_sayfalar.join(", ") + ".");
    }
    if (s.kesildi) bildirim("dikkat", "Ekranda ilk " + s.bulgular.length + " bulgu gösteriliyor; hepsi indirilen raporda var.");

    const adlar = s.ozel_isimler;
    $("#ozel-kutu").classList.toggle("gizli", !adlar.length);
    $("#ozel-baslik").textContent = "Ayrılan özel isimler (" + adlar.length + ") · yazım hatası sayılmadı";
    $("#ozel-liste").textContent = adlar.map(([ad, adet]) => ad + " (" + adet + ")").join(", ");

    $("#indir-csv").href = "/indir/" + s.id + "/csv";
    $("#indir-html").href = "/indir/" + s.id + "/html";
    filtreleriCiz();
    listeyiCiz();
    const bolum = $("#sonuclar");
    bolum.classList.remove("gizli");
    $("#yeni-btn").classList.remove("gizli");
    bolum.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  // ---------------- Değerlendirme ----------------
  const sayi = (x, b = 2) => Number(x).toLocaleString("tr-TR", { maximumFractionDigits: b });

  function degerlendirmeyiCiz(d) {
    const kutu = $("#degerlendirme");
    kutu.className = "kart degerlendirme " + d.seviye;
    $("#deg-puan").textContent = d.puan;
    const cevre = 2 * Math.PI * 52;                     // puan halkası: puan kadar dolar
    $("#deg-halka").style.strokeDasharray = cevre;
    $("#deg-halka").style.strokeDashoffset = cevre * (1 - d.puan / 100);
    $("#deg-seviye").textContent = d.seviye_adi;
    $("#deg-yorum").textContent = d.yorum;
    $("#deg-binde").textContent = sayi(d.binde);
    $("#deg-dogru").textContent = "%" + sayi(d.dogru_yuzde);
    $("#deg-sayfa").textContent = sayi(d.sayfa_basina);
    $("#deg-kelime").textContent = sayi(d.kelime, 0);
    const turler = $("#deg-turler");
    turler.replaceChildren();
    const enBuyuk = Math.max(1, ...Object.values(d.turler).map((t) => t.hata));
    [["ARGO", "argo"], ["YAZIM", "yazim"], ["NOKTALAMA", "nokta"]].forEach(([kod, sinif]) => {
      const t = d.turler[kod], satir = el("div", "tur-satir " + sinif);
      const cubuk = el("span", "tur-cubuk");
      const dolu = el("span");
      dolu.style.width = (t.hata / enBuyuk * 100) + "%";
      cubuk.append(dolu);
      satir.append(el("span", "tur-ad", KRITER[kod].ad), cubuk,
        el("span", "tur-deger", t.hata + " yer · 1000 kelimede " + sayi(t.binde)));
      turler.append(satir);
    });
    const uyari = $("#deg-uyarilar");
    uyari.replaceChildren();
    d.uyarilar.forEach((u) => uyari.append(el("li", null, u)));
    $("#deg-not").textContent = d.not;
  }

  // ---------------- Sayfa görüntüleyici ----------------
  let gAcik = null, gSonOdak = null;

  function bulguSayfalari(b) {
    return String(b.sayfalar || b.sayfa).split(",").map((s) => Number(s.trim())).concat(Number(b.sayfa));
  }

  function sayfaAc(no, b) {
    gSonOdak = document.activeElement;
    gAcik = { no, b };
    $("#gosterici").hidden = false;
    document.body.classList.add("kilitli");
    sayfaCiz();
    $("#g-kapat").focus();
  }

  function sayfaCiz() {
    const { no, b } = gAcik, son = sonuc.toplam_sayfa || no;
    const asilSayfa = bulguSayfalari(b).includes(no);
    $("#g-baslik").textContent = "Sayfa " + no + " / " + son;
    $("#g-baglam").replaceChildren();
    if (no === Number(b.sayfa)) vurgula($("#g-baglam"), b.baglam, b.kelime);
    $("#g-durum").textContent = "Yükleniyor…";
    $("#g-onceki").disabled = no <= 1;
    $("#g-sonraki").disabled = no >= son;
    $("#g-pdf").href = "/pdf/" + sonuc.id + "#page=" + no;
    const resim = $("#g-resim");
    $("#g-yukleniyor").classList.remove("gizli");
    resim.classList.add("yukleniyor");
    const adres = "/sayfa/" + sonuc.id + "/" + no + (asilSayfa ? "?k=" + encodeURIComponent(b.kelime) : "");
    fetch(adres).then((r) => {
      if (!r.ok) throw new Error();
      const sayi = Number(r.headers.get("X-Isaretlenen") || 0);
      if (gAcik) gAcik.konum = r.headers.get("X-Konum");
      if (gAcik && gAcik.no === no) {
        $("#g-durum").textContent = !asilSayfa ? "“" + b.kelime + "” bu sayfada geçmiyor."
          : sayi ? "“" + b.kelime + "” sayfada sarıyla işaretlendi."
          : "“" + b.kelime + "” sayfada otomatik işaretlenemedi; üstteki cümleye bakın.";
      }
      return r.blob();
    }).then((blob) => {
      if (!gAcik || gAcik.no !== no) return;           // bu arada başka sayfaya geçildi
      if (resim.src.startsWith("blob:")) URL.revokeObjectURL(resim.src);
      resim.onload = () => {                          // işaretli kelime görünsün diye o yere kaydırılır
        const govde = $("#g-govde"), konum = gAcik && gAcik.konum;
        govde.scrollTop = konum ? Math.max(0, resim.offsetTop + resim.offsetHeight * Number(konum) - govde.clientHeight / 3) : 0;
      };
      resim.src = URL.createObjectURL(blob);
      resim.alt = "Kitabın " + no + ". sayfası";
    }).catch(() => {
      $("#g-durum").textContent = "Sayfa açılamadı. Site yeniden başlatıldıysa kitabı tekrar denetleyin.";
    }).finally(() => {
      $("#g-yukleniyor").classList.add("gizli");
      resim.classList.remove("yukleniyor");
    });
  }

  function sayfaKapat() {
    if (!gAcik) return;
    gAcik = null;
    $("#gosterici").hidden = true;
    document.body.classList.remove("kilitli");
    if (gSonOdak) gSonOdak.focus();
  }

  $("#g-kapat").addEventListener("click", sayfaKapat);
  $("#g-onceki").addEventListener("click", () => { if (gAcik.no > 1) { gAcik.no--; sayfaCiz(); } });
  $("#g-sonraki").addEventListener("click", () => { gAcik.no++; sayfaCiz(); });
  $("#gosterici").addEventListener("click", (e) => { if (e.target.id === "gosterici") sayfaKapat(); });
  document.addEventListener("keydown", (e) => {
    if (!gAcik) return;
    if (e.key === "Escape") sayfaKapat();
    else if (e.key === "ArrowLeft" && !$("#g-onceki").disabled) $("#g-onceki").click();
    else if (e.key === "ArrowRight" && !$("#g-sonraki").disabled) $("#g-sonraki").click();
    else if (e.key === "Tab") {                       // odak pencerenin içinde kalsın
      const odak = [...$("#gosterici").querySelectorAll("button:not(:disabled), a[href]")];
      const ilk = odak[0], son = odak[odak.length - 1];
      if (e.shiftKey && document.activeElement === ilk) { e.preventDefault(); son.focus(); }
      else if (!e.shiftKey && document.activeElement === son) { e.preventDefault(); ilk.focus(); }
    }
  });

  // ---------------- Olaylar ----------------
  $("#sekme-pdf").addEventListener("click", () => sekmeSec(true));
  $("#sekme-metin").addEventListener("click", () => sekmeSec(false));
  document.querySelector(".sekmeler").addEventListener("keydown", (e) => {
    if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
      sekmeSec(!pdfSekmesi());
      (pdfSekmesi() ? $("#sekme-pdf") : $("#sekme-metin")).focus();
    }
  });
  $("#pdf-girdi").addEventListener("change", (e) => dosyaSec(e.target.files[0]));
  $("#secili-kaldir").addEventListener("click", () => { $("#pdf-girdi").value = ""; dosyaSec(null); });
  const yukle = $("#yukle");
  yukle.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); if (kitapTuru()) $("#pdf-girdi").click(); else dosyaSec({ name: ".pdf" }); } });
  yukle.addEventListener("click", (e) => { if (!kitapTuru()) { e.preventDefault(); dosyaSec({ name: ".pdf" }); } });
  document.querySelectorAll('input[name="tur"]').forEach((r) => r.addEventListener("change", () => { hataGizle(); dugmeDurumu(); }));
  ["dragenter", "dragover"].forEach((t) => yukle.addEventListener(t, (e) => { e.preventDefault(); yukle.classList.add("surukle"); }));
  ["dragleave", "drop"].forEach((t) => yukle.addEventListener(t, (e) => { e.preventDefault(); yukle.classList.remove("surukle"); }));
  yukle.addEventListener("drop", (e) => dosyaSec(e.dataTransfer.files[0]));
  $("#metin-girdi").addEventListener("input", dugmeDurumu);
  $("#ornek-btn").addEventListener("click", () => { $("#metin-girdi").value = ORNEK_METIN; dugmeDurumu(); });
  $("#denetle-btn").addEventListener("click", denetle);
  $("#ara").addEventListener("input", (e) => { arama = e.target.value; gosterilen = SAYFA_BOYUTU; listeyiCiz(); });
  $("#sirala").addEventListener("change", (e) => { siralama = e.target.value; listeyiCiz(); });
  $("#daha-btn").addEventListener("click", () => { gosterilen += SAYFA_BOYUTU; listeyiCiz(); });
  $("#yazdir-btn").addEventListener("click", () => { gosterilen = Infinity; listeyiCiz(); window.print(); });
  // Yeni denetim: sonuçlar kapanır, form temizlenir. Seçilen kitap türü ve seçenekler korunur.
  $("#yeni-btn").addEventListener("click", () => {
    $("#sonuclar").classList.add("gizli");
    $("#yeni-btn").classList.add("gizli");
    $("#pdf-girdi").value = "";
    $("#metin-girdi").value = "";
    dosyaSec(null);
    window.scrollTo({ top: 0, behavior: "smooth" });
  });
  dugmeDurumu();
})();
