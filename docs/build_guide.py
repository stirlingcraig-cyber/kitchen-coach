"""Builds docs/Kitchen_Coach_User_Guide.pdf (dev tool: needs reportlab; screenshots come from
tests/e2e_browser.py).  Run:  python docs/build_guide.py"""
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (Image, KeepTogether, ListFlowable, ListItem, PageBreak, Paragraph,
                                SimpleDocTemplate, Spacer, Table, TableStyle)
from reportlab.platypus.tableofcontents import TableOfContents

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SHOTS = HERE / "screens"
OUT = HERE / "Kitchen_Coach_User_Guide.pdf"
VERSION = "1.0.0"

INK = colors.HexColor("#17251f")
GREEN = colors.HexColor("#285b43")
DARK = colors.HexColor("#0f1814")
ORANGE = colors.HexColor("#ef8a3c")
CREAM = colors.HexColor("#f6f2e9")
MUTED = colors.HexColor("#56625b")
SOFT = colors.HexColor("#fff4df")

FONT_DIR = Path("/usr/share/fonts/truetype/dejavu")
try:
    pdfmetrics.registerFont(TTFont("Body", str(FONT_DIR / "DejaVuSans.ttf")))
    pdfmetrics.registerFont(TTFont("Body-Bold", str(FONT_DIR / "DejaVuSans-Bold.ttf")))
    pdfmetrics.registerFont(TTFont("Head", str(FONT_DIR / "DejaVuSerif-Bold.ttf")))
    pdfmetrics.registerFont(TTFont("Mono", str(FONT_DIR / "DejaVuSansMono.ttf")))
    pdfmetrics.registerFontFamily("Body", normal="Body", bold="Body-Bold", italic="Body", boldItalic="Body-Bold")
    BODY, BOLD, HEAD, MONO = "Body", "Body-Bold", "Head", "Mono"
except Exception:  # fonts missing - fall back to the PDF built-ins
    BODY, BOLD, HEAD, MONO = "Helvetica", "Helvetica-Bold", "Times-Bold", "Courier"

S = {
    "body": ParagraphStyle("body", fontName=BODY, fontSize=10, leading=14.5, textColor=INK, spaceAfter=6),
    "small": ParagraphStyle("small", fontName=BODY, fontSize=8.5, leading=12, textColor=MUTED),
    "h1": ParagraphStyle("h1", fontName=HEAD, fontSize=21, leading=26, textColor=GREEN, spaceBefore=4, spaceAfter=10),
    "h2": ParagraphStyle("h2", fontName=HEAD, fontSize=13.5, leading=18, textColor=INK, spaceBefore=10, spaceAfter=5),
    "code": ParagraphStyle("code", fontName=MONO, fontSize=8.6, leading=12, textColor=INK, backColor=colors.HexColor("#eef1ec"),
                           borderPadding=(5, 6, 5, 6), spaceBefore=4, spaceAfter=9, leftIndent=6, rightIndent=6),
    "caption": ParagraphStyle("caption", fontName=BODY, fontSize=8.5, leading=11, textColor=MUTED, alignment=TA_CENTER, spaceAfter=10),
    "cell": ParagraphStyle("cell", fontName=BODY, fontSize=8.8, leading=12, textColor=INK),
    "cellb": ParagraphStyle("cellb", fontName=BOLD, fontSize=8.8, leading=12, textColor=INK),
    "toc1": ParagraphStyle("toc1", fontName=BODY, fontSize=11, leading=20, textColor=INK, leftIndent=8),
}


class Guide(SimpleDocTemplate):
    def afterFlowable(self, flowable):
        if isinstance(flowable, Paragraph) and flowable.style.name == "h1":
            text = flowable.getPlainText()
            self.notify("TOCEntry", (0, text, self.page))
            key = f"h{self.page}{abs(hash(text))}"
            self.canv.bookmarkPage(key)
            self.canv.addOutlineEntry(text, key, level=0)


def P(text, style="body"):
    return Paragraph(text, S[style])


def H1(text):
    return Paragraph(text, S["h1"])


def H2(text):
    return Paragraph(text, S["h2"])


