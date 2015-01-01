#!/usr/bin/env bash

set -e

basedir=$(cd $(dirname $0);pwd)
pyenv=${basedir}/venv/bin/activate
customenv=${basedir}/nicocomment.env
program=${basedir}/nicocomment.py
pgrep_target="python ${program}"

monitor_threshold=$((30))

nohupfile=${basedir}/log/nohup.out
logfile=${basedir}/log/nicocomment.log
alertlogfile=${basedir}/log/alert.log

max_stack_size=120


start() {
  if [ 0 -lt $(pgrep -f "${pgrep_target}" | wc -l) ]
  then
    echo "already started."
  else
    nohup ${program} >> ${nohupfile} 2>&1 &
  fi
}

stop() {
  pkill -f "${pgrep_target}" || true
  echo "killed." >> ${logfile}
}

monitor() {
  target_logfile=${1}
  restarted=0

  echo $(date) monitor start
  echo $(date) target logfile: ${target_logfile}

  if [ ! -e ${target_logfile} ]; then
    echo $(date) "log file ${target_logfile} does not exist."
    echo $(date) "trying to start application."
    stop
    start
    restarted=1
  else
    last_modified=$(date -r ${target_logfile} +%s)
    current=$(date +%s)

    if [ $((${last_modified} + ${monitor_threshold})) -lt ${current} ]
    then
      echo $(date) "log file ${target_logfile} has not been updated for ${monitor_threshold} seconds."
      echo $(date) "trying to restart application."
      stop
      start
      restarted=1
    fi
  fi

  echo $(date) monitor end
  return ${restarted}
}

ulimit -s ${max_stack_size}

cd ${basedir}
source ${pyenv}

if [ -e ${customenv} ]; then
    source ${customenv}
fi

case "$1" in
  start)
    stop
    start
    ;;
  stop)
    stop
    ;;
  restart)
    stop
    sleep 2
    start
    ;;
  monitor)
    echo $(date) "checking root logfile..."
    monitor ${logfile}
    if [ ${?} -eq 0 ]; then
      echo $(date) "checking alert logfile..."
      monitor ${alertlogfile}
    fi
    ;;
  *)
    echo $"usage: ${0} {start|stop|restart|monitor}"
    exit 1
esac
