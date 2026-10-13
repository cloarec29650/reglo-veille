"""Dashboard Streamlit de la veille marché Reglo.

Lancer :  .venv\\Scripts\\streamlit run dashboard.py
Lit l'historique SQLite (data/veille.sqlite) ; le bouton « Lancer une collecte » rafraîchit les données.
"""

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from veille import queries
from veille.__main__ import load_config, run_collect, write_digest
from veille.storage import Store, now_iso

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "data" / "veille.sqlite"
# Lecture seule en ligne : Streamlit Community Cloud monte le dépôt sous /mount/src (disque temporaire,
# visiteurs invités) ; la collecte y est faite par GitHub Actions. Forçable avec VEILLE_LECTURE_SEULE=1.
READ_ONLY = str(ROOT).startswith("/mount/src") or os.environ.get("VEILLE_LECTURE_SEULE") == "1"

# ── Direction visuelle : registre d'inspection QHSE (même charte que le digest HTML) ──
# Bleu de série validé (plage de luminosité et contraste) ; le bleu ISO #005387 reste réservé aux liens.
SERIES = "#1f6fb0"        # série unique / emphase
MUTED_MARK = "#c5ccd3"    # éléments hors cible (emphase par contraste)
REFERENCE = "#5b6672"     # ligne de référence (moyenne nationale)
INK, MUTED_INK, GRID = "#1b2430", "#5b6672", "#dde2e6"
FONT = "Barlow, 'Segoe UI', sans-serif"

PAGE_CSS = """
<link href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@600;700&family=Barlow:wght@400;500;600&display=swap" rel="stylesheet">
<style>
html, body, [class*="st-"], .stMarkdown, .stDataFrame, button, input, textarea { font-family: Barlow, "Segoe UI", sans-serif; }
h1, h2, h3, [data-testid="stHeading"] * { font-family: "Barlow Condensed", "Arial Narrow", sans-serif !important; letter-spacing: 0; }
[data-testid="stHeader"] { background: transparent; }
.masthead h1 { font: 700 3.2rem/1 "Barlow Condensed", sans-serif !important; margin: 8px 0 10px; padding: 0; }
.masthead p { font-size: 1.12rem; max-width: 70ch; margin: 0; color: #1b2430; }
.masthead p.meta { font-size: .95rem; color: #5b6672; margin-top: 6px; }
h2 { border-top: 2px solid #1b2430; padding-top: 10px !important; }
[data-baseweb="tab-list"] button p { font-size: 1.02rem; }
</style>
"""


def chart_theme():
    return {"config": {
        "font": FONT,
        "background": "transparent",
        "view": {"stroke": None},
        "axis": {"labelColor": MUTED_INK, "titleColor": MUTED_INK, "gridColor": GRID, "domainColor": MUTED_MARK,
                 "tickColor": MUTED_MARK, "labelFontSize": 12, "titleFontSize": 12, "titleFontWeight": "normal"},
        "legend": {"labelColor": INK, "titleColor": MUTED_INK},
        "bar": {"cornerRadiusEnd": 4},
    }}


alt.themes.register("reglo", chart_theme)
alt.themes.enable("reglo")

st.set_page_config(page_title="Veille marché Reglo", layout="wide")
st.markdown(PAGE_CSS, unsafe_allow_html=True)


def fmt_int(v) -> str:
    return "—" if v is None or pd.isna(v) else f"{v:,.0f}".replace(",", " ")


def fmt_pct(v, signed=True) -> str:
    return "—" if v is None or pd.isna(v) else (f"{v * 100:+.1f} %" if signed else f"{v * 100:.1f} %").replace(".", ",")


def integer_axis(max_value) -> alt.Axis:
    """Axe de comptage : graduations entières uniquement (pas de « 0,5 article »)."""
    top = int(max_value or 1)
    step = max(1, round(top / 5))
    return alt.Axis(values=list(range(0, top + step, step)), format="d")


def table_view(df: pd.DataFrame, label: str = "Voir les données", **kwargs) -> None:
    """Équivalent tabulaire de chaque graphique (accessibilité : lecture sans le visuel)."""
    with st.expander(label):
        st.dataframe(df, hide_index=True, use_container_width=True, **kwargs)


