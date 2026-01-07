import json
import requests
from urllib.parse import quote, urlencode
from flask import Blueprint, render_template, request, session, Response, stream_with_context, current_app
from flask_login import login_required
from core.models import Node, CompanyConfig
from core.api_client import OpenNotebookAPI

bp = Blueprint('dashboard', __name__, template_folder='templates')

SERVICE_KB_NOTEBOOK_NAMES = [
    'service_kb_new',
    'service_kb_peerreview',
    'service_kb_internal',
    'service_kb_customer',
    'service_kb_unapproved',
]

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


def _get_node():
    return Node.query.first()


def _ui_base_for_node(node: Node) -> str:
    ui_base = node.ui_host if node.ui_host else f"{node.ip_address}:8502"
    if not ui_base.startswith('http'):
        ui_base = f"http://{ui_base}"
    return ui_base


def _get_service_kb_notebooks(node_ip: str):
    notebooks = OpenNotebookAPI.get_notebooks(node_ip)
    name_to_id = {n.get('name'): n.get('id') for n in notebooks if n.get('name') and n.get('id')}
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

    lines = []
    lines.append(
        f"You are {company_name} AI Knowledgebase assistant.\n"
        "Use only the CONTEXT below.\n"
        "If the answer is not in the context, say you don't know.\n"
        "Be concise and actionable.\n\n"
    )
    lines.append("QUESTION:\n" + question.strip() + "\n\n")
    lines.append("CONTEXT:\n")

    used = len(''.join(lines))
    for i, item in enumerate(picked, start=1):
        s = item['source']
        loc = item['location']
        title = (s.get('title') or '').strip()
        asset = s.get('asset') or {}
        url = (asset.get('url') or '').strip()
        full_text = (s.get('full_text') or '').strip()

        header = f"[SOURCE {i}] title={title} | location={loc}\n"
        body = full_text or (f"URL: {url}\n" if url else "(No text content)\n")
        chunk = header + body + "\n\n"

        if used + len(chunk) > max_chars:
            break
        lines.append(chunk)
        used += len(chunk)

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
    node = _get_node()
    if not node:
        return Response(_sse('done', json.dumps({'warnings': ['No node configured'], 'citations': []})), mimetype='text/event-stream')

    ui_base = _ui_base_for_node(node)

    question = (request.form.get('message') or '').strip()
    if not question:
        return Response(_sse('done', json.dumps({'warnings': [], 'citations': []})), mimetype='text/event-stream')

    try:
        min_relevance = float(request.form.get('min_relevance') or '0')
    except ValueError:
        min_relevance = 0.0

    svc_name_to_id, svc_id_to_name = _get_service_kb_notebooks(node.ip_address)

    requested_notebooks = request.form.getlist('notebooks')
    requested_notebooks = [n for n in requested_notebooks if n in svc_name_to_id]

    if not requested_notebooks:
        warnings = ['Select at least one notebook to search.']
        return Response(_sse('done', json.dumps({'warnings': warnings, 'citations': []})), mimetype='text/event-stream')

    # Persist UI prefs
    session['kb_chat_selected_notebooks'] = requested_notebooks
    session['kb_chat_min_relevance'] = min_relevance

    allowed_notebook_ids = {svc_name_to_id[n] for n in requested_notebooks}

    cfg = CompanyConfig.query.first()
    company_name = (cfg.company_name if cfg and cfg.company_name else 'Cudo')

    def generate():
        yield _sse('status', 'Searching index…')

        # 1) Search
        try:
            sr = requests.post(
                f"http://{node.ip_address}:5055/api/search",
                json={'query': question, 'type': 'text', 'limit': 50, 'search_sources': True, 'search_notes': False},
                timeout=20,
            )
            if sr.status_code != 200:
                yield _sse('token', json.dumps('(Search failed)'))
                yield _sse('done', json.dumps({'warnings': [], 'citations': []}))
                return
            results = (sr.json() or {}).get('results') or []
        except Exception:
            yield _sse('token', json.dumps('(Search failed)'))
            yield _sse('done', json.dumps({'warnings': [], 'citations': []}))
            return

        yield _sse('status', f'Ranking {len(results)} results…')
        results.sort(key=lambda r: float(r.get('relevance') or 0), reverse=True)

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

            try:
                src_resp = requests.get(f"http://{node.ip_address}:5055/api/sources/{sid}", timeout=15)
                if src_resp.status_code != 200:
                    continue
                src_obj = src_resp.json() or {}
            except Exception:
                continue

            src_notebook_ids = set(src_obj.get('notebooks') or [])
            if not (src_notebook_ids & allowed_notebook_ids):
                continue

            loc = _pick_location_for_source(src_obj.get('notebooks'), svc_id_to_name)
            if not loc:
                continue

            notebook_id = None
            for nid in (src_obj.get('notebooks') or []):
                if svc_id_to_name.get(nid) == loc:
                    notebook_id = nid
                    break
            if not notebook_id:
                for nid in (src_obj.get('notebooks') or []):
                    if nid in allowed_notebook_ids:
                        notebook_id = nid
                        break

            picked.append({'source': src_obj, 'location': loc, 'relevance': rel, 'notebook_id': notebook_id})
            if len(picked) >= TOP_K_DEFAULT:
                break

        yield _sse('status', f'Building prompt from {len(picked)} sources…')
        warnings, citations = _flags_and_citations(picked, ui_base)

        model_name = _pick_ollama_model(node.ip_address)
        if not model_name:
            yield _sse('token', json.dumps('(No Ollama model configured in Open Notebook.)\n'))
            yield _sse('done', json.dumps({'warnings': warnings, 'citations': citations}))
            return

        prompt = _build_prompt(company_name, question, picked)

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
