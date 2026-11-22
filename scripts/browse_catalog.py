"""Make the searchable catalog from the live release cards and album tracklists."""

from html import unescape
import json
import re
import unicodedata

BROWSE_FILE = "data/browse.json"
GENRES = ["Funny", "Patriotic", "Thanksgiving", "Christmas", "Faith", "Family & Life", "Cars & Garage"]
CURATED = {
    "holdtheline": ("Patriotic",),
    "steelandnailprints": ("Patriotic", "Faith"),
    "garagegospel": ("Faith", "Cars & Garage"),
    "altarsinthewilderness": ("Faith",),
    "battlescars": ("Family & Life",),
    "blackscirocco": ("Cars & Garage",),
    "memoryred": ("Cars & Garage",),
    "theotherguy": ("Faith",),
    "beforewehangthelights": ("Thanksgiving", "Faith"),
    "areyoustillthankful": ("Thanksgiving",),
}
PATTERNS = {
    "Funny": r"\b(comedy|comedic|humou?r(?:ous)?|funny|parody|novelty song)\b",
    "Patriotic": r"\b(patriotic|veterans day|independence day|pearl harbor|national anthem|naval history)\b",
    "Thanksgiving": r"\b(thanksgiving|still thankful)\b",
    "Christmas": r"\b(christmas|nativity|no[eë]l|christmas eve)\b",
    "Faith": r"\b(christian|gospel|worship|hymn|scripture|bible)\b",
    "Family & Life": r"\b(family life|fatherhood|motherhood|family story)\b",
    "Cars & Garage": r"\b(garage|scirocco|mechanic|check engine|go.kart|car song)\b",
}
RAIL_TYPES = {"albums-track": "Album", "singles-track": "Single", "featured-track": "Video"}


def title_key(value):
    value = unicodedata.normalize("NFKD", value.casefold().replace("&", " and "))
    return "".join(c for c in value if c.isalnum())


def classify(title, hints="", inherited=()):
    genres = set(inherited) | set(CURATED.get(title_key(title), ()))
    text = (title + " " + hints).replace("-", " ").casefold()
    genres.update(genre for genre, pattern in PATTERNS.items() if re.search(pattern, text))
    return [genre for genre in GENRES if genre in genres]


def release_cards(homepage):
    items = []
    for rail, kind in RAIL_TYPES.items():
        section = re.search(rf'<ul\b[^>]*\bid="{rail}"[^>]*>(.*?)</ul>', homepage, re.S)
        if not section:
            raise ValueError(f"Missing {rail}")
        for match in re.finditer(r'<li\b[^>]*>(.*?)</li>', section[1], re.S):
            route = re.search(r'href="((?:albums|singles|videos)/[a-zA-Z0-9_-]+/)"', match[1])
            title = re.search(r'<h3>([^<]+)</h3>', match[1])
            if not route or not title:
                raise ValueError(f"Unrecognized release in {rail}")
            items.append({"title": unescape(title[1]), "kind": kind, "href": route[1]})
    return items


def build_index(homepage, releases, album_songs, previous, scores):
    previous = previous or {}
    legacy = {(item["kind"], item["href"], title_key(item["title"])): item
              for item in previous.get("items", [])}
    hints = {}
    for release in releases:
        key = title_key(release.title)
        hints[key] = " ".join(filter(None, (hints.get(key), release.tags)))
    items = release_cards(homepage)
    for item in items:
        key = title_key(item["title"])
        old = legacy.get((item["kind"], item["href"], key), {})
        item["genres"] = classify(item["title"], hints.get(key, ""), old.get("genres", ()))
        if item["href"] in scores:
            item["likes"], item["metric"] = scores[item["href"]]

    for item in list(items):
        if item["kind"] != "Album":
            continue
        album_title = item["title"]
        href = item["href"] + "#listen"
        key = title_key(album_title)
        if album_songs is None or key not in album_songs:
            items.extend(track for track in previous.get("items", []) if track.get("kind") == "Album track" and track.get("href") == href)
            continue
        for title, count, embed in album_songs.get(key, ()):
            track = {"title": title, "kind": "Album track", "album": album_title, "href": href,
                     "genres": classify(title, hints.get(title_key(title), ""), item["genres"]), "embed": embed}
            previous_track = legacy.get(("Album track", href, title_key(title)), {})
            if count is None:
                count = previous_track.get("likes")
            if count is not None:
                track["likes"], track["metric"] = count, "favorite"
            items.append(track)

    return {"genres": GENRES, "items": items}


def serialize(index):
    return json.dumps(index, ensure_ascii=False, indent=2) + "\n"
