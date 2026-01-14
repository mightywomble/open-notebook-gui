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

bp = Blueprint('search', __name__, template_folder='templates', url_prefix='/search')

LOCATION_LABELS = {
    'service_kb_new': 'New (not peer reviewed)',
    'service_kb_peerreview': 'Peer Review',
    'service_kb_internal': 'Internal (internal only)',
    'service_kb_customer': 'Customer',
    'service_kb_unapproved': 'Unapproved',
}


def _sse(event: str, data: str):
    return f"event: {event}\ndata: {data}\n\n"


def _get_node():
    return Node.query.first()


def _ui_base_for_node(node):
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


def _pick_language_model(node_ip: str):
    """Pick best language model ID for AI chat."""
    defaults = _get_defaults(node_ip)
    model_id = defaults.get('default_chat_model') or defaults.get('default_transformation_model')
    if model_id:
        return model_id
    return None


def _extract_source_refs(text: str):
    """Extract source/note/insight references from AI response like [source:id] [note:id] [insight:id]"""
    pattern = r'\[(source|note|insight):([^\]]+)\]'
    matches = re.findall(pattern, text)
    refs = []
    seen = set()
    for ref_type, ref_id in matches:
        key = f"{ref_type}:{ref_id}"
        if key not in seen:
            seen.add(key)
            refs.append({'type': ref_type, 'id': ref_id})
    return refs


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

    selected = session.get('search_selected_notebooks')
    if not selected:
        if 'service_kb_new' in [n['name'] for n in service_kb_notebooks]:
            selected = ['service_kb_new']
        else:
            selected = [nb['name'] for nb in service_kb_notebooks]

    messages = session.get('search_messages', [])
    return render_template(
        'search/index.html',
        messages=messages,
        citations=[],
        warnings=[],
        service_kb_notebooks=service_kb_notebooks,
        selected_notebooks=selected,
    )


@bp.route('/chat/clear', methods=['POST'])
@login_required
def chat_clear():
    session.pop('search_messages', None)
    session.pop('search_chat_session_id', None)
    return render_template('search/chat_messages.html', messages=[], citations=[], warnings=[])


