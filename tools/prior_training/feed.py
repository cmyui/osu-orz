"""Replays from the bucket as frames_prior_gen's stdin records, in manifest order: per replay its e_mode byte, its size
in 4 bytes, then its replay data. Reads build_manifest.py rows (order, split, score id, e_mode, user id), so a sorted
and filtered manifest feeds a shuffled training or held-out set; --skip and --count take a slice of it. Replays missing
from the bucket are skipped and counted.

The credentials file holds the bucket's S3 settings as KEY=VALUE lines: S3_ENDPOINT_URL, S3_BUCKET_NAME,
AWS_DEFAULT_REGION, AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY.
"""

import argparse
import collections
import itertools
import struct
import sys
from concurrent.futures import ThreadPoolExecutor

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError


def load_env(path):
    values = {}

    for line in open(path):
        line = line.strip()

        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip("\"'")

    return values


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest")
    parser.add_argument("--credentials", required=True, help="file with the S3 lines of Akatsuki's .env")
    parser.add_argument("--skip", type=int, default=0, help="rows to skip first")
    parser.add_argument("--count", type=int, help="rows to feed (default all)")
    parser.add_argument("--workers", type=int, default=16, help="downloads at once")
    args = parser.parse_args()

    env = load_env(args.credentials)
    s3 = boto3.client(
        "s3",
        endpoint_url=env["S3_ENDPOINT_URL"],
        region_name=env.get("AWS_DEFAULT_REGION"),
        aws_access_key_id=env["AWS_ACCESS_KEY_ID"],
        aws_secret_access_key=env["AWS_SECRET_ACCESS_KEY"],
        config=Config(max_pool_connections=args.workers, retries={"mode": "adaptive", "max_attempts": 5}),
    )
    out = sys.stdout.buffer

    def fetch(score_id):
        try:
            return s3.get_object(Bucket=env["S3_BUCKET_NAME"], Key=f"replays/{score_id}.osr")["Body"].read()
        except ClientError as error:
            # without permission to list the bucket, a missing replay reads as access denied
            if error.response["Error"]["Code"] in ("NoSuchKey", "AccessDenied"):
                return None

            raise

    rows = (line.split("\t") for line in open(args.manifest))
    rows = itertools.islice(rows, args.skip, None if args.count is None else args.skip + args.count)

    fed = missing = 0

    # downloads run ahead in a window, written in manifest order
    with ThreadPoolExecutor(args.workers) as pool:
        window = collections.deque()

        def write_oldest():
            nonlocal fed, missing

            mode, data = window.popleft()
            data = data.result()

            if data is None:
                missing += 1
                return

            out.write(struct.pack("<BI", mode, len(data)))
            out.write(data)
            fed += 1

            if fed % 10000 == 0:
                print(f"fed {fed} replays, {missing} missing", file=sys.stderr)

        for row in rows:
            window.append((int(row[3]), pool.submit(fetch, row[2])))

            if len(window) >= args.workers * 4:
                write_oldest()

        while window:
            write_oldest()

    out.flush()
    print(f"fed {fed} replays, {missing} missing", file=sys.stderr)


if __name__ == "__main__":
    main()
