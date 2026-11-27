const VIEWER_SECTIONS = [
  { id: "section-viewer", dock: "viewer" },
  { id: "section-processing", dock: "compare" },
  { id: "section-roi", dock: "roi" },
  { id: "section-summary", dock: "viewer-summary" },
  { id: "section-memo", dock: "memo" },
];

const DOCK_TO_SECTION = {
  viewer: "section-viewer",
  compare: "section-processing",
  roi: "section-roi",
  memo: "section-memo",
};

function findScrollContainers() {
  const candidates = [
    document.querySelector('[data-testid="stMain"]'),
    document.querySelector('[data-testid="stAppViewContainer"]'),
    document.querySelector("section.main"),
    document.scrollingElement,
    document.documentElement,
  ].filter(Boolean);
  return [...new Set(candidates)];
}

function scrollToSection(sectionId) {
  if (sectionId === "section-viewer") {
    for (const container of findScrollContainers()) {
      if (typeof container.scrollTo === "function") {
        container.scrollTo({ top: 0, behavior: "smooth" });
      }
    }
    window.scrollTo({ top: 0, behavior: "smooth" });
    return;
  }
  const target = document.getElementById(sectionId);
  if (target) {
    target.scrollIntoView({ behavior: "smooth", block: "start" });
  }
}

function setActiveIndicators(dockRoot, activeSection, mode) {
  const navLinks = document.querySelectorAll(".appbar-nav [data-section]");
  navLinks.forEach((link) => {
    link.classList.toggle("is-active", link.dataset.section === activeSection);
  });

  let activeDockKey = "cases";
  if (mode === "viewer") {
    if (activeSection === "section-processing") {
      activeDockKey = "compare";
    } else if (activeSection === "section-roi") {
      activeDockKey = "roi";
    } else if (activeSection === "section-memo") {
      activeDockKey = "memo";
    } else {
      activeDockKey = "viewer";
    }
  }

  const buttons = dockRoot.querySelectorAll(".dock-btn");
  buttons.forEach((btn) => {
    const isActive = btn.dataset.dockAction === activeDockKey;
    btn.classList.toggle("is-active", isActive);
    btn.setAttribute("aria-current", isActive ? "true" : "false");
  });
}

function detectActiveSection() {
  const threshold = 132;
  let current = "section-viewer";
  for (const { id } of VIEWER_SECTIONS) {
    const el = document.getElementById(id);
    if (!el) continue;
    const rect = el.getBoundingClientRect();
    if (rect.top <= threshold) {
      current = id;
    }
  }
  return current;
}

