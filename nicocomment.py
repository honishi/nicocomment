#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import logging
import logging.config
import ConfigParser
import nicoalert

NICOCOMMENT_CONFIG = os.path.dirname(os.path.abspath(__file__)) + '/nicocomment.config'


class NicoComment(object):
# object life cycle
    def __init__(self):
        logging.config.fileConfig(NICOCOMMENT_CONFIG)
        self.logger = logging.getLogger("root")
        self.logger.debug("nicocomment initialized.")

    def __del__(self):
        pass

# main
    def open_alert(self):
        alert = nicoalert.NicoAlert()
        alert.start()

if __name__ == "__main__":
    nicocomment = NicoComment()
    nicocomment.open_alert()
