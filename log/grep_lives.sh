#!/usr/bin/env bash

unset GREP_OPTIONS
set -e

find . -name '*.gz' -exec zcat {} \; | grep --line-buffered -P -i "${1}"
