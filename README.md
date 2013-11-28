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
max open files for opening tons of sockets to comment servers.
````
$ ulimit -a

$ sudo vi /etc/security/limits.conf
honishi soft nofile 32768
honishi hard nofile 32768
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
