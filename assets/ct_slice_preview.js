const FULL_SLICE_PREFIX = "st-key-ct_full_slice_";
const DEFAULT_VIEW = { zoom: 1, x: 0, y: 0 };
const MIN_ZOOM = 0.5;
const MAX_ZOOM = 4;
const ZOOM_STEP = 0.25;
const PAN_KEYS = {
  ArrowLeft: [-0.05, 0],
  ArrowRight: [0.05, 0],
  ArrowUp: [0, -0.05],
  ArrowDown: [0, 0.05],
};

function loadView(storageKey) {
  try {
    const saved = JSON.parse(sessionStorage.getItem(storageKey));
    if ([saved?.zoom, saved?.x, saved?.y].every(Number.isFinite)) {
      return saved;
    }
  } catch {
    // The viewer can start with its default view when storage is unavailable.
  }
  return { ...DEFAULT_VIEW };
}

function installViewControls(root, caseId) {
  const viewport = root.querySelector(".ct-slice-preview");
  const content = viewport.querySelector(".ct-view-content");
  const zoomOut = root.querySelector('[data-view-action="zoom-out"]');
  const zoomIn = root.querySelector('[data-view-action="zoom-in"]');
  const reset = root.querySelector('[data-view-action="reset"]');
  const readout = root.querySelector(".ct-view-controls output");
  const listeners = new AbortController();
  const options = { signal: listeners.signal };
  const storageKey = "project-a:ct-view:" + caseId;
  let view = loadView(storageKey);
  let drag = null;

  function renderView() {
    const panLimit = Math.max(0, (view.zoom - 1) / 2);
    view.x = Math.max(-panLimit, Math.min(panLimit, view.x));
    view.y = Math.max(-panLimit, Math.min(panLimit, view.y));
    content.style.transform = "translate(" + view.x * 100 + "%, " + view.y * 100
      + "%) scale(" + view.zoom + ")";
    const percent = Math.round(view.zoom * 100) + "%";
    if (readout.value !== percent) {
      readout.value = percent;
    }
    viewport.classList.toggle("is-zoomed", view.zoom > 1);
    zoomOut.disabled = view.zoom <= MIN_ZOOM;
    zoomIn.disabled = view.zoom >= MAX_ZOOM;
    reset.disabled = view.zoom === DEFAULT_VIEW.zoom;
  }

  function saveView() {
    try {
      sessionStorage.setItem(storageKey, JSON.stringify(view));
    } catch {
      // The current view still works when browser storage is restricted.
    }
  }

  function zoomBy(amount) {
    const zoom = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, view.zoom + amount));
    const ratio = zoom / view.zoom;
    view.x *= ratio;
    view.y *= ratio;
    view.zoom = zoom;
    renderView();
    saveView();
  }

  zoomOut.addEventListener("click", () => zoomBy(-ZOOM_STEP), options);
  zoomIn.addEventListener("click", () => zoomBy(ZOOM_STEP), options);
  reset.addEventListener("click", () => {
    view = { ...DEFAULT_VIEW };
    renderView();
    saveView();
  }, options);

  viewport.addEventListener("pointerdown", (event) => {
    if (view.zoom <= 1 || !event.isPrimary || event.button !== 0) {
      return;
    }
    viewport.setPointerCapture(event.pointerId);
    drag = {
      id: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      x: view.x,
      y: view.y,
    };
    viewport.classList.add("is-panning");
  }, options);
  viewport.addEventListener("pointermove", (event) => {
    if (drag?.id !== event.pointerId) {
      return;
    }
    view.x = drag.x + (event.clientX - drag.startX) / viewport.clientWidth;
    view.y = drag.y + (event.clientY - drag.startY) / viewport.clientHeight;
    renderView();
  }, options);

  function endDrag(event) {
    if (drag?.id === event.pointerId) {
      drag = null;
      viewport.classList.remove("is-panning");
      saveView();
    }
  }

  viewport.addEventListener("pointerup", endDrag, options);
  viewport.addEventListener("pointercancel", endDrag, options);
  viewport.addEventListener("lostpointercapture", endDrag, options);
  viewport.addEventListener("keydown", (event) => {
    const step = PAN_KEYS[event.key];
    if (!step || view.zoom <= 1) {
      return;
    }
    event.preventDefault();
    view.x += step[0];
    view.y += step[1];
    renderView();
    saveView();
  }, options);

  view.zoom = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, view.zoom));
  renderView();
  return () => {
    listeners.abort();
    if (drag) {
      if (viewport.hasPointerCapture(drag.id)) {
        viewport.releasePointerCapture(drag.id);
      }
      viewport.classList.remove("is-panning");
      saveView();
    }
  };
}

