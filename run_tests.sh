#!/usr/bin/env bash

set -e

env_file=./tests/test.env

if [ -e ${env_file} ]; then
  source ${env_file}
fi

py.test tests
