#!/usr/bin/env bash

set -e
# set -x

env_files="./nicocomment.env ./tests/test.env"

for env_file in ${env_files}
do
  if [ -e ${env_file} ]; then
    source ${env_file}
  fi
done

py.test tests
