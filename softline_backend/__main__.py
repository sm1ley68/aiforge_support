import os

from .store import ChatStore


def main():
    ChatStore(os.environ["DATABASE_URL"]).initialize()


if __name__ == "__main__":
    main()
