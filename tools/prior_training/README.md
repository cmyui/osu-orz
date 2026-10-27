# Training ORZ priors on Akatsuki's replays

`frames_prior_gen` (in [osu_replay_zip](https://github.com/rumoi/osu_replay_zip)) fits `frames_prior.h`, the
starting state of the codec's models, to a set of replays. These tools feed it Akatsuki's replays straight from the
Wasabi bucket, so nothing is staged on disk but the generator's cache of encoded replays, about a third the size of
the replays it trains on. Its memory does not grow with the replays: about 0.6 GB per prior set fit at once.

| File | Runs on | Does |
|---|---|---|
| `build_manifest.py` | a machine that can `ssh hetzner-new` | lists the completed scores (read replica, read-only): mode, relax, user |
| `feed.py` | the training machine | streams the scores' replays from the bucket as the generator's stdin records |
| `snapshots.sh` | the training machine | fits priors to growing samples and measures each on held-out replays |
| `encoded_size.cpp` | the training machine | the held-out measure: encodes replays with the priors it is built with |
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

On the training machine, shuffle the manifest and split off the held-out users into `train.tsv` and `test.tsv`:

```sh
LC_ALL=C sort manifest.tsv | awk -F'\t' '{ print > ($2 ".tsv") }'
```

The shuffle makes every prefix of `train.tsv` a uniform sample, and the held-out users in `test.tsv` never appear in it.
Scores whose replay is not in the bucket are skipped, and `feed.py` reports how many.

Fit priors to growing samples, on one core at low priority:

```sh
docker run -d --name orz-snapshots --cpus 1 --user "$(id -u):$(id -g)" -v "$PWD:/work" orz-priors \
    sh -c '/tools/snapshots.sh train.tsv test.tsv s3.env 36000 288000 >> snapshots.log 2>&1'
```

Each fit takes the first replays of `train.tsv`, twice as many as the last (36,000, 72,000, ... up to 288,000), and is
written as `priors-<replays>.h`, a drop-in `frames_prior.h`. After each fit the same first 2,000 replays of `test.tsv`
are encoded with it, and `learning.tsv` gets a line: the replays fit, then the held-out replays, their bytes and their
encoded bytes. The `repo` line measures the priors osu_replay_zip ships with. How much the encoded size shrinks from one
sample to the next is what the larger fit bought. A stopped run picks up from the sizes not yet in `learning.tsv`.

A fit's cache of encoded replays takes about a third of the size of the replays it fits.
