"""
Re-check fighter images with the identity-anchored pipeline (image_pipeline.py).

Dry run by default: prints what would be added / replaced / flagged, changes nothing.

Usage:
    python scripts/fetch_boxer_images.py                 # dry run over the cached schedule
    python scripts/fetch_boxer_images.py --apply         # apply (same as the admin "Apply new rules")
    python scripts/fetch_boxer_images.py "Name One" ...  # only these fighters (sport: Boxing)
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

import image_pipeline as images  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('names', nargs='*')
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--sport', default='Boxing', choices=['Boxing', 'UFC'])
    args = ap.parse_args()

    fighters = [(n, args.sport) for n in args.names] or None
    images.run_job(apply=args.apply, fighters=fighters)
    job = images.read_job() or {}
    r = job.get('report', {})
    print(f"{job.get('mode')} — checked {job.get('total')}, skipped {job.get('skipped')}")
    for bucket in ('would_replace', 'would_add', 'unverified', 'none_found', 'errors'):
        print(f"\n{bucket}: {len(r.get(bucket, []))}")
        for row in r.get(bucket, []):
            print('  ', json.dumps(row, ensure_ascii=False))


if __name__ == '__main__':
    main()
