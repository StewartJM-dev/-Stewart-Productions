"""Order release cards by the public reaction count on their own player."""

from html import unescape
import re

from browse_catalog import title_key

CARD = re.compile(r'<li\b[^>]*>.*?</li>', re.S)
COUNT = re.compile(r'\s*<p class="release-popularity">[^<]*</p>')


def public_count(value):
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    if isinstance(value, str) and re.fullmatch(r"[0-9]+", value):
        return int(value)
    return None


def youtube_count(document):
    match = re.search(r'"likeCount"\s*:\s*"?([0-9]+)"?(?=[,}\s])', document)
    return public_count(match[1]) if match else None


def card_route(card):
    return re.search(r'href="((?:albums|singles|videos)/[a-zA-Z0-9_-]+/)"', card)[1]


def video_id(card):
    match = re.search(r'https://i\.ytimg\.com/vi/([a-zA-Z0-9_-]{11})/', card)
    return match[1] if match else None


def reaction_text(score):
    if not score:
        return ""
    count, metric = score
    return f'<p class="release-popularity">{count:,} {metric}{"s" if count != 1 else ""}</p>'


def score_value(scores, route):
    value = scores.get(route)
    return value[0] if value else -1


def rank_cards(homepage, rows, releases, video_counts, previous):
    prior = {item["href"]: (item["likes"], item.get("metric", "like")) for item in previous.get("items", [])
             if public_count(item.get("likes")) is not None and item.get("kind") != "Album track"}
    by_id = {item.identity: item for item in releases}
    by_title = {}
    for release in releases:
        by_title.setdefault((release.category, title_key(release.title)), []).append(release)

    scores, changed = {}, set()
    for category, (row, _, _, _) in sorted(rows.items(), key=lambda pair: pair[1][0].start(), reverse=True):
        ordered = []
        for match in CARD.finditer(row[1]):
            card = match[0]
            route = card_route(card)
            heading = re.search(r"<h3>(.*?)</h3>", card, re.S)
            key = title_key(unescape(heading[1]))
            tag = re.search(r'data-release-id="([^"]+)"', card)
            release = by_id.get(tag[1]) if tag else None
            if release is None and not tag:
                candidates = by_title.get((category, key), ())
                if len(candidates) == 1:
                    release = candidates[0]

            score = prior.get(route)
            if category == "videos":
                count = video_counts.get(video_id(card))
                if count is not None:
                    score = (count, "like")
            elif release is not None and release.likes is not None:
                score = (release.likes, "favorite" if release.provider == "Audiomack" else "like")

            if score is not None:
                scores[route] = score
            updated = COUNT.sub("", card)
            if score is not None:
                ending = updated.rindex("            </div>")
                updated = updated[:ending] + "              " + reaction_text(score) + "\n" + updated[ending:]
            ordered.append((route, updated))

        ordered.sort(key=lambda item: score_value(scores, item[0]), reverse=True)
        replacement = "\n" + "".join("        " + card + "\n" for _, card in ordered) + "      "
        if replacement != row[1]:
            changed.add(category)
            homepage = homepage[:row.start(1)] + replacement + homepage[row.end(1):]
    return homepage, scores, changed
