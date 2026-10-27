"""What each replay is, from the score tables: prints one row per completed score (a replay in the bucket, unless it was
never stored):

    order, split, score id, e_mode, user id

order places the replay in a fixed shuffle (sort the rows by it), and split is "test" for the held-out users (a fixed
share of users, by a hash of the user id) and "train" for the rest. e_mode is the mode frames_prior_gen takes for replay
data: the game mode, plus 4 for relax (osu!mania has no relax); autopilot scores are plain osu!, as the encoder finds
the autopilot path itself.

Reads the read replica through the score service on hetzner-new, as a read-only session, a page of ids at a time with a
pause between pages.
"""

import argparse
import hashlib
import json
import subprocess
import sys
import time

REMOTE = """
import asyncio, json, asyncmy
from starlette.config import Config
config = Config("/srv/root/.env")
async def main():
    db = await asyncmy.connect(host=config("READ_DB_HOST"), port=config("READ_DB_PORT", cast=int),
        user=config("READ_DB_USER"), password=config("READ_DB_PASS"), database=config("READ_DB_NAME"),
        read_timeout=120, autocommit=True)
    async with db.cursor() as cur:
        await cur.execute("SET SESSION MAX_EXECUTION_TIME=90000")
        await cur.execute("SET SESSION TRANSACTION READ ONLY")
        await cur.execute(SQL)
        for row in await cur.fetchall():
            print(json.dumps(row))
    db.close()
asyncio.run(main())
"""

TABLES = (("scores", "vanilla"), ("scores_relax", "relax"), ("scores_ap", "autopilot"))


def e_mode(play_mode, variant):
    if variant == "relax" and play_mode < 3:
        return play_mode + 4

    return 0 if variant == "autopilot" else play_mode


def digest(text):
    return int(hashlib.sha1(text.encode()).hexdigest()[:16], 16)


def page(table, after, size):
    """(score id, play mode, user id) of the next completed scores after an id."""
    sql = (
        f"SELECT id, play_mode, userid FROM {table} WHERE id > {after} AND completed IN (2, 3) "
        f"ORDER BY id LIMIT {size}"
    )

    result = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "hetzner-new", "docker exec -i akatsuki-score-service-1 python -"],
        input=REMOTE.replace("SQL", repr(sql)),
        text=True,
        capture_output=True,
    )

    if result.returncode != 0:
        raise SystemExit(f"query failed: {result.stderr.strip()[-500:]}")

    return [tuple(map(int, json.loads(line))) for line in result.stdout.splitlines()]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--page", type=int, default=50000, help="scores per query")
    parser.add_argument("--pause", type=float, default=1.0, help="seconds between queries")
    parser.add_argument("--test-percent", type=float, default=1.0, help="share of users held out")
    args = parser.parse_args()

    for table, variant in TABLES:
        after = written = 0

        while rows := page(table, after, args.page):
            for score_id, play_mode, user_id in rows:
                order = digest(f"orz-priors:{score_id}")
                held_out = digest(f"orz-priors-user:{user_id}") % 10000 < args.test_percent * 100

                print(f"{order:016x}\t{'test' if held_out else 'train'}\t{score_id}\t{e_mode(play_mode, variant)}\t{user_id}")

            after = rows[-1][0]
            written += len(rows)

            sys.stdout.flush()
            print(f"{table}: {written} scores, up to id {after}", file=sys.stderr)
            time.sleep(args.pause)


if __name__ == "__main__":
    main()
