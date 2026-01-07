import os


class Config:
    # Database Configuration
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or \
        'postgresql://david:Qw3rty123?@localhost/nodebook_db'

    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Security
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'vibecode-super-secret-key'

    OPEN_NOTEBOOK_API_PORT = 5055

    # Chatbot (Ollama)
    # Used by the UI homepage chatbot streaming endpoint.
    OLLAMA_API_BASE = os.environ.get('OLLAMA_API_BASE') or 'https://ollama.paedave.com'
    OLLAMA_MODEL = os.environ.get('OLLAMA_MODEL') or 'qwen2.5:14b'
