"""Regenerate the sample recipes in tests/samples (PDF, DOCX, XHTML, HTML, XML, TXT).

Run:  python tests/make_samples.py
Needs reportlab and python-docx (dev only - the app itself does not need them).
"""
from pathlib import Path

HERE = Path(__file__).parent / "samples"
HERE.mkdir(exist_ok=True)

RAGU_METHOD = [
    "Heat the oil in a large casserole over a high heat. Brown the beef in batches for 5-6 minutes per batch, then lift onto a plate.",
    "Lower the heat, add the onion, carrot and celery and fry gently for 10 minutes until soft. Add the garlic and cook for 1 minute.",
    "Pour in the wine and bubble for a few minutes until reduced by half.",
    "Return the beef, add the tomatoes and stock, cover and simmer for 1 hour 30 minutes, stirring every 20 minutes.",
    "Meanwhile, cook the pappardelle in salted boiling water for 8-10 minutes, then drain.",
    "Shred the beef with two forks, toss with the pasta and serve with parmesan.",
]
RAGU_INGREDIENTS = [
    "2 tbsp olive oil", "1.5 kg beef shin, cut into large chunks", "1 onion, finely chopped",
    "1 carrot, finely chopped", "1 celery stick, finely chopped", "3 garlic cloves, crushed",
    "250 ml red wine", "2 x 400 g tins chopped tomatoes", "300 ml beef stock", "400 g pappardelle",
]


def make_pdf():
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

    ss = getSampleStyleSheet()
    story = [Paragraph("Slow-Cooked Beef Ragu", ss["Title"]),
             Paragraph("Serves: 6", ss["Normal"]), Paragraph("Prep time: 20 mins", ss["Normal"]),
             Paragraph("Cook time: 2 hrs", ss["Normal"]), Spacer(1, 10),
             Paragraph("Ingredients", ss["Heading2"])]
    story += [Paragraph(i, ss["Normal"]) for i in RAGU_INGREDIENTS]
    story += [Spacer(1, 10), Paragraph("Method", ss["Heading2"])]
    story += [Paragraph(f"{n}. {t}", ss["Normal"]) for n, t in enumerate(RAGU_METHOD, 1)]
    story += [Spacer(1, 10), Paragraph("Notes", ss["Heading2"]),
              Paragraph("The ragu freezes well for up to 3 months.", ss["Normal"])]
    # narrow frame so long steps wrap onto several lines, like real recipe PDFs
    SimpleDocTemplate(str(HERE / "beef_ragu.pdf"), pagesize=A4, leftMargin=150, rightMargin=150).build(story)


def make_docx():
    from docx import Document

    doc = Document()
    doc.add_heading("Lemon Drizzle Cake", 0)
    doc.add_paragraph("Serves 8")
    doc.add_heading("Ingredients", 1)
    for item in ["225 g unsalted butter, softened", "225 g caster sugar", "4 eggs", "225 g self-raising flour",
                 "1 lemon, zested", "For the drizzle:", "85 g caster sugar", "Juice of 1½ lemons"]:
        doc.add_paragraph(item, style="List Bullet")
    doc.add_heading("Method", 1)
    for step in [
        "Heat oven to 180C/160C fan/gas 4. Line a 2lb loaf tin with baking parchment.",
        "Beat together the butter and sugar until pale and creamy, then add the eggs one at a time.",
        "Fold in the flour and lemon zest. Spoon into the tin and level the top.",
        "Bake for 45-50 minutes until a skewer comes out clean.",
        "Mix the lemon juice and sugar. Prick the warm cake all over and pour over the drizzle.",
        "Leave in the tin until completely cool, about 30 minutes, then lift out and serve.",
    ]:
        doc.add_paragraph(step, style="List Number")  # Word auto-numbering: no "1." in the text
    doc.save(HERE / "lemon_drizzle.docx")


