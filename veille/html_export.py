"""Export HTML du digest : une page autonome (CSS intégré), lisible dans un navigateur ou envoyée par email.

Direction visuelle : un registre d'inspection QHSE. Papier froid, encre ardoise, bleu « obligation » ISO 7010
pour les liens ; l'élément fort est le grand numéro de semaine en tête.
Charte graphique : modifier uniquement les variables CSS de :root (bloc THEME ci-dessous).
"""

import html
import re

import markdown

FONTS = ('<link rel="preconnect" href="https://fonts.googleapis.com">'
         '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
         '<link href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@500;600;700'
         '&family=Barlow:ital,wght@0,400;0,500;0,600;1,400&display=swap" rel="stylesheet">')

THEME = """
:root {
  color-scheme: light;
  --paper: #f3f5f6;        /* fond « papier de rapport », froid */
  --sheet: #fbfcfc;        /* surfaces de tableau */
  --ink: #1b2430;          /* encre ardoise */
  --ink-2: #5b6672;        /* texte secondaire */
  --rule: #d3d9de;         /* filets */
  --link: #005387;         /* bleu « obligation » ISO 7010 */
  --display: "Barlow Condensed", "Roboto Condensed", "Arial Narrow", sans-serif;
  --text: "Barlow", "Segoe UI", Roboto, sans-serif;
}
@media (prefers-color-scheme: dark) {
  :root:where(:not([data-theme="light"])) {
    color-scheme: dark;
    --paper: #141a20; --sheet: #1a2129; --ink: #e4e9ee; --ink-2: #a3aeb9; --rule: #2c3640; --link: #74b3e6;
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --paper: #141a20; --sheet: #1a2129; --ink: #e4e9ee; --ink-2: #a3aeb9; --rule: #2c3640; --link: #74b3e6;
}
"""

LAYOUT = """
* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
@media (prefers-reduced-motion: reduce) { html { scroll-behavior: auto; } }
body { margin: 0; background: var(--paper); color: var(--ink); font: 400 1.0625rem/1.6 var(--text); }
a { color: var(--link); text-underline-offset: .18em; text-decoration-thickness: 1px; }
a:hover { text-decoration-thickness: 2px; }
a:focus-visible { outline: 2px solid var(--link); outline-offset: 2px; border-radius: 2px; }

.masthead { max-width: 1120px; margin: 0 auto; padding: 28px 24px 8px; }
.product { margin: 0 0 18px; font-size: .95rem; color: var(--ink-2); }
.issue { display: grid; grid-template-columns: auto 1fr; gap: 8px 28px; align-items: end; }
.week { font: 700 clamp(4.5rem, 14vw, 8.5rem)/.8 var(--display); letter-spacing: -.02em; }
.issue h1 { margin: 0 0 6px; font: 600 clamp(1.5rem, 3.2vw, 2.1rem)/1.15 var(--display); }
.lede { margin: 0; max-width: 62ch; font-size: 1.12rem; color: var(--ink); }

.layout { max-width: 1120px; margin: 0 auto; padding: 8px 24px 64px;
          display: grid; grid-template-columns: 190px minmax(0, 1fr); gap: 48px; }
.toc { position: sticky; top: 24px; align-self: start; padding-top: 34px; font-size: .95rem; }
.toc p { margin: 0 0 8px; color: var(--ink-2); }
.toc ul { list-style: none; margin: 0; padding: 0; border-left: 2px solid var(--rule); }
.toc li { margin: 0; }
.toc a { display: block; padding: 5px 0 5px 14px; margin-left: -2px; border-left: 2px solid transparent;
         color: var(--ink); text-decoration: none; }
.toc a:hover { border-left-color: var(--link); color: var(--link); }

.content { min-width: 0; }
.content h2 { margin: 44px 0 14px; padding-top: 12px; border-top: 2px solid var(--ink);
              font: 600 1.85rem/1.1 var(--display); scroll-margin-top: 16px; }
.content h3 { margin: 28px 0 8px; font: 600 1.25rem/1.2 var(--display); }
.content p, .content ul, .content ol { max-width: 72ch; }
.content ul { padding-left: 1.1em; }
.content li { margin: 6px 0; }
.content li::marker { color: var(--ink-2); }
.content em { color: var(--ink-2); }
blockquote { margin: 4px 0 12px; padding: 0 0 0 14px; border-left: 2px solid var(--rule); color: var(--ink-2); font-size: .97rem; }
blockquote p { margin: 0; }

.table-wrap { overflow-x: auto; margin: 10px 0 20px; background: var(--sheet); }
table { border-collapse: collapse; width: 100%; font-size: .95rem; }
th { text-align: left; font-weight: 600; color: var(--ink-2); border-bottom: 2px solid var(--ink); white-space: nowrap; }
th, td { padding: 9px 12px; vertical-align: top; }
td { border-bottom: 1px solid var(--rule); }
td:not(:first-child) { font-variant-numeric: tabular-nums; }
tr:last-child td { border-bottom: none; }

footer { max-width: 1120px; margin: 0 auto; padding: 0 24px 40px; color: var(--ink-2); font-size: .9rem; }
footer p { margin: 0; padding-top: 14px; border-top: 1px solid var(--rule); }

@media (max-width: 900px) {
  .layout { grid-template-columns: 1fr; gap: 0; }
  .toc { position: static; padding-top: 12px; }
  .toc ul { display: flex; flex-wrap: wrap; gap: 4px 20px; border-left: none; }
  .toc a { padding: 4px 0; margin: 0; border-left: none; text-decoration: underline; text-decoration-color: var(--rule); }
}
@media (max-width: 560px) {
  .issue { grid-template-columns: 1fr; }
  .masthead, .layout, footer { padding-left: 16px; padding-right: 16px; }
}
@media print {
  body { background: #fff; }
  .toc { display: none; }
  .layout { grid-template-columns: 1fr; }
}
"""