# ─────────────────────────────── Barre latérale ───────────────────────────────
cfg = load_config(ROOT / "config.yaml")
labels = {tid: t["label"] for tid, t in cfg["themes"].items()} | {"autres": "Autres"}

with st.sidebar:
    st.header("Veille Reglo")
    period_label = st.radio("Période analysée", ["7 jours", "30 jours", "90 jours", "Tout l'historique"], index=1)
    days = {"7 jours": 7, "30 jours": 30, "90 jours": 90}.get(period_label)
    since = datetime.now(timezone.utc) - timedelta(days=days) if days else None

    st.divider()
    st.subheader("Collecte")
    if READ_ONLY:
        st.caption("Version en ligne, en lecture seule : les données sont mises à jour automatiquement "
                   "chaque lundi par la collecte planifiée (GitHub Actions).")
    else:
        volets = st.multiselect("Volets", ["press", "competitors", "market", "atmp"],
                                default=["press", "competitors", "market", "atmp"],
                                format_func={"press": "Presse", "competitors": "Concurrents",
                                             "market": "Marché", "atmp": "AT/MP"}.get, placeholder="Choisir des volets")
        if st.button("Lancer une collecte", type="primary", use_container_width=True, disabled=not volets):
            with st.spinner("Collecte en cours (environ 1 à 2 minutes)…"):
                store = Store(DB_PATH)
                try:
                    started = now_iso()
                    report = run_collect(cfg, store, volets, days or 7)
                    store.save_run(started, report)
                    write_digest(cfg, store, days or 7, ROOT / "reports")
                finally:
                    store.close()
            failed = sum(1 for s in report.values() for r in s.values() if r.get("ok") is False)
            st.success("Collecte terminée, digest régénéré." + (f" {failed} source(s) en échec." if failed else ""))
        st.caption("Les digests HTML/Markdown sont dans `reports/`.")

# ─────────────────────────────── Données ───────────────────────────────
if not DB_PATH.exists():
    st.title("Veille marché Reglo")
    st.info("Aucune donnée pour l'instant." if READ_ONLY
            else "Aucune donnée pour l'instant : lancez une collecte depuis la barre latérale.")
    st.stop()

store = Store(DB_PATH)
arts = queries.articles(store)
changes = queries.competitor_changes(store)
tracked = queries.tracked_pages(store)
tend = queries.tenders(store)
src = queries.sources(store)
size_period, by_size = queries.market_by_size(store)
seg = queries.segmentation(store)
atmp_period, atmp_df, national = queries.atmp(store)
last_run, _ = store.source_status()
store.close()

if since is not None:
    arts_p = arts[arts["date"] >= since] if not arts.empty else arts
    changes_p = changes[changes["detected_at"] >= since] if not changes.empty else changes
    tend_p = tend[tend["published_at"] >= since.replace(tzinfo=None)] if not tend.empty else tend
else:
    arts_p, changes_p, tend_p = arts, changes, tend

# ─────────────────────────────── En-tête ───────────────────────────────
targets_default = cfg["market"]["target_size_orders"]


def count_phrase(n: int, singular: str, plural_form: str, feminine: bool = False) -> str:
    if n == 0:
        return f"{'aucune' if feminine else 'aucun'} {singular}"
    return f"{fmt_int(n)} {singular if n == 1 else plural_form}"


scope = f"Sur les {days} derniers jours" if days else "Sur tout l'historique"
counts = [count_phrase(len(arts_p), "article retenu", "articles retenus"),
          count_phrase(len(tend_p), "appel d'offres", "appels d'offres"),
          count_phrase(len(changes_p), "changement", "changements") + " chez les concurrents"]
summary = f"{scope} : {counts[0]}, {counts[1]} et {counts[2]}."
collected = f"{last_run[8:10]}/{last_run[5:7]}/{last_run[:4]}" if last_run else "jamais"
st.markdown(f'''<div class="masthead"><h1>Veille marché QHSE et RSE</h1><p>{summary}</p>
<p class="meta">Dernière collecte le {collected}. Données publiques datées ; l'interprétation revient à l'équipe.</p></div>''',
            unsafe_allow_html=True)

tab_press, tab_comp, tab_market, tab_atmp, tab_tenders, tab_src = st.tabs(
    ["Presse", "Concurrents", "Marché et segmentation", "Sinistralité AT/MP", "Appels d'offres", "Sources"])

