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


def _get_notebook_sources(base_url: str, notebook_id: str):
    """Fetch all sources in a notebook."""
    try:
        # Note: Don't URL-encode - the API expects raw notebook_id parameter
        # Try with a large limit to get all sources
        url = f"{base_url}/api/sources?notebook_id={notebook_id}"
        r = requests.get(url, timeout=30)
        if r.status_code == 200:
            data = r.json() or []
            current_app.logger.warning(f"[SOURCES] Fetched {len(data)} sources from {notebook_id} via {url}")
            return data
        else:
            current_app.logger.warning(f"[SOURCES] API returned status {r.status_code} for {notebook_id}")
    except requests.exceptions.Timeout:
        current_app.logger.warning(f"[SOURCES] Timeout fetching {notebook_id}")
    except Exception as e:
        current_app.logger.warning(f"[SOURCES] Error fetching {notebook_id}: {e}")
    return []


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

        # Step 2: Search for relevant sources using semantic search
        yield _sse('status', 'Searching for relevant sources…')
        
        relevant_sources = []
        try:
            search_url = f"{base_url}/api/search"
            search_payload = {
                'query': question,
                'type': 'vector',  # Use vector/semantic search
                'limit': 20,  # Get top 20 relevant results
                'search_sources': True,
                'search_notes': False,
                'notebook_ids': [notebook_id]
            }
            sr = requests.post(search_url, json=search_payload, timeout=30)
            current_app.logger.warning(f"[SEARCH] API response status: {sr.status_code}")
            if sr.status_code == 200:
                search_json = sr.json() or {}
                current_app.logger.warning(f"[SEARCH] Response keys: {search_json.keys()}")
                search_results = search_json.get('results') or []
                current_app.logger.warning(f"[SEARCH] Found {len(search_results)} raw results")
                if search_results:
                    current_app.logger.warning(f"[SEARCH] First result: {search_results[0]}")
                # Extract unique source IDs from search results
                relevant_sources = []
                seen_ids = set()
                for result in search_results:
                    src_id = result.get('source_id') or result.get('id')
                    if src_id and src_id not in seen_ids:
                        relevant_sources.append(result)
                        seen_ids.add(src_id)
                current_app.logger.warning(f"[SEARCH] Found {len(relevant_sources)} unique relevant sources for query: {question[:50]}")
            else:
                current_app.logger.warning(f"[SEARCH] Search API returned {sr.status_code}: {sr.text[:200]}")
        except Exception as e:
            current_app.logger.warning(f"[SEARCH] Error: {e}")
        
        # If search didn't work, fall back to fetching all sources
        if not relevant_sources:
            yield _sse('log', json.dumps({'step': 'sources:fetch', 'method': 'fallback', 'count': 0}))
            relevant_sources = _get_notebook_sources(base_url, notebook_id)
        
        yield _sse('log', json.dumps({'step': 'sources:fetch', 'count': len(relevant_sources)}))

        # Step 3: Build context from relevant sources
        yield _sse('status', 'Building context from relevant sources…')
        
        # Pass the search results directly to the AI
        context = {
            'sources': relevant_sources,
            'notebook_id': notebook_id,
        }
        current_app.logger.warning(f"[CONTEXT] Built context with {len(relevant_sources)} relevant sources")
        yield _sse('log', json.dumps({'step': 'context:build', 'source_count': len(context.get('sources', []))}))

        # Step 4: Execute the chat
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
            
            # Extract sources from context response
            yield _sse('status', 'Building source list…')
            
            citations = []
            
            # The context response has structure: {'context': {...}, 'token_count': X, 'char_count': Y}
            # where context is a dict with 'sources' and 'notes' keys
            context_dict = context.get('context', {}) if isinstance(context, dict) else {}
            current_app.logger.warning(f"[DEBUG] context_dict type: {type(context_dict)}, keys: {context_dict.keys() if isinstance(context_dict, dict) else 'N/A'}")
            
            # Extract source IDs from the sources array in context
            sources_in_context = context_dict.get('sources', []) if isinstance(context_dict, dict) else []
            current_app.logger.warning(f"[DEBUG] Sources in context: {len(sources_in_context)} - {sources_in_context[:3]}")
            
            # If context has sources, use those
            if sources_in_context:
                for src in sources_in_context[:20]:
                    if isinstance(src, dict):
                        source_id = src.get('id') or src.get('source_id')
                        title = src.get('title') or source_id or 'Unknown'
                    else:
                        source_id = str(src)
                        title = source_id
                    
                    if source_id:
                        url = f"{ui_base}/notebooks/{quote(str(notebook_id), safe='')}?" + urlencode({'modal': 'source', 'id': source_id})
                        citations.append({
                            'type': 'source',
                            'id': source_id,
                            'title': title,
                            'url': url,
                        })
            
            # Use relevant sources from search results
            if not citations and relevant_sources:
                current_app.logger.warning(f"[DEBUG] Using {len(relevant_sources)} relevant sources")
                for src in relevant_sources:
                    source_id = src.get('source_id') or src.get('id')
                    title = src.get('title') or src.get('name') or source_id
                    if source_id:
                        url = f"{ui_base}/notebooks/{quote(str(notebook_id), safe='')}?" + urlencode({'modal': 'source', 'id': source_id})
                        citations.append({
                            'type': 'source',
                            'id': source_id,
                            'title': title,
                            'url': url,
                        })
            
            current_app.logger.warning(f"[DEBUG] Final citations count: {len(citations)}")
            yield _sse('log', json.dumps({'step': 'sources:list', 'count': len(citations)}))
            
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
