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
  const buttons = ["All", ...catalog.genres].map(genre => {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = genre;
    button.addEventListener("click", () => {
      selected = genre;
      update();
    });
    controls.append(button);
    return button;
  });

  function update(updateUrl = true) {
    const query = fold(input.value).split(" ").filter(Boolean);
    for (const button of buttons) button.setAttribute("aria-pressed", String(button.textContent === selected));
    const visible = prepared.filter(item => {
      if (item.kind === "Album track" && !query.length && selected === "All") return false;
      return (selected === "All" || item.genres.includes(selected)) &&
        query.every(word => item.search.includes(word));
    });

    results.replaceChildren();
    for (const item of visible) {
      const row = document.createElement("li");
      const link = document.createElement("a");
      link.href = "../" + item.href;
      link.textContent = item.title;
      const detail = document.createElement("p");
      detail.textContent = item.album ? "Song on " + item.album : item.kind;
      row.append(link, detail);
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