# ─────────────────────────────── Presse ───────────────────────────────
with tab_press:
    if arts_p.empty:
        st.info("Aucun article retenu sur la période.")
    else:
        f1, f2, f3 = st.columns([2, 2, 3])
        theme_sel = f1.multiselect("Thèmes", list(labels), format_func=labels.get, placeholder="Tous les thèmes")
        source_sel = f2.multiselect("Sources", sorted(arts_p["source"].unique()), placeholder="Toutes les sources")
        search = f3.text_input("Recherche", placeholder="mot dans le titre ou l'extrait")
        view = arts_p
        if theme_sel:
            view = view[view["themes"].map(lambda t: any(x in t for x in theme_sel))]
        if source_sel:
            view = view[view["source"].isin(source_sel)]
        if search:
            mask = view["title"].str.contains(search, case=False, na=False) | view["snippet"].str.contains(search, case=False, na=False)
            view = view[mask]

        counts = (view.explode("themes").dropna(subset=["themes"])
                  .assign(theme=lambda d: d["themes"].map(labels))
                  .groupby("theme").size().reset_index(name="articles"))
        c1, c2 = st.columns([2, 3])
        with c1:
            st.subheader("Articles par thème")
            st.caption("Un article peut relever de plusieurs thèmes.")
            if not counts.empty:
                st.altair_chart(
                    alt.Chart(counts).mark_bar(color=SERIES, height={"band": 0.7}).encode(
                        x=alt.X("articles:Q", title="Articles", axis=integer_axis(counts["articles"].max())),
                        y=alt.Y("theme:N", sort="-x", title=None, axis=alt.Axis(labelLimit=260)),
                        tooltip=[alt.Tooltip("theme:N", title="Thème"), alt.Tooltip("articles:Q", title="Articles")],
                    ).properties(height=36 * len(counts) + 40),
                    use_container_width=True)
                table_view(counts.sort_values("articles", ascending=False))
        with c2:
            st.subheader(f"Articles ({len(view)})")
            st.dataframe(
                view.assign(theme=view["theme_principal"].map(labels),
                            concurrents=view["competitors"].map(", ".join),
                            jour=view["date"].dt.strftime("%Y-%m-%d"))
                [["jour", "title", "source", "theme", "concurrents", "snippet", "url"]],
                hide_index=True, use_container_width=True, height=420,
                column_config={
                    "jour": "Date", "title": st.column_config.TextColumn("Titre", width="large"),
                    "source": "Source", "theme": "Thème principal", "concurrents": "Concurrents cités",
                    "snippet": st.column_config.TextColumn("Extrait", width="large"),
                    "url": st.column_config.LinkColumn("Lien", display_text="ouvrir"),
                })

# ─────────────────────────────── Concurrents ───────────────────────────────
with tab_comp:
    st.subheader("Changements détectés sur les pages suivies")
    if changes_p.empty:
        st.info("Aucun changement sur la période. Les pages sont comparées d'une collecte à l'autre : "
                "les premiers changements apparaissent à partir de la 2e collecte.")
    else:
        for _, ch in changes_p.iterrows():
            title = (f"{ch['competitor']}, {ch['detected_at']:%d/%m/%Y} : +{len(ch['added'])} / "
                     f"−{len(ch['removed'])} ligne(s)" + (", prix modifié" if ch["price_change"] else ""))
            with st.expander(title, expanded=bool(ch["price_change"])):
                st.caption(ch["url"] + (". **Mention de prix modifiée.**" if ch["price_change"] else ""))
                a, r = st.columns(2)
                a.markdown("**Ajouté**\n\n" + ("\n".join(f"- {l}" for l in ch["added"][:30]) or "_rien_"))
                r.markdown("**Retiré**\n\n" + ("\n".join(f"- {l}" for l in ch["removed"][:30]) or "_rien_"))

    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Pages suivies")
        blocked = src[(src["Volet"] == "Concurrents") & (src["État"].str.startswith("❌"))]
        if not tracked.empty:
            st.dataframe(tracked.rename(columns={"competitor": "Concurrent", "url": "Page", "first": "Suivie depuis",
                                                 "last": "Dernière version", "n": "Versions"})
                         .assign(**{"Suivie depuis": lambda d: d["Suivie depuis"].str[:10],
                                    "Dernière version": lambda d: d["Dernière version"].str[:10]}),
                         hide_index=True, use_container_width=True)
        if not blocked.empty:
            st.warning("Suivi manuel (sites qui refusent les robots) : " + ", ".join(blocked["Source"].str.split(" \\(").str[0]))
    with c2:
        st.subheader("Concurrents cités dans la presse")
        mentions = arts_p.explode("competitors").dropna(subset=["competitors"]) if not arts_p.empty else pd.DataFrame()
        if mentions.empty:
            st.info("Aucun concurrent cité sur la période.")
        else:
            m = mentions.groupby("competitors").size().reset_index(name="articles")
            st.altair_chart(alt.Chart(m).mark_bar(color=SERIES, height={"band": 0.7}).encode(
                x=alt.X("articles:Q", title="Articles", axis=integer_axis(m["articles"].max())),
                y=alt.Y("competitors:N", sort="-x", title=None),
                tooltip=["competitors:N", "articles:Q"]), use_container_width=True)
            table_view(m)

