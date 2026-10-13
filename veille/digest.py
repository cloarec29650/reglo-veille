"""Digest hebdomadaire Markdown : ce qui a changé sur la période, prêt à partager à l'équipe."""

from datetime import date, datetime, timedelta, timezone

from .storage import Store

THEME_ORDER_FALLBACK = "autres"


def fmt_int(v: float | None) -> str:
    return "—" if v is None else f"{v:,.0f}".replace(",", "\u00a0")  # espace insécable : U+202F absente de Barlow gras


def fmt_float(v: float | None, digits: int = 1) -> str:
    return "—" if v is None else f"{v:.{digits}f}".replace(".", ",")


MONTHS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
          "septembre", "octobre", "novembre", "décembre"]


def fmt_date(iso: str | None) -> str:
    """Date courte française : 09/10/2026."""
    return f"{iso[8:10]}/{iso[5:7]}/{iso[:4]}" if iso else "—"


def fmt_long(d: date) -> str:
    return f"{d.day} {MONTHS[d.month - 1]} {d.year}"


def fmt_period(start: date, end: date) -> str:
    """« du 5 au 12 octobre 2026 », mois et année répétés seulement si nécessaire."""
    if start.year != end.year:
        return f"du {fmt_long(start)} au {fmt_long(end)}"
    if start.month != end.month:
        return f"du {start.day} {MONTHS[start.month - 1]} au {fmt_long(end)}"
    return f"du {start.day} au {fmt_long(end)}"


def count_phrase(n: int, singular: str, plural_form: str | None = None, feminine: bool = False) -> str:
    """« aucun changement », « 1 article », « 4 appels d'offres »."""
    if n == 0:
        return f"{'aucune' if feminine else 'aucun'} {singular}"
    return f"{fmt_int(n)} {singular if n == 1 else (plural_form or singular + 's')}"


def md_escape(text: str) -> str:
    return (text or "").replace("|", "\\|").replace("\n", " ")