def code(text):
    return Paragraph(text.replace("&", "&amp;").replace("<", "&lt;").replace("\n", "<br/>").replace("  ", "&nbsp;&nbsp;"), S["code"])


def bullets(items, numbered=False):
    return ListFlowable([ListItem(P(i), leftIndent=14, value=None) for i in items],
                        bulletType="1" if numbered else "bullet", start=1 if numbered else None,
                        bulletFontName=BOLD if numbered else BODY, bulletFontSize=9.5, bulletColor=ORANGE,
                        leftIndent=16, spaceAfter=6)


def tip(text, title="Tip"):
    t = Table([[P(f"<b>{title}</b>&nbsp;&nbsp;{text}")]], colWidths=[170 * mm])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), SOFT), ("BOX", (0, 0), (-1, -1), 0.6, ORANGE),
                           ("LEFTPADDING", (0, 0), (-1, -1), 9), ("RIGHTPADDING", (0, 0), (-1, -1), 9),
                           ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
    return KeepTogether([t, Spacer(1, 8)])


def shot(name, caption, width_mm=165):
    path = SHOTS / name
    if not path.exists():
        return P(f"[screenshot {name} missing - run tests/e2e_browser.py]", "small")
    img = Image(str(path))
    ratio = img.imageHeight / img.imageWidth
    img.drawWidth = width_mm * mm
    img.drawHeight = width_mm * mm * ratio
    return KeepTogether([img, P(caption, "caption")])


