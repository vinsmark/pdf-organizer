import base64
import os
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components
from pypdf import PdfReader, PdfWriter
from io import BytesIO
import pypdfium2 as pdfium
from PIL import Image

st.set_page_config(
    page_title="Organize PDF",
    page_icon="📄",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ---------------------------------------------------------------------------
# Self-bootstrapping components.
#
# Streamlit components with a real return value (not a CSS/DOM hack) need a
# tiny static index.html file living in its own folder. To keep this whole
# app a single file to manage, we just write those helper files out to a
# hidden folder next to this script the first time it runs (idempotent —
# safe to run every time, it just rewrites the same small files).
# ---------------------------------------------------------------------------
_BASE_DIR = Path(__file__).resolve().parent
_COMPONENTS_DIR = _BASE_DIR / ".organize_pdf_components"
_DRAG_GRID_DIR = _COMPONENTS_DIR / "drag_grid"
_STATE_BRIDGE_DIR = _COMPONENTS_DIR / "state_bridge"

_DRAG_GRID_HTML = r"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<style>
  html, body {
    margin: 0; padding: 0;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    background: transparent;
  }
  #grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(110px, 1fr));
    gap: 14px;
    padding: 4px;
  }
  /* Force exactly two cards per row on small / mobile screens */
  @media (max-width: 520px) {
    #grid {
      grid-template-columns: repeat(2, 1fr);
      gap: 10px;
    }
  }
  .card {
    border: 2px solid #f43f5e;
    border-radius: 12px;
    background: #fff;
    padding: 8px;
    box-sizing: border-box;
    text-align: center;
    cursor: grab;
    box-shadow: 0 1px 4px rgba(244,63,94,0.1);
    transition: box-shadow 0.15s ease, background-color 0.15s ease, opacity 0.15s ease;
    user-select: none;
  }
  .card:hover {
    box-shadow: 0 6px 18px rgba(244,63,94,0.2);
    background-color: #fff1f2;
  }
  .card.dragging {
    opacity: 0.4;
  }
  .thumb-wrap {
    width: 100%;
    aspect-ratio: 3 / 4;
    display: flex;
    align-items: center;
    justify-content: center;
    overflow: hidden;
    cursor: zoom-in;
  }
  .thumb-wrap img {
    max-width: 100%;
    max-height: 100%;
    pointer-events: none;
  }
  .num {
    margin-top: 6px;
    font-family: 'Courier New', monospace;
    font-size: 0.8rem;
    font-weight: 600;
    color: #666;
  }
  #apply-btn {
    margin-top: 14px;
    background-color: #111;
    color: #fff;
    border: none;
    border-radius: 10px;
    font-weight: 500;
    padding: 10px 18px;
    cursor: pointer;
    font-size: 0.9rem;
  }
  #apply-btn:hover {
    background-color: #333;
  }
  #status {
    display: inline-block;
    margin-left: 10px;
    font-size: 0.8rem;
  }
  #lightbox {
    display: none;
    position: fixed;
    inset: 0;
    background: rgba(17,17,17,0.85);
    z-index: 999;
    align-items: center;
    justify-content: center;
    flex-direction: column;
    padding: 24px;
    box-sizing: border-box;
  }
  #lightbox.open { display: flex; }
  #lightbox img {
    max-width: 100%;
    max-height: 80vh;
    border-radius: 8px;
    box-shadow: 0 10px 40px rgba(0,0,0,0.5);
  }
  #lightbox-caption {
    color: #fff;
    font-family: 'Courier New', monospace;
    font-size: 0.85rem;
    margin-top: 12px;
  }
  #lightbox-close {
    position: absolute;
    top: 16px;
    right: 20px;
    color: #fff;
    font-size: 1.6rem;
    background: none;
    border: none;
    cursor: pointer;
    line-height: 1;
  }