# ─────────────────────────────── Marché & segmentation ───────────────────────────────
with tab_market:
    if by_size.empty:
        st.info("Indicateurs marché non collectés : lancez une collecte avec le volet « Marché ».")
    else:
        st.subheader(f"Taille du marché ({size_period}, régime général)")
        size_labels = dict(zip(by_size["ordre"], by_size["tranche"]))
        f1, f2 = st.columns([2, 3])
        targets = f1.multiselect("Tranches d'effectif ciblées", list(size_labels), default=targets_default,
                                 format_func=size_labels.get, placeholder="Choisir des tranches")
        with f2:
            st.caption("Hypothèses de prix annuel (€ HT) par tranche ciblée : à fixer par l'équipe (0 = non renseigné).")
            price_cols = st.columns(max(len(targets), 1))
            cfg_prices = cfg["market"].get("annual_price_by_size_order") or {}
            prices = {o: price_cols[i].number_input(size_labels[o], min_value=0, step=100,
                                                    value=int(cfg_prices.get(o) or 0), key=f"price_{o}")
                      for i, o in enumerate(targets)}

        target_df = by_size[by_size["ordre"].isin(targets)]
        m1, m2, m3 = st.columns(3)
        m1.metric("Entreprises ciblées", fmt_int(target_df["entreprises"].sum()))
        m2.metric("Salariés couverts", fmt_int(target_df["salaries"].sum()))
        priced = {o: p for o, p in prices.items() if p > 0}
        if targets and len(priced) == len(targets):
            m3.metric("Marché adressable estimé", f"{fmt_int(queries.addressable_market(by_size, priced))} € / an",
                      help="Entreprises ciblées × hypothèse de prix annuel. Ordre de grandeur, pas une prévision de CA.")
        else:
            m3.metric("Marché adressable estimé", "—", help="Renseigner un prix pour chaque tranche ciblée.")

        chart_df = by_size.assign(cible=by_size["ordre"].isin(targets).map({True: "Ciblée", False: "Hors cible"}))
        # Les moins de 10 salariés (~2 M) écraseraient les autres barres sur une échelle linéaire :
        # tant qu'ils ne sont pas ciblés, ils sont indiqués en légende plutôt que tracés.
        tiny = by_size[by_size["ordre"] == 1]
        if 1 not in targets and not tiny.empty:
            chart_df = chart_df[chart_df["ordre"] != 1]
        st.altair_chart(alt.Chart(chart_df).mark_bar(width={"band": 0.7}).encode(
            x=alt.X("tranche:N", sort=alt.SortField("ordre"), title="Tranche d'effectif", axis=alt.Axis(labelAngle=0)),
            y=alt.Y("entreprises:Q", title="Entreprises", axis=alt.Axis(format=",.0f")),
            color=alt.Color("cible:N", scale=alt.Scale(domain=["Ciblée", "Hors cible"], range=[SERIES, MUTED_MARK]),
                            legend=alt.Legend(title=None, orient="top")),
            tooltip=[alt.Tooltip("tranche:N", title="Tranche"), alt.Tooltip("entreprises:Q", title="Entreprises", format=",.0f"),
                     alt.Tooltip("salaries:Q", title="Salariés", format=",.0f"),
                     alt.Tooltip("evolution:Q", title="Évolution sur 1 an", format="+.1%")],
        ).properties(height=280), use_container_width=True)
        if 1 not in targets and not tiny.empty:
            st.caption(f"Non tracé : {fmt_int(tiny['entreprises'].iloc[0])} entreprises de moins de 10 salariés "
                       "(hors cible ; plus de 10 fois la tranche suivante, elles écraseraient le graphique).")
        table_view(by_size.assign(evolution=by_size["evolution"].map(fmt_pct))
                   .rename(columns={"ordre": "Ordre", "tranche": "Tranche", "entreprises": "Entreprises",
                                    "salaries": "Salariés", "evolution": f"Évolution vs {int(size_period) - 1}"}))

        st.divider()
        st.subheader("Segmentation : taille du segment × exposition au risque")
        st.caption("Chaque point est un secteur (NAF niveau 1) : entreprises dans les tranches ciblées par défaut "
                   "(config.yaml) en abscisse, indice de fréquence des accidents du travail en ordonnée. "
                   "La ligne horizontale est la moyenne nationale.")
        if not seg.empty and seg["indice_frequence_at"].notna().any():
            plot = seg.dropna(subset=["indice_frequence_at"])
            x_med = plot["entreprises_cibles"].median()
            avg = national.get("indice_frequence_at")
            # Étiquettes sélectives : grands segments ou forte exposition.
            plot = plot.assign(etiquette=plot.apply(
                lambda r: r["naf"] if (r["entreprises_cibles"] >= x_med and r["indice_frequence_at"] >= (avg or 0)) else "", axis=1))
            base = alt.Chart(plot)
            points = base.mark_circle(color=SERIES, opacity=0.85, stroke="white", strokeWidth=2).encode(
                x=alt.X("entreprises_cibles:Q", title="Entreprises ciblées", axis=alt.Axis(format="~s")),
                y=alt.Y("indice_frequence_at:Q", title="Indice de fréquence AT (pour 1 000 salariés)"),
                size=alt.Size("salaries_cibles:Q", title="Salariés ciblés", scale=alt.Scale(range=[60, 900]),
                              legend=alt.Legend(values=[100_000, 500_000, 1_500_000], format="~s", orient="right")),
                tooltip=[alt.Tooltip("secteur:N", title="Secteur"), alt.Tooltip("naf:N", title="NAF"),
                         alt.Tooltip("entreprises_cibles:Q", title="Entreprises ciblées", format=",.0f"),
                         alt.Tooltip("salaries_cibles:Q", title="Salariés ciblés", format=",.0f"),
                         alt.Tooltip("indice_frequence_at:Q", title="Indice de fréquence AT", format=".1f")])
            text = base.mark_text(dx=12, align="left", color=INK, fontSize=12).encode(
                x="entreprises_cibles:Q", y="indice_frequence_at:Q", text="etiquette:N")
            layers = [points, text]
            if avg:
                layers.append(alt.Chart(pd.DataFrame({"y": [avg]})).mark_rule(color=REFERENCE, strokeWidth=1).encode(y="y:Q"))
            st.altair_chart(alt.layer(*layers).properties(height=420), use_container_width=True)
            st.caption("Étiquetés : secteurs au-dessus de la médiane en taille **et** de la moyenne nationale en sinistralité. "
                       "Lettres NAF : F construction, H transports, N services administratifs, Q santé et action sociale…")
        table_view(seg.rename(columns={"naf": "NAF", "secteur": "Secteur", "entreprises_cibles": "Entreprises ciblées",
                                       "salaries_cibles": "Salariés ciblés", "indice_frequence_at": "Indice de fréquence AT",
                                       "accidents_travail": "Accidents du travail", "maladies_pro": "Maladies pro."}),
                   "Voir le tableau de segmentation")
        st.caption("Source : Assurance Maladie, data.ameli.fr (régime général, hors régime agricole).")

