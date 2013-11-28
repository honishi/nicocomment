#!/usr/bin/env bash

set -e

source venv/bin/activate
export LD_LIBRARY_PATH=/home/honishi/local/openssl-1.0.0k/lib
# LD_LIBRARY_PATH=/home/honishi/local/openssl-1.0.0k/lib

./nicocomment.py

