"""Command line entry point.

  python -m pipeline.run fetch [--only fara,lda,sec117]
  python -m pipeline.run clean
  python -m pipeline.run fees [--country QA]
  python -m pipeline.run site
  python -m pipeline.run check-links [--limit N] [--max-minutes M]
"""
import argparse
import sys

from . import (build_dataset, build_site, check_links, extract_fara_fees,
               fetch_fara, fetch_lda, fetch_sec117)

FETCHERS = {"fara": fetch_fara, "lda": fetch_lda, "sec117": fetch_sec117}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch")
    f.add_argument("--only", default="fara,lda,sec117")
    sub.add_parser("clean")
    sub.add_parser("site")
    f2 = sub.add_parser("fees")
    f2.add_argument("--country", default="QA")
    c = sub.add_parser("check-links")
    c.add_argument("--limit", type=int, default=None)
    c.add_argument("--max-minutes", type=float, default=None)
    args = ap.parse_args()

    if args.cmd == "fetch":
        failed = False
        for name in [n.strip() for n in args.only.split(",") if n.strip()]:
            entries = FETCHERS[name].run()
            failed |= any(e.get("status") == "error" for e in entries)
        return 1 if failed else 0
    if args.cmd == "clean":
        return build_dataset.run()
    if args.cmd == "fees":
        extract_fara_fees.run(args.country)
        return 0
    if args.cmd == "site":
        return build_site.run()
    if args.cmd == "check-links":
        return check_links.run(limit=args.limit, max_minutes=args.max_minutes)
    return 2


if __name__ == "__main__":
    sys.exit(main())
