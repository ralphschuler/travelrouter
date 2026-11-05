"""Build the public documentation site from tracked Markdown sources."""
import html
import shutil
from pathlib import Path
from urllib.parse import urlsplit

import markdown

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / 'site'
OUT = SITE / 'public'
PAGES = {
    'getting-started': ('README.md', 'Getting started'),
    'operations': ('docs/operations.md', 'Operations & recovery'),
    'security': ('SECURITY.md', 'Security'),
    'design': ('docs/design.md', 'Architecture'),
    'panel-design': ('docs/panel-design.md', 'Panel design'),
    'hardware-test': ('docs/hardware-test.md', 'Hardware qualification'),
    'wifi-support': ('docs/wifi-support.md', 'Wi-Fi driver support'),
    'verification': ('docs/verification.md', 'Verification'),
    'image-testing': ('docs/image-testing.md', 'Image boot tests'),
    'build-targets': ('docs/build-targets.md', 'Platforms & installation'),
    'third-party-notices': ('THIRD_PARTY_NOTICES.md', 'Licenses & notices'),
}
LINKS = {Path(source).stem.lower(): slug + '.html' for slug, (source, _) in PAGES.items()}


class Links(markdown.treeprocessors.Treeprocessor):
    def run(self, root):
        for element in root.iter('a'):
            href = element.get('href', '')
            parsed = urlsplit(href)
            if parsed.scheme or parsed.netloc or not parsed.path.endswith('.md'):
                continue
            target = LINKS.get(Path(parsed.path).stem.lower())
            if target:
                element.set('href', target + ('#' + parsed.fragment if parsed.fragment else ''))


class LocalLinks(markdown.extensions.Extension):
    def extendMarkdown(self, md):
        md.treeprocessors.register(Links(md), 'local-links', 5)


OUT.mkdir(parents=True, exist_ok=True)
shutil.copytree(SITE / 'assets', OUT / 'assets', dirs_exist_ok=True)
shutil.copytree(ROOT / 'src/travelrouter/static/fonts', OUT / 'assets/fonts', dirs_exist_ok=True)
shutil.copyfile(SITE / 'index.html', OUT / 'index.html')
(OUT / '.nojekyll').touch()
template = (SITE / 'template.html').read_text()
for slug, (source, title) in PAGES.items():
    content = markdown.markdown((ROOT / source).read_text(),
                                extensions=['fenced_code', 'tables', 'toc', LocalLinks()])
    nav = ''.join('<a href="' + name + '.html"' + (' aria-current="page"' if name == slug else '') + '>'
                  + html.escape(label) + '</a>' for name, (_, label) in PAGES.items())
    page = template.replace('{{title}}', html.escape(title)).replace('{{navigation}}', nav).replace('{{content}}', content)
    (OUT / (slug + '.html')).write_text(page)
print('Built public documentation:', len(PAGES) + 1, 'pages')
