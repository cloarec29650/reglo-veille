"""Tests hors ligne : aucune requête réseau, données de test maîtrisées."""

from datetime import date
from pathlib import Path

import pytest
import yaml

from veille.classify import classify, compile_competitors, compile_themes
from veille.collectors.competitors import diff_lines, mentions_price, page_lines
from veille.collectors.market import boamp_where
from veille.collectors.press import parse_entries
from veille.digest import build_digest
from veille.html_export import render_html
from veille.http import RobotsDisallowed, describe_error
from veille.storage import Store
from veille.text import normalize, strip_html, title_key, truncate

CFG = yaml.safe_load((Path(__file__).parent.parent / "config.yaml").read_text(encoding="utf-8"))
THEMES = compile_themes(CFG["themes"])
COMPETITORS = compile_competitors(CFG["competitors"])


# ── Texte ──
def test_normalize_retire_accents_et_casse():
    assert normalize("  Sécurité  au TRAVAIL ") == "securite au travail"


def test_strip_html_et_mention_wordpress():
    raw = "<p>ISO 9001 &amp; risques</p> The post Titre appeared first on qualiblog.fr ."
    assert strip_html(raw) == "ISO 9001 & risques"


def test_truncate_coupe_sur_un_mot():
    assert truncate("un deux trois quatre", 12) == "un deux…"


def test_title_key_deduplique_les_variantes():
    assert title_key("CSRD : ce qui change !") == title_key("csrd ce qui change")


# ── Classement ──
def test_article_qhse_retenu_avec_theme_principal():
    c = classify("Accident du travail : le DUERP devient central pour la prévention des risques", THEMES, COMPETITORS)
    assert c.relevant
    assert c.themes[0] == "sst_prevention"


def test_mot_cle_entier_uniquement():
    # « hse » ne doit pas être trouvé dans « qhse », ni « rse » dans « course ».
    c = classify("Une course de QHSE", THEMES, COMPETITORS)
    assert "normes_certification" in c.themes
    assert "contexte" not in c.themes


def test_theme_non_coeur_seul_non_retenu():
    c = classify("Une startup SaaS pour les PME", THEMES, COMPETITORS)
    assert not c.relevant


def test_score_minimal_ecarte_les_mentions_isolees():
    # Un seul mot-clé coeur (2 points) : retenu sans seuil, écarté avec un seuil de 4.
    assert classify("Une certification obtenue", THEMES, COMPETITORS).relevant
    assert not classify("Une certification obtenue", THEMES, COMPETITORS, min_score=4).relevant
    assert classify("Certification ISO 45001 et DUERP à jour", THEMES, COMPETITORS, min_score=4).relevant


def test_concurrent_homonyme_exige_un_theme_metier():
    # « Sweep » est aussi un nom de vélo : sans thème métier, la mention est ignorée.
    assert classify("Test Scott Sweep : trois vélos électriques", THEMES, COMPETITORS).competitors == []
    c = classify("Sweep accompagne les PME dans leur reporting CSRD", THEMES, COMPETITORS)
    assert c.competitors == ["Sweep"]


def test_concurrent_cite_rend_l_article_pertinent():
    c = classify("EcoVadis annonce une nouvelle offre", THEMES, COMPETITORS)
    assert c.relevant and c.competitors == ["EcoVadis"]


