nicocomment
==

setup
--
````
$ virtualenv --distribute venv
$ source ./venv/bin/activate
$ pip install -r requirements.txt
````
note: you should install exact same version of `mecab-python` with `mecab` installed in system. 

configure env
--
max open files.
````
$ ulimit -a

$ sudo vi /etc/security/limits.conf
honishi soft nofile 8192
honishi hard nofile 10240
$ sudo reboot

$ ulimit -a
````

memo
--
````
py.test --pep8 *.py
````
