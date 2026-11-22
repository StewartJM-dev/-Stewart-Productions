#!/usr/bin/env python3
"""Plan additive updates from Stewart Productions' three public catalogs."""

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from html import escape, unescape
from pathlib import Path
from urllib.parse import urlsplit
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from xml.etree import ElementTree
from browse_catalog import BROWSE_FILE, build_index, serialize, title_key
from lyrics_catalog import LYRICS_FILE, LYRICS_PANEL, build_lyrics
from rank_catalog import card_route, public_count, rank_cards, reaction_text, score_value, video_id, youtube_count
import json
import re
import unicodedata

AUDIOMACK = "https://audiomack.com"
SUNO = "https://suno.com"
YOUTUBE = "https://www.youtube.com"
YOUTUBE_FEED = YOUTUBE + "/feeds/videos.xml?channel_id=UCAkkuAvytd_RzBigc0w6W9Q"
RAW = "https://raw.githubusercontent.com/StewartJM-dev/-Stewart-Productions/"
SOURCE_LINKS = (
    ("Audiomack", AUDIOMACK + "/stewartjm"),
    ("Suno", SUNO + "/@stewartjm"),
    ("YouTube", YOUTUBE + "/@stewartproductions1982"),
)
RAILS = {"albums": "albums-track", "singles": "singles-track", "videos": "featured-track"}
SECTION_IDS = {"albums": "albums", "singles": "singles", "videos": "featured", "about": "about", "browse": "browse"}
SHARE_PANEL = '''      <div class="share-control" data-share-control hidden>
        <button type="button" data-share-button>Share</button>
        <span data-share-status role="status"></span>
        <input type="url" data-share-url aria-label="Link to this page" readonly hidden>
      </div>
'''


@dataclass(frozen=True)
class Release:
    category: str
    title: str
    identity: str
    slug: str
    artwork: str
    url: str
    embed: str
    provider: str
    tracks: int = 0
    tags: str = ""
    likes: int | None = None


def fetch(url):
    request = Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "en-US"})
    with urlopen(request, timeout=15) as response:
        return response.read().decode("utf-8")


def public_image(url, domains):
    if not isinstance(url, str):
        return ""
    parsed = urlsplit(url)
    if parsed.scheme == "https" and parsed.hostname in domains and not parsed.username and not parsed.port:
        return url
    return ""


def slug_for(title):
    text = unicodedata.normalize("NFKD", title.casefold()).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")[:80].rstrip("-")


def structured_data(document):
    """Read the public Next.js payload in addition to the visible profile cards."""
    chunks = []
    for match in re.finditer(r"self\.__next_f\.push\(", document):
        try:
            entry = json.JSONDecoder().raw_decode(document[match.end():])[0]
        except ValueError:
            continue
        if isinstance(entry, list) and len(entry) > 1 and entry[0] == 1 and isinstance(entry[1], str):
            chunks.append(entry[1])
    for line in "".join(chunks).splitlines():
        _, _, body = line.partition(":")
        try:
            yield json.loads(body)
        except ValueError:
            continue


