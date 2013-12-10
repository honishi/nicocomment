#!/usr/bin/env bash

set -e

log_file=./nicocomment.log
live_log_dir=./live
datetime=$(date "+%Y%m%d-%H%M%S")

mv ${log_file} ${log_file}.${datetime}
mv ${live_log_dir} ${live_log_dir}.${datetime}
touch ${log_file}