# ─────────────────────────────── Sinistralité AT/MP ───────────────────────────────
with tab_atmp:
    if atmp_df.empty:
        st.info("Sinistralité non collectée : lancez une collecte avec le volet « AT/MP ».")
    else:
        n1, n2, n3 = st.columns(3)
        n1.metric(f"Accidents du travail ({atmp_period})", fmt_int(national.get("accidents_travail")))
        n2.metric("Indice de fréquence national", str(national.get("indice_frequence_at", "—")).replace(".", ","),
                  help="Accidents du travail pour 1 000 salariés.")
        n3.metric(f"Maladies professionnelles ({atmp_period})", fmt_int(national.get("maladies_pro")),
                  delta=fmt_pct(national.get("evolution_mp")) + " sur un an" if national.get("evolution_mp") is not None else None,
                  delta_color="inverse")

        st.subheader(f"Indice de fréquence AT par secteur ({atmp_period})")
        avg = national.get("indice_frequence_at")
        bars = alt.Chart(atmp_df).mark_bar(color=SERIES, height={"band": 0.7}).encode(
            x=alt.X("indice_frequence_at:Q", title="Accidents du travail pour 1 000 salariés"),
            y=alt.Y("secteur:N", sort="-x", title=None, axis=alt.Axis(labelLimit=320)),
            tooltip=[alt.Tooltip("secteur:N", title="Secteur"),
                     alt.Tooltip("indice_frequence_at:Q", title="Indice de fréquence", format=".1f"),
                     alt.Tooltip("evolution_if:Q", title="Évolution sur 1 an (points)", format="+.1f"),
                     alt.Tooltip("accidents_travail:Q", title="Accidents du travail", format=",.0f"),
                     alt.Tooltip("maladies_pro:Q", title="Maladies pro.", format=",.0f")])
        layers = [bars]
        if avg:
            rule = alt.Chart(pd.DataFrame({"x": [avg], "label": [f"Moyenne nationale {avg:.1f}".replace(".", ",")]}))
            layers += [rule.mark_rule(color=REFERENCE, strokeWidth=1).encode(x="x:Q"),
                       rule.mark_text(align="left", dx=4, dy=-6, color=MUTED_INK, fontSize=11).encode(
                           x="x:Q", y=alt.value(0), text="label:N")]
        st.altair_chart(alt.layer(*layers).properties(height=30 * len(atmp_df) + 40), use_container_width=True)
        table_view(atmp_df.rename(columns={"naf": "NAF", "secteur": "Secteur", "indice_frequence_at": "Indice de fréquence AT",
                                           "evolution_if": f"Évolution vs {int(atmp_period) - 1} (points)",
                                           "accidents_travail": "Accidents du travail", "maladies_pro": "Maladies pro."}))
        st.caption("Source : Assurance Maladie, data.ameli.fr (régime général).")

