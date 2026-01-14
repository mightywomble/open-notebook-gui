from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from functools import wraps
from core.models import Node
from core.constants import WORKFLOW_NOTEBOOKS
from core.api_client import OpenNotebookAPI
import datetime
import requests
import time
import yaml
import re

bp = Blueprint('kb', __name__, template_folder='templates', url_prefix='/kb')


def _is_htmx_request():
    return (request.headers.get('HX-Request') or '').lower() == 'true'


def reviewer_required(f):
    @wraps(f)
    @login_required
    def decorated_function(*args, **kwargs):
        if not getattr(current_user, 'is_reviewer', lambda: False)():
            flash('You are not authorized to perform this action.', 'danger')
            return redirect(url_for('dashboard.index'))
        return f(*args, **kwargs)

    return decorated_function


def _ui_base_for_node(node: Node) -> str:
    ui_base = node.ui_host if node.ui_host else f"{node.ip_address}:8502"
    if not ui_base.startswith('http'):
        ui_base = f"http://{ui_base}"
    return ui_base


def _ensure_workflow_notebooks(ip: str):
    required = list(WORKFLOW_NOTEBOOKS.values())

    notebooks = OpenNotebookAPI.get_notebooks(ip)
    name_to_id = {nb.get('name'): nb.get('id') for nb in notebooks if nb.get('name') and nb.get('id')}

    created_any = False
    for nb_name in required:
        if nb_name not in name_to_id:
            ok = OpenNotebookAPI.create_notebook(ip, nb_name)
            created_any = created_any or ok

    if created_any:
        notebooks = OpenNotebookAPI.get_notebooks(ip)
        name_to_id = {nb.get('name'): nb.get('id') for nb in notebooks if nb.get('name') and nb.get('id')}

    id_to_name = {v: k for k, v in name_to_id.items()}
    return notebooks, name_to_id, id_to_name


