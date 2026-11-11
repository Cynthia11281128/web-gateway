import argparse
import json
from pathlib import Path
import subprocess
import sys

from .config import Settings
from .publishing import Sites, private_write


def disable_login(settings):
    sites = Sites(settings)
    with sites.lock():
        private_write(settings.state_root / "access.json",
                      json.dumps({"require_password": False}, indent=2) + "\n")
        settings.auth_file.unlink(missing_ok=True)
        settings.auth_file.with_name("password.txt").unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    for kind in ("static", "service"):
        publish = commands.add_parser("publish-" + kind)
        publish.add_argument("id")
        publish.add_argument("--title")
        publish.add_argument("--replace", action="store_true")
        publish.add_argument("--offline", action="store_true")
        if kind == "static":
            publish.add_argument("--dir", type=Path, required=True)
            publish.add_argument("--spa", action="store_true")
        else:
            publish.add_argument("--upstream", required=True)
            publish.add_argument("--prefix-mode", choices=["strip", "preserve"], default="strip")
    commands.add_parser("list")
    disable = commands.add_parser("disable-login",
                                  help="Allow everyone who can reach the gateway")
    disable.add_argument("--confirm-public", action="store_true", required=True,
                         help="Confirm anonymous access to every registered site")
    url = commands.add_parser("url")
    url.add_argument("id")
    remove = commands.add_parser("unpublish")
    remove.add_argument("id")
    remove.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    try:
        sites = Sites(Settings.load(args.config))
        if args.command == "disable-login":
            disable_login(sites.settings)
            print("Password login disabled; all registered sites allow anonymous access.")
            print("Stored password files removed; Origin checks remain enabled.")
        elif args.command == "list":
            print(json.dumps([{**site, "url": sites.url(site["id"])}
                              for site in sites.read()], indent=2))
        elif args.command == "url":
            if not any(site["id"] == args.id for site in sites.read()):
                raise ValueError("Unknown site")
            print(sites.url(args.id))
        elif args.command == "unpublish":
            sites.unpublish(args.id, offline=args.offline)
            print("Unpublished " + args.id + "; source and backend unchanged")
        else:
            kind = args.command.removeprefix("publish-")
            site = {"id": args.id, "kind": kind, "title": args.title or args.id}
            if kind == "static":
                site.update(root=str(args.dir.resolve(strict=True)), spa=args.spa)
            else:
                site.update(upstream=args.upstream, prefix_mode=args.prefix_mode)
            print(sites.publish(site, replace=args.replace, offline=args.offline))
        return 0
    except subprocess.CalledProcessError as error:
        print(error.stderr or str(error), file=sys.stderr)
        return 1
    except (OSError, ValueError, KeyError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
