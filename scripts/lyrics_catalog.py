"""Collect lyrics shown by Suno for the artist's public tracks."""

from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
import re

from browse_catalog import title_key

LYRICS_FILE = "data/lyrics.json"
LYRICS_PANEL = '''    <section class="section lyrics" id="lyrics" aria-labelledby="lyrics-title" hidden>
      <h2 id="lyrics-title">Lyrics</h2>
      <div id="lyrics-list"></div>
    </section>
'''
PUBLIC_LYRICS = re.compile(
    r'<p\b[^>]*class="[^"]*\bwhitespace-pre-wrap\b[^"]*"[^>]*>((?:(?!</p>).)*)</p>'
    r'\s*<button\b[^>]*aria-label="Copy lyrics to clipboard"',
    re.S,
)
SONG_URL = re.compile(r"https://suno\.com/song/[a-f0-9-]{36}")


class LyricText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag == "br":
            self.parts.append("\n")

    def handle_data(self, data):
        self.parts.append(data)


def shown_lyrics(document):
    match = PUBLIC_LYRICS.search(document)
    if not match:
        return ""
    text = LyricText()
    text.feed(match[1])
    text.close()
    return "".join(text.parts).replace("\r\n", "\n").strip()


def build_lyrics(index, releases, previous, fetch):
    old_pages = (previous or {}).get("pages", {})
    songs = {}
    for release in releases:
        if SONG_URL.fullmatch(release.url):
            songs.setdefault(title_key(release.title), set()).add(release.url)

    items = [item for item in index["items"] if item["kind"] in ("Single", "Album track")]
    matches = []
    for item in items:
        candidates = songs.get(title_key(item["title"]), ())
        if len(candidates) == 1:
            matches.append((item, next(iter(candidates))))

    def read(url):
        try:
            return url, shown_lyrics(fetch(url)) or None
        except (OSError, ValueError):
            return url, None

    with ThreadPoolExecutor(max_workers=6) as pool:
        lyrics = dict(pool.map(read, list(dict.fromkeys(source for _, source in matches))))

    pages = {path: list(entries) for path, entries in old_pages.items()}
    for item, source in matches:
        text = lyrics[source]
        if not text:
            continue
        path = item["href"].partition("#")[0]
        entries = pages.setdefault(path, [])
        title = item["title"]
        lyrics_entry = {"title": title, "source": source, "text": text}
        for i, entry in enumerate(entries):
            if title_key(entry["title"]) == title_key(title):
                entries[i] = lyrics_entry
                break
        else:
            entries.append(lyrics_entry)
    return {"pages": pages}