def _fetch_sources(node: Node, notebook_id: str, search_query: str, filter_type: str):
    items = []
    if not notebook_id:
        print(f"[!] _fetch_sources: notebook_id is empty")
        return items

    try:
        url = f"http://{node.ip_address}:5055/api/sources?notebook_id={notebook_id}"
        print(f"[*] _fetch_sources: fetching from {url}")
        resp = requests.get(url, timeout=30)
        print(f"[*] _fetch_sources: status {resp.status_code}")
        all_sources = resp.json()
        print(f"[*] _fetch_sources: got {len(all_sources)} sources")

        for s in all_sources:
            title = s.get('title', '') or ''
            asset = s.get('asset')
            url_val = asset.get('url', '') if asset else ''

            is_article = title.endswith('.yaml')
            is_yt = "youtube.com" in url_val or "youtu.be" in url_val
            is_link = bool(url_val) and not is_article

            if search_query and search_query not in title.lower():
                continue
            if filter_type == 'articles' and not is_article:
                continue
            if filter_type == 'links' and not is_link:
                continue
            if filter_type == 'youtube' and not is_yt:
                continue

            s['is_article'] = is_article
            s['is_yt'] = is_yt
            s['display_url'] = url_val
            items.append(s)

    except Exception as e:
        print(f"[!] API Fetch Error for {notebook_id}: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()

    return items


def _inject_unapproved_notes_into_yaml(yaml_text: str, reviewer_email: str, notes: str) -> str:
    ts = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
    notes_block = {
        'type': 'Peer Review Notes',
        'content': f"```\nUNAPPROVED {ts} by {reviewer_email}\n\n{notes}\n```",
    }

    data = yaml.safe_load(yaml_text) or {}
    article = data.setdefault('article', {})
    guide_blocks = article.setdefault('guide_blocks', [])

    if not isinstance(guide_blocks, list):
        guide_blocks = []
        article['guide_blocks'] = guide_blocks

    guide_blocks.insert(0, notes_block)
    return yaml.dump(data, sort_keys=False)


def _move_source(node: Node, source_id: str, dest_notebook_id: str, *, unapprove_notes: str | None = None):
    """Move a source by cloning it into destination notebook then deleting the original."""
    src = OpenNotebookAPI.get_source(node.ip_address, source_id)
    if not src:
        return False, 'Source not found'

    title = src.get('title') or ''
    src_notebook_id = src.get('notebook_id')
    asset = src.get('asset') or {}
    url_val = asset.get('url') or ''

    is_article = title.endswith('.yaml')
    is_link = bool(url_val) and not is_article

    ok = False

    if is_link:
        ok = OpenNotebookAPI.create_link_source(node.ip_address, dest_notebook_id, title, url_val)
        if ok and unapprove_notes:
            ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
            notes_title = f"UNAPPROVED_NOTES_{ts}_{re.sub(r'[^a-zA-Z0-9]', '_', title)[:40]}.txt"
            body = f"UNAPPROVED by {current_user.email} at {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n{unapprove_notes}\n\nLink: {url_val}\n"
            OpenNotebookAPI.create_text_source(node.ip_address, dest_notebook_id, notes_title, body, async_processing=False)

    else:
        # For text sources, Open Notebook returns the content in the source object as full_text.
        # The /download endpoint may return 404 for these sources.
        text = src.get('full_text') or ''

        if not text:
            raw = OpenNotebookAPI.download_source(node.ip_address, source_id)
            if raw is None:
                return False, 'Failed to fetch source content'
            text = raw.decode('utf-8', errors='replace')

        if unapprove_notes and is_article:
            try:
                text = _inject_unapproved_notes_into_yaml(text, current_user.email, unapprove_notes)
            except Exception:
                # Fallback: prepend notes as code block
                text = f"```\nUNAPPROVED by {current_user.email} at {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n{unapprove_notes}\n```\n\n" + text

        ok = OpenNotebookAPI.create_text_source(node.ip_address, dest_notebook_id, title, text)

    if not ok:
        return False, 'Failed to create source in destination notebook'

    # Delete original
    if not OpenNotebookAPI.delete_source(node.ip_address, source_id):
        return False, 'Moved, but failed to delete original source'

    return True, 'Moved'


@bp.route('/create', methods=['GET', 'POST'])
@login_required
def create_article():
    if request.method == 'POST':
        summary = request.form.get('summary', '').strip()

        kb_data = {
            "metadata": {
                "summary": summary,
                "category": request.form.get('category'),
                "author": request.form.get('author'),
                "status": request.form.get('status'),
                "date_created": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
            },
            "article": {
                "purpose": request.form.get('purpose'),
                "prerequisites": [p for p in request.form.getlist('prereqs[]') if p.strip()],
                "guide_blocks": [],
            },
        }

        types = request.form.getlist('block_type[]')
        values = request.form.getlist('block_value[]')
        for t, v in zip(types, values):
            if v.strip():
                kb_data["article"]["guide_blocks"].append({"type": t, "content": v})

        node = Node.query.first()
        if not node:
            return "No node registered", 400

        notebooks, name_to_id, _ = _ensure_workflow_notebooks(node.ip_address)
        target_notebook_id = name_to_id.get(WORKFLOW_NOTEBOOKS['new'])

        if not target_notebook_id:
            return "Notebook 'service_kb_new' not found. Please create it first.", 400

        filename = f"KB_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"
        success = OpenNotebookAPI.save_kb_content(
            node.ip_address,
            target_notebook_id,
            summary,
            kb_data,
        )
        if success:
            print(f"[*] KB Article {filename} saved successfully.")
            return redirect(url_for('kb.archive'))

        return "Failed to save to Open-Notebook API", 500

    return render_template('kb/form.html')


@bp.route('/archive')
@login_required
def archive():
    node = Node.query.first()
    if not node:
        return "No node registered", 400

    ui_base = _ui_base_for_node(node)

    _, name_to_id, _ = _ensure_workflow_notebooks(node.ip_address)
    target_nb_id = name_to_id.get(WORKFLOW_NOTEBOOKS['new'])

    if not target_nb_id:
        return render_template('kb/archive.html', articles=[], node=node, error="KB Notebook not found")

    try:
        url = f"http://{node.ip_address}:5055/api/sources?notebook_id={target_nb_id}"
        response = requests.get(url, timeout=5)
        all_sources = response.json()

        articles = [s for s in all_sources if (s.get('title', '') or '').endswith('.yaml')]

        return render_template(
            'kb/archive.html',
            articles=articles,
            node=node,
            ui_base=ui_base,
            raw_nb_id=target_nb_id,
        )
    except Exception as e:
        return render_template('kb/archive.html', articles=[], node=node, error=str(e))


@bp.route('/delete/<string:source_id>', methods=['DELETE'])
@login_required
def delete_kb_source(source_id):
    """Delete a specific source from the node.

    Policy:
    - Allow delete for items in service_kb_new to any authenticated user.
    - Require reviewer for deletes in peerreview/internal/customer/unapproved buckets.
    """
    node = Node.query.first()
    if not node:
        return 'No node configured', 400

    src = OpenNotebookAPI.get_source(node.ip_address, source_id)
    if not src:
        return 'Not found', 404

    # Open Notebook v0.2.x uses a list of notebook IDs in 'notebooks'
    src_nb_ids = set(src.get('notebooks') or [])
    legacy_nb_id = src.get('notebook_id')
    if legacy_nb_id:
        src_nb_ids.add(legacy_nb_id)

    _, name_to_id, _ = _ensure_workflow_notebooks(node.ip_address)
    protected_ids = {
        name_to_id.get(WORKFLOW_NOTEBOOKS['peerreview']),
        name_to_id.get(WORKFLOW_NOTEBOOKS['internal']),
        name_to_id.get(WORKFLOW_NOTEBOOKS['customer']),
        name_to_id.get(WORKFLOW_NOTEBOOKS['unapproved']),
    }
    protected_ids.discard(None)

    if (src_nb_ids & protected_ids) and not getattr(current_user, 'is_reviewer', lambda: False)():
        return 'Forbidden', 403

    if OpenNotebookAPI.delete_source(node.ip_address, source_id):
        return '', 200

    return 'Delete Failed', 500


@bp.route('/list')
@login_required
def list_articles():
    """All Knowledge view.

    Aggregates sources across workflow notebooks. Reviewers see internal/customer/unapproved too.
    """
    node = Node.query.first()
    if not node:
        return "No node configured", 400

    _, name_to_id, _ = _ensure_workflow_notebooks(node.ip_address)
    ui_base = _ui_base_for_node(node)

    # Filters
    search_query = request.args.get('search', '').lower()
    filter_type = request.args.get('filter', 'all')
    location_filter = request.args.get('location', 'all')
    older_than_days = request.args.get('older_than_days', '').strip()

    try:
        older_than_days_int = int(older_than_days) if older_than_days else None
    except ValueError:
        older_than_days_int = None

    def parse_dt(val: str | None):
        if not val:
            return None
        try:
            return datetime.datetime.fromisoformat(val)
        except Exception:
            pass
        try:
            return datetime.datetime.strptime(val, '%Y-%m-%d %H:%M')
        except Exception:
            return None

    def extract_article_meta(source_id: str):
        src = OpenNotebookAPI.get_source(node.ip_address, source_id)
        if not src:
            return None, None
        ft = src.get('full_text') or ''
        if not ft:
            return None, None
        try:
            data = yaml.safe_load(ft) or {}
            md = data.get('metadata') or {}
            author = md.get('author')
            date_created = md.get('date_created')
            return author, date_created
        except Exception:
            return None, None

    bucket_keys = ['new', 'peerreview']
    if current_user.is_reviewer():
        bucket_keys += ['internal', 'customer', 'unapproved']

    allowed_locations = {WORKFLOW_NOTEBOOKS[k] for k in bucket_keys}

    all_items = []
    for k in bucket_keys:
        nb_name = WORKFLOW_NOTEBOOKS[k]
        nb_id = name_to_id.get(nb_name)
        if not nb_id:
            continue

        try:
            url = f"http://{node.ip_address}:5055/api/sources?notebook_id={nb_id}"
            resp = requests.get(url, timeout=30)
            sources = resp.json()
        except Exception:
            sources = []

        for s in sources:
            title = (s.get('title') or '')
            asset = s.get('asset') or {}
            url_val = asset.get('url', '') or ''

            is_article = title.endswith('.yaml')
            is_yt = 'youtube.com' in url_val or 'youtu.be' in url_val
            is_link = bool(url_val) and not is_article

            if search_query and search_query not in title.lower():
                continue
            if filter_type == 'articles' and not is_article:
                continue
            if filter_type == 'links' and not is_link:
                continue
            if filter_type == 'youtube' and not is_yt:
                continue

            if location_filter != 'all' and nb_name != location_filter:
                continue

            created_raw = s.get('created')
            created_dt = parse_dt(created_raw)

            created_by = None
            yaml_date_created = None
            if is_article:
                created_by, yaml_date_created = extract_article_meta(s.get('id'))
                md_dt = parse_dt(yaml_date_created)
                if md_dt:
                    created_dt = md_dt
                    created_raw = yaml_date_created

            if older_than_days_int is not None and created_dt is not None:
                cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=older_than_days_int)
                if created_dt.tzinfo is None:
                    created_dt = created_dt.replace(tzinfo=datetime.timezone.utc)
                if created_dt > cutoff:
                    continue

            s['is_article'] = is_article
            s['is_yt'] = is_yt
            s['display_url'] = url_val
            s['location'] = nb_name
            s['notebook_id'] = nb_id
            s['location_key'] = k
            s['created_by'] = created_by
            if created_dt:
                if created_dt.tzinfo is None:
                    created_dt = created_dt.replace(tzinfo=datetime.timezone.utc)
                s['created_display'] = created_dt.astimezone(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M')
            else:
                s['created_display'] = created_raw or ''

            all_items.append(s)

    def sort_key(s):
        dt = parse_dt(s.get('created'))
        if dt is None:
            dt = parse_dt(s.get('created_display'))
        if dt is None:
            return datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return dt

    all_items.sort(key=sort_key, reverse=True)

    locations = sorted(allowed_locations)

    return render_template(
        'kb/all_knowledge.html',
        items=all_items,
        ui_base=ui_base,
        search_query=search_query,
        filter_type=filter_type,
        location_filter=location_filter,
        older_than_days=older_than_days,
        locations=locations,
    )


@bp.route('/new')
@login_required
def new_articles():
    return _render_bucket('new', 'New Articles', 'Newly created items awaiting peer review submission')


def _render_bucket(bucket_key: str, title: str, description: str):
    node = Node.query.first()
    if not node:
        return "No node configured", 400

    notebooks, name_to_id, id_to_name = _ensure_workflow_notebooks(node.ip_address)
    ui_base = _ui_base_for_node(node)

    nb_name = WORKFLOW_NOTEBOOKS[bucket_key]
    nb_id = name_to_id.get(nb_name)

    if not nb_id:
        return f"Notebook '{nb_name}' not found.", 400

    search_query = request.args.get('search', '').lower()
    filter_type = request.args.get('filter', 'all')

    items = _fetch_sources(node, nb_id, search_query, filter_type)

    return render_template(
        'kb/list_articles.html',
        page_title=title,
        page_description=description,
        hide_selector=True,
        notebooks=notebooks,
        items=items,
        selected_nb_id=nb_id,
        selected_nb_name=nb_name,
        search_query=search_query,
        filter_type=filter_type,
        ui_base=ui_base,
        node=node,
    )


@bp.route('/peer-review')
@login_required
def peer_review():
    return _render_bucket('peerreview', 'Peer Review', 'Items awaiting peer review approval')


@bp.route('/internal')
@reviewer_required
def internal_list():
    return _render_bucket('internal', 'Internal KB', 'Approved internal knowledge base content')


@bp.route('/customer')
@reviewer_required
def customer_list():
    return _render_bucket('customer', 'Customer KB', 'Customer-ready knowledge base content')


@bp.route('/unapproved')
@reviewer_required
def unapproved_list():
    return _render_bucket('unapproved', 'Unapproved', 'Items rejected during peer review')


@bp.route('/action/peer-review/<string:source_id>', methods=['POST'])
@login_required
def action_peer_review(source_id):
    node = Node.query.first()
    if not node:
        return 'No node configured', 400

    _, name_to_id, _ = _ensure_workflow_notebooks(node.ip_address)
    dest_id = name_to_id.get(WORKFLOW_NOTEBOOKS['peerreview'])

    if not dest_id:
        msg = 'Destination notebook not found'
        flash(msg, 'danger')
        return (msg, 500) if _is_htmx_request() else redirect(url_for('kb.list_articles'))


    ok, msg = _move_source(node, source_id, dest_id)
    if not ok:
        flash(msg, 'danger')
        return (msg, 500) if _is_htmx_request() else redirect(url_for('kb.list_articles'))

    if _is_htmx_request():
        return '', 200

    flash('Moved to Peer Review.', 'success')
    return redirect(url_for('kb.list_articles'))


@bp.route('/action/approve/<string:source_id>', methods=['POST'])
@reviewer_required
def action_approve(source_id):
    node = Node.query.first()
    if not node:
        return 'No node configured', 400

    _, name_to_id, _ = _ensure_workflow_notebooks(node.ip_address)
    dest_id = name_to_id.get(WORKFLOW_NOTEBOOKS['internal'])

    ok, msg = _move_source(node, source_id, dest_id)
    if not ok:
        flash(msg, 'danger')
        return (msg, 500) if _is_htmx_request() else redirect(url_for('kb.peer_review'))

    if _is_htmx_request():
        return '', 200

    flash('Approved and moved to Internal.', 'success')
    return redirect(url_for('kb.peer_review'))


@bp.route('/action/customer-ready/<string:source_id>', methods=['POST'])
@reviewer_required
def action_customer_ready(source_id):
    node = Node.query.first()
    if not node:
        return 'No node configured', 400

    _, name_to_id, _ = _ensure_workflow_notebooks(node.ip_address)
    dest_id = name_to_id.get(WORKFLOW_NOTEBOOKS['customer'])

    ok, msg = _move_source(node, source_id, dest_id)
    if not ok:
        flash(msg, 'danger')
        return (msg, 500) if _is_htmx_request() else redirect(url_for('kb.internal_list'))

    if _is_htmx_request():
        return '', 200

    flash('Moved to Customer KB.', 'success')
    return redirect(url_for('kb.internal_list'))


@bp.route('/action/internal/<string:source_id>', methods=['POST'])
@reviewer_required
def action_back_to_internal(source_id):
    node = Node.query.first()
    if not node:
        return 'No node configured', 400

    _, name_to_id, _ = _ensure_workflow_notebooks(node.ip_address)
    dest_id = name_to_id.get(WORKFLOW_NOTEBOOKS['internal'])

    ok, msg = _move_source(node, source_id, dest_id)
    if not ok:
        flash(msg, 'danger')
        return (msg, 500) if _is_htmx_request() else redirect(url_for('kb.customer_list'))

    if _is_htmx_request():
        return '', 200

    flash('Moved back to Internal.', 'success')
    return redirect(url_for('kb.customer_list'))


@bp.route('/unapprove/<string:source_id>', methods=['GET', 'POST'])
@reviewer_required
def unapprove(source_id):
    node = Node.query.first()
    if not node:
        return 'No node configured', 400

    src = OpenNotebookAPI.get_source(node.ip_address, source_id)
    if not src:
        return 'Not found', 404

    ui_base = _ui_base_for_node(node)

    _, name_to_id, _ = _ensure_workflow_notebooks(node.ip_address)
    dest_id = name_to_id.get(WORKFLOW_NOTEBOOKS['unapproved'])

    if not dest_id:
        flash('Destination notebook not found', 'danger')
        return redirect(url_for('kb.peer_review'))


    if request.method == 'POST':
        notes = (request.form.get('notes') or '').strip()
        if not notes:
            flash('Please provide notes for why this was unapproved.', 'danger')
            return redirect(url_for('kb.unapprove', source_id=source_id))

        ok, msg = _move_source(node, source_id, dest_id, unapprove_notes=notes)
        if not ok:
            flash(msg, 'danger')
            return redirect(url_for('kb.peer_review'))

        flash('Marked Unapproved and moved to Unapproved.', 'warning')
        return redirect(url_for('kb.peer_review'))

    return render_template('kb/unapprove.html', source=src, source_id=source_id, ui_base=ui_base)


@bp.route('/manage-notebooks/<int:node_id>')
@login_required
def manage_notebooks(node_id):
    node = Node.query.get_or_404(node_id)
    notebooks = OpenNotebookAPI.get_notebooks(node.ip_address)
    return render_template('kb/manage_notebooks.html', node=node, notebooks=notebooks)


@bp.route('/notebook/create/<int:node_id>', methods=['POST'])
@login_required
def create_notebook(node_id):
    node = Node.query.get_or_404(node_id)
    name = request.form.get('notebook_name')
    requests.post(f"http://{node.ip_address}:5055/api/notebooks", json={"name": name})
    return redirect(url_for('kb.manage_notebooks', node_id=node.id))


@bp.route('/notebook/delete/<int:node_id>/<string:nb_id>', methods=['DELETE'])
@login_required
def delete_notebook(node_id, nb_id):
    node = Node.query.get_or_404(node_id)
    requests.delete(f"http://{node.ip_address}:5055/api/notebooks/{nb_id}")
    return '', 200


@bp.route('/add-link', methods=['GET', 'POST'])
@login_required
def add_link():
    node = Node.query.first()
    if not node:
        return "No node configured", 400

    if request.method == 'POST':
        title = request.form.get('title')
        url_val = request.form.get('url')

        _, name_to_id, _ = _ensure_workflow_notebooks(node.ip_address)
        target_id = name_to_id.get(WORKFLOW_NOTEBOOKS['new'])

        if target_id and OpenNotebookAPI.save_link(node.ip_address, target_id, title, url_val):
            return redirect(url_for('kb.list_links'))

    return render_template('kb/link_form.html')


@bp.route('/links')
@login_required
def list_links():
    node = Node.query.first()
    if not node:
        return "No node configured", 400

    if request.referrer and 'add-link' in request.referrer:
        time.sleep(2)

    _, name_to_id, _ = _ensure_workflow_notebooks(node.ip_address)
    target_id = name_to_id.get(WORKFLOW_NOTEBOOKS['new'])

    links = []
    filter_type = request.args.get('filter', 'all')
    search_query = request.args.get('search', '').lower()

    if target_id:
        url = f"http://{node.ip_address}:5055/api/sources?notebook_id={target_id}"
        resp = requests.get(url)
        all_sources = resp.json()

        for s in all_sources:
            asset = s.get('asset')
            actual_url = asset.get('url', '') if asset else ''
            title = s.get('title', '')

            if not actual_url or title.endswith('.yaml'):
                continue

            is_yt = "youtube.com" in actual_url or "youtu.be" in actual_url

            if search_query and search_query not in title.lower():
                continue

            if filter_type == 'youtube' and not is_yt:
                continue
            if filter_type == 'other' and is_yt:
                continue

            links.append(s)

    return render_template(
        'kb/link_list.html',
        links=links,
        node=node,
        filter_type=filter_type,
        search_query=search_query,
    )
