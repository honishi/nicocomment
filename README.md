nicocomment
==
monitoring specified user's niconama comments, and tweet them.

setup
--
````
$ virtualenv --distribute venv
$ source ./venv/bin/activate
$ pip install -r requirements.txt
````

configure env
--
nicocomment requires lots of os resources, please tune the system to be able to use more resources.
````
$ ulimit -a

$ sudo vi /etc/security/limits.conf
// for opening tons of sockets to comment servers.
honishi soft nofile 32768
honishi hard nofile 32768
// for forking thread in the live comment listening.
// thread is treated as process internally in the kernel that uses NPTL(Native POSIX Thread Library)
honishi soft nproc 32768
honishi hard nproc 32768
$ sudo reboot

$ ulimit -a
````

memo
--
````
py.test --pep8 *.py
pep8 *.py
./nicolive.py "test@example.com" "password" 160603xxx
````
