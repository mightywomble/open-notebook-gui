import json
import re
import requests
import uuid
from urllib.parse import quote, urlencode
from flask import Blueprint, render_template, request, session, Response, stream_with_context, current_app
from flask_login import login_required
from core.models import Node, CompanyConfig
from core.constants import SERVICE_KB_NOTEBOOK_NAMES
from core.api_client import OpenNotebookAPI

bp = Blueprint('dashboard', __name__, template_folder='templates')

LOCATION_LABELS = {
    'service_kb_new': 'New (not peer reviewed)',
    'service_kb_peerreview': 'Peer Review',
    'service_kb_internal': 'Internal (internal only)',
    'service_kb_customer': 'Customer',
    'service_kb_unapproved': 'Unapproved',
}

LOCATION_PRIORITY = [
    'service_kb_internal',
    'service_kb_customer',
    'service_kb_peerreview',
    'service_kb_new',
    'service_kb_unapproved',
]

TOP_K_DEFAULT = 6


# --- Chat extraction helpers ---

def _is_text_response(resp) -> bool:
    ct = (resp.headers.get('Content-Type') or '').lower()
    return ct.startswith('text/') or 'json' in ct or 'yaml' in ct or 'markdown' in ct or 'plain' in ct


def _try_extract_text_from_pdf_bytes(data: bytes) -> str:
    # Best-effort: try pdfminer, then PyPDF2; otherwise return empty
    try:
        from pdfminer.high_level import extract_text
        import io
        return extract_text(io.BytesIO(data)) or ''
    except Exception:
        try:
            import PyPDF2, io
            reader = PyPDF2.PdfReader(io.BytesIO(data))
            txt = []
            for page in reader.pages[:10]:  # cap pages for speed
                try:
                    txt.append(page.extract_text() or '')
                except Exception:
                    continue
            return '\n'.join(txt)
        except Exception:
            return ''


def _basic_ascii(t: str) -> str:
    return "".join(ch for ch in t if ch == "\n" or 32 <= ord(ch) <= 126)


def _sanitize_text(t: str) -> str:
    if not t:
        return ''
    # Keep printable ASCII and newlines
    t = ''.join(ch for ch in t if ch == '\n' or 32 <= ord(ch) <= 126)
    # Collapse runs of the same char > 6 to 6 (e.g., JJJJJJJJ)
    t = re.sub(r'(.){6,}', lambda m: m.group(1)*6, t)
    # Drop lines that are mostly repeated single chars (artifacts)
    lines = []
    for line in t.splitlines():
        if not line.strip():
            lines.append(line)
            continue
        majority = max((line.count(c) for c in set(line)), default=0)
        if majority >= 0.8 * len(line):
            continue
        lines.append(line)
    t = '\n'.join(lines)
    # Heuristic: require at least 20% alnum
    alnum = sum(c.isalnum() for c in t)
    if len(t) > 0 and (alnum / max(len(t),1)) < 0.2:
        return ''
    return t.strip()


def _get_node():
    return Node.query.first()


def _ui_base_for_node(node: Node) -> str:
    ui_base = node.ui_host if node.ui_host else f"{node.ip_address}:8502"
    if not ui_base.startswith('http'):
        ui_base = f"http://{ui_base}"
    return ui_base


def _get_service_kb_notebooks(node_ip: str):
    notebooks = OpenNotebookAPI.get_notebooks(node_ip)
    name_to_id = {n.get('name'): str(n.get('id')) for n in notebooks if n.get('name') and n.get('id')}
    svc = {name: name_to_id[name] for name in SERVICE_KB_NOTEBOOK_NAMES if name in name_to_id}
    id_to_name = {v: k for k, v in svc.items()}
    return svc, id_to_name


def _get_defaults(node_ip: str):
    try:
        r = requests.get(f"http://{node_ip}:5055/api/models/defaults", timeout=10)
        if r.status_code == 200:
            return r.json() or {}
    except Exception:
        pass
    return {}


