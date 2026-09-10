# -*- coding: utf-8 -*-
"""Build the client-facing ViaBolat mockups, one per prospect segment.

Each variant is a self-contained HTML file: fonts, React and the icon set are
embedded, so it renders with no network access. The heavy assets are lifted from
BASE_BUNDLE and never rebuilt -- only the template block is swapped.

    python3 mockup/build_variants.py

Edit BRAND below, then re-run. Sample deadlines are stored as offsets in days and
formatted at render time, so a file mailed today still reads correctly next month.
"""
import io, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BASE_BUNDLE = os.path.join(ROOT, "ViaBolat - machetă.html")
TEMPLATE_SRC = os.path.join(HERE, "template.src.html")
OUT_DIR = os.path.join(HERE, "dist")

# ---------------------------------------------------------------------------
# EDIT THIS BLOCK, then re-run. Placeholders in [square brackets] are reported
# as unfilled and must not go out to a prospect.
# ---------------------------------------------------------------------------
BRAND = {
    "name":    "ViaBolat",
    "tagline": "Urmărim automat sursele de finanțare europene și naționale și vă semnalăm doar apelurile care se potrivesc organizației dumneavoastră.",
    "email":   "ahmet@viabolat.com",
    "phone":   "+40 741 716 553",
    "site":    "viabolat.com",
    "cta_label":   "Programați o demonstrație",
    "cta_subject": "ViaBolat — solicitare demonstrație",
    "next_step":   "Pasul următor: o discuție de 30 de minute în care configurăm profilul organizației dumneavoastră și vă arătăm apelurile reale, deschise în acest moment.",
}

MUTED = "color-mix(in srgb,var(--color-text) 55%,transparent)"


def call(cid, source, title, prog, budget_short, budget, days, seen_days,
         programme_line, match_reason, tags, status, assignee, note=""):
    """One sample row. `days` is an offset from today; None means no deadline."""
    return dict(id=cid, source=source, title=title, prog=prog,
                budgetShort=budget_short, budget=budget, days=days,
                seenDays=seen_days, programmeLine=programme_line,
                matchReason=match_reason, tags=tags, status=status,
                assignee=assignee, note=note)


