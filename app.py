"""Start the Speech Annotation Tool.

    python app.py                 serve on HOST:PORT from .env (default 0.0.0.0:8000)
    python app.py --port 9000     override the port
    python app.py --dev           Flask debug server with auto reload
"""
import argparse
import logging

from sat import create_app
from sat.config import HOST, PORT


def main():
    parser = argparse.ArgumentParser(description="Speech Annotation Tool")
    parser.add_argument("--host", default=HOST)
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--dev", action="store_true", help="use the Flask debug server")
    parser.add_argument("--threads", type=int, default=16, help="waitress worker threads")
    args = parser.parse_args()

    app = create_app()
    log = logging.getLogger("sat")
    log.info("Speech Annotation Tool listening on http://%s:%s", args.host, args.port)
    if args.dev:
        app.run(host=args.host, port=args.port, debug=True, use_reloader=False, threaded=True)
        return
    from waitress import serve

    serve(app, host=args.host, port=args.port, threads=args.threads, channel_timeout=600, max_request_body_size=2 * 1024 * 1024 * 1024)


if __name__ == "__main__":
    main()