def _get_models(node_ip: str):
    try:
        r = requests.get(f"http://{node_ip}:5055/api/models", timeout=10)
        if r.status_code == 200:
            return r.json() or []
    except Exception:
        pass
    return []


def _pick_ollama_model(node_ip: str):
    defaults = _get_defaults(node_ip)
    default_id = defaults.get('default_chat_model') or defaults.get('default_transformation_model')
    models = _get_models(node_ip)

    by_id = {m.get('id'): m for m in models if m.get('id')}
    if default_id and default_id in by_id:
        m = by_id[default_id]
        if m.get('provider') == 'ollama' and m.get('name'):
            return m.get('name')

    for m in models:
        if m.get('provider') == 'ollama' and m.get('type') == 'language' and m.get('name'):
            return m.get('name')

    return None


def _pick_location_for_source(notebook_ids: list[str] | None, id_to_name: dict[str, str]):
    names = []
    for nid in (notebook_ids or []):
        nm = id_to_name.get(nid)
        if nm:
            names.append(nm)
    if not names:
        return None
    for pref in LOCATION_PRIORITY:
        if pref in names:
            return pref
    return names[0]


def _flags_and_citations(picked: list[dict], ui_base: str):
    citations = []
    locs = set()

    for item in picked:
        s = item['source']
        loc = item['location']
        rel = item.get('relevance')
        locs.add(loc)

        notebook_id = item.get('notebook_id')
        sid = s.get('id')

        url = None
        if notebook_id and sid:
            url = f"{ui_base}/notebooks/{quote(str(notebook_id), safe='')}?" + urlencode({'modal': 'source', 'id': sid})

        citations.append({
            'id': sid,
            'title': s.get('title') or sid,
            'location': LOCATION_LABELS.get(loc, loc),
            'relevance': rel,
            'url': url,
        })

    warnings = []
    if 'service_kb_new' in locs:
        warnings.append('This answer may include information from New Articles that has not been peer reviewed.')
    if 'service_kb_internal' in locs:
        warnings.append('This answer may include Internal KB information (internal only).')

    return warnings, citations