# ─────────────────────────────── Appels d'offres ───────────────────────────────
with tab_tenders:
    st.subheader(f"Avis BOAMP QHSE / RSE ({len(tend_p)})")
    st.caption("Mots-clés recherchés dans l'objet : " + ", ".join(cfg["tenders"]["keywords"]))
    if tend_p.empty:
        st.info("Aucun avis sur la période.")
    else:
        st.dataframe(
            tend_p.assign(date=tend_p["published_at"].dt.strftime("%Y-%m-%d"))
            [["date", "title", "buyer", "nature", "winners", "deadline", "url"]],
            hide_index=True, use_container_width=True,
            column_config={"date": "Parution", "title": st.column_config.TextColumn("Objet", width="large"),
                           "buyer": "Acheteur", "nature": "Nature", "winners": "Titulaire(s)",
                           "deadline": "Date limite", "url": st.column_config.LinkColumn("Avis", display_text="ouvrir")})

# ─────────────────────────────── Sources ───────────────────────────────
with tab_src:
    st.subheader("État des sources")
    st.dataframe(src, hide_index=True, use_container_width=True)
    st.markdown(
        "- **Presse** : flux RSS publics, robots.txt respecté ; titre, lien et extrait court uniquement (droit voisin).\n"
        "- **Classement** : mots-clés par thème (`config.yaml`), sans IA générative.\n"
        "- **Concurrents** : comparaison du texte visible des pages publiques ; pas de contournement des sites qui refusent les robots.\n"
        "- **Marché & AT/MP** : open data Assurance Maladie (régime général) ; BOAMP (DILA) ; France Travail si configuré.")
