import os
import uuid

from flask import Blueprint, render_template, request, redirect, url_for, flash, abort, current_app
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename

from core.models import db, CompanyConfig

bp = Blueprint('setup', __name__, template_folder='templates')

ALLOWED_ICON_EXTENSIONS = {'png', 'jpg', 'jpeg', 'svg', 'webp', 'gif'}


def _get_company_cfg() -> CompanyConfig:
    cfg = CompanyConfig.query.first()
    if not cfg:
        cfg = CompanyConfig(company_name='Cudo', icon_path=None)
        db.session.add(cfg)
        db.session.commit()
    return cfg


def _save_company_icon(file_storage, previous_icon_path: str | None) -> str:
    if not file_storage or not getattr(file_storage, 'filename', None):
        return previous_icon_path

    filename = secure_filename(file_storage.filename)
    if '.' not in filename:
        raise ValueError('Icon must have a file extension.')

    ext = filename.rsplit('.', 1)[1].lower()
    if ext not in ALLOWED_ICON_EXTENSIONS:
        raise ValueError('Icon must be one of: ' + ', '.join(sorted(ALLOWED_ICON_EXTENSIONS)))

    rel_dir = 'uploads/company'
    abs_dir = os.path.join(current_app.static_folder, rel_dir)
    os.makedirs(abs_dir, exist_ok=True)

    new_name = f"{uuid.uuid4().hex}.{ext}"
    abs_path = os.path.join(abs_dir, new_name)
    file_storage.save(abs_path)

    # Best-effort cleanup of previous icon if it was in our uploads folder
    if previous_icon_path and previous_icon_path.startswith(rel_dir + '/'):
        try:
            old_abs = os.path.join(current_app.static_folder, previous_icon_path)
            if os.path.exists(old_abs):
                os.remove(old_abs)
        except Exception:
            pass

    return f"{rel_dir}/{new_name}"


@bp.route('/setup', methods=['GET', 'POST'])
@login_required
def company_setup():
    if not current_user.is_admin():
        abort(403)

    cfg = _get_company_cfg()

    if request.method == 'POST':
        name = (request.form.get('company_name') or '').strip()
        if not name:
            flash('Company name is required.', 'danger')
            return redirect(url_for('setup.company_setup'))

        try:
            icon_file = request.files.get('company_icon')
            cfg.icon_path = _save_company_icon(icon_file, cfg.icon_path)
        except ValueError as e:
            flash(str(e), 'danger')
            return redirect(url_for('setup.company_setup'))

        cfg.company_name = name
        db.session.add(cfg)
        db.session.commit()

        flash('Company branding updated.', 'success')
        return redirect(url_for('setup.company_setup'))

    return render_template('setup/company_setup.html', cfg=cfg)
