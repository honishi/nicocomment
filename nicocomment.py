#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import ConfigParser
import logging
import logging.config
import time
import threading

import nicoapi
import nicolive

NICOCOMMENT_CONFIG = os.path.dirname(os.path.abspath(__file__)) + '/nicocomment.config'

LOG_STATISTICS_INTERVAL = 10


class NicoComment(object):
# magic methods
    def __init__(self):
        logging.config.fileConfig(NICOCOMMENT_CONFIG)

        self.received_alert_count = 0

        self.mail, self.password = self.get_basic_config()
        logging.debug("mail: %s password: xxxxxxxxxx" % self.mail)

        self.api = nicoapi.NicoAPI(self.mail, self.password)

        logging.info("nicocomment initialized.")

    def __del__(self):
        pass

    # utility
    def get_basic_config(self):
        config = ConfigParser.ConfigParser()
        config.read(NICOCOMMENT_CONFIG)

        section = "nicocomment"
        mail = config.get(section, "mail")
        password = config.get(section, "password")

        return mail, password

# public methods, main
    def start_monitoring(self):
        self.api.listen_alert(self.handle_alert)

# private methods, alert
    def handle_alert(self, live_id, community_id, user_id):
        logging.getLogger("alert").info(
            "received alert, live_id: %-9s community_id: %-9s user_id: %-9s" %
            (live_id, community_id, user_id))
        self.received_alert_count += 1

        try:
            live = nicolive.NicoLive(self.mail, self.password, community_id, live_id)
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
    nicocomment = NicoComment()
    nicocomment.start_monitoring()
