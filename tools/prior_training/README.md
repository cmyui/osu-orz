# Training ORZ priors on Akatsuki's replays

`frames_prior_gen` (in [osu_replay_zip](https://github.com/rumoi/osu_replay_zip)) fits `frames_prior.h`, the
starting state of the codec's models, to a set of replays. These tools feed it Akatsuki's replays straight from the
Wasabi bucket, so nothing is staged on disk but the generator's cache of encoded replays, about a third the size of
the replays it trains on. Its memory does not grow with the replays: about 0.6 GB per prior set fit at once.

| File | Runs on | Does |
|---|---|---|
| `build_manifest.py` | a machine that can `ssh hetzner-new` | lists the completed scores (read replica, read-only): mode, relax, user |
| `feed.py` | the training machine | streams the scores' replays from the bucket as the generator's stdin records |
| `Dockerfile` | the training machine | builds `frames_prior_gen` and the tools, with Python and boto3 |

## Credentials

`feed.py` reads the bucket's S3 settings from a file passed as `--credentials`, as KEY=VALUE lines: `S3_ENDPOINT_URL`,
`S3_BUCKET_NAME`, `AWS_DEFAULT_REGION`, `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY`. The key needs to read
`replays/` only. Keep the file readable only by you (`chmod 600`).

## Steps

Build the image on the training machine. `ORZ_REF` picks the osu_replay_zip version: a branch, tag, commit or
`refs/pull/<n>/head`.

```sh
docker build -t orz-priors --build-arg ORZ_REF=master path/to/osu-orz/tools/prior_training
```

From a machine that can reach both hetzner-new and the training machine (`training` below), list the scores straight
into a file there:

```sh
python3 build_manifest.py | ssh training 'cat > manifest.tsv'
```

On the training machine, shuffle the manifest and split off the held-out users:

```sh
sort manifest.tsv | awk -F'\t' '$2 == "train"' > train.tsv
sort manifest.tsv | awk -F'\t' '$2 == "test"' > test.tsv
```

Fit the priors to the first replays of the shuffled training set, on one core at low priority:

```sh
docker run --rm --cpus 1 --user "$(id -u):$(id -g)" -v "$PWD:/work" orz-priors sh -c \
    'python3 /tools/feed.py train.tsv --credentials s3.env --count 36000 \
        | nice -n 19 frames_prior_gen - 36000 1 cache > frames_prior.h'
```

A larger `--count` fits a larger sample. The shuffle makes every prefix of `train.tsv` a uniform sample, and the
held-out users in `test.tsv` never appear in it, so priors fit to growing prefixes can be compared on the same test
replays. Scores whose replay is not in the bucket are skipped, and `feed.py` reports how many.