VARIANTS = {
    # ---------------------------------------------------------------- generic
    "general": {
        "title": "ViaBolat",
        "org_type": "Organizație neguvernamentală",
        "profile_terms": ["dezvoltare comunitară", "digitalizare", "formare profesională", "mediu"],
        "subtitle": "Urmărește și triază într-un singur loc apelurile de finanțare din surse europene și naționale, filtrate după profilul organizației dumneavoastră.",
        "calls": [
            call("c1", "eu", "Digitalizarea serviciilor publice locale", "Europa Digitală",
                 "12 mil. €", "12.000.000 €", 12, 14,
                 "Programul Europa Digitală · Portalul Funding & Tenders",
                 "Termeni din profilul organizației: „digitalizare”, „servicii publice” — în titlul și în descrierea apelului.",
                 ["digitalizare", "servicii publice", "administrație locală"], "new", "Ana M.",
                 "Se potrivește cu direcția noastră strategică — de verificat regulile de cofinanțare."),
            call("c2", "eu", "Formare profesională și competențe verzi", "Erasmus+",
                 "8 mil. €", "8.000.000 €", 46, 17,
                 "Erasmus+ · Portalul Funding & Tenders",
                 "Termen din profilul organizației: „formare profesională” — în descrierea apelului.",
                 ["educație", "formare profesională", "tranziție verde"], "relevant", "Ana M."),
            call("c3", "ro", "Economie socială și incluziune activă", "POEO",
                 "900 mii lei", "900.000 lei", 27, 4, "POEO · adieuronest.ro",
                 "Termeni din profilul organizației: „dezvoltare comunitară”, „formare profesională” — în descrierea apelului.",
                 ["economie socială", "incluziune", "POEO"], "review", "—"),
            call("c4", "ro", "Sprijin pentru ONG-uri și inițiative comunitare", "PNRR",
                 "500 mii lei", "500.000 lei", 2, 24, "PNRR · adieuronest.ro",
                 "Categorie eligibilă: ong. Termen din profil: „comunitar”.",
                 ["ong", "dezvoltare comunitară", "PNRR"], "applied", "Dan P.",
                 "Depus — așteptăm evaluarea."),
            call("c5", "ro", "Regenerare urbană și spații publice verzi", "adieuronest",
                 "1,2 mil. lei", "1.200.000 lei", 6, 13, "adieuronest.ro",
                 "Termeni din profilul organizației: „regenerare urbană”, „spații publice”.",
                 ["regenerare urbană", "mediu", "comunitate"], "new", "—"),
        ],
    },
    # ------------------------------------------------- health / patient support
    "sanatate": {
        "title": "ViaBolat — sănătate și sprijinul pacienților",
        "org_type": "Organizație neguvernamentală din domeniul sănătății",
        "profile_terms": ["cancer", "terapii complementare", "psihoterapie", "nutriție"],
        "subtitle": "Configurat pentru organizațiile din domeniul sănătății: urmărește și triază într-un singur loc apelurile de sprijinire a pacienților, sănătate mintală și prevenție din surse europene și naționale.",
        "calls": [
            call("c1", "eu", "Consolidarea programelor de screening pentru cancer și a depistării precoce", "EU4Health",
                 "6 mil. €", "6.000.000 €", 12, 14,
                 "Programul EU4Health (EU4H) · Portalul Funding & Tenders",
                 "Termeni din profilul organizației: „screening”, „cancer” — în titlul apelului.",
                 ["cancer", "screening", "prevenție"], "new", "Ana M.",
                 "Se potrivește cu programul nostru de informare — de verificat regulile de cofinanțare."),
            call("c2", "eu", "Sprijin psihosocial și calitatea vieții pentru supraviețuitorii de cancer", "Orizont Europa — Misiunea Cancer",
                 "10 mil. €", "10.000.000 €", 46, 18,
                 "Orizont Europa · Misiunea „Cancer” · Portalul Funding & Tenders",
                 "Termeni din profilul organizației: „supraviețuitori de cancer”, „sprijin psihosocial” — în titlul apelului.",
                 ["oncologie", "sprijin psihosocial", "calitatea vieții"], "relevant", "Ana M."),
            call("c3", "ro", "Dezvoltarea serviciilor de îngrijire paliativă și la domiciliu", "Programul Operațional Sănătate",
                 "2,5 mil. lei", "2.500.000 lei", 27, 4, "POS · adieuronest.ro",
                 "Termeni din profilul organizației: „paliativ”, „pacient” — în descrierea apelului.",
                 ["îngrijire paliativă", "pacienți", "POS"], "review", "—"),
            call("c4", "ro", "Servicii comunitare de sănătate mintală și sprijin emoțional", "PNRR — Componenta Sănătate",
                 "800 mii lei", "800.000 lei", 2, 24, "PNRR · adieuronest.ro",
                 "Categorie eligibilă: sănătate. Termeni din profil: „sănătate mintală”, „sprijin emoțional”.",
                 ["sănătate mintală", "sprijin emoțional", "PNRR"], "applied", "Dan P.",
                 "Depus — așteptăm evaluarea."),
            call("c5", "ro", "Programe de nutriție și terapii complementare pentru pacienți oncologici", "adieuronest",
                 "1,1 mil. lei", "1.100.000 lei", 6, 13, "adieuronest.ro",
                 "Termeni din profilul organizației: „nutriție”, „terapii complementare”, „pacienți oncologici”.",
                 ["nutriție", "terapii complementare", "oncologie"], "new", "—"),
        ],
    },
    # ----------------------------------------------------------- municipality
    "primarii": {
        "title": "ViaBolat — administrație publică locală",
        "org_type": "Autoritate publică locală",
        "profile_terms": ["regenerare urbană", "mobilitate urbană", "eficiență energetică", "infrastructură locală"],
        "subtitle": "Configurat pentru administrația publică locală: urmărește și triază într-un singur loc apelurile de regenerare urbană, mobilitate și infrastructură din surse europene și naționale.",
        "calls": [
            call("c1", "eu", "Regenerarea zonelor urbane degradate și a spațiilor publice", "Inițiativa Urbană Europeană",
                 "5 mil. €", "5.000.000 €", 12, 15,
                 "Inițiativa Urbană Europeană (EUI) · Portalul Funding & Tenders",
                 "Termeni din profilul organizației: „regenerare urbană”, „spații publice” — în titlul apelului.",
                 ["regenerare urbană", "spații publice", "coeziune"], "new", "Ana M.",
                 "Se potrivește cu masterplanul zonei centrale — de verificat cota de cofinanțare."),
            call("c2", "eu", "Mobilitate urbană durabilă și transport public curat", "Orizont Europa",
                 "8 mil. €", "8.000.000 €", 46, 19,
                 "Orizont Europa · Misiunea „Orașe neutre climatic”",
                 "Termeni din profilul organizației: „mobilitate urbană”, „transport public”.",
                 ["mobilitate urbană", "transport public", "neutralitate climatică"], "relevant", "Ana M."),
            call("c3", "ro", "Modernizarea rețelelor de apă și canalizare", "POR",
                 "3 mil. lei", "3.000.000 lei", 27, 4, "POR · adieuronest.ro",
                 "Termen din profilul organizației: „infrastructură locală” — în titlul apelului.",
                 ["infrastructură locală", "utilități", "POR"], "review", "—"),
            call("c4", "ro", "Reabilitarea energetică a clădirilor publice", "PNRR",
                 "4,5 mil. lei", "4.500.000 lei", 2, 26, "PNRR · adieuronest.ro",
                 "Categorie eligibilă: autorități. Termen din profil: „eficiență energetică”.",
                 ["eficiență energetică", "clădiri publice", "PNRR"], "applied", "Dan P.",
                 "Depus pentru corpul de clădire al școlii gimnaziale — așteptăm evaluarea."),
            call("c5", "ro", "Amenajarea zonelor pietonale și a pistelor de biciclete", "adieuronest",
                 "1,2 mil. lei", "1.200.000 lei", 6, 11, "adieuronest.ro",
                 "Termeni din profilul organizației: „infrastructură locală”, „mobilitate urbană”.",
                 ["infrastructură locală", "pietonal", "biciclete"], "new", "—"),
        ],
    },
    # ------------------------------------------------------------ universities
    "universitati": {
        "title": "ViaBolat — învățământ superior",
        "org_type": "Instituție de învățământ superior",
        "profile_terms": ["Erasmus+", "mobilități", "cooperare internațională", "cercetare"],
        "subtitle": "Configurat pentru învățământul superior: urmărește și triază într-un singur loc apelurile Erasmus+, de cercetare și de infrastructură educațională din surse europene și naționale.",
        "calls": [
            call("c1", "eu", "Parteneriate de cooperare în învățământul superior", "Erasmus+ KA220",
                 "400 mii €", "400.000 €", 12, 15,
                 "Erasmus+ KA220 · Portalul Funding & Tenders",
                 "Termeni din profilul organizației: „Erasmus+”, „cooperare internațională” — în titlul apelului.",
                 ["Erasmus+", "cooperare internațională", "învățământ superior"], "new", "Ana M.",
                 "Avem deja doi parteneri interesați — de confirmat consorțiul până la termen."),
            call("c2", "eu", "Mobilități internaționale pentru studenți și personal didactic", "Erasmus+ KA171",
                 "1,5 mil. €", "1.500.000 €", 46, 18,
                 "Erasmus+ KA171 · Portalul Funding & Tenders",
                 "Termen din profilul organizației: „mobilități” — în titlul și în descrierea apelului.",
                 ["Erasmus+", "mobilități", "studenți"], "relevant", "Ana M."),
            call("c3", "ro", "Infrastructură digitală pentru cercetare universitară", "POEO",
                 "1,1 mil. lei", "1.100.000 lei", 27, 4, "POEO · adieuronest.ro",
                 "Termen din profilul organizației: „cercetare” — în titlul și în descrierea apelului.",
                 ["cercetare", "digitalizare", "POEO"], "review", "—"),
            call("c4", "ro", "Burse și sprijin pentru cercetarea doctorală", "PNRR",
                 "850 mii lei", "850.000 lei", 2, 27, "PNRR · adieuronest.ro",
                 "Categorie eligibilă: universități. Termen din profil: „cercetare”.",
                 ["cercetare", "doctorat", "PNRR"], "applied", "Dan P.",
                 "Depus pentru școala doctorală — așteptăm evaluarea."),
            call("c5", "ro", "Dotarea laboratoarelor didactice și de cercetare", "adieuronest",
                 "2,4 mil. lei", "2.400.000 lei", 6, 12, "adieuronest.ro",
                 "Termeni din profilul organizației: „cercetare”, „infrastructură educațională”.",
                 ["laboratoare", "cercetare", "infrastructură educațională"], "new", "—"),
        ],
    },
    # -------------------------------------------------------- funding consultancy
    # Sold to a firm that pursues grants on behalf of many clients. The "profile"
    # is the client portfolio; each row is annotated with the client it fits and
    # the business-development next step, not an internal strategy note.
    "consultanta": {
        "title": "ViaBolat — pentru firme de consultanță",
        "org_type": "Firmă de consultanță · 5 profiluri de client active",
        "profile_label": "Portofoliu de clienți",
        "profile_note": "profiluri gestionate din aplicație",
        "footnote_profile": "profilul fiecărui client",
        "brand": {
            "tagline": "Urmărim automat sursele de finanțare europene și naționale și repartizăm fiecare apel pe clientul din portofoliul dumneavoastră care se califică.",
            "next_step": "Pasul următor: o discuție de 30 de minute în care configurăm un profil pentru câțiva dintre clienții dumneavoastră și vă arătăm apelurile reale, deschise în acest moment, care li se potrivesc.",
        },
        "profile_terms": ["ONG sănătate", "Primărie orășenească", "Universitate", "IMM producție", "Cooperativă agricolă"],
        "subtitle": "Configurat pentru firmele de consultanță: un profil pentru fiecare client, apelurile europene și naționale monitorizate automat și repartizate pe clientul care se califică — pipeline de dezvoltare, nu doar o listă.",
        "calls": [
            call("c1", "eu", "Digitalizarea IMM-urilor și adoptarea inteligenței artificiale", "Europa Digitală",
                 "12 mil. €", "12.000.000 €", 12, 3,
                 "Programul Europa Digitală · Portalul Funding & Tenders",
                 "Se potrivește profilului de client „IMM producție”: termenii „digitalizare”, „inteligență artificială” — în titlul apelului.",
                 ["client: IMM producție", "digitalizare", "inteligență artificială"], "new", "Ana M.",
                 "De trimis oferta către Metalica SRL — eligibil, cofinanțare 25%, termen strâns."),
            call("c2", "eu", "Sprijin psihosocial și calitatea vieții pentru supraviețuitorii de cancer", "Orizont Europa — Misiunea Cancer",
                 "10 mil. €", "10.000.000 €", 46, 12,
                 "Orizont Europa · Misiunea „Cancer” · Portalul Funding & Tenders",
                 "Se potrivește profilului de client „ONG sănătate”: termenii „supraviețuitori de cancer”, „sprijin psihosocial” — în titlul apelului.",
                 ["client: ONG sănătate", "oncologie", "sprijin psihosocial"], "relevant", "Ana M.",
                 "Fundația Renașterea a confirmat interesul — de pregătit consorțiul."),
            call("c3", "ro", "Modernizarea rețelelor de apă și canalizare", "POR",
                 "3 mil. lei", "3.000.000 lei", 27, 6, "POR · adieuronest.ro",
                 "Se potrivește profilului de client „Primărie orășenească”: termenul „infrastructură locală” — în titlul apelului.",
                 ["client: Primărie orășenească", "infrastructură locală", "POR"], "review", "Dan P.",
                 "De verificat dacă UAT-ul are studiul de fezabilitate actualizat înainte de a propune mandatul."),
            call("c4", "ro", "Burse și sprijin pentru cercetarea doctorală", "PNRR",
                 "850 mii lei", "850.000 lei", 2, 21, "PNRR · adieuronest.ro",
                 "Se potrivește profilului de client „Universitate”: categorie eligibilă „universități”, termenul „cercetare”.",
                 ["client: Universitate", "cercetare", "doctorat"], "applied", "Dan P.",
                 "Depus în numele universității — mandat de consultanță semnat, onorariu de succes 4%."),
            call("c5", "ro", "Investiții în ferme mici și lanțuri scurte de aprovizionare", "Planul Strategic PAC",
                 "600 mii lei", "600.000 lei", 6, 2, "PS PAC · adieuronest.ro",
                 "Se potrivește profilului de client „Cooperativă agricolă”: termenii „ferme mici”, „lanțuri scurte” — în titlul apelului.",
                 ["client: Cooperativă agricolă", "agricultură", "lanțuri scurte"], "new", "—",
                 "Client nou, fără responsabil alocat — de repartizat."),
        ],
    },
}


