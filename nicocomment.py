#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import ConfigParser
import logging
import logging.config
import time
import threading
from datetime import datetime as dt

import nicoapi
import nicolive

NICOCOMMENT_CONFIG = os.path.dirname(os.path.abspath(__file__)) + '/nicocomment.config'
NICOCOMMENT_CONFIG_SAMPLE = NICOCOMMENT_CONFIG + '.sample'

LOG_STATISTICS_INTERVAL = 10

DEBUG_ENABLE_PROFILE = False
PROFILE_DURATION = 60 * 10


class NicoComment(object):
# magic methods
    def __init__(self):
        config_file = NICOCOMMENT_CONFIG
        if not os.path.exists(config_file):
            config_file = NICOCOMMENT_CONFIG_SAMPLE

        logging.config.fileConfig(config_file)

        self.received_alert_count = 0

        self.mail, self.password = self.get_basic_config(config_file)
        logging.debug("mail: %s password: xxxxxxxxxx" % self.mail)

        self.api = nicoapi.NicoAPI(self.mail, self.password)

        logging.info("nicocomment initialized.")

    def __del__(self):
        pass

    # utility
    def get_basic_config(self, config_file):
        config = ConfigParser.ConfigParser()
        config.read(config_file)

        section = "nicocomment"
        mail = config.get(section, "mail")
        password = config.get(section, "password")

        return mail, password

# public methods, main
    def start_monitoring(self):
        alert_thread = threading.Thread(
            name="listen_alert", target=self.api.listen_alert, args=(self.handle_alert,))
        if DEBUG_ENABLE_PROFILE:
            alert_thread.daemon = True

        alert_thread.start()

        if DEBUG_ENABLE_PROFILE:
            time.sleep(PROFILE_DURATION)

# private methods, alert
    def handle_alert(self, live_id, community_id, user_id):
        logging.getLogger("alert").info(
            "received alert, live_id: %-9s community_id: %-9s user_id: %-9s" %
            (live_id, community_id, user_id))
        self.received_alert_count += 1

        try:
            live = nicolive.NicoLive(self.mail, self.password, community_id, live_id, user_id)
            live_thread = threading.Thread(
                name="%s,%s" % (community_id, live_id), target=live.start_listening_live)
            live_thread.start()
        except Exception, e:
            logging.error("failed to start nicolive thread, error: %s" % e)

# private methods, log statistics
    def kick_log_statistics(self):
        log_stat_thread = threading.Thread(
            name="alert_statistics",
            target=self.log_alert_statistics)
        log_stat_thread.start()

    def log_alert_statistics(self):
        while True:
            logging.info("received alert count: %-5d" % (self.received_alert_count))
            time.sleep(LOG_STATISTICS_INTERVAL)

if __name__ == "__main__":

    if DEBUG_ENABLE_PROFILE:
        import yappi
        yappi.start()

    nicocomment = NicoComment()
    nicocomment.start_monitoring()

    if DEBUG_ENABLE_PROFILE:
        path = (os.path.dirname(os.path.abspath(__file__)) + '/profile.' +
                dt.now().strftime('%Y%m%d-%H%M%S'))
        yappi.get_func_stats().save(path)
        logging.info("finished to profile.")