</style>
</head>
<body>
  <div id="grid"></div>
  <button id="apply-btn">Apply order &darr;</button>
  <span id="status"></span>

  <div id="lightbox">
    <button id="lightbox-close" aria-label="Close">&times;</button>
    <img id="lightbox-img" src="" />
    <div id="lightbox-caption"></div>
  </div>

  <script>
    function sendMessageToStreamlitClient(type, data) {
      var outData = Object.assign({ isStreamlitMessage: true, type: type }, data);
      window.parent.postMessage(outData, "*");
    }
    function componentReady() {
      sendMessageToStreamlitClient("streamlit:componentReady", { apiVersion: 1 });
    }
    function setFrameHeight(height) {
      sendMessageToStreamlitClient("streamlit:setFrameHeight", { height: height });
    }
    function sendValue(value) {
      sendMessageToStreamlitClient("streamlit:setComponentValue", { value: value, dataType: "json" });
    }

    let dragEl = null;
    // Populated on each render: page number -> larger image src, for the zoom lightbox.
    let zoomSrcByPage = {};

    function renumber() {
      Array.from(document.querySelectorAll('.card')).forEach((c, i) => {
        c.querySelector('.num').textContent = (i + 1);
      });
    }

    function openLightbox(pageNum, positionLabel) {
      const src = zoomSrcByPage[pageNum];
      if (!src) return;
      document.getElementById('lightbox-img').src = src;
      document.getElementById('lightbox-caption').textContent = 'Position ' + positionLabel;
      document.getElementById('lightbox').classList.add('open');
    }
    function closeLightbox() {
      document.getElementById('lightbox').classList.remove('open');
      document.getElementById('lightbox-img').src = '';
    }
    document.getElementById('lightbox-close').addEventListener('click', closeLightbox);
    document.getElementById('lightbox').addEventListener('click', (e) => {
      if (e.target.id === 'lightbox') closeLightbox();
    });

    // Reordering is driven by whichever card is under the pointer, using
    // elementFromPoint. This works correctly in a multi-row / multi-column
    // grid (unlike a left/right-only check across a single flex row).
    function attachDnD() {
      const grid = document.getElementById('grid');
      Array.from(grid.querySelectorAll('.card')).forEach(card => {
        card.addEventListener('dragstart', () => {
          dragEl = card;
          setTimeout(() => card.classList.add('dragging'), 0);
        });
        card.addEventListener('dragend', () => {
          card.classList.remove('dragging');
          dragEl = null;
          renumber();
          updateHeight();
        });
      });
      grid.addEventListener('dragover', (e) => {
        e.preventDefault();
        if (!dragEl) return;
        const target = document.elementFromPoint(e.clientX, e.clientY);
        const card = target && target.closest ? target.closest('.card') : null;
        if (!card || card === dragEl) return;
        const rect = card.getBoundingClientRect();
        const beforeInRow = e.clientX < rect.left + rect.width / 2;
        grid.insertBefore(dragEl, beforeInRow ? card : card.nextSibling);
      });
      grid.addEventListener('drop', (e) => e.preventDefault());
    }

    function updateHeight() {
      requestAnimationFrame(() => {
        setFrameHeight(document.body.scrollHeight + 16);
      });
    }

    function renderGrid(pages, width) {
      const grid = document.getElementById('grid');
      grid.innerHTML = '';
      zoomSrcByPage = {};
      pages.forEach(p => {
        zoomSrcByPage[p.page] = p.zoom || p.thumb;

        const card = document.createElement('div');
        card.className = 'card';
        card.draggable = true;
        card.dataset.page = p.page;

        const thumbWrap = document.createElement('div');
        thumbWrap.className = 'thumb-wrap';
        if (p.thumb) {
          const img = document.createElement('img');
          img.src = p.thumb;
          img.draggable = false;
          thumbWrap.appendChild(img);
        }
        // Click (not drag) zooms in. Native drag only fires after real
        // pointer movement, so a plain tap/click still reaches here.
        thumbWrap.addEventListener('click', () => {
          const positionLabel = Array.from(grid.querySelectorAll('.card')).indexOf(card) + 1;
          openLightbox(p.page, positionLabel);
        });

        const num = document.createElement('div');
        num.className = 'num';

        card.appendChild(thumbWrap);
        card.appendChild(num);
        grid.appendChild(card);
      });
      attachDnD();
      renumber();
      updateHeight();
    }

    document.getElementById('apply-btn').addEventListener('click', () => {
      const cards = Array.from(document.querySelectorAll('.card'));
      const order = cards.map(c => parseInt(c.dataset.page, 10));
      sendValue(order);
      const status = document.getElementById('status');
      status.style.color = '#16a34a';
      status.textContent = 'Order applied \u2713';
      setTimeout(() => { status.textContent = ''; }, 2500);
    });

    window.addEventListener('message', (event) => {
      if (!event.data || event.data.type !== 'streamlit:render') return;
      const args = event.data.args || {};
      renderGrid(args.pages || [], args.thumb_width || 110);
    });

    componentReady();
    setFrameHeight(200);
  </script>