def objects(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from objects(child)
    elif isinstance(value, list):
        for child in value:
            yield from objects(child)


def audiomack_releases(document):
    by_path = {}
    for payload in structured_data(document):
        for item in objects(payload):
            path = item.get("href")
            owner = item.get("uploadedBy")
            if not isinstance(path, str) or not isinstance(owner, dict):
                continue
            match = re.fullmatch(r"/stewartjm/(album|song)/([a-zA-Z0-9_-]+)", path)
            if not match or owner.get("slug") != "stewartjm" or item.get("isPrivate") is True:
                continue
            if not isinstance(item.get("title"), str) or not item.get("id"):
                continue
            if path not in by_path or "trackCount" in item:
                by_path[path] = item

    if not by_path:
        raise ValueError("Audiomack's public profile did not expose verified release data")

    releases = []
    album_tracks = set()
    for path, item in by_path.items():
        _, _, kind, slug = path.split("/")
        title = item["title"].strip()
        if kind == "song" and (item.get("albumId") or item.get("parentAlbum") or item.get("releaseAlbum")):
            album_tracks.add(title_key(title))
            continue
        image = public_image(item.get("coverUrl"), {"i.audiomack.com"})
        releases.append(Release(
            "albums" if kind == "album" else "singles",
            title, "audiomack:" + str(item["id"]), slug, image,
            AUDIOMACK + path, AUDIOMACK + "/embed" + path, "Audiomack",
            int(item.get("trackCount") or 0),
            tags=item.get("genre") if isinstance(item.get("genre"), str) else "",
            likes=public_count((item.get("stats") or {}).get("favorites-raw")),
        ))
    return releases, album_tracks


def suno_releases(document):
    releases = []
    seen = set()
    for payload in structured_data(document):
        for item in objects(payload):
            if item.get("feedId") != "user_songs":
                continue
            for result in item.get("items", []):
                song = result.get("contentItem") or {}
                identity, title = song.get("id"), song.get("title")
                if not isinstance(identity, str) or not isinstance(title, str):
                    continue
                if identity in seen or not re.fullmatch(r"[a-f0-9-]{36}", identity):
                    continue
                seen.add(identity)
                image = public_image(
                    song.get("imageLargeUrl") or song.get("imageUrl"),
                    {"cdn1.suno.ai", "cdn2.suno.ai", "cdn.suno.ai"},
                )
                metadata = song.get("metadata") or {}
                tags = " ".join(v for v in (song.get("displayTags"), metadata.get("tags")) if isinstance(v, str))
                releases.append(Release(
                    "singles", title.strip(), "suno:" + identity, slug_for(title) or identity,
                    image, SUNO + "/song/" + identity, SUNO + "/embed/" + identity, "Suno",
                    tags=tags, likes=public_count(song.get("upvoteCount")),
                ))
    if not releases:
        raise ValueError("Suno's public profile did not expose verified songs")
    return releases


def youtube_releases(document):
    ns = {"a": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015"}
    feed = ElementTree.fromstring(document)
    releases = []
    for entry in feed.findall("a:entry", ns):
        identity = entry.findtext("yt:videoId", "", ns)
        title = entry.findtext("a:title", "", ns).strip()
        if not title or not re.fullmatch(r"[a-zA-Z0-9_-]{11}", identity):
            continue
        releases.append(Release(
            "videos", title, "youtube:" + identity, slug_for(title) or identity,
            f"https://i.ytimg.com/vi/{identity}/mqdefault.jpg",
            YOUTUBE + "/watch?v=" + identity, YOUTUBE + "/embed/" + identity, "YouTube",
        ))
    if not releases:
        raise ValueError("YouTube's public feed contained no verified videos")
    return releases


def youtube_catalog(homepage):
    releases = youtube_releases(fetch(YOUTUBE_FEED))
    row = existing_cards(homepage)["videos"][0]
    ids = {release.identity.split(":", 1)[1] for release in releases}
    ids.update(video_id(card[0]) for card in re.finditer(r'<li\b[^>]*>.*?</li>', row[1], re.S))
    ids.discard(None)

    def likes(identity):
        try:
            return identity, youtube_count(fetch(YOUTUBE + "/watch?v=" + identity))
        except (OSError, ValueError):
            return identity, None

    with ThreadPoolExecutor(max_workers=5) as pool:
        return releases, dict(pool.map(likes, sorted(ids)))


def audiomack_catalog():
    releases, album_tracks = audiomack_releases(fetch(SOURCE_LINKS[0][1]))

    def album_tracklist(album):
        # Some tracks are unlisted outside the public album. Read its player
        # tracklist so those tracks still count when comparing Suno singles.
        document = fetch(album.embed)
        links = list(dict.fromkeys(re.findall(r'href="(?:https://audiomack\.com)?/stewartjm/song/([a-zA-Z0-9_-]+)"', document)))
        if not links or album.tracks and len(links) < album.tracks:
            raise ValueError(f"Incomplete Audiomack tracklist for {album.title}")
        verified = set(links)
        titles, votes, tags = {}, {}, {}
        for payload in structured_data(document):
            for item in objects(payload):
                path, title = item.get("href"), item.get("title")
                if isinstance(path, str) and path.startswith("/stewartjm/song/") and isinstance(title, str):
                    slug = path.rsplit("/", 1)[1]
                    if slug in verified:
                        titles[slug] = title
                        if isinstance(item.get("genre"), str):
                            tags[slug] = item["genre"]
                        count = public_count((item.get("stats") or {}).get("favorites-raw"))
                        if count is not None:
                            votes[slug] = count

        def readable(slug):
            name = titles.get(slug, slug.replace("-", " ").title())
            if " " not in name and "-" in name:
                name = re.sub(r"---(?=[sStT](?:-|$))", "’", name)
                name = re.sub(r"-+", " ", name).strip()
            return name

        tracks = [(readable(slug), votes.get(slug), f"{AUDIOMACK}/embed/stewartjm/song/{slug}", tags.get(slug, ""))
                  for slug in links]
        return title_key(album.title), tracks, {title_key(slug) for slug in links}

    album_songs = {}
    with ThreadPoolExecutor(max_workers=6) as pool:
        for title, songs, keys in pool.map(album_tracklist, (release for release in releases if release.category == "albums")):
            album_songs[title] = songs
            album_tracks.update(keys)
    return releases, album_tracks, album_songs


def existing_cards(homepage):
    cards = {}
    for category, rail_id in RAILS.items():
        matches = list(re.finditer(rf'<ul\b[^>]*\bid="{rail_id}"[^>]*>(.*?)</ul>', homepage, re.S))
        if len(matches) != 1:
            raise ValueError(f"Expected exactly one {category} row in index.html")
        row = matches[0]
        titles, identities, paths = set(), set(), set()
        for card in re.finditer(r"<li\b[^>]*>(.*?)</li>", row[1], re.S):
            content = card[1]
            link = re.search(r'href="(' + category + r'/[^"]+/)"', content)
            heading = re.search(r"<h3>(.*?)</h3>", content, re.S)
            identity = re.search(r'data-release-id="([^"]+)"', content)
            image = re.search(r'https://i\.ytimg\.com/vi/([\w-]{11})/', content)
            if not link or not heading:
                raise ValueError(f"Could not verify an existing {category} card")
            paths.add(link[1])
            titles.add(title_key(unescape(heading[1])))
            if identity:
                identities.add(identity[1])
            elif category == "videos" and image:
                identities.add("youtube:" + image[1])
        cards[category] = (row, titles, identities, paths)
    return cards


def card_html(release, route):
    image = escape(release.artwork or "assets/stewart-badge.webp", quote=True)
    title = escape(release.title)
    dimensions = 'width="320" height="180"' if release.category == "videos" else 'width="700" height="700"'
    count = f"\n              <p>{release.tracks} tracks</p>" if release.tracks else ""
    return f'''        <li>
          <a class="catalog-card" href="{route}" data-release-id="{escape(release.identity, quote=True)}">
            <img src="{image}" alt="" {dimensions} loading="lazy">
            <div class="card-copy">
              <h3>{title}</h3>{count}
            </div>
          </a>
        </li>
'''


def feature_releases(homepage, routes, scores=None):
    match = re.search(r'<ul\b[^>]*\bid="new-or-featured-items"[^>]*>(.*?)</ul>', homepage, re.S)
    if not match:
        return homepage
    priority = []
    for i, card in enumerate(re.finditer(r'<li\b[^>]*>.*?</li>', match[1], re.S)):
        order = re.search(r'data-feature-order="([0-9]+)"', card[0])
        priority.append((int(order[1]) if order else i, card_route(card[0])))
    previous = [route for _, route in sorted(priority)]
    selected = list(dict.fromkeys([*routes, *previous]))[:3]
    position = {route: i for i, route in enumerate(selected)}
    scores = scores or {}
    selected.sort(key=lambda route: score_value(scores, route), reverse=True)
    cards = {}
    rows = existing_cards(homepage)
    for category, kind in (("albums", "Album"), ("singles", "Single"), ("videos", "Video")):
        row = rows[category][0]
        for card in re.finditer(r'<li\b[^>]*>(.*?)</li>', row[1], re.S):
            href = re.search(r'href="([^"]+)"', card[1])
            image = re.search(r'<img\b[^>]*\bsrc="([^"]+)"', card[1])
            title = re.search(r'<h3>([^<]+)</h3>', card[1])
            if href and image and title:
                cards[href[1]] = (image[1], title[1], kind)
    featured = []
    for route in selected:
        if route not in cards:
            continue
        image, title, kind = cards[route]
        featured.append(f'''        <li data-feature-order="{position[route]}">
          <a class="home-feature-card" href="{route}">
            <img src="{image}" alt="" loading="lazy">
            <div><p>{kind}</p><h3>{title}</h3>{reaction_text(scores.get(route))}</div>
          </a>
        </li>
''')
    return homepage[:match.start(1)] + "\n" + "".join(featured) + "      " + homepage[match.end(1):]


def extract(layout, pattern):
    match = re.search(pattern, layout, re.S)
    if not match:
        raise ValueError("Could not reuse the current site layout")
    return match[0]


def site_page(layout, title, main, depth, current=None, load_rails=False, load_lyrics=False, load_playlist=False):
    prefix = "../" * depth
    header = extract(layout, r'<a class="skip-link".*?</header>')
    footer = extract(layout, r'<footer\b.*?</footer>')
    footer = footer.replace('href="playlist/"', f'href="{prefix}playlist/"')
    footer = footer.replace('      <nav aria-label="Music platforms">', SHARE_PANEL + '      <nav aria-label="Music platforms">')
    header = header.replace(' aria-current="page"', "").replace('src="assets/', f'src="{prefix}assets/')
    header = header.replace('href="./"', f'href="{prefix}"')
    for folder in SECTION_IDS:
        header = header.replace(f'href="{folder}/"', f'href="{prefix}{folder}/"')
    if current:
        header = header.replace(f'href="{prefix}{current}/">', f'href="{prefix}{current}/" aria-current="page">')
    rails = f'\n  <script src="{prefix}assets/catalog.js" defer></script>' if load_rails else ""
    lyrics = f'\n  <script src="{prefix}assets/lyrics.js" defer></script>' if load_lyrics else ""
    playlist = f'\n  <script src="{prefix}assets/playlist.js" defer></script>' if load_playlist else ""
    return f'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="theme-color" content="#164632">
  <title>{title} | Stewart Productions</title>
  <link rel="manifest" href="{prefix}app.webmanifest">
  <link rel="apple-touch-icon" href="{prefix}assets/app-icon-180.png">
  <link rel="icon" href="{prefix}assets/stewart-badge.webp">
  <link rel="stylesheet" href="{prefix}assets/catalog.css?v=playlist1">{rails}{lyrics}{playlist}
  <script src="{prefix}assets/share.js" defer></script>
</head>
<body>
  {header}

  {main}

  {footer}
</body>
</html>
'''


def category_page(category, layout):
    section_id = SECTION_IDS[category]
    section = extract(layout, rf'<section\b[^>]*\bid="{section_id}"[^>]*>.*?</section>')
    section = section.replace('<h2 ', '<h1 ', 1).replace('</h2>', '</h1>', 1)
    section = section.replace('src="assets/', 'src="../assets/')
    section = section.replace(f'href="{category}/', 'href="')
    main = f'<main class="catalog-page" id="main">\n    {section}\n  </main>'
    return site_page(layout, category.title(), main, depth=1, current=category, load_rails=category != "about")


def detail_page(release, layout):
    title = escape(release.title)
    artwork = escape(release.artwork or "../../assets/stewart-badge.webp", quote=True)
    url = escape(release.url, quote=True)
    embed = escape(release.embed, quote=True)
    if release.category == "videos":
        main = f'''<main class="wrap video-page" id="main">
    <a class="back-link" href="../../videos/">Back to videos</a>
    <h1>{title}</h1>
    <div class="media-card">
      <iframe class="video" src="{embed}" title="{title} on YouTube" loading="lazy" referrerpolicy="strict-origin-when-cross-origin" allow="autoplay; encrypted-media; picture-in-picture; web-share" allowfullscreen></iframe>
      <a href="{url}">Watch on YouTube</a>
    </div>
  </main>'''
    else:
        label = f"{release.tracks} tracks" if release.tracks else ("Album" if release.category == "albums" else "Single")
        size = 'class="album-player"' if release.category == "albums" else 'height="252"'
        main = f'''<main class="wrap album-page" id="main">
    <a class="back-link" href="../../{release.category}/">Back to {release.category}</a>
    <section class="album-hero" aria-labelledby="release-title">
      <img class="cover" src="{artwork}" alt="{title} cover art" width="700" height="700" fetchpriority="high">
      <div>
        <h1 id="release-title">{title}</h1>
        <p class="release-meta">John Stewart · {label}</p>
        <a class="button" href="#listen">Listen</a>
      </div>
    </section>
    <section class="section" id="listen" aria-labelledby="listen-title">
      <h2 id="listen-title">Listen</h2>
      <div class="media-card">
        <iframe {size} src="{embed}" title="{title} on {release.provider}" loading="lazy" allow="autoplay; encrypted-media"></iframe>
        <a href="{url}">Open on {release.provider}</a>
      </div>
    </section>
  </main>'''
    audio = release.category != "videos"
    if audio:
        main = main.replace('  </main>', LYRICS_PANEL + '  </main>')
    return site_page(layout, title, main, depth=2, load_lyrics=audio, load_playlist=True)


def plan(homepage, releases, album_tracks):
    cards = existing_cards(homepage)
    changes = {}
    added = []
    changed_categories = []
    for category, (row, titles, identities, paths) in sorted(cards.items(), key=lambda item: item[1][0].start(), reverse=True):
        new_cards = []
        for release in (r for r in releases if r.category == category):
            key = title_key(release.title)
            if not key or release.identity in identities:
                continue
            if category != "videos" and (key in titles or category == "singles" and key in album_tracks):
                continue
            route = f"{category}/{release.slug}/"
            if route in paths:
                if category != "videos":
                    continue
                route = f"{category}/{release.slug}-{release.identity.split(':', 1)[1]}/"
                if route in paths:
                    continue
            paths.add(route)
            titles.add(key)
            identities.add(release.identity)
            new_cards.append(card_html(release, route))
            changes[route + "index.html"] = detail_page(release, homepage)
            added.append({"title": release.title, "category": category, "provider": release.provider, "route": route})
        if new_cards:
            start = homepage.find("\n", row.start()) + 1
            homepage = homepage[:start] + "".join(new_cards) + homepage[start:]
            changed_categories.append(category)
    if changes:
        homepage = feature_releases(homepage, [release["route"] for release in added])
        changes["index.html"] = homepage
        for category in changed_categories:
            changes[f"{category}/index.html"] = category_page(category, homepage)
    return changes, added


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    homepage = parser.add_mutually_exclusive_group(required=True)
    homepage.add_argument("--home", type=Path, help="Use a local index.html")
    homepage.add_argument("--commit", help="Read index.html from an exact GitHub commit")
    args = parser.parse_args()
    if args.commit and not re.fullmatch(r"[a-f0-9]{40}", args.commit):
        parser.error("--commit must be a full commit SHA")
    html = args.home.read_text(encoding="utf-8") if args.home else fetch(RAW + args.commit + "/index.html")

    def prior(filename):
        if args.home:
            path = args.home.parent / filename
            return path.read_text(encoding="utf-8") if path.is_file() else ""
        try:
            return fetch(RAW + args.commit + "/" + filename)
        except HTTPError as error:
            if error.code == 404:
                return ""
            raise

    previous_index = prior(BROWSE_FILE)
    previous_lyrics = prior(LYRICS_FILE)
    warnings, found = [], {}
    with ThreadPoolExecutor() as pool:
        pending = {
            "Audiomack": pool.submit(audiomack_catalog),
            "Suno": pool.submit(lambda: suno_releases(fetch(SOURCE_LINKS[1][1]))),
            "YouTube": pool.submit(youtube_catalog, html),
        }
        for name, future in pending.items():
            try:
                found[name] = future.result()
            except Exception as error:
                warnings.append(f"{name}: {error}")
    audiomack, album_tracks, album_songs = found.get("Audiomack", ([], set(), None))
    suno = found.get("Suno", [])
    youtube, video_counts = found.get("YouTube", ([], {}))
    releases = [*audiomack, *suno, *youtube] if "Audiomack" in found and "Suno" in found else youtube
    changes, added = plan(html, releases, album_tracks)
    prior_index = json.loads(previous_index) if previous_index else {}
    current = changes.get("index.html", html)
    ranked, scores, changed_rows = rank_cards(current, existing_cards(current), [*audiomack, *suno, *youtube], video_counts, prior_index)
    ranked = feature_releases(ranked, [], scores)
    if ranked != html:
        changes["index.html"] = ranked
    for category in changed_rows | {item["category"] for item in added}:
        changes[f"{category}/index.html"] = category_page(category, ranked)
    index = build_index(ranked, [*audiomack, *suno, *youtube], album_songs, prior_index, scores)
    if serialize(index) != previous_index:
        changes[BROWSE_FILE] = serialize(index)
    lyrics = serialize(build_lyrics(index, suno, json.loads(previous_lyrics) if previous_lyrics else None, fetch))
    if lyrics != previous_lyrics:
        changes[LYRICS_FILE] = lyrics
    print(json.dumps({
        "changes": changes, "added": added, "warnings": warnings,
        "observed": dict(Counter(release.provider + " " + release.category for release in [*audiomack, *suno, *youtube])),
        "audiomack_album_tracks": len(album_tracks),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
