import base64
import json

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
    /* Hide the sync field used to receive the drag order from the component */
    div[data-testid="stTextInput"]:has(input[aria-label="__order_sync__"]) {
        position: absolute !important;
        width: 1px !important;
        height: 1px !important;
        padding: 0 !important;
        margin: -1px !important;
        overflow: hidden !important;
        opacity: 0 !important;
        pointer-events: none;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

if "pdf_bytes" not in st.session_state:
    st.session_state.pdf_bytes = None
if "page_order" not in st.session_state:
    st.session_state.page_order = []
if "filename" not in st.session_state:
    st.session_state.filename = "document.pdf"
if "order_sync_last" not in st.session_state:
    st.session_state.order_sync_last = ""


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


def build_drag_grid_html(pdf_bytes, order, thumb_width=110):
    """Self-contained HTML5 drag-and-drop grid. Each card carries its own
    real thumbnail image and page-index — nothing is derived from sibling
    position, so nothing can glitch or mismatch while dragging."""
    card_h = int(thumb_width * 1.3)
    cards_html = []
    for page_idx in order:
        thumb = render_thumbnail(pdf_bytes, page_idx, max_width=thumb_width)
        img_tag = (
            f'<img src="{image_to_data_uri(thumb)}" draggable="false" />'
            if thumb is not None
            else ""
        )
        cards_html.append(
            f'<div class="card" draggable="true" data-page="{page_idx}">'
            f'<div class="thumb-wrap">{img_tag}</div>'
            f'<div class="num"></div>'
            f"</div>"
        )
    cards_joined = "\n".join(cards_html)

    return f"""
    <html>
    <head>
    <style>
        html, body {{
            margin: 0; padding: 0;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            background: transparent;
        }}
        #grid {{
            display: flex;
            flex-direction: row;
            flex-wrap: wrap;
            gap: 14px;
            padding: 4px;
        }}
        .card {{
            width: {thumb_width + 20}px;
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
        }}
        .card:hover {{
            box-shadow: 0 6px 18px rgba(244,63,94,0.2);
            background-color: #fff1f2;
        }}
        .card.dragging {{
            opacity: 0.4;
        }}
        .thumb-wrap {{
            width: 100%;
            height: {card_h}px;
            display: flex;
            align-items: center;
            justify-content: center;
            overflow: hidden;
        }}
        .thumb-wrap img {{
            max-width: 100%;
            max-height: 100%;
            pointer-events: none;
        }}
        .num {{
            margin-top: 6px;
            font-family: 'Geist Mono', 'Courier New', monospace;
            font-size: 0.8rem;
            font-weight: 600;
            color: #666;
        }}
        #apply-btn {{
            margin-top: 14px;
            background-color: #111;
            color: #fff;
            border: none;
            border-radius: 10px;
            font-weight: 500;
            padding: 10px 18px;
            cursor: pointer;
            font-size: 0.9rem;
        }}
        #apply-btn:hover {{
            background-color: #333;
        }}
        #status {{
            display: inline-block;
            margin-left: 10px;
            font-size: 0.8rem;
            color: #16a34a;
        }}
    </style>
    </head>
    <body>
        <div id="grid">
            {cards_joined}
        </div>
        <button id="apply-btn">Apply order ↓</button>
        <span id="status"></span>

        <script>
        const grid = document.getElementById('grid');
        let dragEl = null;

        function renumber() {{
            Array.from(grid.querySelectorAll('.card')).forEach((c, i) => {{
                c.querySelector('.num').textContent = (i + 1);
            }});
        }}

        Array.from(grid.querySelectorAll('.card')).forEach(card => {{
            card.addEventListener('dragstart', () => {{
                dragEl = card;
                setTimeout(() => card.classList.add('dragging'), 0);
            }});
            card.addEventListener('dragend', () => {{
                card.classList.remove('dragging');
                dragEl = null;
                renumber();
            }});
            card.addEventListener('dragover', (e) => {{
                e.preventDefault();
                if (!dragEl || dragEl === card) return;
                const rect = card.getBoundingClientRect();
                const before = e.clientX < rect.left + rect.width / 2;
                grid.insertBefore(dragEl, before ? card : card.nextSibling);
            }});
        }});
        grid.addEventListener('dragover', (e) => e.preventDefault());
        grid.addEventListener('drop', (e) => e.preventDefault());

        renumber();

        document.getElementById('apply-btn').addEventListener('click', () => {{
            const status = document.getElementById('status');
            try {{
                const cards = Array.from(grid.querySelectorAll('.card'));
                const order = cards.map(c => c.getAttribute('data-page'));
                const orderJson = JSON.stringify(order);

                const doc = window.parent.document;
                const input = doc.querySelector('input[aria-label="__order_sync__"]');
                if (!input) {{
                    status.style.color = '#dc2626';
                    status.textContent = 'Could not sync — reload the page.';
                    return;
                }}
                const setter = Object.getOwnPropertyDescriptor(
                    window.parent.HTMLInputElement.prototype, 'value'
                ).set;
                setter.call(input, orderJson);
                input.dispatchEvent(new Event('input', {{ bubbles: true }}));
                input.dispatchEvent(new Event('change', {{ bubbles: true }}));
                input.blur();
                status.style.color = '#16a34a';
                status.textContent = 'Order applied ✓';
            }} catch (err) {{
                status.style.color = '#dc2626';
                status.textContent = 'Sync error: ' + err.message;
            }}
        }});
        </script>
    </body>
    </html>
    """


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

    # Rows needed for a rough height estimate (actual wrapping is responsive).
    approx_cols = 8
    rows = max(1, -(-n // approx_cols))
    grid_height = rows * 190 + 90

    grid_html = build_drag_grid_html(st.session_state.pdf_bytes, order, thumb_width=110)
    components.html(grid_html, height=grid_height, scrolling=True)

    sync_value = st.text_input(
        "__order_sync__", key="order_sync", label_visibility="collapsed"
    )
    if sync_value and sync_value != st.session_state.order_sync_last:
        try:
            new_order = [int(x) for x in json.loads(sync_value)]
            if len(new_order) == len(order) and set(new_order) == set(order):
                st.session_state.order_sync_last = sync_value
                st.session_state.page_order = new_order
                st.rerun()
        except (ValueError, TypeError, json.JSONDecodeError):
            pass

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
            if st.checkbox(f"p{page_idx + 1}", key=f"del_{page_idx}"):
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