def _build_prompt(company_name: str, question: str, picked: list[dict]):
    max_chars = 24000

    def _clip_relevant(text: str, terms: list[str], limit: int) -> str:
        if not text:
            return ''
        if len(text) <= limit:
            return text
        low = text.lower()
        hits = [low.find(t) for t in terms if t and t in low]
        hits = [h for h in hits if h >= 0]
        if not hits:
            return text[:limit]
        pos = min(hits)
        start = max(0, pos - limit // 2)
        end = start + limit
        return text[start:end]

    lines = []
    lines.append(
        f"You are {company_name} AI Knowledgebase assistant.\n"
        "Use only the CONTEXT below.\n"
        "If the answer is not in the context, say you don't know.\n"
        "Be concise and actionable.\n\n"
    )
    q = (question or '').strip()
    lines.append("QUESTION:\n" + q + "\n\n")
    lines.append("CONTEXT:\n")

    terms = [t for t in q.lower().split() if t]

    used = len(''.join(lines))
    for i, item in enumerate(picked, start=1):
        s = item['source']
        loc = item['location']
        title = (s.get('title') or '').strip()
        asset = s.get('asset') or {}
        url = (asset.get('url') or '').strip()
        full_text = (s.get('full_text') or '').strip()

        header = f"[SOURCE {i}] title={title} | location={loc}\n"
        remaining = max_chars - used - len(header) - 2  # for trailing newlines
        if remaining <= 0:
            break

        body = ''
        if full_text:
            body = _clip_relevant(full_text, terms, remaining)
        elif url:
            body = f"URL: {url}\n"
        else:
            body = "(No text content)\n"

        if len(body) > remaining:
            body = body[:remaining]

        chunk = header + body + "\n\n"
        lines.append(chunk)
        used += len(chunk)

        if used >= max_chars:
            break

    return ''.join(lines)


def _sse(event: str, data: str):
    return f"event: {event}\ndata: {data}\n\n"


@bp.route('/')
@login_required
def index():
    node = _get_node()
    if not node:
        return "No node configured", 400

    svc_name_to_id, _ = _get_service_kb_notebooks(node.ip_address)

    service_kb_notebooks = [
        {'name': name, 'label': LOCATION_LABELS.get(name, name)}
        for name in SERVICE_KB_NOTEBOOK_NAMES
        if name in svc_name_to_id
    ]

    selected_notebooks = session.get('kb_chat_selected_notebooks')
    if not selected_notebooks:
        selected_notebooks = [nb['name'] for nb in service_kb_notebooks]

    min_relevance = session.get('kb_chat_min_relevance', 0)

    messages = session.get('kb_chat_messages', [])
    return render_template(
        'dashboard/index.html',
        messages=messages,
        citations=[],
        warnings=[],
        service_kb_notebooks=service_kb_notebooks,
        selected_notebooks=selected_notebooks,
        min_relevance=min_relevance,
    )


@bp.route('/chat/clear', methods=['POST'])
@login_required
def chat_clear():
    session.pop('kb_chat_messages', None)
    return render_template('dashboard/chat_messages.html', messages=[], citations=[], warnings=[])


@bp.route('/chat/stream', methods=['POST'])
@login_required
def chat_stream():
    rid = str(uuid.uuid4())[:8]
    log = lambda m: current_app.logger.warning(f'[KB_CHAT {rid}] ' + m)
    node = _get_node()
    if not node:
        return Response(_sse('done', json.dumps({'warnings': ['No node configured'], 'citations': []})), mimetype='text/event-stream')

    ui_base = _ui_base_for_node(node)

    question = (request.form.get('message') or '').strip()
    log(f'question len={len(question)}')
    if not question:
        return Response(_sse('done', json.dumps({'warnings': [], 'citations': []})), mimetype='text/event-stream')

    try:
        min_relevance = float(request.form.get('min_relevance') or '0')
    except ValueError:
        min_relevance = 0.0

    svc_name_to_id, svc_id_to_name = _get_service_kb_notebooks(node.ip_address)

    requested_notebooks = request.form.getlist('notebooks')
    requested_notebooks = [n for n in requested_notebooks if n in svc_name_to_id]
    log(f'requested_notebooks={requested_notebooks}')

    if not requested_notebooks:
        warnings = ['Select at least one notebook to search.']
        return Response(_sse('done', json.dumps({'warnings': warnings, 'citations': []})), mimetype='text/event-stream')

    # Persist UI prefs
    session['kb_chat_selected_notebooks'] = requested_notebooks
    session['kb_chat_min_relevance'] = min_relevance

    allowed_notebook_ids = {str(svc_name_to_id[n]) for n in requested_notebooks}
    log(f'allowed_notebook_ids={sorted(list(allowed_notebook_ids))}')

    cfg = CompanyConfig.query.first()
    company_name = (cfg.company_name if cfg and cfg.company_name else 'Cudo')

    def generate():
        log('search:start'); yield _sse('status', 'Searching index…')

        # 1) Search
        try:
            sr = requests.post(
                f"http://{node.ip_address}:5055/api/search",
                json={'query': question, 'type': 'text', 'limit': 100, 'search_sources': True, 'search_notes': False, 'notebook_ids': list(allowed_notebook_ids)},
                timeout=20,
            )
            if sr.status_code != 200:
                yield _sse('token', json.dumps('(Search failed)'))
                yield _sse('done', json.dumps({'warnings': [], 'citations': []}))
                return
            results = (sr.json() or {}).get('results') or []
            log(f'search:status={sr.status_code} results={len(results)}')
        except Exception:
            yield _sse('token', json.dumps('(Search failed)'))
            yield _sse('done', json.dumps({'warnings': [], 'citations': []}))
            return

        yield _sse('status', f'Ranking {len(results)} results…')
        results.sort(key=lambda r: float(r.get('relevance') or 0), reverse=True)
        log(f'search:sorted results={len(results)} min_relevance={min_relevance}')

        # 2) Fetch source details and filter to selected notebooks
        picked = []
        considered = 0
        for r in results:
            rel = float(r.get('relevance') or 0)
            if rel < min_relevance:
                continue

            sid = r.get('id')
            if not sid:
                continue

            considered += 1
            if considered == 1:
                yield _sse('status', 'Fetching source details…')

            # We don't know how many we'll fetch; report progress as we go.
            yield _sse('status', f"Fetching source details ({considered} checked, {len(picked)}/{TOP_K_DEFAULT} selected)…")

            # Pull text directly from search hit when available (helps PDFs and binary sources)
            text_hint = (r.get('snippet') or r.get('content') or r.get('text') or '').strip()
            result_nb_ids = {str(x) for x in (r.get('notebooks') or r.get('notebook_ids') or [])}

            src_obj = None
            try:
                src_resp = requests.get(f"http://{node.ip_address}:5055/api/sources/{sid}", timeout=15)
                if src_resp.status_code == 200:
                    src_obj = src_resp.json() or {}
            except Exception:
                src_obj = None

            if not src_obj:
                # Synthesize a minimal source object from the search hit
                src_obj = {
                    'id': sid,
                    'title': r.get('title') or sid,
                    'asset': {'url': r.get('url') or ''},
                    'notebooks': list(result_nb_ids),
                    'full_text': text_hint,
                }

            # Ensure we have text for the prompt: if full_text is missing, try downloading
            ft = (src_obj.get('full_text') or '').strip()
            if not ft:
                try:
                    dl = requests.get(f"http://{node.ip_address}:5055/api/sources/{sid}/download", timeout=15)
                    if dl.status_code == 200 and dl.content:
                        ct = (dl.headers.get('Content-Type') or '').lower()
                        b = dl.content
                        fn = (src_obj.get('title') or '').lower()
                        txt = ''
                        is_pdf = b.startswith(b'%PDF') or ('pdf' in ct) or fn.endswith('.pdf')
                        if _is_text_response(dl):
                            try:
                                txt = b.decode('utf-8', errors='replace')
                            except Exception:
                                txt = ''
                        elif is_pdf:
                            txt = _try_extract_text_from_pdf_bytes(b)
                            if not txt:
                                try:
                                    ocr_txt, ocr_status = _try_ocr_pdf_bytes(b)
                                except Exception:
                                    ocr_txt, ocr_status = '', 'missing'
                                if ocr_txt:
                                    txt = ocr_txt
                        tmp_txt = _sanitize_text(txt)
                        kept = bool(tmp_txt)
                        if not kept and txt:
                            tmp_txt = _basic_ascii(txt)[:4000]
                        src_obj['full_text'] = tmp_txt
                        log(f'extract sid={sid} ct={ct} is_pdf=' + str(is_pdf) + ' bytes={len(dl.content)} txt={len(txt)} sanitized={len(tmp_txt)} kept={kept}')
                    else:
                        src_obj['full_text'] = src_obj.get('full_text') or ''
                except Exception:
                    pass

            src_notebook_ids = {str(x) for x in (src_obj.get('notebooks') or [])}
            # If we can determine notebooks, enforce the selection; otherwise allow if we have text
            if src_notebook_ids:
                if not (src_notebook_ids & allowed_notebook_ids):
                    continue
            else:
                # No notebook metadata; only keep if we have usable text
                if not (src_obj.get('full_text') or '').strip():
                    continue

            loc = _pick_location_for_source(src_obj.get('notebooks'), svc_id_to_name)
            if not loc:
                continue

            notebook_id = None
            for nid in (src_obj.get('notebooks') or []):
                if svc_id_to_name.get(str(nid)) == loc:
                    notebook_id = nid
                    break
            if not notebook_id:
                for nid in (src_obj.get('notebooks') or []):
                    if str(nid) in allowed_notebook_ids:
                        notebook_id = nid
                        break

            text_len = len((src_obj.get('full_text') or '').strip())
            log(f'pick sid={sid} rel={rel:.3f} loc={loc} text_len={text_len}')
            picked.append({'source': src_obj, 'location': loc, 'relevance': rel, 'notebook_id': notebook_id})
            if len(picked) >= TOP_K_DEFAULT:
                break

        # Fallback: if nothing picked, expand to all notebooks
        if not picked:
            log('fallback:scan_sources')
            # Scan selected (or all service KB) notebooks and score locally if remote search returns nothing
            scan_ids = list(allowed_notebook_ids) if allowed_notebook_ids else list(svc_name_to_id.values())
            terms = [t for t in (question.lower().split()) if t]
            scored = []
            for nbid in scan_ids:
                try:
                    rls = requests.get(f"http://{node.ip_address}:5055/api/sources?notebook_id={nbid}", timeout=15)
                    if rls.status_code != 200:
                        continue
                    lst = rls.json() or []
                    log(f'fallback:scan nbid={nbid} count={len(lst)}')
                    for sobj in lst:
                        sid2 = sobj.get('id')
                        title2 = (sobj.get('title') or '')
                        init_ft = (sobj.get('full_text') or '')
                        log(f'scan sid={sid2} init_ft_len={len(init_ft)}')
                        # Always try download if we have no usable text, even if full_text field exists but is empty
                        text2 = _sanitize_text(init_ft)
                        if not text2:
                            try:
                                dl2 = requests.get(f"http://{node.ip_address}:5055/api/sources/{sid2}/download", timeout=10)
                                if dl2.status_code == 200 and dl2.content:
                                    ct2 = (dl2.headers.get('Content-Type') or '').lower()
                                    b2 = dl2.content
                                    raw2 = ''
                                    is_pdf2 = b2.startswith(b'%PDF') or ('pdf' in ct2) or (title2.lower().endswith('.pdf'))
                                    if _is_text_response(dl2):
                                        raw2 = b2.decode('utf-8', errors='replace')
                                    elif is_pdf2:
                                        raw2 = _try_extract_text_from_pdf_bytes(b2)
                                    if not raw2 and is_pdf2:
                                        try:
                                            ocr2, ocr2_status = _try_ocr_pdf_bytes(b2)
                                        except Exception:
                                            ocr2, ocr2_status = '', 'missing'
                                        if ocr2:
                                            raw2 = ocr2
                                    text2 = _sanitize_text(raw2)
                                    if not text2 and raw2:
                                        text2 = _basic_ascii(raw2)[:4000]
                                    log(f'extract sid={sid2} ct={ct2} is_pdf={is_pdf2} bytes={len(dl2.content)} txt={len(raw2)} sanitized={len(text2)} kept={bool(text2)}')
                            except Exception as ex:
                                log(f'download_error sid={sid2} err={str(ex)[:100]}')
                        log(f'fallback:before_blob sid={sid2} title_len={len(title2)} text2_len={len(text2)}')
                        blob = (title2 + '\n' + (text2 or '')).lower()
                        log(f'fallback:blob_preview sid={sid2} blob_preview={blob[:200]}')
                        if not blob:
                            continue
                        stopwords = {'how', 'do', 'i', 'the', 'a', 'an', 'and', 'or', 'is', 'are', 'in', 'on', 'at', 'to', 'for'}
                        score = sum(1 for t in terms if t not in stopwords and t in blob)
                        if score > 0:
                            sobj['full_text'] = text2 or ''
                            sobj['notebooks'] = sobj.get('notebooks') or [nbid]
                            scored.append((float(score), sobj, nbid))
                except Exception:
                    continue
            scored.sort(key=lambda x: x[0], reverse=True)
            for sc, sobj, nbid in scored[:TOP_K_DEFAULT]:
                loc = _pick_location_for_source(sobj.get('notebooks'), svc_id_to_name) or 'other'
                text_len2 = len((sobj.get('full_text') or '').strip())
                log(f'fallback:pick sid={sobj.get("id")} title={sobj.get("title")[:50]} score={sc} loc={loc} text_len={text_len2}')
                picked.append({'source': sobj, 'location': loc, 'relevance': sc, 'notebook_id': nbid})
                log(f'fallback:appended to picked, len now={len(picked)}')
        log(f'build: sources={len(picked)}'); yield _sse('status', f'Building prompt from {len(picked)} sources…')
        warnings, citations = _flags_and_citations(picked, ui_base)

        model_name = _pick_ollama_model(node.ip_address)
        log(f'model: {model_name}')
        if not model_name:
            yield _sse('token', json.dumps('(No Ollama model configured in Open Notebook.)\n'))
            yield _sse('done', json.dumps({'warnings': warnings, 'citations': citations}))
            return

        prompt = _build_prompt(company_name, question, picked)
        log(f'prompt: chars={len(prompt)}')

        yield _sse('status', f'Generating answer with {model_name}…')

        ollama_base = current_app.config.get('OLLAMA_API_BASE') or 'https://ollama.paedave.com'

        try:
            resp = requests.post(
                f"{ollama_base}/api/generate",
                json={'model': model_name, 'prompt': prompt, 'stream': True},
                stream=True,
                timeout=120,
            )
        except Exception:
            yield _sse('token', json.dumps('(Error contacting Ollama.)\n'))
            yield _sse('done', json.dumps({'warnings': warnings, 'citations': citations}))
            return

        if resp.status_code != 200:
            yield _sse('token', json.dumps(f"(Ollama error {resp.status_code})\n"))
            yield _sse('done', json.dumps({'warnings': warnings, 'citations': citations}))
            return

        full = []
        for line in resp.iter_lines(decode_unicode=True):
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue

            chunk = obj.get('response') or ''
            if chunk:
                full.append(chunk)
                yield _sse('token', json.dumps(chunk))

            if obj.get('done') is True:
                break

        history = session.get('kb_chat_messages', [])
        history.append({'role': 'user', 'content': question})
        history.append({'role': 'assistant', 'content': ''.join(full)})
        session['kb_chat_messages'] = history[-20:]

        yield _sse('done', json.dumps({'warnings': warnings, 'citations': citations}))

    return Response(stream_with_context(generate()), mimetype='text/event-stream')

@bp.route('/check_api_alive/<int:node_id>', methods=['POST'])
@login_required
def check_api_alive(node_id: int):
    """HTMX endpoint: checks whether the node's API (port 5055) responds."""
    node = Node.query.get_or_404(node_id)
    ok = False
    try:
        ok = bool(OpenNotebookAPI.check_health(node.ip_address))
    except Exception:
        ok = False

    if ok:
        return '<span class="pf-v5-c-badge pf-m-success">API reachable</span>', 200
    return '<span class="pf-v5-c-badge pf-m-danger">API unreachable</span>', 503


@bp.route('/check_ui_alive/<int:node_id>', methods=['POST'])
@login_required
def check_ui_alive(node_id: int):
    """HTMX endpoint: checks whether the node's UI (port 8502 or configured ui_host) responds."""
    node = Node.query.get_or_404(node_id)
    ui_base = _ui_base_for_node(node)
    alive = False
    try:
        resp = requests.get(ui_base, timeout=3, allow_redirects=True)
        alive = resp.status_code < 400
    except Exception:
        alive = False

    if alive:
        return '<span class="pf-v5-c-badge pf-m-success">UI reachable</span>', 200
    return '<span class="pf-v5-c-badge pf-m-danger">UI unreachable</span>', 503