# --------------------------------------------------------------------------- render helpers
def js_str(v):
    """A JS string literal. json.dumps escapes quotes and backslashes correctly."""
    return json.dumps(v, ensure_ascii=False)


def render_calls(calls):
    rows = []
    for c in calls:
        fields = [
            "id:%s" % js_str(c["id"]), "source:%s" % js_str(c["source"]),
            "title:%s" % js_str(c["title"]), "prog:%s" % js_str(c["prog"]),
            "budgetShort:%s" % js_str(c["budgetShort"]), "budget:%s" % js_str(c["budget"]),
            "days:%s" % ("null" if c["days"] is None else c["days"]),
            "seenDays:%d" % c["seenDays"],
            "programmeLine:%s" % js_str(c["programmeLine"]),
            "matchReason:%s" % js_str(c["matchReason"]),
            "tags:[%s]" % ",".join(js_str(t) for t in c["tags"]),
            "status:%s" % js_str(c["status"]), "assignee:%s" % js_str(c["assignee"]),
            "note:%s" % js_str(c["note"]),
        ]
        rows.append("      { %s }," % ", ".join(fields))
    return "\n" + "\n".join(rows) + "\n    "


def render_profile_bar(v):
    chips = "".join(
        '<span class="tag tag-neutral" style="font-size:11px">%s</span>' % t
        for t in v["profile_terms"])
    # A consultancy tracks a client portfolio, not one org profile; the label and
    # the trailing note switch with it. Defaults keep every other variant identical.
    label = v.get("profile_label", "Profilul organizației")
    note = v.get("profile_note", "profil configurabil")
    return (
        '\n  <div id="profil" style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;'
        'background:var(--color-surface);border:1px solid var(--color-divider);border-radius:10px;'
        'padding:11px 14px;margin-bottom:16px">\n'
        '    <span style="display:inline-flex;align-items:center;gap:6px;font-size:10.5px;'
        'letter-spacing:.08em;text-transform:uppercase;color:%s">'
        '<i class="ph ph-sliders-horizontal"></i>%s</span>\n'
        '    <span style="font-size:13px;font-weight:500">%s</span>\n'
        '    <span style="width:1px;height:14px;background:var(--color-divider)"></span>\n'
        '    %s\n'
        '    <span style="margin-left:auto;font-size:11.5px;color:%s">%s</span>\n'
        '  </div>\n' % (MUTED, label, v["org_type"], chips, MUTED, note))


