#! /bin/bash

git submodule update --init appledb
git -C appledb checkout -B main origin/main
git -C appledb pull

docker run --pull always -ti --rm -v "$(pwd)":/src -w /src --entrypoint /usr/bin/bash blacktop/ipsw -c "cat <<'EOF' | bash
set -ex
apt-get update
apt-get install -y curl git jq python3 python3-pip
git config --global safe.directory '*'
./update.py
EOF"