@bp.route('/chat/stream', methods=['POST'])
@login_required
def chat_stream():
    rid = str(uuid.uuid4())[:8]
    log = lambda m: current_app.logger.warning(f'[SEARCH_CHAT {rid}] ' + m)
    node = _get_node()
    if not node:
        return Response(_sse('done', json.dumps({'warnings': ['No node configured'], 'citations': []})), mimetype='text/event-stream')

    question = (request.form.get('message') or '').strip()
    log(f'question len={len(question)}')
    if not question:
        return Response(_sse('done', json.dumps({'warnings': [], 'citations': []})), mimetype='text/event-stream')

    svc_name_to_id, svc_id_to_name = _get_service_kb_notebooks(node.ip_address)

    requested_notebooks = request.form.getlist('notebooks')
    requested_notebooks = [n for n in requested_notebooks if n in svc_name_to_id]
    log(f'requested_notebooks={requested_notebooks}')

    if not requested_notebooks:
        warnings = ['Select at least one notebook to search.']
        return Response(_sse('done', json.dumps({'warnings': warnings, 'citations': []})), mimetype='text/event-stream')

    session['search_selected_notebooks'] = requested_notebooks
    
    # Use the first selected notebook for chat
    notebook_name = requested_notebooks[0]
    notebook_id = svc_name_to_id[notebook_name]
    log(f'Using notebook: {notebook_name} ({notebook_id})')

    base_url = f"http://{node.ip_address}:5055"
    ui_base = _ui_base_for_node(node)

    def generate():
        yield _sse('status', 'Initializing…')
        yield _sse('log', json.dumps({'step': 'init', 'notebook': notebook_name, 'notebook_id': notebook_id}))

        # Step 1: Get or create a chat session for this notebook
        yield _sse('status', 'Creating chat session…')
        
        chat_session_id = session.get('search_chat_session_id')
        
        if not chat_session_id:
            try:
                create_url = f"{base_url}/api/chat/sessions"
                create_payload = {'notebook_id': notebook_id, 'title': 'KB Search Session'}
                yield _sse('log', json.dumps({'step': 'session:create', 'url': create_url, 'payload': create_payload}))
                
                resp = requests.post(create_url, json=create_payload, timeout=30)
                yield _sse('log', json.dumps({'step': 'session:create', 'status': resp.status_code}))
                
                if resp.status_code != 200:
                    yield _sse('token', json.dumps(f'(Failed to create chat session: {resp.status_code})'))
                    yield _sse('log', json.dumps({'step': 'session:create', 'error': resp.text[:300]}))
                    yield _sse('done', json.dumps({'warnings': [], 'citations': []}))
                    return
                
                sess_data = resp.json()
                chat_session_id = sess_data.get('id')
                session['search_chat_session_id'] = chat_session_id
                yield _sse('log', json.dumps({'step': 'session:create', 'session_id': chat_session_id}))
            except Exception as e:
                yield _sse('token', json.dumps(f'(Error creating session: {str(e)[:100]})'))
                yield _sse('log', json.dumps({'step': 'session:create', 'error': str(e)}))
                yield _sse('done', json.dumps({'warnings': [], 'citations': []}))
                return
        else:
            yield _sse('log', json.dumps({'step': 'session:reuse', 'session_id': chat_session_id}))

        # Step 2: Build context for the notebook
        yield _sse('status', 'Building context from notebook…')
        
        try:
            context_url = f"{base_url}/api/chat/context"
            context_config = {
                'include_sources': True,
                'include_notes': True,
            }
            context_payload = {'notebook_id': notebook_id, 'context_config': context_config}
            yield _sse('log', json.dumps({'step': 'context:build', 'url': context_url}))
            
            resp = requests.post(context_url, json=context_payload, timeout=60)
            yield _sse('log', json.dumps({'step': 'context:build', 'status': resp.status_code, 'size': len(resp.content)}))
            
            if resp.status_code != 200:
                yield _sse('token', json.dumps(f'(Failed to build context: {resp.status_code})'))
                yield _sse('log', json.dumps({'step': 'context:build', 'error': resp.text[:300]}))
                yield _sse('done', json.dumps({'warnings': [], 'citations': []}))
                return
            
            context = resp.json()
            yield _sse('log', json.dumps({'step': 'context:build', 'context_keys': list(context.keys()) if isinstance(context, dict) else 'not_dict'}))
        except Exception as e:
            yield _sse('token', json.dumps(f'(Error building context: {str(e)[:100]})'))
            yield _sse('log', json.dumps({'step': 'context:build', 'error': str(e)}))
            yield _sse('done', json.dumps({'warnings': [], 'citations': []}))
            return

        # Step 3: Execute the chat
        yield _sse('status', 'Asking AI (this may take a while)…')
        
        try:
            execute_url = f"{base_url}/api/chat/execute"
            model_id = _pick_language_model(node.ip_address)
            execute_payload = {
                'session_id': chat_session_id,
                'message': question,
                'context': context,
            }
            if model_id:
                execute_payload['model_override'] = model_id
            
            yield _sse('log', json.dumps({'step': 'chat:execute', 'url': execute_url, 'model': model_id, 'context_size': len(json.dumps(context))}))
            
            resp = requests.post(execute_url, json=execute_payload, timeout=600)
            yield _sse('log', json.dumps({'step': 'chat:execute', 'status': resp.status_code, 'size': len(resp.content)}))
            
            if resp.status_code != 200:
                yield _sse('token', json.dumps(f'(Chat failed: {resp.status_code})'))
                yield _sse('log', json.dumps({'step': 'chat:execute', 'error': resp.text[:500]}))
                yield _sse('done', json.dumps({'warnings': [], 'citations': []}))
                return
            
            result = resp.json()
            yield _sse('log', json.dumps({'step': 'chat:execute', 'result_keys': list(result.keys()) if isinstance(result, dict) else 'not_dict'}))
            
            # Extract the AI's response from messages (type='ai' not role='assistant')
            messages_list = result.get('messages', [])
            yield _sse('log', json.dumps({'step': 'chat:execute', 'messages': [{'type': m.get('type'), 'content_len': len(m.get('content',''))} for m in messages_list]}))
            
            answer = ''
            for msg in reversed(messages_list):
                if msg.get('type') == 'ai':
                    answer = msg.get('content', '')
                    break
            
            if not answer:
                yield _sse('token', json.dumps('(No response from AI)'))
                yield _sse('log', json.dumps({'step': 'chat:execute', 'error': 'no ai message', 'messages_count': len(messages_list), 'types': [m.get('type') for m in messages_list]}))
                yield _sse('done', json.dumps({'warnings': [], 'citations': []}))
                return
            
            yield _sse('log', json.dumps({'step': 'answer', 'length': len(answer)}))
            
            # Extract source references from answer
            source_refs = _extract_source_refs(answer)
            yield _sse('log', json.dumps({'step': 'sources:extract', 'refs': source_refs}))
            
            # Build citations with links to Open-Notebook UI
            citations = []
            for ref in source_refs:
                ref_type = ref['type']
                ref_id = ref['id']
                # Build URL to the source/note/insight in Open-Notebook
                if ref_type == 'source':
                    url = f"{ui_base}/notebooks/{quote(str(notebook_id), safe='')}?" + urlencode({'modal': 'source', 'id': ref_id})
                elif ref_type == 'note':
                    url = f"{ui_base}/notebooks/{quote(str(notebook_id), safe='')}?" + urlencode({'modal': 'note', 'id': ref_id})
                else:  # insight
                    url = f"{ui_base}/notebooks/{quote(str(notebook_id), safe='')}?" + urlencode({'modal': 'insight', 'id': ref_id})
                
                citations.append({
                    'type': ref_type,
                    'id': ref_id,
                    'title': f"[{ref_type}:{ref_id}]",
                    'url': url,
                })
            
            # Stream the answer in chunks
            for chunk in [answer[i:i+50] for i in range(0, len(answer), 50)]:
                yield _sse('token', json.dumps(chunk))
            
            # Save to history
            history = session.get('search_messages', [])
            history.append({'role': 'user', 'content': question})
            history.append({'role': 'assistant', 'content': answer})
            session['search_messages'] = history[-20:]
            
            # Send citations with the done event
            yield _sse('done', json.dumps({'warnings': [], 'citations': citations}))
            
        except requests.exceptions.Timeout:
            yield _sse('token', json.dumps('(Request timed out - the AI is taking too long)'))
            yield _sse('log', json.dumps({'step': 'chat:execute', 'error': 'timeout after 600s'}))
            yield _sse('done', json.dumps({'warnings': [], 'citations': []}))
            return
        except Exception as e:
            yield _sse('token', json.dumps(f'(Error: {str(e)[:100]})'))
            yield _sse('log', json.dumps({'step': 'chat:execute', 'error': str(e)}))
            yield _sse('done', json.dumps({'warnings': [], 'citations': []}))
            return

    return Response(stream_with_context(generate()), mimetype='text/event-stream')