def substitute(tpl, variant):
    out = tpl

    def sub(pattern, value, what):
        nonlocal out
        new, n = re.subn(pattern, lambda m: value, out, count=1, flags=re.S)
        if n != 1:
            sys.exit("substitution failed: %s" % what)
        out = new

    sub(r"<title>.*?</title>", "<title>%s</title>" % variant["title"], "title")
    sub(r'<p class="sub">.*?</p>', '<p class="sub">%s</p>' % variant["subtitle"], "subtitle")
    sub(r'\n  <div id="profil".*?\n  </div>\n', render_profile_bar(variant), "profile bar")
    sub(r"(?<=BASE\(\)\{\n    return \[).*?(?=\];)", render_calls(variant["calls"]), "calls")
    # The "date fictive" footnote also says the list is filtered by the org profile;
    # for the consultancy that is per-client. The subtitle <p> above has already been
    # replaced, so the phrase now survives only in the footnote. Default = no change.
    sub(r"profilul organizației dumneavoastră",
        variant.get("footnote_profile", "profilul organizației dumneavoastră"),
        "footnote profile phrase")

    # A variant may override a BRAND string where the seed copy is org-centric and the
    # segment is not (the consultancy's footer tagline and next-step line). Absent an
    # override the seed BRAND value is used, so every other variant is unchanged.
    brand = dict(BRAND, **variant.get("brand", {}))
    for key, token in [("name", "__BRAND_NAME__"), ("tagline", "__BRAND_TAGLINE__"),
                       ("email", "__BRAND_EMAIL__"), ("phone", "__BRAND_PHONE__"),
                       ("site", "__BRAND_SITE__"), ("cta_label", "__CTA_LABEL__"),
                       ("next_step", "__NEXT_STEP__")]:
        out = out.replace(token, brand[key])
    # The subject rides in a mailto URL, so it needs percent-encoding, not raw text.
    try:
        from urllib.parse import quote
    except ImportError:
        from urllib import quote
    out = out.replace("__CTA_SUBJECT__", quote(BRAND["cta_subject"]))
    return out


