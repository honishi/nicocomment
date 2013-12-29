#!/usr/bin/env bash

set -e

log='./nicocomment.log'
alertlog='./alert.log'

netstat_target_host='202.248.110.'
netstat_sleep_time=10

GREP_OPTIONS='--line-buffered -P'

case "$1" in
  all)
    tail -F ${log}
    ;;
  error)
    tail -F ${log} | grep -i "\[ERROR\]|\[WARNING\]|Traceback"
    ;;
  retry)
    tail -F ${log} | grep -i "retry"
    ;;
  stat)
    tail -F ${log} | grep -i 'instances'
    ;;
  alert)
    tail -F ${alertlog}
    ;;
  rank)
    tail -F ${log} | grep -i 'rank'
    ;;
  channel)
    tail -F ${log} | grep 'ch\d+'
    ;;
  netstat)
    while :
    do
      connections=$(netstat -na | grep ${netstat_target_host} | wc -l)
      echo \[$(date +'%Y-%m-%d %H:%M:%S')\] total ${connections} connections to host contains ${netstat_target_host}
      sleep ${netstat_sleep_time}
    done
    ;;
  *)
    echo $"usage: $prog {all|error|retry|stat|alert|rank|channel|netstat}" && exit 1
esac
