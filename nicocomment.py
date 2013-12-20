#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import logging
import logging.config
import nicoalert

NICOCOMMENT_CONFIG = os.path.dirname(os.path.abspath(__file__)) + '/nicocomment.config'


class NicoComment(object):
# magic methods
    def __init__(self):
        logging.config.fileConfig(NICOCOMMENT_CONFIG)
        logging.info("nicocomment initialized.")

    def __del__(self):
        pass

# public methods, main
    def fork_alert(self):
        alert = nicoalert.NicoAlert()
        alert.start_listening_alert()

if __name__ == "__main__":
    nicocomment = NicoComment()
    nicocomment.fork_alert()
