"""Command line interface for the Ink2MD service."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .config import load_config
from .processor import build_processor


def configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config.json"),
        help="Path to the JSON configuration file.",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single iteration instead of the continuous loop.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose (debug) logging output.",
    )
    parser.add_argument(
        "--headless-token",
        action="store_true",
        help=(
            "Force the Google Drive OAuth flow to run in console mode, prompting "
            "for the verification code or redirected URL even when a browser is available "
            "and delete any cached token so the run acquires a fresh refresh token."
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    configure_logging(args.verbose)
    config = load_config(args.config)
    processor = build_processor(
        config,
        force_console_oauth=args.headless_token,
        force_token_refresh=args.headless_token,
    )
    if args.once:
        processed = processor.run_once()
        logging.getLogger(__name__).info("Processed %s document(s)", processed)
        return 0
    processor.run_forever(config.poll_interval)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
