const manifest = document.querySelector('link[rel="manifest"]');
const siteRoot = new URL(".", manifest.href);
const key = "stewart-productions:playlist:v1";
const providers = {
  "audiomack.com": /^\/embed\/(?:stewartjm\/)?(?:album|song)\//,
  "suno.com": /^\/embed\/[0-9a-f-]{36}(?:\/|$)/,
  "www.youtube.com": /^\/embed\/[a-zA-Z0-9_-]{11}(?:\/|$)/,
};

function element(tag, text) {
  const node = document.createElement(tag);
  if (text) node.textContent = text;
  return node;
}

function playerUrl(link) {
  try {
    const url = new URL(link);
    return url.protocol === "https:" && providers[url.hostname]?.test(url.pathname) ? url : null;
  } catch {
    return null;
  }
}

function readPlaylist() {
  try {
    const data = JSON.parse(localStorage.getItem(key));
    if (Array.isArray(data?.items)) {
      return {
        name: typeof data.name === "string" ? data.name.slice(0, 80) : "My Playlist",
        items: data.items.filter(item => typeof item?.id === "string" && typeof item.title === "string" && playerUrl(item.embed)),
      };
    }
  } catch { /* The page still works when browser storage is unavailable. */ }
  return { name: "My Playlist", items: [] };
}

function savePlaylist(data) {
  try {
    localStorage.setItem(key, JSON.stringify(data));
    return true;
  } catch {
    return false;
  }
}

function makeItem(title, kind, link, page) {
  const player = playerUrl(link);
  if (!player) return null;
  player.search = "";
  const titleKey = title.toLowerCase().normalize("NFKD").replace(/[^\p{L}\p{N}]+/gu, "");
  const id = kind === "Video" ? player.href : kind + ":" + titleKey;
  return { id, title, kind, embed: player.href, page };
}

function addControl(item) {
  const row = element("div");
  row.className = "playlist-actions";
  const button = element("button", "Add to playlist");
  button.type = "button";
  const link = element("a", "Open playlist");
  link.href = new URL("playlist/", siteRoot);
  const status = element("span");
  status.setAttribute("role", "status");
  button.addEventListener("click", () => {
    const data = readPlaylist();
    if (data.items.some(entry => entry.id === item.id)) {
      status.textContent = "Already in your playlist.";
      return;
    }
    data.items.push(item);
    status.textContent = savePlaylist(data) ? "Added to your playlist." : "Your browser couldn’t save the playlist.";
  });
  row.append(button, link, status);
  return row;
}

async function addAlbumTracks(card, route) {
  const response = await fetch(new URL("data/browse.json", siteRoot), { cache: "no-cache" });
  if (!response.ok) return;
  const catalog = await response.json();
  const list = element("ul");
  list.className = "playlist-album-tracks";
  for (const track of catalog.items) {
    if (track.kind !== "Album track" || track.href.split("#")[0] !== route) continue;
    const item = makeItem(track.title, "Song", track.embed, track.href);
    if (!item) continue;
    const row = element("li");
    row.append(element("span", track.title), addControl(item));
    list.append(row);
  }
  if (!list.children.length) return;
  const details = element("details");
  details.className = "playlist-track-picker";
  details.append(element("summary", "Add individual album tracks"), list);
  card.after(details);
}

const media = document.querySelector("main .media-card iframe");
if (media && !document.querySelector("#playlist-page")) {
  const route = location.pathname.slice(siteRoot.pathname.length).replace(/index\.html$/, "");
  const kind = route.startsWith("videos/") ? "Video" : route.startsWith("albums/") ? "Album" : "Song";
  const title = document.querySelector("main h1")?.textContent.trim();
  const item = title && makeItem(title, kind, media.src, route);
  if (item) {
    const card = media.closest(".media-card");
    card.append(addControl(item));
    if (kind === "Album") addAlbumTracks(card, route).catch(() => {});
  }
}

if (document.querySelector("#playlist-page")) {
  const form = document.querySelector("#playlist-name-form");
  const name = document.querySelector("#playlist-name");
  const status = document.querySelector("#playlist-status");
  const queue = document.querySelector("#playlist-queue");
  const playback = document.querySelector("#playlist-playback");
  const player = document.querySelector("#playlist-player");
  const nowPlaying = document.querySelector("#playlist-current");
  const previous = document.querySelector("#playlist-previous");
  const next = document.querySelector("#playlist-next");
  let activeId;

  function show(item) {
    const url = playerUrl(item.embed);
    if (!url) return;
    if (url.hostname !== "suno.com") url.searchParams.set("autoplay", "1");
    const iframe = element("iframe");
    iframe.src = url.href;
    iframe.title = item.title + " player";
    iframe.className = item.kind === "Video" ? "video" : item.kind === "Album" ? "album-player" : "playlist-song-player";
    iframe.allow = "autoplay; encrypted-media; picture-in-picture";
    iframe.referrerPolicy = "strict-origin-when-cross-origin";
    iframe.allowFullscreen = true;
    player.replaceChildren(iframe);
    nowPlaying.textContent = item.title;
    playback.hidden = false;
    activeId = item.id;
    render();
  }

  function control(label, fn, disabled = false) {
    const button = element("button", label);
    button.type = "button";
    button.disabled = disabled;
    button.addEventListener("click", fn);
    return button;
  }

  function render() {
    const data = readPlaylist();
    queue.replaceChildren();
    data.items.forEach((item, i) => {
      const row = element("li");
      const title = element("div");
      const link = element("a", item.title);
      const page = new URL(item.page, siteRoot);
      if (page.origin === siteRoot.origin && page.pathname.startsWith(siteRoot.pathname)) link.href = page;
      title.append(link, element("p", item.kind));
      const actions = element("div");
      actions.className = "playlist-actions";
      const move = step => {
        [data.items[i], data.items[i + step]] = [data.items[i + step], data.items[i]];
        if (savePlaylist(data)) render();
      };
      actions.append(
        control("Play", () => show(item)),
        control("Move up", () => move(-1), !i),
        control("Move down", () => move(1), i === data.items.length - 1),
        control("Remove", () => {
          data.items.splice(i, 1);
          if (!savePlaylist(data)) return;
          if (item.id === activeId) {
            player.replaceChildren();
            playback.hidden = true;
            activeId = undefined;
          }
          render();
        }),
      );
      row.append(title, actions);
      queue.append(row);
    });
    const active = data.items.findIndex(item => item.id === activeId);
    previous.disabled = active < 1;
    next.disabled = active < 0 || active === data.items.length - 1;
    status.textContent = data.items.length ? data.items.length + (data.items.length === 1 ? " item" : " items") :
      "Your playlist is empty. Open an album, single, or video and choose Add to playlist.";
  }

  name.value = readPlaylist().name;
  form.addEventListener("submit", event => {
    event.preventDefault();
    const data = readPlaylist();
    data.name = name.value.trim() || "My Playlist";
    name.value = data.name;
    status.textContent = savePlaylist(data) ? "Playlist name saved." : "Your browser couldn’t save the name.";
  });
  for (const [button, step] of [[previous, -1], [next, 1]]) {
    button.addEventListener("click", () => {
      const { items } = readPlaylist();
      const i = items.findIndex(item => item.id === activeId) + step;
      if (items[i]) show(items[i]);
    });
  }
  addEventListener("storage", event => { if (event.key === key) render(); });
  render();
}
