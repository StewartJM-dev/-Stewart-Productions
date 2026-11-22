for (const catalog of document.querySelectorAll(".catalog")) {
  const rail = catalog.querySelector(".rail");
  const controls = catalog.querySelector(".rail-controls");
  const [previous, next] = controls.querySelectorAll("button");

  function updateControls() {
    const limit = rail.scrollWidth - rail.clientWidth;
    controls.hidden = limit < 2;
    previous.disabled = rail.scrollLeft < 2;
    next.disabled = rail.scrollLeft > limit - 2;
  }

  for (const button of [previous, next]) {
    button.addEventListener("click", () => {
      const [first, second] = rail.children;
      if (!second) return;

      rail.scrollBy({
        left: (second.offsetLeft - first.offsetLeft) * Number(button.dataset.step),
        behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth",
      });
    });
  }

  rail.addEventListener("scroll", updateControls, { passive: true });
  new ResizeObserver(updateControls).observe(rail);
  updateControls();
}