</body>
</html>
"""

_STATE_BRIDGE_HTML = r"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8" /></head>
<body>
<script>
  function sendMessageToStreamlitClient(type, data) {
    var outData = Object.assign({ isStreamlitMessage: true, type: type }, data);
    window.parent.postMessage(outData, "*");
  }
  function componentReady() {
    sendMessageToStreamlitClient("streamlit:componentReady", { apiVersion: 1 });
    sendMessageToStreamlitClient("streamlit:setFrameHeight", { height: 0 });
  }
  function sendValue(value) {
    sendMessageToStreamlitClient("streamlit:setComponentValue", { value: value, dataType: "json" });
  }

  const STORAGE_KEY = "organize_pdf_state_v1";
  let restored = false;

  window.addEventListener('message', (event) => {
    if (!event.data || event.data.type !== 'streamlit:render') return;
    const args = event.data.args || {};

    if (!restored) {
      restored = true;
      let existing = null;
      try {
        const raw = localStorage.getItem(STORAGE_KEY);
        if (raw) existing = JSON.parse(raw);
      } catch (e) {
        existing = null;
      }
      // Wrapped so Python can tell "checked, found nothing" (data: null)
      // apart from "component hasn't answered yet" (the raw default None).
      sendValue({ status: "restored", data: existing });
    }

    if (args.clear) {
      try { localStorage.removeItem(STORAGE_KEY); } catch (e) {}
    } else if (args.state !== null && args.state !== undefined) {
      try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(args.state));
      } catch (e) {
        // storage full or unavailable - fail silently, app still works without persistence
      }
    }
  });

  componentReady();
</script>
</body>
</html>
"""


def _bootstrap_components():
    for d in (_DRAG_GRID_DIR, _STATE_BRIDGE_DIR):
        d.mkdir(parents=True, exist_ok=True)
    (_DRAG_GRID_DIR / "index.html").write_text(_DRAG_GRID_HTML, encoding="utf-8")
    (_STATE_BRIDGE_DIR / "index.html").write_text(_STATE_BRIDGE_HTML, encoding="utf-8")


_bootstrap_components()

_drag_grid_component = components.declare_component("drag_grid", path=str(_DRAG_GRID_DIR))
_state_bridge_component = components.declare_component("state_bridge", path=str(_STATE_BRIDGE_DIR))


def drag_grid(pages, thumb_width=110, key=None):
    return _drag_grid_component(pages=pages, thumb_width=thumb_width, key=key, default=None)


def state_bridge(state=None, clear=False, key=None):
    return _state_bridge_component(state=state, clear=clear, key=key, default=None)


