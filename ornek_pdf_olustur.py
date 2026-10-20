import pymupdf
doc = pymupdf.open()
page = doc.new_page()
f = "C:/Windows/Fonts/arial.ttf"  # Mac/Linux: Türkçe karakterli bir .ttf yolu yaz
page.insert_font(fontname="dj", fontfile=f)
paras = [
 "Ders Kitaplarında İçerik Denetimi",
 "Bu projede öğrenciler PDF formatındaki ders kitaplarını inceler. Herşey otomatik yapılır ve guzel sonuçlar verir.",
 "Bu konuyu anlamayan salak öğrenciler kanka gibi konuşmamalı!! Bu bu cümlede hata var ,değil mi?",
 "Öğrenciler okulda matematik dersinde problmleri çözdü ve yanlız kaldı.",
]
y = 60
for p in paras:
    page.insert_textbox(pymupdf.Rect(50,y,545,y+70), p, fontname="dj", fontsize=11)
    y += 80
doc.save("ornek.pdf")