def make_xhtml():
    (HERE / "pancakes.xhtml").write_text("""<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
<head><title>Fluffy Pancakes | Kitchen Coach Samples</title><style>body{font-family:serif}</style></head>
<body>
<nav><a href="#">Home</a> <a href="#">Recipes</a></nav>
<h1>Fluffy American Pancakes</h1>
<p>Makes 10 pancakes</p>
<h2>Ingredients</h2>
<ul><li>200 g self-raising flour</li><li>1 tsp baking powder</li><li>1 tbsp golden caster sugar</li>
<li>3 large eggs</li><li>25 g butter, melted</li><li>200 ml milk</li></ul>
<h2>Method</h2>
<ol>
<li>Mix the flour, baking powder and sugar in a large bowl.</li>
<li>Whisk the eggs, melted butter and milk together, then whisk into the dry ingredients. Leave the batter to rest for <strong>10 minutes</strong>.</li>
<li>Heat a non-stick pan over a medium heat. Add a ladle of batter and cook for <em>about 1&#189; minutes</em>, until bubbles appear.</li>
<li>Flip and cook for 30 seconds - 1 minute on the other side.</li>
<li>Serve stacked with maple syrup and berries.</li>
</ol>
<footer>Copyright</footer>
</body></html>
""", encoding="utf-8")


def make_html_jsonld():
    (HERE / "tray_bake.html").write_text("""<!doctype html>
<html><head><title>Chicken Tray Bake - Saved page</title>
<script type="application/ld+json">
{"@context":"https://schema.org","@graph":[{"@type":"WebPage","name":"x"},
 {"@type":"Recipe","name":"Easy Chicken Tray Bake","recipeYield":"4 servings",
  "prepTime":"PT15M","cookTime":"PT45M",
  "recipeIngredient":["8 chicken thighs","500 g new potatoes, halved","2 red onions, cut into wedges","2 tbsp olive oil"],
  "recipeInstructions":[
   {"@type":"HowToSection","name":"Prep","itemListElement":[
     {"@type":"HowToStep","text":"Heat oven to 200C/180C fan."},
     {"@type":"HowToStep","text":"Toss everything with the oil and season well."}]},
   {"@type":"HowToStep","text":"Roast for 25 minutes. Turn everything over and roast for another 20 minutes until golden."},
   {"@type":"HowToStep","text":"Rest for 5 mins before serving."}]}]}
</script></head>
<body><h1>Tray bake</h1><p>Some page text that should be ignored because JSON-LD wins.</p></body></html>
""", encoding="utf-8")


def make_xml():
    (HERE / "risotto.xml").write_text("""<?xml version="1.0" encoding="UTF-8"?>
<recipeml version="0.5">
  <recipe>
    <head><title>Mushroom Risotto</title><yield>4</yield></head>
    <ingredients>
      <ing><amt><qty>1</qty><unit>litre</unit></amt><item>hot vegetable stock</item></ing>
      <ing><amt><qty>300</qty><unit>g</unit></amt><item>arborio rice</item></ing>
      <ing><amt><qty>250</qty><unit>g</unit></amt><item>chestnut mushrooms, sliced</item></ing>
      <ing><amt><qty>1</qty></amt><item>onion, finely chopped</item></ing>
      <ing><amt><qty>50</qty><unit>g</unit></amt><item>parmesan, grated</item></ing>
    </ingredients>
    <directions>
      <step>Fry the onion in a little butter for 5 minutes until soft.</step>
      <step>Add the mushrooms and cook for 3 minutes.</step>
      <step>Stir in the rice and toast for 1 minute.</step>
      <step>Add the stock a ladle at a time, stirring, for 18-20 minutes until the rice is creamy.</step>
      <step>Stir in the parmesan, cover and rest for 2 minutes. Serve.</step>
    </directions>
  </recipe>
</recipeml>
""", encoding="utf-8")


def make_txt():
    (HERE / "boiled_eggs.txt").write_text("""Perfect Soft-Boiled Eggs

Ingredients
4 large eggs, at room temperature

Method
Step 1: Bring a pan of water to a rolling boil.
Step 2: Lower in the eggs and boil for 6 minutes and 30 seconds.
Step 3: Transfer to iced water for 2 mins, then peel and serve.
""", encoding="utf-8")


if __name__ == "__main__":
    make_pdf(); make_docx(); make_xhtml(); make_html_jsonld(); make_xml(); make_txt()
    print("Samples written to", HERE)
