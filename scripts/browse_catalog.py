"""Make the searchable catalog from the live release cards and album tracklists."""

from html import unescape
import json
import re
import unicodedata

BROWSE_FILE = "data/browse.json"
GENRE_GROUPS = [
    {"title": "Audience & themes", "genres": ["Kids Songs", "Funny", "Faith", "Family & Life", "Story Songs", "Cars & Garage", "Patriotic", "History"]},
    {"title": "Holidays", "genres": ["Thanksgiving", "Christmas"]},
    {"title": "Music styles", "genres": ["Rock", "Christian Rock", "Rock & Roll", "Country Rock", "Ballads", "Cinematic", "Hymns & Worship", "A Cappella", "Celtic", "Sing-Alongs", "Spoken Cadence"]},
]
GENRES = [genre for group in GENRE_GROUPS for genre in group["genres"]]
THEMES = set(GENRE_GROUPS[0]["genres"] + GENRE_GROUPS[1]["genres"])
CURATED = {
    "holdtheline": ("Patriotic", "History"),
    "steelandnailprints": ("Patriotic", "Faith", "Story Songs", "History"),
    "garagegospel": ("Faith", "Cars & Garage"),
    "altarsinthewilderness": ("Faith",),
    "battlescars": ("Family & Life",),
    "blackscirocco": ("Cars & Garage",),
    "memoryred": ("Cars & Garage",),
    "theotherguy": ("Faith",),
    "beforewehangthelights": ("Thanksgiving", "Faith"),
    "areyoustillthankful": ("Thanksgiving",),
    "godmadethedinosaurs": ("Kids Songs", "Faith"),
    "nomorestinkyelephants": ("Kids Songs", "Funny"),
    "thestewartzoo": ("Kids Songs", "Funny"),
    "allaboardwithdaniel": ("Kids Songs", "Story Songs"),
    "stewartcadets": ("Kids Songs", "Funny", "Family & Life"),
}
PATTERNS = {
    "Funny": r"\b(comedy|comedic|humou?r(?:ous)?|funny|parody|novelty song|wacky)\b",
    "Patriotic": r"\b(patriotic|veterans day|independence day|pearl harbor|national anthem|naval history)\b",
    "Thanksgiving": r"\b(thanksgiving|still thankful)\b",
    "Christmas": r"\b(christmas|nativity|no[eë]l|christmas eve)\b",
    "Faith": r"\b(christian|gospel|worship|hymn|scripture|bible)\b",
    "Family & Life": r"\b(family life|fatherhood|motherhood|family story)\b",
    "Story Songs": r"\b(storytelling|story song|story ballad)\b",
    "Cars & Garage": r"\b(garage|scirocco|mechanic|check engine|go.kart|car song)\b",
    "History": r"\b(american history|naval history|historical ballad)\b",
}
STYLE_HINTS = {
    "Kids Songs": r"\b(kids?|children)(?:['’]s?|s)?\s+(music|song|rock|country|singalong|sing along|vocals)\b",
    "Rock": r"\brock\b",
    "Christian Rock": r"\bchristian rock\b",
    "Rock & Roll": r"\brock (?:and|&|['’]?n['’]?) roll\b",
    "Country Rock": r"\bcountry rock\b",
    "Ballads": r"\bballads?\b",
    "Cinematic": r"\bcinematic\b",
    "Hymns & Worship": r"\b(hymns?|worship)\b",
    "A Cappella": r"\ba cap+pella\b",
    "Celtic": r"\bceltic\b",
    "Sing-Alongs": r"\b(singalong|sing along|call and response)\b",
    "Spoken Cadence": r"\b(marching cadence|marching drill)\b",
}
RAIL_TYPES = {"albums-track": "Album", "singles-track": "Single", "featured-track": "Video"}


def title_key(value):
    value = unicodedata.normalize("NFKD", value.casefold().replace("&", " and "))
    return "".join(c for c in value if c.isalnum())


def classify(title, hints="", inherited=()):
    genres = set(inherited) | set(CURATED.get(title_key(title), ()))
    text = (title + " " + hints).replace("-", " ").casefold()
    genres.update(genre for genre, pattern in PATTERNS.items() if re.search(pattern, text))
    style = hints.replace("-", " ").casefold()
    genres.update(genre for genre, pattern in STYLE_HINTS.items() if re.search(pattern, style))
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
        inherited = [genre for genre in item["genres"] if genre in THEMES]
        for title, count, embed, track_hint in album_songs.get(key, ()):
            tags = " ".join(filter(None, (hints.get(title_key(title)), track_hint)))
            track = {"title": title, "kind": "Album track", "album": album_title, "href": href,
                     "genres": classify(title, tags, inherited), "embed": embed}
            previous_track = legacy.get(("Album track", href, title_key(title)), {})
            if count is None:
                count = previous_track.get("likes")
            if count is not None:
                track["likes"], track["metric"] = count, "favorite"
            items.append(track)

    return {"genres": GENRES, "genreGroups": GENRE_GROUPS, "items": items}


def serialize(index):
    return json.dumps(index, ensure_ascii=False, indent=2) + "\n"
