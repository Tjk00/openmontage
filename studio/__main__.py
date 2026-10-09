"""Run the studio: ``python -m studio`` (or ``python -m studio --port 8080``)."""
from __future__ import annotations

import argparse


def main() -> None:
    parser = argparse.ArgumentParser(description="OpenMontage AI Studio")
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--no-worker", action="store_true",
                        help="API only (run the worker in a separate process)")
    args = parser.parse_args()

    import uvicorn

    from studio.config import load_config

    cfg = load_config()
    if args.host:
        cfg.host = args.host
    if args.port:
        cfg.port = args.port

    from studio.api import create_app

    app = create_app(cfg)
    if args.no_worker:
        app.state.worker.stop()  # do not process jobs in this process

    uvicorn.run(app, host=cfg.host, port=cfg.port, log_level="info")


if __name__ == "__main__":
    main()
