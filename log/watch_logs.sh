#!/usr/bin/env bash

log='./nicocomment.log'

netstat_target_host='202.248.110.'
netstat_sleep_time=10

set -e

case "$1" in
  all)
    tail -F ${log}
    ;;
  error)
    tail -F ${log} | \
      grep --line-buffered -P -i "error" | \
      grep --line-buffered -P -v "require_community_member|notfound"
    ;;
  retry)
    tail -F ${log} | grep --line-buffered -P -i "retry"
    ;;
  alert)
    tail -F ${log} | \
      grep --line-buffered -P -i "received alert" | \
      grep --line-buffered -P " \d+ |co\d+"
    ;;
  channel)
    tail -F ${log} | grep --line-buffered -P 'ch\d+'
    ;;
  thread)
    tail -F ${log} | \
      grep --line-buffered -P -i 'active live threads' | \
      grep --line-buffered -P " \d+(?: |\$)"
    ;;
  netstat)
    while :
    do
      connections=$(netstat -na | grep -P ${netstat_target_host} | wc -l)
      echo $(date) total ${connections} connections to host contains ${netstat_target_host} | \
        grep --line-buffered -P "\d+ connections"
      sleep ${netstat_sleep_time}
    done
    ;;
  *)
    echo $"usage: $prog {all|error|retry|alert|channel|thread|netstat}" && exit 1
esac
