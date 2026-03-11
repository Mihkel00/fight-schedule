"""
Bulk migrate local fighter images to Cloudflare R2

Usage:
    python migrate_to_r2.py              # Dry run (shows what would be uploaded)
    python migrate_to_r2.py --execute    # Actually upload and update JSON references

Requires R2 environment variables:
    R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_ACCOUNT_ID, R2_BUCKET_NAME
    Optionally: R2_PUBLIC_URL
"""

import os
import sys
import json
import argparse

# Resolve DATA_DIR the same way the app does
DATA_DIR = os.environ.get('DATA_DIR', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data'))


def data_path(filename):
    return os.path.join(DATA_DIR, filename)


def main():
    parser = argparse.ArgumentParser(description='Migrate local fighter images to Cloudflare R2')
    parser.add_argument('--execute', action='store_true', help='Actually perform the migration (default is dry run)')
    args = parser.parse_args()

    from r2_storage import upload_fighter_image, get_fighter_image_url, is_r2_enabled

    if not is_r2_enabled():
        print("ERROR: R2 is not configured. Set R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_ACCOUNT_ID env vars.")
        sys.exit(1)

    static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'fighters')

    # Load both fighter databases
    json_files = {
        'fighters.json': data_path('fighters.json'),
        'fighters_ufc.json': data_path('fighters_ufc.json'),
    }

    total_local = 0
    total_uploaded = 0
    total_updated = 0

    for json_name, json_path in json_files.items():
        if not os.path.exists(json_path):
            print(f"\nSkipping {json_name} (not found at {json_path})")
            continue

        with open(json_path, 'r', encoding='utf-8') as f:
            fighters = json.load(f)

        print(f"\n{'='*60}")
        print(f"Processing {json_name} ({len(fighters)} entries)")
        print(f"{'='*60}")

        updated = False
        for name, url in list(fighters.items()):
            # Only migrate local /static/fighters/ references
            if not url or not url.startswith('/static/fighters/'):
                continue

            total_local += 1
            filename = url.replace('/static/fighters/', '')
            local_path = os.path.join(static_dir, filename)

            if not os.path.exists(local_path):
                print(f"  SKIP {name}: local file missing ({filename})")
                continue

            r2_url = get_fighter_image_url(filename)

            if args.execute:
                # Upload to R2
                with open(local_path, 'rb') as img_file:
                    result_url = upload_fighter_image(img_file.read(), filename)

                if result_url:
                    fighters[name] = result_url
                    updated = True
                    total_uploaded += 1
                    print(f"  OK {name}: {url} → {result_url}")
                else:
                    print(f"  FAIL {name}: upload failed for {filename}")
            else:
                print(f"  [DRY RUN] {name}: {url} → {r2_url}")
                total_uploaded += 1

        if args.execute and updated:
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(fighters, f, indent=2, ensure_ascii=False)
            total_updated += 1
            print(f"\n  Saved updated {json_name}")

    print(f"\n{'='*60}")
    print(f"SUMMARY {'(DRY RUN)' if not args.execute else ''}")
    print(f"{'='*60}")
    print(f"  Local image references found: {total_local}")
    print(f"  {'Would upload' if not args.execute else 'Uploaded'}: {total_uploaded}")
    print(f"  JSON files updated: {total_updated}")

    if not args.execute and total_local > 0:
        print(f"\nRun with --execute to perform the migration:")
        print(f"  python migrate_to_r2.py --execute")


if __name__ == '__main__':
    main()
