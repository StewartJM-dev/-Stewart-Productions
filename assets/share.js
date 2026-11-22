for (const control of document.querySelectorAll("[data-share-control]")) {
  const button = control.querySelector("[data-share-button]");
  const status = control.querySelector("[data-share-status]");
  const field = control.querySelector("[data-share-url]");
  control.hidden = false;

  button.addEventListener("click", async () => {
    const url = new URL(location.href);
    url.pathname = url.pathname.replace(/index\.html$/, "");
    url.hash = "";
    if (!url.pathname.endsWith("/browse/")) url.search = "";

    field.hidden = true;
    status.textContent = "";

    if (typeof navigator.share === "function") {
      try {
        await navigator.share({ title: document.title, url: url.href });
        return;
      } catch (error) {
        if (error.name === "AbortError") return;
      }
    }

    try {
      await navigator.clipboard.writeText(url.href);
      status.textContent = "Link copied.";
    } catch {
      field.value = url.href;
      field.hidden = false;
      field.focus();
      field.select();
      status.textContent = "Copy this link to share.";
    }
  });
}
