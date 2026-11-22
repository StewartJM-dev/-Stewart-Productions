const installPanel = document.querySelector("#install-app");
const installButton = installPanel.querySelector("summary");
let pendingPrompt;

if (matchMedia("(display-mode: standalone)").matches || navigator.standalone === true) {
  installPanel.hidden = true;
}

window.addEventListener("beforeinstallprompt", event => {
  event.preventDefault();
  pendingPrompt = event;
});

installButton.addEventListener("click", async event => {
  if (!pendingPrompt) return;

  event.preventDefault();
  const prompt = pendingPrompt;
  pendingPrompt = undefined;
  try {
    await prompt.prompt();
    const choice = await prompt.userChoice;
    installPanel.open = choice.outcome !== "accepted";
  } catch {
    installPanel.open = true;
  }
});

window.addEventListener("appinstalled", () => {
  pendingPrompt = undefined;
  installPanel.hidden = true;
});

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("./sw.js").catch(error => {
    console.warn("Stewart Productions app registration:", error);
  });
}
