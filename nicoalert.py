#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import ConfigParser
import logging
import logging.config
import time
import urllib
import urllib2
import socket
import threading
from lxml import etree

import nicoerror
import nicolive

NICOCOMMENT_CONFIG = os.path.dirname(os.path.abspath(__file__)) + '/nicocomment.config'

ANTENNA_URL = 'https://secure.nicovideo.jp/secure/login?site=nicolive_antenna'
GET_ALERT_STATUS_URL = 'http://live.nicovideo.jp/api/getalertstatus'

MAX_RECENT_LIVES_COUNT = 500
LOG_STATISTICS_INTERVAL = 10

class NicoAlert(object):
# magic methods
    def __init__(self):
        self.recent_lives = []
        self.received_live_count = 0

        (self.mail, self.password) = self.get_config()
        logging.debug("mail: %s password: xxxxxxxxxx" % self.mail)
        logging.info("nicoalert initialized.")

    def __del__(self):
        pass

    # utility
    def get_config(self):
        config = ConfigParser.ConfigParser()
        config.read(NICOCOMMENT_CONFIG)

        section = "nicoalert"
        mail = config.get(section, "mail")
        password = config.get(section, "password")

        return mail, password

# public methods
    def start_listening_alert(self):
        ticket = self.get_ticket()
        communities, host, port, thread = self.get_alert_status(ticket)
        self.listen_alert(host, port, thread)

# private methods, niconico
    def get_ticket(self):
        query = {'mail': self.mail, 'password': self.password}
        res = urllib2.urlopen(ANTENNA_URL, urllib.urlencode(query))

        # res_data = xml.fromstring(res.read())
        res_data = etree.fromstring(res.read())
        # logging.debug(etree.tostring(res_data))
        # sample response
        #{'nicovideo_user_response': {'status': {'value': 'ok'},
        #                             'ticket': {'value': 'xxx'},
        #                             'value': '\n\t'}}

        ticket = res_data.xpath("//ticket")[0].text
        logging.debug("ticket: %s" % ticket)

        return ticket

    def get_alert_status(self, ticket):
        query = {'ticket': ticket}
        res = urllib2.urlopen(GET_ALERT_STATUS_URL, urllib.urlencode(query))

        res_data = etree.fromstring(res.read())
        # logging.debug(etree.tostring(res_data))
        status = res_data.xpath("//getalertstatus")[0].attrib["status"]
        # sample response
        # {'getalertstatus':
        #     {'communities': {'community_id': {'value': 'co9320'}},
        #      'ms': {'addr': {'value': 'twr02.live.nicovideo.jp'},
        #             'port': {'value': '2532'},
        #             'thread': {'value': '1000000015'}},
        #      'status': {'value': 'ok'},
        #      'time': {'value': '1324980560'},
        #      'user_age': {'value': '19'},
        #      'user_hash': {'value': 'xxxxxxxxxxxxxxxxxxxxxxxxxxx'},
        #      'user_id': {'value': 'xxxxxxxx'},
        #      'user_name': {'value': 'miettal'},
        #      'user_prefecture': {'value': '12'},
        #      'user_sex': {'value': '1'}}}
        # if res_data.getalertstatus.status != 'ok' :
        if status != 'ok':
            raise nicoerror.NicoAuthorizationError

        communities = []
        for community_id in res_data.xpath("//community_id"):
            communities.append(community_id.text)
        # logging.debug(communities)

        host = None
        port = None
        thread = None

        host = res_data.xpath("//getalertstatus/ms/addr")[0].text
        port = int(res_data.xpath("//getalertstatus/ms/port")[0].text)
        thread = res_data.xpath("//getalertstatus/ms/thread")[0].text
        logging.debug("host: %s port: %s thread: %s" % (host, port, thread))

        return communities, host, port, thread

# private method, main sequence
    def listen_alert(self, host, port, thread):
        alert_logger = logging.getLogger("alert")

        # main loop
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(60)
        sock.connect((host, port))
        sock.sendall(('<thread thread="%s" version="20061206" res_form="-1"/>'
                      + chr(0)) % thread)

        # schedule log timer
        self.kick_log_statistics()

        msg = ""
        while True:
            rcvmsg = sock.recv(1024)
            for ch in rcvmsg:
                if ch == chr(0):
                    res_data = etree.fromstring(msg)

                    try:
                        # 'thread'
                        thread = res_data.xpath("//thread")
                        if thread:
                            logging.info("started receiving live information.")

                        # 'chat'
                        chats = res_data.xpath("//chat")
                        if chats:
                            for chat in chats:
                                # logging.debug(etree.tostring(chat[0]))
                                live_info = chat.text
                                # logging.debug(live_info)
                                lives = live_info.split(',')

                                if len(lives) == 3:
                                    # the stream is NOT the official one
                                    live_id, community_id, user_id = lives
                                    alert_logger.info(
                                        "received alert, live_id: %s community_id: %s "
                                        "user_id: %s" % (live_id, community_id, user_id))

                                    self.handle_live(live_id, community_id, user_id)
                                    self.received_live_count += 1
                    except KeyError:
                        logging.debug("received unknown information.")
                    msg = ""
                else:
                    msg += ch
        logging.error("encountered unexpected alert recv() end.")

    def handle_live(self, live_id, community_id, user_id):
        # logging.debug("*** live started: %s" % live_id)
        if self.recent_lives.count(live_id):
            logging.debug(
                "skipped duplicate alert, live_id: %s community_id: %s user_id: %s" %
                (live_id, community_id, user_id))
            return

        if MAX_RECENT_LIVES_COUNT < len(self.recent_lives):
            self.recent_lives.pop(0)
        self.recent_lives.append(live_id)
        # logging.debug("recent_lives: %s" % self.recent_lives)

        try:
            live = nicolive.NicoLive(self.mail, self.password, community_id, live_id)
            live_thread = threading.Thread(
                name="%s,%s" % (community_id, live_id), target=live.start_listening_live)
            live_thread.start()
        except Exception, e:
            logging.error("failed to start nicolive thread, error: %s" % e)

# private method, log statistics
    def kick_log_statistics(self):
        log_stat_thread = threading.Thread(target=self.log_statistics)
        log_stat_thread.start()

    def log_statistics(self):
        while True:
            logging.info(
                "*** received lives: %s active live threads: %s sum total comments: %s" %
                (self.received_live_count,
                 threading.active_count(), nicolive.NicoLive.sum_total_comment_count))

            index = 0
            for (active, community_id, live_id, community_name, live_name,
                    live_start_time) in self.calculate_active_ranking():
                logging.info("ranking-%d: [%d][%s][%s][%s][%s][%s]" %
                    (index, active, community_id, community_name, live_id,
                     live_name, live_start_time))
                index += 1

            time.sleep(LOG_STATISTICS_INTERVAL)

    def calculate_active_ranking(self):
        ranking = []
        index = 0

        # logging.info("aaa")
        for live_id, active in sorted(
                nicolive.NicoLive.lives_active.items(), key=lambda x:x[1], reverse=True):
            # logging.info("bbb: %s %d" % (live_id, active))
            try:
                (community_id, live_id, community_name, live_name, live_start_time) = (
                    nicolive.NicoLive.lives_info[live_id])
                ranking.append(
                    (active, community_id, live_id, community_name, live_name, live_start_time))
            except Exception, e:
                logging.warning("unexpected error in creating active ranking, error: %s" % e)

            if 20 < index:
                break
            index += 1

        return ranking

if __name__ == "__main__":
    nicoalert = NicoAlert()
    nicoalert.go()
