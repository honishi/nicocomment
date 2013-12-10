#!/usr/bin/env bash

set -e

find . -name '*.gz' -exec zcat {} \; | grep --line-buffered -P -i "${1}"
