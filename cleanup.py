"""Run one cleanup process alongside the web workers: python cleanup.py."""

import argparse
import logging
from threading import Event

from pymongo.errors import PyMongoError

from config import Config
from db import Store


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="Perform one pass and exit.")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    store = Store(Config.MONGO_URI, Config.MONGO_DB_NAME)
    try:
        store.ensure_indexes()
        while True:
            try:
                result = store.cleanup_expired()
                logging.info("Closed %s underfilled sessions; confirmed %s sessions.",
                             result["closed"], result["confirmed"])
            except PyMongoError as error:
                logging.error("Cleanup failed (%s); retrying next interval.", type(error).__name__)
                if args.once:
                    return 1
            if args.once:
                return 0
            Event().wait(Config.CLEANUP_INTERVAL_SECONDS)
    except KeyboardInterrupt:
        logging.info("Cleanup stopped.")
        return 0
    except PyMongoError as error:
        logging.error("Cannot initialize MongoDB (%s).", type(error).__name__)
        return 1
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