export default function renderFloatingDock({ parentElement, data }) {
  const dock = parentElement.querySelector(".floating-dock");
  if (!dock) {
    return;
  }

  const mode = data?.mode || "list";
  const labels = data?.labels || {};
  const hasSelected = Boolean(data?.hasSelected);
  const controller = new AbortController();
  const signal = controller.signal;

  if (labels.dockAria) {
    dock.setAttribute("aria-label", labels.dockAria);
  }

  const btnCases = dock.querySelector('[data-dock-action="cases"]');
  const btnSecond = dock.querySelector('[data-dock-action="second"]');
  const btnViewer = dock.querySelector('[data-dock-action="viewer"]');
  const btnRoi = dock.querySelector('[data-dock-action="roi"]');
  const btnMemo = dock.querySelector('[data-dock-action="memo"]');

  if (btnCases) {
    btnCases.dataset.tooltip = labels.cases || "Cases";
    btnCases.setAttribute("aria-label", labels.cases || "Cases");
  }

  if (btnSecond) {
    if (mode === "viewer") {
      btnSecond.dataset.dockAction = "compare";
      btnSecond.dataset.tooltip = labels.compare || "Compare";
      btnSecond.setAttribute("aria-label", labels.compare || "Compare");
      btnSecond.querySelector(".icon-search")?.setAttribute("hidden", "");
      btnSecond.querySelector(".icon-sliders")?.removeAttribute("hidden");
    } else {
      btnSecond.dataset.dockAction = "search";
      btnSecond.dataset.tooltip = labels.search || "Search";
      btnSecond.setAttribute("aria-label", labels.search || "Search");
      btnSecond.querySelector(".icon-sliders")?.setAttribute("hidden", "");
      btnSecond.querySelector(".icon-search")?.removeAttribute("hidden");
    }
  }

  if (btnViewer) {
    const label = mode === "viewer" ? (labels.viewer || "Viewer") : (labels.openViewer || "Open Viewer");
    btnViewer.dataset.tooltip = label;
    btnViewer.setAttribute("aria-label", label);
    btnViewer.disabled = mode === "list" && !hasSelected;
  }

  if (btnRoi) {
    const label = mode === "viewer" ? (labels.roi || "ROI") : (labels.viewerOnly || "Viewer only");
    btnRoi.dataset.tooltip = label;
    btnRoi.setAttribute("aria-label", label);
    btnRoi.disabled = mode !== "viewer";
  }

  if (btnMemo) {
    const label = mode === "viewer" ? (labels.memo || "Memo") : (labels.viewerOnly || "Viewer only");
    btnMemo.dataset.tooltip = label;
    btnMemo.setAttribute("aria-label", label);
    btnMemo.disabled = mode !== "viewer";
  }

  // Handle top segmented pill clicks (smooth scroll or switch view)
  const onTopNavClick = (event) => {
    const trigger = event.target.closest(".appbar-nav [data-section], .appbar-nav [data-nav-action]");
    if (!trigger) return;
    event.preventDefault();
    if (trigger.dataset.navAction === "open-viewer") {
      const openBtn = document.querySelector(".st-key-open_selected_viewer button");
      if (openBtn) openBtn.click();
      return;
    }
    if (trigger.dataset.navAction === "cases-top") {
      scrollToSection("section-viewer");
      return;
    }
    const sectionId = trigger.dataset.section;
    if (sectionId) {
      setActiveIndicators(dock, sectionId, mode);
      scrollToSection(sectionId);
      try {
        history.replaceState(null, "", "#" + sectionId);
      } catch {
        // Ignore history restrictions in embedded frames.
      }
    }
  };
  document.addEventListener("click", onTopNavClick, { signal });

  // Handle bottom black floating dock clicks
  dock.addEventListener(
    "click",
    (event) => {
      const btn = event.target.closest(".dock-btn");
      if (!btn || btn.disabled) return;
      const action = btn.dataset.dockAction;

      if (action === "cases") {
        if (mode === "viewer") {
          try {
            history.replaceState(null, "", window.location.pathname + window.location.search);
          } catch {
            // Ignore history restrictions.
          }
          const backBtn = document.querySelector(".st-key-back_to_list button");
          if (backBtn) backBtn.click();
        } else {
          scrollToSection("section-viewer");
        }
        return;
      }

      if (action === "search") {
        const searchInput = document.querySelector('[data-testid="stTextInput"] input');
        if (searchInput) {
          searchInput.scrollIntoView({ behavior: "smooth", block: "center" });
          searchInput.focus();
        }
        return;
      }

      if (action === "viewer" && mode === "list") {
        const openBtn = document.querySelector(".st-key-open_selected_viewer button");
        if (openBtn) openBtn.click();
        return;
      }

      const sectionId = DOCK_TO_SECTION[action];
      if (sectionId) {
        setActiveIndicators(dock, sectionId, mode);
        scrollToSection(sectionId);
        try {
          history.replaceState(null, "", "#" + sectionId);
        } catch {
          // Ignore history restrictions.
        }
      }
    },
    { signal }
  );

  // Scroll-spy for viewer sections
  let rafId = 0;
  const syncFromScroll = () => {
    rafId = 0;
    if (mode !== "viewer") {
      setActiveIndicators(dock, "cases", "list");
      return;
    }
    setActiveIndicators(dock, detectActiveSection(), "viewer");
  };

  const scheduleSync = () => {
    if (!rafId) {
      rafId = requestAnimationFrame(syncFromScroll);
    }
  };

  if (mode === "viewer") {
    window.addEventListener("scroll", scheduleSync, { passive: true, signal });
    for (const container of findScrollContainers()) {
      container.addEventListener("scroll", scheduleSync, { passive: true, signal });
    }
  }

  // Respect initial hash anchor (e.g. #section-roi) when opening viewer
  if (mode === "viewer") {
    const hash = window.location.hash.replace(/^#/, "");
    const knownHash = VIEWER_SECTIONS.some((s) => s.id === hash);
    setActiveIndicators(dock, knownHash ? hash : detectActiveSection(), "viewer");
  } else {
    setActiveIndicators(dock, "cases", "list");
  }

  return () => {
    controller.abort();
    if (rafId) {
      cancelAnimationFrame(rafId);
    }
  };
}
