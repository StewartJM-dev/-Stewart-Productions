#!/usr/bin/env python3
"""Plan additive updates from Stewart Productions' three public catalogs."""

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from html import escape, unescape
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from xml.etree import ElementTree
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


def title_key(title):
    title = unicodedata.normalize("NFKD", title.casefold().replace("&", " and "))
    return "".join(char for char in title if char.isalnum())


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
                releases.append(Release(
                    "singles", title.strip(), "suno:" + identity, slug_for(title) or identity,
                    image, SUNO + "/song/" + identity, SUNO + "/embed/" + identity, "Suno",
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


def audiomack_catalog():
    releases, album_tracks = audiomack_releases(fetch(SOURCE_LINKS[0][1]))

    def track_keys(album):
        # Some tracks are unlisted outside the public album. Read its player
        # tracklist so those tracks still count when comparing Suno singles.
        document = fetch(album.embed)
        links = set(re.findall(r'href="(?:https://audiomack\.com)?/stewartjm/song/([a-zA-Z0-9_-]+)"', document))
        if not links or album.tracks and len(links) < album.tracks:
            raise ValueError(f"Incomplete Audiomack tracklist for {album.title}")
        return {title_key(slug) for slug in links}

    with ThreadPoolExecutor(max_workers=6) as pool:
        for keys in pool.map(track_keys, (release for release in releases if release.category == "albums")):
            album_tracks.update(keys)
    return releases, album_tracks


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


def extract(layout, pattern):
    match = re.search(pattern, layout, re.S)
    if not match:
        raise ValueError("Could not reuse the current site layout")
    return match[0]


def detail_page(release, layout):
    title = escape(release.title)
    artwork = escape(release.artwork or "../../assets/stewart-badge.webp", quote=True)
    url = escape(release.url, quote=True)
    embed = escape(release.embed, quote=True)
    header = extract(layout, r'<a class="skip-link".*?</header>')
    footer = extract(layout, r'<footer\b.*?</footer>')
    header = re.sub(r'href="(#(?:albums|featured|about)|\./)"', lambda match: f'href="../../{match[1] if match[1] != "./" else ""}"', header)
    header = header.replace(' aria-current="page"', "").replace('src="assets/', 'src="../../assets/')
    if release.category == "videos":
        main = f'''<main class="wrap video-page" id="main">
    <a class="back-link" href="../../#featured">Back to videos</a>
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
    <a class="back-link" href="../../#{release.category}">Back to {release.category}</a>
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
    return f'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="theme-color" content="#164632">
  <title>{title} | Stewart Productions</title>
  <link rel="icon" href="../../assets/stewart-badge.webp">
  <link rel="stylesheet" href="../../assets/catalog.css">
</head>
<body>
  {header}

  {main}

  {footer}
</body>
</html>
'''


def plan(homepage, releases, album_tracks):
    cards = existing_cards(homepage)
    changes = {}
    added = []
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
    if changes:
        changes["index.html"] = homepage
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
    warnings, found = [], {}
    with ThreadPoolExecutor() as pool:
        pending = {
            "Audiomack": pool.submit(audiomack_catalog),
            "Suno": pool.submit(lambda: suno_releases(fetch(SOURCE_LINKS[1][1]))),
            "YouTube": pool.submit(lambda: youtube_releases(fetch(YOUTUBE_FEED))),
        }
        for name, future in pending.items():
            try:
                found[name] = future.result()
            except Exception as error:
                warnings.append(f"{name}: {error}")
    audiomack, album_tracks = found.get("Audiomack", ([], set()))
    suno = found.get("Suno", [])
    youtube = found.get("YouTube", [])
    releases = [*audiomack, *suno, *youtube] if "Audiomack" in found and "Suno" in found else youtube
    changes, added = plan(html, releases, album_tracks)
    print(json.dumps({
        "changes": changes, "added": added, "warnings": warnings,
        "observed": dict(Counter(release.provider + " " + release.category for release in [*audiomack, *suno, *youtube])),
        "audiomack_album_tracks": len(album_tracks),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