def table(headers: list[str], rows: list[list[str]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    lines += ["| " + " | ".join(md_escape(str(c)) for c in r) + " |" for r in rows]
    return "\n".join(lines)


def _section_highlights(articles: list[dict], labels: dict) -> list[str]:
    out = ["## À retenir", ""]
    if not articles:
        return out + ["_Aucun article pertinent sur la période._", ""]
    for a in articles[:5]:
        tags = ", ".join(labels.get(t, t) for t in a["themes"][:3])
        comp = f" Cite **{', '.join(a['competitors'])}**." if a["competitors"] else ""
        # Deux espaces avant le retour à la ligne : saut de ligne Markdown dans l'élément de liste.
        out.append(f"- **[{a['title']}]({a['url']})**  \n  {a['source']}, {fmt_date(a['published_at'])}. _{tags}._{comp}")
    return out + [""]


def _section_press(articles: list[dict], labels: dict) -> list[str]:
    out = ["## Presse et tendances", ""]
    if not articles:
        return out + ["_Rien de nouveau._", ""]
    groups: dict[str, list[dict]] = {}
    for a in articles:
        groups.setdefault(a["themes"][0] if a["themes"] else THEME_ORDER_FALLBACK, []).append(a)
    ordered = [t for t in labels if t in groups] + ([THEME_ORDER_FALLBACK] if THEME_ORDER_FALLBACK in groups else [])
    for theme in ordered:
        items = groups[theme]
        out += [f"### {labels.get(theme, 'Autres')} ({len(items)})", ""]
        for a in items:
            out.append(f"- [{a['title']}]({a['url']}), {a['source']}, {fmt_date(a['published_at'])}")
            if a.get("snippet"):
                out.append(f"  > {a['snippet']}")
        out.append("")
    mentions: dict[str, int] = {}
    for a in articles:
        for c in a["competitors"]:
            mentions[c] = mentions.get(c, 0) + 1
    if mentions:
        out += ["**Concurrents cités dans la presse :** "
                + ", ".join(f"{c} ({n})" for c, n in sorted(mentions.items(), key=lambda x: -x[1])), ""]
    return out


def _section_competitors(store: Store, since: str) -> list[str]:
    out = ["## Concurrents", ""]
    changes = store.changes_since(since)
    if changes:
        for ch in changes:
            flag = " 💶 **mention de prix modifiée**" if ch["price_change"] else ""
            out.append(f"### {ch['competitor']} — {ch['url']}{flag}")
            out.append(f"_Détecté le {fmt_date(ch['detected_at'])} : {len(ch['added'])} ligne(s) ajoutée(s), "
                       f"{len(ch['removed'])} retirée(s)._")
            out += [f"- ➕ {md_escape(l)[:200]}" for l in ch["added"][:8]]
            out += [f"- ➖ {md_escape(l)[:200]}" for l in ch["removed"][:5]]
            out.append("")
    else:
        out += ["_Aucun changement détecté sur les pages suivies._", ""]
    pages = store.tracked_pages()
    if pages:
        out += [table(["Concurrent", "Page suivie", "Suivie depuis", "Versions"],
                      [[p["competitor"], p["url"], fmt_date(p["first"]), p["n"]] for p in pages]), ""]
    return out


def _section_market(store: Store, cfg: dict, since_date: str) -> list[str]:
    out = ["## Marché", ""]
    period = store.latest_period("entreprises")
    if period:
        current = {r["dimension"]: r for r in store.indicators("entreprises", period)}
        previous = {r["dimension"]: r for r in store.indicators("entreprises", str(int(period) - 1))}
        salaries = {r["dimension"]: r for r in store.indicators("salaries", period)}
        targets = {f"taille:{o}" for o in cfg["market"]["target_size_orders"]}
        prices = cfg["market"].get("annual_price_by_size_order") or {}
        rows, total_target, tam, tam_complete = [], 0.0, 0.0, True
        for dim in sorted(current, key=lambda d: int(d.split(":")[1])):
            r = current[dim]
            prev = previous.get(dim, {}).get("value")
            evol = f"{(r['value'] / prev - 1) * 100:+.1f} %".replace(".", ",") if prev else "—"
            target = dim in targets
            if target:
                total_target += r["value"]
                price = prices.get(int(dim.split(":")[1]))
                if price is None:
                    tam_complete = False
                else:
                    tam += r["value"] * price
            rows.append([("**" if target else "") + r["label"] + ("**" if target else ""), fmt_int(r["value"]),
                         fmt_int(salaries.get(dim, {}).get("value")), evol, "✔" if target else ""])
        out += [f"### Entreprises du régime général par taille ({period})", "",
                table(["Tranche d'effectif", "Entreprises", "Salariés", f"Évol. vs {int(period) - 1}", "Cible"], rows), "",
                f"**Entreprises dans les tranches ciblées : {fmt_int(total_target)}**", ""]
        if tam_complete:
            out += [f"**Marché adressable estimé : {fmt_int(tam)} € HT / an** "
                    "(entreprises ciblées × hypothèses de prix de `config.yaml`).", ""]
        else:
            out += ["_Marché adressable en € : renseigner `market.annual_price_by_size_order` dans `config.yaml`._", ""]

        sectors = store.indicators("entreprises_cible")
        freq = {r["dimension"]: r["value"] for r in store.indicators("at_indice_frequence")}
        # Écarte « x » (secteur non renseigné) et les secteurs sans entreprise ciblée.
        sectors = [r for r in sectors if r["dimension"] != "naf1:x" and (r["value"] or 0) > 0]
        if sectors:
            sectors.sort(key=lambda r: -(r["value"] or 0))
            out += [f"### Entreprises ciblées par secteur, croisées avec la sinistralité ({period})", "",
                    table(["Secteur (NAF)", "Entreprises ciblées", "Indice de fréquence AT"],
                          [[f"{r['label']} ({r['dimension'].split(':')[1]})", fmt_int(r["value"]),
                            fmt_float(freq.get(r["dimension"]))] for r in sectors]), ""]
    else:
        out += ["_Indicateurs non collectés (lancer `run --only market`)._", ""]

    tenders = store.tenders_since(since_date)
    out += [f"### Appels d'offres publics QHSE / RSE (BOAMP, {len(tenders)} sur la période)", ""]
    if tenders:
        out += [table(["Date", "Objet", "Acheteur", "Nature", "Titulaire(s)"],
                      [[fmt_date(t["published_at"]), f"[{(t['title'] or '')[:90]}]({t['url']})", t["buyer"] or "—",
                        t["nature"] or "—", t["winners"] or "—"] for t in tenders[:20]]), ""]
    else:
        out += ["_Aucun avis sur la période._", ""]

    jobs = store.indicators("offres_emploi")
    if jobs:
        out += [f"### Offres d'emploi publiées (France Travail, relevé du {jobs[0]['period']})", "",
                table(["Mot-clé", "Offres"], [[j["label"], fmt_int(j["value"])] for j in jobs]), ""]
    return out


def _section_atmp(store: Store, cfg: dict) -> list[str]:
    out = ["## Sinistralité AT/MP", ""]
    period = store.latest_period("at_indice_frequence")
    if not period:
        return out + ["_Non collecté (lancer `run --only atmp`)._", ""]
    prev = str(int(period) - 1)
    at = {r["dimension"]: r for r in store.indicators("at_indice_frequence", period)}
    at_prev = {r["dimension"]: r["value"] for r in store.indicators("at_indice_frequence", prev)}
    at_n = {r["dimension"]: r["value"] for r in store.indicators("at_sinistres", period)}
    mp_n = {r["dimension"]: r["value"] for r in store.indicators("mp_sinistres", period)}
    mp_prev = {r["dimension"]: r["value"] for r in store.indicators("mp_sinistres", prev)}

    national = at.pop("naf1:TOUS", None)
    if national:
        mp_evol = ""
        if mp_n.get("naf1:TOUS") and mp_prev.get("naf1:TOUS"):
            mp_evol = f" ({(mp_n['naf1:TOUS'] / mp_prev['naf1:TOUS'] - 1) * 100:+.1f} % vs {prev})".replace(".", ",")
        out += [f"**France entière ({period}) :** {fmt_int(at_n.get('naf1:TOUS'))} accidents du travail, "
                f"indice de fréquence {fmt_float(national['value'])} pour 1 000 salariés ; "
                f"{fmt_int(mp_n.get('naf1:TOUS'))} maladies professionnelles{mp_evol}.", ""]
    top = sorted((r for r in at.values() if r["value"] is not None), key=lambda r: -r["value"])[: cfg["atmp"]["top_sectors"]]
    rows = []
    for r in top:
        d = r["dimension"]
        evol = f"{r['value'] - at_prev[d]:+.1f}".replace(".", ",") if at_prev.get(d) is not None else "—"
        rows.append([f"{r['label']} ({d.split(':')[1]})", fmt_float(r["value"]), evol, fmt_int(at_n.get(d)), fmt_int(mp_n.get(d))])
    out += [f"Secteurs les plus exposés (indice de fréquence AT, {period}) :", "",
            table(["Secteur (NAF)", "Indice de fréquence AT", f"Évol. vs {prev}", "AT", "MP"], rows), ""]
    return out


def _section_sources(store: Store) -> list[str]:
    out = ["## Sources et méthode", ""]
    last, sources_by_volet = store.source_status()
    if last:
        rows = []
        for volet, sources in sources_by_volet.items():
            for name, s in sources.items():
                status = {True: "✅", False: "❌", None: "⏸"}[s.get("ok")]
                detail = s.get("erreur") or s.get("statut") or ", ".join(
                    f"{k} {v}" for k, v in s.items() if k not in ("ok", "_at"))
                rows.append([volet, name, status, detail, fmt_date(s["_at"])])
        out += [f"Dernière collecte : {fmt_date(last)}.", "",
                table(["Volet", "Source", "État", "Détail", "Relevé le"], rows), ""]
    out += [
        "- **Presse** : flux RSS publics, robots.txt respecté ; seuls le titre, le lien et un court extrait sont conservés (droit voisin de la presse).",
        "- **Classement** : mots-clés par thème (`config.yaml`), sans IA générative ; un article est retenu s'il touche un thème « coeur » ou cite un concurrent.",
        "- **Concurrents** : comparaison du texte visible des pages publiques entre deux collectes.",
        "- **Marché & AT/MP** : open data Assurance Maladie (data.ameli.fr), régime général ; BOAMP (DILA) ; France Travail si configuré.",
        "- **Limites** : le régime général exclut le régime agricole (MSA), d'où le faible poids du secteur A ; "
        "la somme des secteurs peut différer légèrement du total national (secteurs non renseignés, secret statistique).",
        "- Les chiffres sont des **données brutes datées** : leur interprétation relève de l'équipe.",
        "",
    ]
    return out


def build_digest(store: Store, cfg: dict, days: int = 7, today: date | None = None) -> str:
    today = today or date.today()
    since_date = (today - timedelta(days=days)).isoformat()
    since_iso = datetime.combine(today - timedelta(days=days), datetime.min.time(), tzinfo=timezone.utc).isoformat()
    labels = {tid: t["label"] for tid, t in cfg["themes"].items()}
    articles = store.articles_since(since_iso)
    week = today.isocalendar()

    n_tenders = len(store.tenders_since(since_date))
    n_changes = len(store.changes_since(since_iso))
    period = fmt_period(today - timedelta(days=days), today)
    counts = [
        count_phrase(len(articles), "article retenu", "articles retenus"),
        count_phrase(n_tenders, "appel d'offres", "appels d'offres"),
        count_phrase(n_changes, "changement", "changements") + " chez les concurrents",
    ]
    lede = f"{period[0].upper()}{period[1:]} : {counts[0]}, {counts[1]} et {counts[2]}."
    lines = [f"# Veille marché, semaine {week.week} de {week.year}", "", lede, ""]
    lines += _section_highlights(articles, labels)
    lines += _section_press(articles, labels)
    lines += _section_competitors(store, since_iso)
    lines += _section_market(store, cfg, since_date)
    lines += _section_atmp(store, cfg)
    lines += _section_sources(store)
    return "\n".join(lines)
