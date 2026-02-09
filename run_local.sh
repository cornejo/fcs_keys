#! /bin/bash

docker run --pull always -ti --rm -v "$(pwd)":/src -w /src --entrypoint /usr/bin/bash blacktop/ipsw -c "cat <<'EOF' | bash
set -ex
apt-get update
apt-get install -y curl git jq python3 python3-pip
./update.py
ls ~/.config/ipsw/appledb
EOF"
