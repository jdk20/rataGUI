"""CLI entry point for headless rataGUI operation.

Usage::

    rataGUI-headless config.json
    rataGUI-headless --config config.json --save-dir /data/output --multiprocess
"""

import argparse
import json
import signal
import logging

logger = logging.getLogger(__name__)


def main() -> None:
    """Parse CLI arguments, load configuration, and run headless pipelines.

    Supports graceful shutdown via SIGINT and SIGTERM.
    """
    parser = argparse.ArgumentParser(
        description="Run rataGUI pipelines in headless mode (no GUI)",
    )
    parser.add_argument(
        "config",
        nargs="?",
        default=None,
        help="Path to config JSON file (default: package launch_config.json)",
    )
    parser.add_argument(
        "--config",
        dest="config_flag",
        default=None,
        help="Alternate way to specify config file path",
    )
    parser.add_argument(
        "--save-dir",
        default=None,
        help="Override save directory from config",
    )
    parser.add_argument(
        "--multiprocess",
        action="store_true",
        default=False,
        help="Use multiprocess camera acquisition",
    )

    args = parser.parse_args()
    config_path = args.config or args.config_flag

    if config_path:
        with open(config_path) as f:
            config = json.load(f)
    else:
        from rataGUI import launch_config

        config = dict(launch_config)

    if not config:
        logger.error(
            "No config provided and launch_config.json is empty. "
            "Pass a config file: rataGUI-headless config.json"
        )
        return

    if args.save_dir:
        config["Save Directory"] = args.save_dir
    if args.multiprocess:
        config["multiprocess"] = True

    from rataGUI.headless.runner import PipelineRunner

    runner = PipelineRunner(config)

    def handle_signal(signum, frame):
        logger.info("Received signal %d, stopping pipelines...", signum)
        runner.stop()

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    logger.info("Starting rataGUI-headless")
    try:
        runner.start()
    except KeyboardInterrupt:
        runner.stop()

    logger.info("rataGUI-headless exited")


if __name__ == "__main__":
    main()