export default function renderViewport({ parentElement, data }) {
  const image = parentElement.querySelector("img");
  const canvas = parentElement.querySelector("canvas");
  const stage = parentElement.closest(".st-key-stage");
  const context = canvas.getContext("2d");
  if (!stage) {
    return;
  }
  const stopControls = installViewControls(parentElement, data.caseId);

  canvas.width = canvas.height = data.tileSize;
  let currentSlice = 0;
  let drawnSheetUrl = "";
  let drawnSlice = 0;
  let pendingFrame = 0;

  function paint() {
    pendingFrame = 0;
    // The image URL and committed slice number arrive in the same element.
    const source = stage.querySelector('[class*="' + FULL_SLICE_PREFIX + '"]');
    const fullImage = source?.querySelector("img");
    if (fullImage?.src) {
      const sourceKey = [...source.classList].find((name) => name.startsWith(FULL_SLICE_PREFIX));
      currentSlice = Number(sourceKey.slice(FULL_SLICE_PREFIX.length));
      if (image.src !== fullImage.src) {
        image.src = fullImage.src;
      }
    }

    const thumb = stage.querySelector('.st-key-slice_row [role="slider"]');
    const sliderValue = Number(thumb?.getAttribute("aria-valuenow"));
    const requested = Number.isInteger(sliderValue) && sliderValue >= 1 && sliderValue <= data.sliceCount
      ? sliderValue
      : currentSlice;
    const sheet = stage.querySelector(".st-key-ct_preview_sheet img");
    const imageReady = image.complete && image.naturalWidth > 0;
    const preview = context && requested > 0 && sheet?.complete && sheet.naturalWidth > 0
      && (requested !== currentSlice || !imageReady);

    if (preview && (requested !== drawnSlice || sheet.src !== drawnSheetUrl)) {
      const columns = sheet.naturalWidth / data.tileSize;
      const index = requested - 1;
      const x = (index % columns) * data.tileSize;
      const y = Math.floor(index / columns) * data.tileSize;
      context.drawImage(
        sheet, x, y, data.tileSize, data.tileSize, 0, 0, canvas.width, canvas.height
      );
      drawnSlice = requested;
      drawnSheetUrl = sheet.src;
    }
    canvas.hidden = !preview;

    const shown = preview ? requested : currentSlice;
    const label = stage.querySelector(".stage-chips .is-strong");
    const text = `단면 ${shown} / ${data.sliceCount}`;
    if (shown > 0 && label && label.textContent !== text) {
      label.textContent = text;
    }
  }

  function schedulePaint() {
    if (!pendingFrame) {
      pendingFrame = requestAnimationFrame(paint);
    }
  }

  // The native slider updates its accessible thumb value before committing to Python.
  const observer = new MutationObserver(schedulePaint);
  observer.observe(stage, {
    subtree: true,
    childList: true,
    attributes: true,
    attributeFilter: ["aria-valuenow", "src"],
  });
  stage.addEventListener("load", schedulePaint, true);
  schedulePaint();

  return () => {
    stopControls();
    observer.disconnect();
    stage.removeEventListener("load", schedulePaint, true);
    cancelAnimationFrame(pendingFrame);
  };
}