def render_html(md_text: str, generated_at: str) -> str:
    """Convertit le digest Markdown en page HTML autonome."""
    # Les titres et extraits viennent de sites tiers : aucun HTML brut ne doit passer
    # (le digest n'en contient pas volontairement, « < » est donc toujours échappé).
    body = markdown.markdown(md_text.replace("<", "&lt;"), extensions=["tables", "sane_lists", "toc"],
                             output_format="html")
    # Seuls les liens http(s) et les ancres internes sont conservés (pas de javascript:, data:…).
    body = re.sub(r'href="(?!https?://|#)[^"]*"', 'href="#"', body)

    # Titre et phrase de synthèse sortis du corps pour l'en-tête.
    title_match = re.search(r"<h1[^>]*>(.*?)</h1>", body, re.DOTALL)
    title = title_match.group(1) if title_match else "Veille marché"
    if title_match:
        body = body.replace(title_match.group(0), "", 1)
    lede_match = re.match(r"\s*<p>(.*?)</p>", body, re.DOTALL)
    lede = lede_match.group(1) if lede_match else ""
    if lede_match:
        body = body[lede_match.end():]
    week_match = re.search(r"semaine (\d+)", title)
    week = f"S{week_match.group(1)}" if week_match else ""

    # Liens externes : nouvel onglet, sans transmettre la page d'origine.
    body = re.sub(r'<a href="(https?://[^"]+)"', r'<a href="\1" target="_blank" rel="noopener noreferrer"', body)
    # Tableaux défilables sur petit écran.
    body = body.replace("<table>", '<div class="table-wrap"><table>').replace("</table>", "</table></div>")

    sections = re.findall(r'<h2 id="([^"]+)">(.*?)</h2>', body)
    toc = "".join(f'<li><a href="#{sid}">{label}</a></li>' for sid, label in sections)
    plain_title = html.unescape(re.sub(r"<[^>]+>", "", title))

    return f"""<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(plain_title)}</title>
{FONTS}
<style>{THEME}{LAYOUT}</style>
</head>
<body>
<header class="masthead">
  <p class="product">Reglo, veille du marché QHSE et RSE</p>
  <div class="issue">
    <span class="week" aria-hidden="true">{week}</span>
    <div>
      <h1>{title}</h1>
      <p class="lede">{lede}</p>
    </div>
  </div>
</header>
<div class="layout">
  <nav class="toc" aria-label="Sommaire"><p>Sommaire</p><ul>{toc}</ul></nav>
  <main class="content">
{body}
  </main>
</div>
<footer><p>Généré automatiquement le {html.escape(generated_at)} à partir de données publiques datées. L'interprétation revient à l'équipe Reglo.</p></footer>
</body>
</html>
"""
