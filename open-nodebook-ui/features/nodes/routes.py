from flask import Blueprint, render_template, request, redirect, url_for, flash
from core.models import db, Node
from core.api_client import OpenNotebookAPI

bp = Blueprint('nodes', __name__, template_folder='templates', url_prefix='/nodes')

@bp.route('/add', methods=['GET', 'POST'])
def add_node():
    if request.method == 'POST':
        name = request.form.get('name')
        ip_address = request.form.get('ip_address')
        # Capture the new field from the form
        ui_host = request.form.get('ui_host') 
        description = request.form.get('description')

        new_node = Node(
            name=name, 
            ip_address=ip_address, 
            ui_host=ui_host, # Save it to the DB
            description=description
        )
        db.session.add(new_node)
        db.session.commit()
        
        flash(f"Node {name} added successfully!", "success")
        return redirect(url_for('dashboard.index'))
        
    return render_template('nodes/add.html')

@bp.route('/manage/<int:node_id>')
def manage_node(node_id):
    node = Node.query.get_or_404(node_id)
    notebooks = OpenNotebookAPI.get_notebooks(node.ip_address)
    return render_template('nodes/manage.html', node=node, notebooks=notebooks)

# ADDED THIS TO FIX THE BUILD ERROR
@bp.route('/manage/<int:node_id>/create', methods=['POST'])
def create_nb(node_id):
    node = Node.query.get_or_404(node_id)
    notebook_name = request.form.get('notebook_name')
    # Call API to create the file
    OpenNotebookAPI.create_notebook(node.ip_address, notebook_name)
    # Refresh the manage page
    return redirect(url_for('nodes.manage_node', node_id=node.id))

@bp.route('/manage/<int:node_id>/delete/<string:nb_id>', methods=['DELETE'])
def delete_nb(node_id, nb_id):
    node = Node.query.get_or_404(node_id)
    
    success = OpenNotebookAPI.delete_notebook(node.ip_address, nb_id)
    
    if success:
        # HTMX will remove the element from the DOM because we return an empty string
        return '', 200
    else:
        return "Delete failed", 500
    
@bp.route('/')
def list_nodes():
    nodes = Node.query.all()
    return render_template('nodes/list.html', nodes=nodes)

@bp.route('/delete/<int:node_id>', methods=['DELETE'])
def delete_node(node_id):
    node = Node.query.get_or_404(node_id)
    db.session.delete(node)
    db.session.commit()
    return '', 200 # HTMX will remove the row

@bp.route('/edit/<int:node_id>', methods=['GET', 'POST'])
def edit_node(node_id):
    node = Node.query.get_or_404(node_id)
    
    if request.method == 'POST':
        node.name = request.form.get('name')
        node.ip_address = request.form.get('ip_address')
        node.ui_host = request.form.get('ui_host')
        node.description = request.form.get('description')
        
        db.session.commit()
        flash(f"Node {node.name} updated successfully!", "success")
        return redirect(url_for('nodes.list_nodes'))
        
    return render_template('nodes/edit.html', node=node)