"""Vercel Serverless Function entry point for AgriLink AI."""
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlencode

# Add project root directory to sys.path so modules are discoverable in serverless execution
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app import app


class VercelPathMiddleware:
    """WSGI Middleware for Vercel deployment of AgriLink AI.

    Ensures Flask receives the correct PATH_INFO and SCRIPT_NAME
    when requests are routed via Vercel serverless rewrites.
    """

    def __init__(self, wsgi_app):
        self.wsgi_app = wsgi_app

    def __call__(self, environ, start_response):
        query_string = environ.get("QUERY_STRING", "")
        path_info = environ.get("PATH_INFO", "")

        # 1. Prefer original path captured via rewrite query parameter
        if "__vercel_path__=" in query_string:
            params = parse_qs(query_string, keep_blank_values=True)
            if "__vercel_path__" in params:
                real_paths = params.pop("__vercel_path__")
                if real_paths and real_paths[0]:
                    raw_path = real_paths[0]
                    if not raw_path.startswith("/"):
                        raw_path = "/" + raw_path
                    path_info = raw_path
                environ["QUERY_STRING"] = urlencode(params, doseq=True)

        # 2. Check headers that Vercel or edge proxies might pass
        elif environ.get("HTTP_X_MATCHED_PATH") and not environ["HTTP_X_MATCHED_PATH"].startswith("/api/index"):
            path_info = environ["HTTP_X_MATCHED_PATH"].split("?")[0]
        elif environ.get("HTTP_X_FORWARDED_URI"):
            path_info = environ["HTTP_X_FORWARDED_URI"].split("?")[0]
        elif environ.get("HTTP_X_ORIGINAL_URL"):
            path_info = environ["HTTP_X_ORIGINAL_URL"].split("?")[0]

        # 3. If path_info still has /api/index prefix (e.g. legacy rewrite or direct function call), strip it
        if path_info.startswith("/api/index.py"):
            path_info = path_info[len("/api/index.py"):] or "/"
        elif path_info.startswith("/api/index"):
            path_info = path_info[len("/api/index"):] or "/"

        # 4. Normalize path_info: ensure leading slash and collapse double slashes
        if not path_info or not path_info.startswith("/"):
            path_info = "/" + (path_info or "")
        while path_info.startswith("//"):
            path_info = path_info[1:]

        environ["PATH_INFO"] = path_info
        environ["SCRIPT_NAME"] = ""

        return self.wsgi_app(environ, start_response)


# Wrap Flask application with VercelPathMiddleware for serverless invocation
app.wsgi_app = VercelPathMiddleware(app.wsgi_app)
