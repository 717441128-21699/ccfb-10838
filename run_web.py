"""Development entry point: python run_web.py [--port 5000] [--workdir .]"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from submask.app import create_app


def main() -> None:
    parser = argparse.ArgumentParser(description="submask web")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--workdir", default=os.path.dirname(
        os.path.abspath(__file__)))
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()
    app = create_app(os.path.abspath(args.workdir))
    print(f"submask web: http://{args.host}:{args.port}")
    app.run(host=args.host, port=args.port, debug=False)


if __name__ == "__main__":
    main()
