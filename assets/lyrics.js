const lyricsPanel = document.querySelector("#lyrics");
const lyricsList = document.querySelector("#lyrics-list");

async function loadLyrics() {
  const root = new URL("../../", location.href);
  const currentPage = location.pathname.slice(root.pathname.length).replace(/index\.html$/, "");
  const response = await fetch(new URL("data/lyrics.json", root), { cache: "no-cache" });
  if (!response.ok) return;
  const index = await response.json();
  const entries = index.pages[currentPage];
  if (!entries?.length) return;

  for (const entry of entries) {
    const details = document.createElement("details");
    const summary = document.createElement("summary");
    summary.textContent = currentPage.startsWith("singles/") ? "View lyrics" : entry.title;

    const text = document.createElement("div");
    text.className = "lyric-text";
    text.textContent = entry.text;

    details.append(summary, text);
    lyricsList.append(details);
  }
  lyricsPanel.hidden = false;
  if (location.hash === "#lyrics") lyricsPanel.scrollIntoView();
}

loadLyrics().catch(() => {});