# ── Presse ──
RSS = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>T</title>
<item><title>CSRD &amp; VSME : le guide</title><link>https://ex.test/a</link>
<description>&lt;p&gt;Les PME et la VSME.&lt;/p&gt;</description><pubDate>Mon, 05 Oct 2026 08:00:00 GMT</pubDate></item>
<item><title></title><link>https://ex.test/vide</link></item>
</channel></rss>"""


def test_parse_entries_rss():
    entries = parse_entries(RSS, "Test", 280)
    assert len(entries) == 1  # l'entrée sans titre est ignorée
    e = entries[0]
    assert e["title"] == "CSRD & VSME : le guide"
    assert e["snippet"] == "Les PME et la VSME."
    assert e["published_at"].startswith("2026-10-05")


# ── Concurrents ──
HTML_V1 = """<html><head><title>x</title><script>var a=1;</script></head><body>
<nav><a href="/">Accueil</a></nav><h1>Logiciel QHSE</h1><p>Offre Essentiel : 49 € HT / mois</p>
<footer>© 2026 Tous droits réservés</footer></body></html>"""
HTML_V2 = HTML_V1.replace("49 €", "59 €").replace("<h1>Logiciel QHSE</h1>", "<h1>Logiciel QHSE</h1><p>Nouveau module CSRD</p>")


def test_page_lines_ignore_scripts_et_bruit():
    lines = page_lines(HTML_V1)
    assert "Logiciel QHSE" in lines
    assert not any("var a" in l for l in lines)
    assert not any("droits" in l.lower() for l in lines)


def test_diff_detecte_ajouts_retraits_et_prix():
    added, removed = diff_lines(page_lines(HTML_V1), page_lines(HTML_V2))
    assert "Nouveau module CSRD" in added
    assert any("59 €" in l for l in added) and any("49 €" in l for l in removed)
    assert mentions_price(added + removed)


def test_aucun_changement():
    assert diff_lines(page_lines(HTML_V1), page_lines(HTML_V1)) == ([], [])


# ── Marché ──
def test_requete_boamp():
    where = boamp_where(["QHSE", "RSE"], date(2026, 10, 5))
    assert where == '(search(objet, "QHSE") or search(objet, "RSE")) and dateparution >= date\'2026-10-05\''


# ── Erreurs ──
def test_describe_error_403_et_robots():
    class Resp:
        status_code = 403

    class HttpErr(Exception):
        response = Resp()

    assert "suivi manuel" in describe_error(HttpErr())
    assert "robots.txt" in describe_error(RobotsDisallowed("u"))


# ── Stockage + digest (bout en bout, hors ligne) ──
@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "t.sqlite")
    yield s
    s.close()


def test_article_deduplique(store):
    a = {"key": "k", "title": "T", "url": "u", "source": "S", "published_at": "2026-10-10T00:00:00+00:00",
         "snippet": "", "themes": ["csrd_vsme"], "competitors": [], "score": 2}
    assert store.add_article(a) is True
    assert store.add_article({**a, "source": "Autre"}) is False


def test_digest_complet(store):
    store.add_article({"key": "k", "title": "VSME pour les PME", "url": "https://ex.test", "source": "S",
                       "published_at": "2026-10-10T00:00:00+00:00", "snippet": "Extrait",
                       "themes": ["csrd_vsme"], "competitors": ["EcoVadis"], "score": 5})
    store.add_change("https://c.test", "Concurrent", ["Prix : 59 €"], ["Prix : 49 €"], True)
    for dim, label, v in [("taille:1", "Moins de 10", 1000), ("taille:2", "10-19", 100), ("taille:3", "20-49", 50)]:
        store.put_indicator("entreprises", "2024", dim, v, "test", label)
        store.put_indicator("entreprises", "2023", dim, v / 2, "test", label)
    store.put_indicator("entreprises_cible", "2024", "naf1:F", 80, "test", "Construction")
    store.put_indicator("entreprises_cible", "2024", "naf1:x", 5, "test", "Valeur manquante")
    for y, v in [("2024", 41.2), ("2023", 42.9)]:
        store.put_indicator("at_indice_frequence", y, "naf1:F", v, "test", "Construction")
        store.put_indicator("at_indice_frequence", y, "naf1:TOUS", 26.4, "test", "Tous")
    store.commit()
    store.save_run("2026-10-12T00:00:00+00:00", {"Presse": {"S": {"ok": True, "lus": 1}}})

    cfg = {**CFG, "market": {**CFG["market"], "target_size_orders": [2, 3],
                             "annual_price_by_size_order": {2: 1000, 3: 2000}}}
    md = build_digest(store, cfg, days=7, today=date(2026, 10, 12))

    assert "VSME pour les PME" in md and "Cite **EcoVadis**" in md
    assert "mention de prix modifiée" in md
    assert "Entreprises dans les tranches ciblées : 150" in md
    assert "200\u00a0000 € HT / an" in md                     # 100 × 1 000 + 50 × 2 000
    assert "+100,0 %" in md                                    # évolution 2023 → 2024
    assert "Valeur manquante" not in md                        # secteur « x » écarté
    assert "-1,7" in md                                        # évolution de l'indice de fréquence


# ── Export HTML ──
def test_html_autonome_avec_sommaire_et_tableaux():
    md = "# Veille S42\n\n## 1. À retenir\n\n- [Titre](https://ex.test/a)\n\n## 2. Marché\n\n| A | B |\n|---|---|\n| 1 | 2 |\n"
    page = render_html(md, "12/10/2026")
    assert page.startswith("<!doctype html>") and "<style>" in page        # CSS intégré, aucun fichier externe
    assert "<title>Veille S42</title>" in page
    assert 'href="#1-a-retenir"' in page  # sommaire vers les sections
    assert '<div class="table-wrap"><table>' in page
    assert 'target="_blank" rel="noopener noreferrer"' in page


def test_html_neutralise_contenu_tiers_malveillant():
    md = "# T\n\n## S\n\n- [<script>alert(1)</script>](javascript:alert(1)) <img src=x onerror=alert(1)>\n"
    page = render_html(md, "x")
    assert "<script>alert" not in page and "<img" not in page
    assert "javascript:" not in page


# ── Requêtes du dashboard ──
def test_requetes_dashboard(store):
    from veille import queries
    for dim, label, v, s in [("taille:1", "Moins de 10", 1000, 2000), ("taille:2", "10-19", 100, 1500)]:
        store.put_indicator("entreprises", "2024", dim, v, "t", label)
        store.put_indicator("entreprises", "2023", dim, v / 2, "t", label)
        store.put_indicator("salaries", "2024", dim, s, "t", label)
    for dim, label, n in [("naf1:F", "Construction", 80), ("naf1:x", "Valeur manquante", 5), ("naf1:T", "Ménages", 0)]:
        store.put_indicator("entreprises_cible", "2024", dim, n, "t", label)
    store.put_indicator("at_indice_frequence", "2024", "naf1:F", 41.2, "t", "Construction")
    store.put_indicator("at_indice_frequence", "2024", "naf1:TOUS", 26.4, "t", "Tous")
    store.put_indicator("at_sinistres", "2024", "naf1:F", 68430, "t", "Construction")
    store.put_indicator("at_sinistres", "2024", "naf1:TOUS", 549614, "t", "Tous")
    store.commit()

    period, by_size = queries.market_by_size(store)
    assert period == "2024" and list(by_size["evolution"]) == [1.0, 1.0]
    assert queries.addressable_market(by_size, {2: 1200}) == 120_000

    seg = queries.segmentation(store)
    assert list(seg["naf"]) == ["F"]                      # « x » et secteurs vides écartés
    assert seg.loc[0, "indice_frequence_at"] == 41.2

    year, sectors, national = queries.atmp(store)
    assert list(sectors["naf"]) == ["F"] and national["indice_frequence_at"] == 26.4


# ── Sources approfondies ──
from datetime import datetime, timezone

from veille.collectors.companies import event_detail
from veille.collectors.press import bing_queries, resolve_link, too_old
from veille.collectors.regulation import build_query, celex_kind
from veille.text import looks_english


def test_lien_bing_resolu_vers_l_article():
    link = ("http://www.bing.com/news/apiclick.aspx?ref=FexRss&aid=&tid=abc"
            "&url=https%3a%2f%2fcdurable.info%2fvsme-pme%2f&c=123")
    assert resolve_link(link) == "https://cdurable.info/vsme-pme/"
    assert resolve_link("https://ex.test/a") == "https://ex.test/a"


def test_detection_anglais():
    assert looks_english("ISO 45001 Certification: Your Key to a Safe Workplace and the Future")
    assert not looks_english("Certification ISO 45001 : l'intérêt d'un audit à blanc pour les PME")


def test_filtre_anciennete():
    now = datetime(2026, 10, 13, tzinfo=timezone.utc)
    assert too_old({"published_at": "2025-01-01T00:00:00+00:00"}, 120, now)
    assert not too_old({"published_at": "2026-09-01T00:00:00+00:00"}, 120, now)
    assert not too_old({"published_at": None}, 120, now)


def test_requetes_bing_incluent_les_concurrents():
    queries = bing_queries(CFG)
    assert ('"Preventeo"', True) in queries
    assert any(not is_comp for _, is_comp in queries)


def test_requete_eurlex():
    q = build_query(["durabilité", "2023/2772"], date(2026, 6, 1), ["rectificatif"])
    assert '"2026-06-01"^^xsd:date' in q
    assert "(durabilité)|(2023/2772)" in q
    assert 'FILTER(!REGEX(?title, "(rectificatif)", "i"))' in q
    assert celex_kind("32026R2241") == "Règlement" and celex_kind("52026PC0985") == "Proposition"


def test_detail_annonce_bodacc():
    record = {"depot": '{"dateCloture": "2025-12-31", "typeDepot": "Comptes annuels et rapports"}', "jugement": None}
    assert event_detail(record) == "2025-12-31 ; Comptes annuels et rapports"
