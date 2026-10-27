#!/bin/bash
# Fits priors to growing prefixes of the shuffled training set, each twice the last, and encodes the same held-out
# replays with each. Each fit is written as priors-<replays>.h, and learning.tsv gets a line per priors file: the replays
# it was fit to ("repo" for the priors osu_replay_zip ships with), then the held-out replays encoded, their bytes and their
# encoded bytes. Sizes already in learning.tsv are skipped, so a stopped run picks up where it left off.
#
# usage: snapshots.sh train.tsv test.tsv credentials [first size] [last size] [held-out replays]
set -euo pipefail

train=$1 test=$2 credentials=$3 size=${4:-36000} last=${5:-288000} held_out=${6:-2000}

# a learning.tsv line: a label, then the held-out replays, their bytes and their encoded bytes with a priors file
measure() {

	rm -rf /tmp/orz
	cp -r /orz /tmp/orz
	cp "$2" /tmp/orz/frames_prior.h

	g++ -std=c++20 -O2 -msse4.2 -ffp-contract=off -DORZ_FP_CONTRACT_OFF -I /tmp/orz -I /tmp/orz/Lib /tools/encoded_size.cpp \
		/orz/LzmaDec.o -o /tmp/encoded_size

	result=$(python3 /tools/feed.py "$test" --credentials "$credentials" --count "$held_out" | nice -n 19 /tmp/encoded_size)
	printf '%s\t%s\n' "$1" "$result" >> learning.tsv
}

[ -s learning.tsv ] || printf 'priors\treplays\tbytes\tencoded\n' > learning.tsv

grep -q $'^repo\t' learning.tsv || measure repo /orz/frames_prior.h

for (( ; size <= last; size *= 2)); do

	grep -q "^$size"$'\t' learning.tsv && continue

	if [ ! -s "priors-$size.h" ]; then
		python3 /tools/feed.py "$train" --credentials "$credentials" --count "$size" \
			| nice -n 19 frames_prior_gen - 36000 1 cache > priors.tmp
		mv priors.tmp "priors-$size.h"
	fi

	measure "$size" "priors-$size.h"

done