def encode_template(tpl):
    """The bundler's own escaping: literal UTF-8, and "</" escaped so a closing
    tag inside the payload cannot terminate the wrapper's <script> block."""
    return json.dumps(tpl, ensure_ascii=False).replace("</", "<\\u002F")


def main():
    bundle = io.open(BASE_BUNDLE, encoding="utf-8").read()
    tpl_src = io.open(TEMPLATE_SRC, encoding="utf-8").read()

    m = re.search(r'(<script type="__bundler/template">\s*)(".*?")(\s*</script>)', bundle, re.S)
    if not m:
        sys.exit("template block not found in %s" % BASE_BUNDLE)
    # Proves the encoder is faithful before anything is written.
    if encode_template(json.loads(m.group(2))) != m.group(2):
        sys.exit("encoder does not round-trip the base bundle")

    if not os.path.isdir(OUT_DIR):
        os.makedirs(OUT_DIR)

    unfilled = sorted(set(re.findall(r"\[[^\]\[]+\]", " ".join(BRAND.values()))))
    for name, variant in sorted(VARIANTS.items()):
        page = substitute(tpl_src, variant)
        out = bundle[:m.start(2)] + encode_template(page) + bundle[m.end(2):]
        path = os.path.join(OUT_DIR, "ViaBolat - %s.html" % name)
        io.open(path, "w", encoding="utf-8").write(out)
        print("  %-13s -> %s (%.1f MB)" % (name, os.path.basename(path),
                                           os.path.getsize(path) / 1e6))
    if unfilled:
        print("\n  WARNING: BRAND still has placeholders -- do not send yet:")
        for u in unfilled:
            print("    %s" % u)


if __name__ == "__main__":
    main()
