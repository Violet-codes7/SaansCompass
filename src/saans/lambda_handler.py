"""Web Lambda entry point: API Gateway HTTP API event -> Flask (WSGI)."""
import logging

from apig_wsgi import make_lambda_handler

from .web import create_app

logging.getLogger().setLevel(logging.INFO)

app = create_app()
handler = make_lambda_handler(app)
