# frames_prior_gen (from osu_replay_zip) and the Wasabi tools in one image, for machines without a C++20 toolchain
FROM ubuntu:24.04

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates g++ gcc git python3 python3-boto3 \
    && rm -rf /var/lib/apt/lists/*

# a branch, tag, commit or pull request ref (refs/pull/<n>/head)
ARG ORZ_REPO=https://github.com/rumoi/osu_replay_zip
ARG ORZ_REF=master

RUN git clone -q "$ORZ_REPO" /orz \
    && cd /orz \
    && git fetch -q origin "$ORZ_REF" \
    && git checkout -q FETCH_HEAD \
    && gcc -O2 -c Lib/LzmaDec.c -o LzmaDec.o \
    && g++ -std=c++20 -O2 -msse4.2 -ffp-contract=off -DORZ_FP_CONTRACT_OFF -I . -I Lib frames_prior_gen.cpp LzmaDec.o \
        -o /usr/local/bin/frames_prior_gen

# snapshots.sh builds encoded_size.cpp against /orz with each priors file
COPY *.py *.cpp *.sh /tools/

WORKDIR /work