# ---------------------------------------------------------------------------
# Styling
# ---------------------------------------------------------------------------
st.markdown(
    """
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/geist@1.3.0/dist/fonts/geist-sans/style.css">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/geist@1.3.0/dist/fonts/geist-mono/style.css">
    <style>
    html, body, [class*="css"] {
        font-family: 'Geist', -apple-system, BlinkMacSystemFont, sans-serif !important;
    }
    #MainMenu, footer, header {visibility: hidden;}
    .main .block-container {
        padding-top: 1.2rem;
        padding-bottom: 2rem;
        max-width: 1400px;
    }
    h1, h2, h3 {
        font-family: 'Geist', sans-serif !important;
        font-weight: 600;
        letter-spacing: -0.03em;
        color: #111 !important;
    }
    .stButton > button, .stDownloadButton > button {
        background-color: #111 !important;
        color: #fff !important;
        border: 1px solid #111 !important;
        border-radius: 10px !important;
        font-family: 'Geist', sans-serif !important;
        font-weight: 500 !important;
        box-shadow: none !important;
    }
    .stButton > button:hover, .stDownloadButton > button:hover {
        background-color: #333 !important;
        color: #fff !important;
    }
    div[data-testid="column"]:last-child .stDownloadButton > button {
        background-color: #e11d48 !important;
        border-color: #e11d48 !important;
        font-weight: 600 !important;
        padding: 0.7rem 1.2rem !important;
    }
    div[data-testid="column"]:last-child .stDownloadButton > button:hover {
        background-color: #be123c !important;
    }
    [data-testid="stFileUploader"] {
        border: 1px solid #e5e5e5;
        border-radius: 10px;
        background: #fff;
    }
    .stCaption { color: #888 !important; font-size: 0.8rem !important; }
    hr { border: none; border-top: 1px solid #eee; margin: 1rem 0; }
    .file-chip {
        background: #ffe4e6;
        color: #9f1239;
        border-radius: 8px;
        padding: 8px 12px;
        font-size: 0.85rem;
        margin: 6px 0;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Session state defaults
# ---------------------------------------------------------------------------
if "pdf_bytes" not in st.session_state:
    st.session_state.pdf_bytes = None
if "page_order" not in st.session_state:
    st.session_state.page_order = []
if "filename" not in st.session_state:
    st.session_state.filename = "document.pdf"
if "hydrated" not in st.session_state:
    st.session_state.hydrated = False
if "pending_clear" not in st.session_state:
    st.session_state.pending_clear = False


def load_pdf(uploaded_file):
    data = uploaded_file.read()
    st.session_state.pdf_bytes = data
    st.session_state.filename = uploaded_file.name
    reader = PdfReader(BytesIO(data))
    st.session_state.page_order = list(range(len(reader.pages)))


def get_reader():
    if st.session_state.pdf_bytes is None:
        return None
    return PdfReader(BytesIO(st.session_state.pdf_bytes))


@st.cache_data(show_spinner=False)
def render_thumbnail(pdf_bytes, page_index, max_width=200):
    try:
        pdf = pdfium.PdfDocument(pdf_bytes)
        if page_index >= len(pdf):
            return None
        page = pdf[page_index]
        bitmap = page.render(scale=2.0)
        pil_image = bitmap.to_pil()
        if pil_image.mode != "RGB":
            pil_image = pil_image.convert("RGB")
        w, h = pil_image.size
        if w == 0 or h == 0:
            return None
        if w > h:
            new_w = max_width
            new_h = max(1, int(h * max_width / w))
        else:
            new_h = max_width
            new_w = max(1, int(w * max_width / h))
        return pil_image.resize((new_w, new_h), Image.Resampling.LANCZOS)
    except Exception:
        return None


def image_to_data_uri(img):
    buf = BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()
    return f"data:image/png;base64,{b64}"


# ---------------------------------------------------------------------------
# Persistence: restore once on a fresh session, then keep localStorage synced
# with the current state on every rerun so a full page reload isn't a reset.
# ---------------------------------------------------------------------------
# If "Clear saved copy" was just clicked, do the reset now (before building
# this run's persist payload) and tell the *already-mounted* bridge to clear
# localStorage in this same message — no fresh component instance, so there's
# no load-timing race with the rerun.
_do_clear = st.session_state.pending_clear
if _do_clear:
    st.session_state.pending_clear = False
    st.session_state.pdf_bytes = None
    st.session_state.page_order = []
    st.session_state.filename = "document.pdf"

_persist_state = None
if st.session_state.pdf_bytes is not None:
    _persist_state = {
        "pdf_b64": base64.b64encode(st.session_state.pdf_bytes).decode(),
        "filename": st.session_state.filename,
        "page_order": st.session_state.page_order,
    }

_bridge_result = state_bridge(state=_persist_state, clear=_do_clear, key="state_bridge_widget")

# _bridge_result is None until the component has actually checked localStorage
# and reported back (that first answer arrives a moment after the very first
# script run and triggers its own automatic rerun) — so only give up waiting
# once we've received the real wrapped answer, not on the initial placeholder.
if not st.session_state.hydrated and isinstance(_bridge_result, dict):
    st.session_state.hydrated = True
    restored_data = _bridge_result.get("data")
    if restored_data and st.session_state.pdf_bytes is None:
        try:
            pdf_bytes = base64.b64decode(restored_data["pdf_b64"])
            reader = PdfReader(BytesIO(pdf_bytes))
            n_pages = len(reader.pages)
            saved_order = restored_data.get("page_order")
            if not (isinstance(saved_order, list) and set(saved_order) == set(range(n_pages))):
                saved_order = list(range(n_pages))
            st.session_state.pdf_bytes = pdf_bytes
            st.session_state.filename = restored_data.get("filename", "document.pdf")
            st.session_state.page_order = saved_order
            st.rerun()
        except Exception:
            pass

left, right = st.columns([3.2, 1.1], gap="large")

# ========================= RIGHT =========================
with right:
    st.markdown(
        '<h2 style="margin:0 0 0.2rem 0;font-size:1.35rem;"><i class="fa-solid fa-file-pdf" style="margin-right:8px;color:#e11d48;"></i>Organize PDF</h2>',
        unsafe_allow_html=True,
    )
    st.caption("Drag pages to reorder · Delete · Download")

    st.markdown("---")
    st.markdown(
        '<p style="font-weight:600;margin-bottom:0.3rem;font-size:0.9rem;"><i class="fa-solid fa-upload" style="margin-right:6px;"></i>Upload PDF</p>',
        unsafe_allow_html=True,
    )
    uploaded = st.file_uploader(
        "Choose a PDF file",
        type=["pdf"],
        key="main_uploader",
        label_visibility="collapsed",
    )
    if uploaded is not None:
        if (
            st.session_state.pdf_bytes is None
            or uploaded.name != st.session_state.filename
            or uploaded.size != len(st.session_state.pdf_bytes)
        ):
            load_pdf(uploaded)
            st.success(f"Loaded: **{uploaded.name}**")

    if st.session_state.pdf_bytes is not None:
        st.markdown(
            f"""
            <p style="font-weight:600;margin:0.8rem 0 0.3rem;font-size:0.9rem;">Files</p>
            <div class="file-chip">
                <i class="fa-solid fa-file" style="margin-right:6px;"></i>
                {st.session_state.filename}
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button("Reset all", use_container_width=True, key="reset_btn"):
            reader = get_reader()
            st.session_state.page_order = list(range(len(reader.pages)))
            st.rerun()

        if st.button("Clear saved copy", use_container_width=True, key="clear_saved_btn"):
            st.session_state.pending_clear = True
            st.rerun()

    st.markdown("---")
    st.markdown(
        '<p style="font-weight:600;margin-bottom:0.3rem;font-size:0.9rem;"><i class="fa-solid fa-plus" style="margin-right:6px;"></i>Add pages from another PDF</p>',
        unsafe_allow_html=True,
    )
    add_file = st.file_uploader(
        "Select PDF to insert",
        type=["pdf"],
        key="add_uploader",
        label_visibility="collapsed",
    )
    insert_position = st.number_input(
        "Insert after page (0 = start)",
        min_value=0,
        value=0,
        step=1,
        key="insert_pos",
    )

    if add_file and st.session_state.pdf_bytes is not None:
        if st.button("Insert pages", use_container_width=True):
            add_reader = PdfReader(BytesIO(add_file.read()))
            writer = PdfWriter()
            reader = get_reader()
            current_order = st.session_state.page_order
            for idx in current_order[:insert_position]:
                writer.add_page(reader.pages[idx])
            for page in add_reader.pages:
                writer.add_page(page)
            for idx in current_order[insert_position:]:
                writer.add_page(reader.pages[idx])
            buf = BytesIO()
            writer.write(buf)
            st.session_state.pdf_bytes = buf.getvalue()
            new_reader = PdfReader(BytesIO(st.session_state.pdf_bytes))
            st.session_state.page_order = list(range(len(new_reader.pages)))
            st.success(f"Inserted {len(add_reader.pages)} page(s).")
            st.rerun()

    if st.session_state.pdf_bytes is not None:
        st.markdown("---")
        st.checkbox(
            "Preview final order before downloading",
            key="show_final_preview",
            help="Shows every page, large, in the exact order the downloaded PDF will use.",
        )
        reader = get_reader()
        writer = PdfWriter()
        for page_idx in st.session_state.page_order:
            writer.add_page(reader.pages[page_idx])
        output = BytesIO()
        writer.write(output)
        output.seek(0)
        download_name = st.session_state.filename
        if not download_name.lower().endswith(".pdf"):
            download_name += ".pdf"
        base = download_name.rsplit(".", 1)[0]
        download_name = f"{base}_organized.pdf"
        st.download_button(
            label="Organize  →",
            data=output,
            file_name=download_name,
            mime="application/pdf",
            use_container_width=True,
        )

# ========================= LEFT =========================
with left:
    if st.session_state.pdf_bytes is None:
        st.markdown(
            """
            <div style="text-align:center;padding:5rem 1rem;">
                <i class="fa-solid fa-file-arrow-up" style="font-size:3rem;color:#ddd;"></i>
                <h2 style="margin:0.6rem 0 0.3rem;">Upload a PDF to get started</h2>
                <p style="color:#999;">Use the panel on the right to select a file.</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.stop()

    order = st.session_state.page_order
    n = len(order)

    st.markdown(
        f"""
        <p style="color:#888;font-size:0.9rem;margin-bottom:0.8rem;">
            <i class="fa-solid fa-hand" style="margin-right:4px;"></i>
            <strong>Drag</strong> the pages below to reorder, then click
            <strong>Apply order</strong> &nbsp;·&nbsp; {n} pages
        </p>
        """,
        unsafe_allow_html=True,
    )

    pages_payload = []
    for page_idx in order:
        thumb = render_thumbnail(st.session_state.pdf_bytes, page_idx, max_width=110)
        zoom = render_thumbnail(st.session_state.pdf_bytes, page_idx, max_width=700)
        pages_payload.append(
            {
                "page": page_idx,
                "thumb": image_to_data_uri(thumb) if thumb is not None else None,
                "zoom": image_to_data_uri(zoom) if zoom is not None else None,
            }
        )

    result = drag_grid(pages_payload, thumb_width=110, key="drag_grid_widget")
    st.caption("Tap or click a thumbnail to zoom in and check it.")

    if result is not None:
        try:
            new_order = [int(x) for x in result]
        except (TypeError, ValueError):
            new_order = None
        if (
            new_order is not None
            and len(new_order) == len(order)
            and set(new_order) == set(order)
            and new_order != st.session_state.page_order
        ):
            st.session_state.page_order = new_order
            st.rerun()

    st.markdown("---")
    st.markdown(
        '<p style="font-weight:600;margin-bottom:0.4rem;font-size:0.9rem;"><i class="fa-solid fa-trash-can" style="margin-right:6px;"></i>Delete pages</p>',
        unsafe_allow_html=True,
    )
    num_cols = min(8, max(1, n))
    del_cols = st.columns(num_cols)
    to_delete = []
    for i, page_idx in enumerate(order):
        with del_cols[i % num_cols]:
            if st.checkbox(f"p{i + 1}", key=f"del_{page_idx}"):
                to_delete.append(page_idx)

    if to_delete:
        if st.button("Delete selected"):
            remaining = [p for p in st.session_state.page_order if p not in to_delete]
            if not remaining:
                st.error("Cannot delete all pages.")
            else:
                st.session_state.page_order = remaining
                st.success(f"Deleted {len(to_delete)} page(s).")
                st.rerun()

    st.markdown("---")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("Reverse order", use_container_width=True):
            st.session_state.page_order = list(reversed(st.session_state.page_order))
            st.rerun()
    with c2:
        if st.button("Restore original", use_container_width=True):
            st.session_state.page_order = list(range(len(get_reader().pages)))
            st.rerun()

    if st.session_state.get("show_final_preview"):
        st.markdown("---")
        st.markdown(
            '<p style="font-weight:600;margin-bottom:0.6rem;font-size:0.95rem;">'
            '<i class="fa-solid fa-eye" style="margin-right:6px;"></i>'
            "Final order preview — exactly what will download</p>",
            unsafe_allow_html=True,
        )
        preview_cols = st.columns(2)
        for i, page_idx in enumerate(st.session_state.page_order):
            large = render_thumbnail(st.session_state.pdf_bytes, page_idx, max_width=700)
            with preview_cols[i % 2]:
                if large is not None:
                    st.image(large, use_container_width=True)
                st.caption(f"Page {i + 1}  ·  originally page {page_idx + 1}")