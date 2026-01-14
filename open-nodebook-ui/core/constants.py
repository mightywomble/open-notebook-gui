"""Shared constants for notebook names and workflow mappings."""

# Canonical list of required service KB notebook names used across the app
SERVICE_KB_NOTEBOOK_NAMES = [
    'service_kb_new',
    'service_kb_peerreview',
    'service_kb_internal',
    'service_kb_customer',
    'service_kb_unapproved',
]

# Mapping used by KB workflow views (stage -> notebook name)
WORKFLOW_NOTEBOOKS = {
    'new': 'service_kb_new',
    'peerreview': 'service_kb_peerreview',
    'internal': 'service_kb_internal',
    'customer': 'service_kb_customer',
    'unapproved': 'service_kb_unapproved',
}
