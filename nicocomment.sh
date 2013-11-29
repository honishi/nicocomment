#!/usr/bin/env bash

set -e

basedir=$(cd $(dirname $0);pwd)
pyenv=${basedir}/venv/bin/activate
program=${basedir}/nicocomment.py
logfile=${basedir}/log/nicocomment.log
kill_python="python ${program}"
monitor_threshold=$((30))
customenv=${basedir}/nicocomment.env

start() {
  nohup ${program} >> ${logfile} 2>&1 &
}

stop() {
  pkill -f "${kill_python}" || true
  echo "killed." >> ${logfile}
}

monitor() {
  echo $(date) monitor start

  last_modified=$(date -r ${logfile} +%s)
  # last_modified=0
  current=$(date +%s)
  # echo $last_modified
  # echo $current

  if [ $((${last_modified} + ${monitor_threshold})) -lt ${current} ]
  then
      echo $(date) "it seems that the file ${logfile} is not updated in ${monitor_threshold} seconds, so try to restart."
      stop
      start
  fi

  echo $(date) monitor end
}

source ${pyenv}

if [ -e ${customenv} ]; then
    source ${customenv}
fi

case "$1" in
  start)
    stop
    start ;;
  stop)
    stop ;;
  restart)
    stop
    start ;;
  monitor)
    monitor ;;
  *)
    echo $"usage: $prog {start|stop|restart|monitor}" && exit 1
esac
