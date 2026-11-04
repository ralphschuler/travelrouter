"""Verify generated documentation has no missing local pages or assets."""

from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parent / 'public'


class Links(HTMLParser):
    def __init__(self, page):
        super().__init__()
        self.page = page

    def handle_starttag(self, _tag, attrs):
        for name, value in attrs:
            if name not in {'href', 'src'} or not value:
                continue
            parsed = urlsplit(value)
            if parsed.scheme or parsed.netloc or not parsed.path:
                continue
            path = (self.page.parent / unquote(parsed.path)).resolve()
            if not path.is_relative_to(ROOT) or not path.exists():
                raise ValueError(f'{self.page.name}: missing or invalid local link: {value}')


for page in ROOT.glob('*.html'):
    parser = Links(page)
    parser.feed(page.read_text())
print('All generated local documentation links and assets are present')