def phones(names_captions):
    cells, caps = [], []
    for name, cap in names_captions:
        img = Image(str(SHOTS / name))
        w = 52 * mm
        img.drawWidth, img.drawHeight = w, w * img.imageHeight / img.imageWidth
        cells.append(img)
        caps.append(P(cap, "caption"))
    t = Table([cells, caps], colWidths=[57 * mm] * len(cells))
    t.setStyle(TableStyle([("ALIGN", (0, 0), (-1, -1), "CENTER"), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    return t


def table(rows, widths, header=True):
    data = [[P(c, "cellb" if (header and r == 0) else "cell") for c in row] for r, row in enumerate(rows)]
    t = Table(data, colWidths=[w * mm for w in widths], repeatRows=1 if header else 0)
    style = [("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#ccd3cc")), ("VALIGN", (0, 0), (-1, -1), "TOP"),
             ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]
    if header:
        style.append(("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e4e9e3")))
    t.setStyle(TableStyle(style))
    return KeepTogether([t, Spacer(1, 10)])


def cover(canvas, doc):
    w, h = A4
    canvas.saveState()
    canvas.setFillColor(DARK)
    canvas.rect(0, 0, w, h, stroke=0, fill=1)
    canvas.setFillColor(colors.HexColor("#1d3a2d"))
    canvas.circle(w * 0.85, h * 0.92, 210, stroke=0, fill=1)
    icon = ROOT / "web" / "icons" / "icon-512.png"
    if icon.exists():
        canvas.drawImage(str(icon), 25 * mm, h - 95 * mm, 52 * mm, 52 * mm, mask="auto")
    canvas.setFillColor(ORANGE)
    canvas.setFont(BOLD, 10)
    canvas.drawString(25 * mm, h - 115 * mm, "USER GUIDE  ·  INSTALLATION  ·  GITHUB & IPHONE")
    canvas.setFillColor(CREAM)
    canvas.setFont(HEAD, 44)
    canvas.drawString(25 * mm, h - 138 * mm, "Kitchen Coach")
    canvas.setFont(BODY, 16)
    canvas.setFillColor(colors.HexColor("#c9d3cc"))
    canvas.drawString(25 * mm, h - 152 * mm, "Your recipe, one spoken, timed step at a time.")
    shotp = SHOTS / "05_cook_running.png"
    if shotp.exists():
        canvas.drawImage(str(shotp), 25 * mm, 38 * mm, 160 * mm, 160 * mm * 860 / 1180)
    canvas.setFont(BODY, 9)
    canvas.setFillColor(colors.HexColor("#a8b5ad"))
    canvas.drawString(25 * mm, 22 * mm, f"Version {VERSION}  ·  Windows desktop and iPhone")
    canvas.restoreState()


def later(canvas, doc):
    w, h = A4
    canvas.saveState()
    canvas.setStrokeColor(colors.HexColor("#dfe4de"))
    canvas.line(20 * mm, h - 15 * mm, w - 20 * mm, h - 15 * mm)
    canvas.setFont(BODY, 8)
    canvas.setFillColor(MUTED)
    canvas.drawString(20 * mm, h - 12 * mm, "Kitchen Coach - User Guide")
    canvas.drawRightString(w - 20 * mm, 10 * mm, f"Page {doc.page}")
    canvas.restoreState()


def build():
    story = [PageBreak()]
    toc = TableOfContents()
    toc.levelStyles = [S["toc1"]]
    story += [H2("Contents"), toc, PageBreak()]

    # ------------------------------------------------------------------ 1
    story += [H1("1. Welcome"),
              P("Kitchen Coach turns a recipe file into a hands-free cooking guide. Upload a PDF, Word, XML or "
                "XHTML recipe and it finds the ingredients, every method step and every time mentioned in the "
                "method. Then it reads each step aloud, shows a large countdown timer, chimes and speaks when "
                "time is up, and lets timers carry on in the background while you move on to the next job."),
              P("There are two versions, built from the same code:"),
              table([["", "Windows desktop", "iPhone"],
                     ["How you open it", "Desktop icon (and automatically when you sign in)", "Home-screen icon"],
                     ["Looks like", "Its own app window", "Full-screen app"],
                     ["Reads recipes with", "The local Python engine on your PC", "The phone itself - no internet needed"],
                     ["Saved recipes", "Kept on the PC", "Kept on the phone"],
                     ["Install from", "Install.bat (exe or source)", "GitHub Pages + Add to Home Screen"]],
                    [36, 67, 67]),
              H2("What's in the package"),
              table([["File / folder", "What it is"],
                     ["app.py", "The local recipe engine and web server (your original Flask app, rebuilt)"],
                     ["launcher.py", "Starts the engine, opens the app window, closes down when you close it"],
                     ["recipe_parser.py", "Reads the recipe files and works out steps and timers"],
                     ["web/", "The app screens - also the iPhone version published on GitHub Pages"],
                     ["windows/Install.bat", "Double-click installer (desktop icon + automatic launch)"],
                     ["windows/Build-Exe.ps1", "Builds KitchenCoach.exe (GitHub does this for you)"],
                     [".github/workflows/", "Automatic tests, iPhone publishing and Windows exe build"],
                     ["tests/", "70+ automatic checks and six sample recipes in every supported format"],
                     ["docs/", "This guide and the screenshots"]],
                    [45, 125]),
              PageBreak()]

    # ------------------------------------------------------------------ 2
    story += [H1("2. Install on Windows"),
              P("You can install the <b>ready-built app</b> (easiest - no Python needed) or <b>from the source "
                "code</b> (needs Python). Both give you the same desktop icon, Start menu entry and automatic "
                "launch when you sign in. No administrator rights are needed."),
              H2("Option A - ready-built app (recommended)"),
              bullets(["On GitHub, open your <b>kitchen-coach</b> repository and click <b>Releases</b> "
                       "(or <b>Actions &gt; Windows build</b> and download the <b>KitchenCoach-Windows</b> artifact) - "
                       "see section 4 for how GitHub builds it.",
                       "Download <b>KitchenCoach-Windows.zip</b>, right-click it and choose <b>Extract All</b>.",
                       "Open the extracted folder and double-click <b>Install.bat</b>.",
                       "A black window shows progress. When it finishes, Kitchen Coach opens and a "
                       "<b>Kitchen Coach</b> icon is on your desktop."], numbered=True),
              tip("Windows may show <b>Windows protected your PC</b> the first time, because the app is not signed "
                  "by a big publisher. Click <b>More info</b> then <b>Run anyway</b>.", "SmartScreen"),
              H2("Option B - from the source code"),
              bullets(["Install <b>Python 3.10 or newer</b> from python.org. On the first installer screen tick "
                       "<b>Add python.exe to PATH</b>.",
                       "On GitHub click <b>Code &gt; Download ZIP</b>, then extract it.",
                       "Open the <b>windows</b> folder and double-click <b>Install.bat</b>. It creates a private "
                       "Python environment, installs Flask, pypdf, defusedxml and waitress, and makes the shortcuts."],
                      numbered=True),
              H2("Desktop icon and automatic launch"),
              P("The installer creates three shortcuts:"),
              bullets(["<b>Desktop</b> - Kitchen Coach (double-click to open).",
                       "<b>Start menu</b> - Kitchen Coach, and Uninstall Kitchen Coach.",
                       "<b>Startup</b> - opens Kitchen Coach automatically each time you sign in to Windows."]),
              P("To stop the automatic launch, either run the installer again with the switch below, or press "
                "<b>Win + R</b>, type <b>shell:startup</b>, press Enter and delete the Kitchen Coach shortcut. "
                "You can also turn it off in <b>Task Manager &gt; Startup apps</b>."),
              code("windows\\Install.bat -NoStartup"),
              H2("How the Windows app runs"),
              P("Kitchen Coach starts a small private engine on your PC (address 127.0.0.1:8765 - nothing on your "
                "network can reach it) and opens it in its own Microsoft Edge app window, with no tabs or address "
                "bar. When you close the window, the engine shuts itself down within about 20 seconds. Opening the "
                "icon again while it is running simply opens another window."),
              H2("Uninstall"),
              P("Start menu &gt; <b>Uninstall Kitchen Coach</b>. Your saved recipes are kept in "
                "<b>%LOCALAPPDATA%\\KitchenCoach</b> in case you reinstall. To delete them too, run:"),
              code('powershell -ExecutionPolicy Bypass -File "%LOCALAPPDATA%\\Programs\\KitchenCoach\\Uninstall-KitchenCoach.ps1" -RemoveData'),
              PageBreak()]

    # ------------------------------------------------------------------ 3
    story += [H1("3. Install on iPhone"),
              P("The iPhone version is a full-screen web app that you add to your Home Screen from Safari. It gets "
                "its own icon, opens without any browser bars, reads recipes on the phone itself and works "
                "offline once it has been opened once. You need the GitHub Pages address from section 4 first."),
              bullets(["On the iPhone, open <b>Safari</b> (it must be Safari) and go to "
                       "<b>https://YOUR-USERNAME.github.io/kitchen-coach/</b>.",
                       "Tap the <b>Share</b> button (square with an arrow).",
                       "Scroll down and tap <b>Add to Home Screen</b>. Leave the name as Kitchen Coach and tap <b>Add</b>.",
                       "Open Kitchen Coach from the new Home Screen icon. Tap <b>Try a sample recipe</b> to check it works.",
                       "To use your own recipes, tap <b>Choose a recipe file</b> and pick a file from <b>Files</b>, iCloud "
                       "Drive, OneDrive or an email attachment you have saved to Files."], numbered=True),
              phones([("11_iphone_home.png", "Home screen"), ("12_iphone_review.png", "Check the steps"),
                      ("13_iphone_cook.png", "Cooking")]),
              H2("Getting the best from it on iPhone"),
              bullets(["<b>Turn the ring/silent switch off</b> (or Action button to Ring) and turn the volume up - the "
                       "spoken steps and chimes follow the ringer volume.",
                       "Leave Kitchen Coach <b>on screen</b> while timers run. Kitchen Coach keeps the screen awake while you "
                       "cook, but iOS pauses any app you switch away from, so alarms can't sound in the background. "
                       "When you come back, finished timers ring straight away and the countdowns are still correct.",
                       "If the screen still dims, set <b>Settings &gt; Display &amp; Brightness &gt; Auto-Lock</b> to "
                       "<b>Never</b> while cooking.",
                       "Requires iOS 16.4 or later. Recipes and settings stay on the phone."]),
              H2("About “sideloading”"),
              P("A true native iPhone app (.ipa) can only be sideloaded with a Mac running Xcode, or a tool such as "
                "AltStore, and it must be re-signed with your Apple ID every 7 days. The Home Screen web app gives "
                "you the same icon, full-screen launch and offline use without any of that, which is why this "
                "package uses it. If you later want an App Store or TestFlight build, the web/ folder can be wrapped "
                "with Capacitor on a Mac without changing the app code."),
              PageBreak()]

    # ------------------------------------------------------------------ 4
    story += [H1("4. Put it on GitHub"),
              P("GitHub stores the code, publishes the iPhone app and builds the Windows .exe for you - you never "
                "have to build anything yourself."),
              H2("Upload the code (no command line)"),
              bullets(["Sign in at github.com and click <b>+ &gt; New repository</b>. Name it <b>kitchen-coach</b>. "
                       "Choose <b>Public</b> (GitHub Pages on a free account needs a public repository). Click <b>Create repository</b>.",
                       "Click <b>uploading an existing file</b>. Unzip kitchen-coach.zip on your PC and drag "
                       "<b>everything inside the kitchen-coach folder</b> into the page, including the hidden "
                       "<b>.github</b> folder (in File Explorer: View &gt; Show &gt; Hidden items).",
                       "Click <b>Commit changes</b>."], numbered=True),
              tip("If the .github folder won't drag in, use the command-line method below, or create the three "
                  "workflow files with <b>Add file &gt; Create new file</b> and paths starting <b>.github/workflows/</b>."),
              H2("Upload the code (Git command line)"),
              code("cd kitchen-coach\ngit init\ngit add .\ngit commit -m \"Kitchen Coach 1.0.0\"\ngit branch -M main\n"
                   "git remote add origin https://github.com/YOUR-USERNAME/kitchen-coach.git\ngit push -u origin main"),
              H2("Publish the iPhone app (GitHub Pages)"),
              bullets(["In the repository open <b>Settings &gt; Pages</b>.",
                       "Under <b>Build and deployment &gt; Source</b> choose <b>GitHub Actions</b>.",
                       "Open the <b>Actions</b> tab, choose <b>Deploy iPhone web app to GitHub Pages</b>, click "
                       "<b>Run workflow</b>. After about a minute your app is live at "
                       "<b>https://YOUR-USERNAME.github.io/kitchen-coach/</b>. It updates automatically whenever you "
                       "change files in web/."], numbered=True),
              H2("Build the Windows app"),
              bullets(["<b>Actions &gt; Windows build &gt; Run workflow</b>. GitHub builds KitchenCoach.exe on a Windows "
                       "machine, test-installs it, checks it starts, and offers <b>KitchenCoach-Windows.zip</b> under "
                       "<b>Artifacts</b> at the bottom of the run.",
                       "For a proper download page, create a release: <b>Releases &gt; Draft a new release</b>, tag "
                       "<b>v1.0.0</b>, <b>Publish</b>. The build runs and attaches the zip to the release automatically."],
                      numbered=True),
              P("Every push also runs the <b>Tests</b> workflow, which checks the recipe reader against all the "
                "sample recipes and confirms the Windows and iPhone readers give identical results."),
              PageBreak()]

    # ------------------------------------------------------------------ 5
    story += [H1("5. Using Kitchen Coach"),
              H2("1 - Add a recipe"),
              P("On the home screen click <b>Choose a recipe file</b> (or drag a file onto the box on Windows). "
                "Supported: <b>PDF</b> (text-based), <b>Word .docx</b>, <b>XML</b>, <b>XHTML</b>, <b>HTML</b> (e.g. a "
                "recipe web page saved with Ctrl+S) and <b>TXT</b>. Recipes you have saved are listed underneath - "
                "<b>Cook</b> starts straight away, <b>Open</b> lets you edit first."),
              shot("01_home.png", "The home screen", 150),
              H2("2 - Check the steps"),
              P("Kitchen Coach shows what it found: title, serves/prep/cook times, ingredients (tick them off as you "
                "weigh out) and the method steps with their timers. Always give this a quick look - you can:"),
              bullets(["edit any step's wording (the box grows as you type)",
                       "change a timer (minutes and seconds; 0 and 0 means no timer)",
                       "move steps up or down, delete them, or <b>+ Add a step</b>",
                       "read the orange notes, e.g. <i>Recipe gives 45-50 min. Timer uses the shorter time</i>"]),
              P("<b>Save</b> keeps the recipe in your list. <b>Start cooking</b> saves it and begins."),
              shot("02_review.png", "Checking the steps and timers", 150),
              PageBreak(),
              H2("3 - Cook"),
              P("Cooking mode fills the screen. Each step is read aloud. If the step has a time, the ring shows it."),
              table([["Control", "What it does"],
                     ["Start timer / Pause / Resume", "The big button. Starts, pauses and resumes this step's timer."],
                     ["Stop alarm", "Shown when time is up - stops the chime (it repeats every 20 s for 2 minutes)."],
                     ["Next step (green arrow)", "Moves on. A running timer keeps going in the tray at the bottom."],
                     ["Back (left arrow)", "Previous step."],
                     ["Repeat", "Reads the step again."],
                     ["+1 min", "Adds a minute. On a step without a timer it starts a 1-minute timer."],
                     ["Restart timer", "Starts this step's timer again from the full time - handy for the second "
                                       "side of a steak or a second batch."],
                     ["Ingredients (top right)", "Shows the ingredients list."],
                     ["X (top left)", "Stop cooking (asks first if timers are running)."]],
                    [52, 118]),
              shot("05_cook_running.png", "A step with its timer running", 150),
              H2("Background timers"),
              P("When you press Next while a timer is still running, it moves to the <b>tray</b> at the bottom - for "
                "example <i>Step 2 09:40</i> - and keeps counting. When it finishes, it chimes, speaks "
                "(<i>Time's up for step 2: Lower the heat...</i>) and turns green. Tap a green pill to stop it, or tap a "
                "running pill to jump back to that step."),
              shot("07_cook_background_timer.png", "Step 3 is on screen while step 2's timer runs in the tray", 150),
              H2("Keyboard shortcuts (Windows)"),
              table([["Key", "Action"], ["Space or Enter", "Start / pause / resume / stop alarm"],
                     ["Right arrow or N", "Next step"], ["Left arrow or B", "Previous step"], ["R", "Repeat the step"],
                     ["+", "Add a minute"], ["Esc", "Stop cooking"]], [45, 125]),
              H2("If the app is closed mid-recipe"),
              P("Kitchen Coach saves your place every few seconds. Next time you open it you'll see "
                "<b>Cooking in progress - Resume</b>. Timers carry on from the right time; any that finished while it "
                "was closed ring as soon as you resume."),
              H2("Settings (gear icon)"),
              table([["Setting", "Default", "Notes"],
                     ["Speak steps and alerts aloud", "On", "Turn off for chimes only."],
                     ["Voice", "Default", "On Windows, the Microsoft … Online (Natural) English (UK) voices sound best."],
                     ["Speaking speed", "1.0", "0.6 (slow) to 1.5 (fast)."],
                     ["Start each step's timer automatically", "Off", "Off means you press Start when the food is in the pan."],
                     ["Chime when a timer finishes", "On", ""],
                     ["Keep chiming until I respond", "On", "Repeats every 20 seconds for up to 2 minutes."],
                     ["Keep the screen awake while cooking", "On", ""]], [62, 22, 86]),
              PageBreak()]

    # ------------------------------------------------------------------ 6
    story += [H1("6. How recipes are read"),
              P("Kitchen Coach looks for an <b>Ingredients</b> section and a <b>Method</b> section (also Instructions, "
                "Directions, Preparation, Steps, How to make it, To serve). Within the method it uses, in order of "
                "preference: numbered steps (1. 1) Step 1 and Word's automatic numbering); otherwise each paragraph. "
                "Saved web pages that contain schema.org recipe data (most big recipe sites) are read from that data, "
                "which is the most accurate of all."),
              H2("How times become timers"),
              table([["Recipe says", "Timer", "Notes shown"],
                     ["Bake for 25 minutes / 25 mins / 25 min", "25:00", ""],
                     ["Simmer for 1 hour 30 minutes / 1½ hours / 1h30", "1:30:00", ""],
                     ["Half an hour / an hour / twenty minutes", "30:00 / 1:00:00 / 20:00", ""],
                     ["Bake for 45-50 minutes", "45:00", "Uses the shorter time - check, then +1 min if needed"],
                     ["Cook for a few minutes / several minutes", "3:00 / 5:00", "Flagged as an estimate"],
                     ["Simmer 20 minutes, stirring every 5 minutes", "20:00", "“every 5 minutes” is ignored"],
                     ["Fry 3-4 minutes on each side", "3:00", "Reminder to Restart timer for the other side"],
                     ["Marinate overnight", "none", "Set your own reminder"],
                     ["Fry the onions for 8 minutes. Add the spices and cook 1 minute.", "two steps",
                      "Long steps with several timed actions are split"]], [72, 30, 68]),
              H2("Tips for the best results"),
              bullets(["Use <b>text-based PDFs</b> (ones where you can select the words). A scanned photo of a page has no "
                       "text - copy the recipe into Word and upload the .docx instead.",
                       "Old <b>.doc</b> files: open in Word and <b>File &gt; Save As &gt; Word Document (.docx)</b>.",
                       "Recipe web pages: in Edge or Chrome press <b>Ctrl+S</b> and save as <b>Webpage, HTML only</b>, then upload the .html file.",
                       "Headings called Ingredients and Method, and numbered steps, give the most reliable result.",
                       "Maximum file size 15 MB; up to 80 steps and 60 PDF pages."]),
              PageBreak()]

    # ------------------------------------------------------------------ 7
    story += [H1("7. Troubleshooting"),
              table([["Problem", "What to do"],
                     ["Nothing happens when I double-click the icon",
                      "Wait 5 seconds - the first start takes a moment. If still nothing, check the log at "
                      "%LOCALAPPDATA%\\KitchenCoach\\kitchen_coach.log, then reinstall with Install.bat."],
                     ["“Windows protected your PC”", "Click More info, then Run anyway (section 2)."],
                     ["Install.bat says Python was not found", "Use the ready-built zip, or install Python 3.10+ with "
                                                                "Add python.exe to PATH ticked, then run Install.bat again."],
                     ["No speech", "Check Settings > Speak aloud is on and use Test voice. On iPhone turn off silent mode "
                                   "and raise the volume. On Windows check a speaker/headphones is the default output."],
                     ["Timer alarm didn't sound on iPhone", "Kitchen Coach must stay on screen; iOS pauses background apps. "
                                                            "Set Auto-Lock to Never while cooking."],
                     ["“This PDF has no readable text”", "It's a scanned image. Copy the recipe into Word or a text file."],
                     ["Steps or timers look wrong", "Edit them on the Check the steps screen before you start, then Save."],
                     ["The app opened in a normal browser tab", "Microsoft Edge wasn't found, so your default browser was "
                                                                "used. Everything still works."],
                     ["Saved recipes disappeared on Windows", "Recipes are stored in the Kitchen Coach window's own profile. "
                      "If port 8765 was busy, Kitchen Coach used another port (see the log) - close the program using 8765 "
                      "and reopen."],
                     ["iPhone shows an old version after an update", "Close the app fully (swipe up) and open it twice - the "
                                                                     "new version downloads in the background."],
                     ["GitHub Pages shows 404", "Settings > Pages > Source must be GitHub Actions and the Deploy workflow "
                                                "must have run successfully (green tick in Actions)."]],
                    [55, 115]),
              PageBreak()]

    # ------------------------------------------------------------------ 8
    story += [H1("8. What was improved from the original code"),
              P("Your original Flask program was the starting point: the upload form, PDF/DOCX/XML reading, the "
                "numbered-step and duration detection, the step editor and the spoken timer. It has been rebuilt "
                "and error-checked. These are the problems found and fixed:"),
              table([["Original behaviour", "Fix"],
                     ["Timer counted down by subtracting 1 every second, so it drifted and froze when the window was "
                      "in the background", "Timers use the real clock, run from a background worker, and survive pauses, "
                      "minimising and app restarts"],
                     ["Ingredients such as “1.5 kg beef” were treated as numbered steps", "Numbering must be "
                      "followed by a space and must run in sequence (1, 2, 3...)"],
                     ["“1 hour 30 minutes” gave a 60-minute timer", "Hours, minutes and seconds are combined; "
                      "fractions, words (half an hour) and ranges understood"],
                     ["“Stir every 5 minutes” created a timer", "Repeating instructions are ignored"],
                     ["XML was read with ElementTree, open to entity-expansion (“billion laughs”) attacks",
                      "Uses defusedxml; DTD entities are refused"],
                     ["XHTML text inside &lt;b&gt;, &lt;em&gt;, &lt;span&gt; was split into separate broken steps; scripts, styles and "
                      "menus were read as steps", "Proper block/inline handling; script, style, nav and footer skipped; "
                      "ordered lists numbered"],
                     ["Word's automatic numbering (and tables) were invisible, so ingredients became steps",
                      "Reads Word numbering definitions and tables"],
                     ["PDF lines that wrapped mid-sentence lost the end of the step (often the time)",
                      "Wrapped lines are joined back to their step"],
                     ["Raw Python error messages were shown; files over 15 MB gave a bare error page",
                      "Friendly messages for every failure (scanned PDF, password, .doc, damaged file, too large)"],
                     ["Only one timer at a time; moving on cancelled it", "Background timer tray with alarms"],
                     ["Speech only on page load; no chime; screen could sleep", "Chime, repeating alarm, wake lock, "
                      "voice choice and speed"],
                     ["Edits were lost on reload; nothing saved", "Recipe library and resumable cooking sessions"],
                     ["Ran on Flask's development server", "Runs on waitress, bound to 127.0.0.1 with host checking"],
                     ["Windows-only, browser tab, no icon", "Desktop/Start/Startup shortcuts, app window, .exe build; "
                      "offline iPhone app"]], [85, 85]),
              H2("Checks that were run"),
              bullets(["59 Python tests: every sample format, 20+ duration phrases, safety cases (entity attacks, "
                       "damaged/encrypted/scanned files, oversized uploads, path traversal, foreign host names).",
                       "14 JavaScript tests proving the iPhone reader gives exactly the same result as the Windows reader.",
                       "A full browser run in Chromium: each sample read by both engines with identical results; start, "
                       "pause, finish, background timer, +1 min, alarm stop, reload-and-resume, finish; iPhone-sized layout.",
                       "The Windows build workflow installs the .exe on a real Windows machine, starts it and checks it "
                       "answers, then uninstalls it, and also tests the from-source install."]),
              PageBreak()]

    # ------------------------------------------------------------------ 9
    story += [H1("9. Technical reference"),
              H2("Run from source for development"),
              code("pip install -r requirements-dev.txt\npython app.py                 # open http://127.0.0.1:8765\n"
                   "python -m pytest -q          # Python tests\nnpm test                      # JS parser parity tests\n"
                   "python tests/build_fixtures.py   # after changing reading rules\n"
                   "python tests/e2e_browser.py      # browser test + screenshots"),
              H2("Launcher options"),
              table([["Command", "Effect"], ["KitchenCoach.exe", "Normal start"],
                     ["KitchenCoach.exe --browser", "Open in your normal browser instead of an app window"],
                     ["KitchenCoach.exe --keep-running", "Don't stop the engine when the window closes"],
                     ["KitchenCoach.exe --no-window --port 8765", "Engine only (testing)"]], [70, 100]),
              H2("Where things are stored"),
              table([["Item", "Location"],
                     ["Program", "%LOCALAPPDATA%\\Programs\\KitchenCoach"],
                     ["Saved recipes and settings (Windows)", "%LOCALAPPDATA%\\KitchenCoach\\window-profile"],
                     ["Log file", "%LOCALAPPDATA%\\KitchenCoach\\kitchen_coach.log"],
                     ["Saved recipes (iPhone)", "Inside the Home Screen app's own storage"]], [65, 105]),
              H2("Privacy and security"),
              P("Recipe files never leave your device. The Windows engine listens only on 127.0.0.1, rejects any "
                "request not addressed to this computer, limits uploads to 15 MB and never shows internal errors. "
                "The app has a strict Content Security Policy and loads nothing from the internet; pdf.js and JSZip "
                "are bundled. Licence: MIT (pdf.js Apache-2.0, JSZip MIT)."),
              ]

    doc = Guide(str(OUT), pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm, topMargin=22 * mm,
                bottomMargin=18 * mm, title="Kitchen Coach - User Guide", author="Kitchen Coach",
                subject="Installation and user guide")
    doc.multiBuild(story, onFirstPage=cover, onLaterPages=later)
    print("Wrote", OUT)


if __name__ == "__main__":
    build()
