const form = document.querySelector("#search-form");
const input = document.querySelector("#search-query");
const controls = document.querySelector("#genre-filters");
const results = document.querySelector("#browse-results");
const status = document.querySelector("#browse-status");

function fold(text) {
  return text.toLowerCase().normalize("NFKD").replace(/\p{M}/gu, "").replace(/[^\p{L}\p{N}]+/gu, " ").trim();
}

async function start() {
  const response = await fetch("../data/browse.json", { cache: "no-cache" });
  if (!response.ok) throw new Error("Catalog unavailable");
  const catalog = await response.json();
  const params = new URLSearchParams(location.search);
  input.value = params.get("q") || "";
  let selected = catalog.genres.includes(params.get("genre")) ? params.get("genre") : "All";
  const prepared = catalog.items.map(item => ({
    ...item,
    search: fold([item.title, item.album, item.kind, ...item.genres].filter(Boolean).join(" ")),
  }));
  const buttons = [];

  function addFilter(container, genre) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = genre;
    button.addEventListener("click", () => {
      selected = genre;
      update();
    });
    container.append(button);
    buttons.push(button);
  }

  const all = document.createElement("div");
  addFilter(all, "All");
  controls.append(all);
  const groups = catalog.genreGroups || [{ title: "Genres", genres: catalog.genres }];
  for (const group of groups) {
    const block = document.createElement("div");
    block.className = "genre-group";
    const heading = document.createElement("h3");
    heading.textContent = group.title;
    const options = document.createElement("div");
    options.className = "genre-options";
    options.setAttribute("role", "group");
    options.setAttribute("aria-label", group.title);
    for (const genre of group.genres) addFilter(options, genre);
    block.append(heading, options);
    controls.append(block);
  }

  function update(updateUrl = true) {
    const query = fold(input.value).split(" ").filter(Boolean);
    for (const button of buttons) button.setAttribute("aria-pressed", String(button.textContent === selected));
    const visible = prepared.filter(item => {
      if (item.kind === "Album track" && !query.length && selected === "All") return false;
      return (selected === "All" || item.genres.includes(selected)) &&
        query.every(word => item.search.includes(word));
    }).sort((a, b) => (b.likes ?? -1) - (a.likes ?? -1));

    results.replaceChildren();
    for (const item of visible) {
      const row = document.createElement("li");
      const link = document.createElement("a");
      link.href = "../" + item.href;
      link.textContent = item.title;
      const detail = document.createElement("p");
      const label = item.album ? "Song on " + item.album : item.kind;
      const count = item.likes;
      detail.textContent = Number.isSafeInteger(count) ?
        label + " · " + count.toLocaleString() + " " + item.metric + (count === 1 ? "" : "s") : label;
      row.append(link, detail);
      if (selected === "All" && item.genres.length) {
        const tags = document.createElement("p");
        tags.textContent = item.genres.join(" · ");
        row.append(tags);
      }
      results.append(row);
    }

    status.textContent = visible.length ? visible.length + (visible.length === 1 ? " result" : " results") :
      query.length ? "No matches. Try another title or genre." : "No releases are tagged " + selected + " yet.";

    if (updateUrl) {
      const url = new URL(location.href);
      if (input.value.trim()) url.searchParams.set("q", input.value.trim());
      else url.searchParams.delete("q");
      if (selected !== "All") url.searchParams.set("genre", selected);
      else url.searchParams.delete("genre");
      history.replaceState(null, "", url);
    }
  }

  input.addEventListener("input", () => update());
  form.addEventListener("submit", event => {
    event.preventDefault();
    update();
  });
  update(false);
}

start().catch(() => {
  status.textContent = "Search is temporarily unavailable. You can still open Albums, Singles, or Videos from the menu.";
});
