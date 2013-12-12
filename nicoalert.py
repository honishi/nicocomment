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


class NicoAlert(object):
# object lifecycle
    def __init__(self):
        self.logger = logging.getLogger()
        self.alert_logger = logging.getLogger("alert")

        self.recent_lives = []
        self.received_live_count = 0

        (self.mail, self.password) = self.get_config()
        self.logger.debug("mail: %s password: xxxxxxxxxx" % self.mail)
        self.logger.info("nicoalert initialized.")

    def __del__(self):
        pass

# utility
    def get_config(self):
        config = ConfigParser.ConfigParser()
        config.read(NICOCOMMENT_CONFIG)
        mail = config.get("nicoalert", "mail")
        password = config.get("nicoalert", "password")

        return mail, password

# nico
    def get_ticket(self):
        query = {'mail': self.mail, 'password': self.password}
        res = urllib2.urlopen(ANTENNA_URL, urllib.urlencode(query))

        # res_data = xml.fromstring(res.read())
        res_data = etree.fromstring(res.read())
        # self.logger.debug(etree.tostring(res_data))
        # sample response
        #{'nicovideo_user_response': {'status': {'value': 'ok'},
        #                             'ticket': {'value': 'xxx'},
        #                             'value': '\n\t'}}

        ticket = res_data.xpath("//ticket")[0].text
        self.logger.debug("ticket: %s" % ticket)

        return ticket

    def get_alert_status(self, ticket):
        query = {'ticket': ticket}
        res = urllib2.urlopen(GET_ALERT_STATUS_URL, urllib.urlencode(query))

        res_data = etree.fromstring(res.read())
        # self.logger.debug(etree.tostring(res_data))
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
        # self.logger.debug(communities)

        host = None
        port = None
        thread = None

        host = res_data.xpath("//getalertstatus/ms/addr")[0].text
        port = int(res_data.xpath("//getalertstatus/ms/port")[0].text)
        thread = res_data.xpath("//getalertstatus/ms/thread")[0].text
        self.logger.debug("host: %s port: %s thread: %s" % (host, port, thread))

        return communities, host, port, thread

# main
    def listen_alert(self, host, port, thread, handler):
        # main loop
        # self.schedule_stream_stat_timer()
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
                            self.logger.info("started receiving live information.")

                        # 'chat'
                        chats = res_data.xpath("//chat")
                        if chats:
                            for chat in chats:
                                # self.logger.debug(etree.tostring(chat[0]))
                                live_info = chat.text
                                # self.logger.debug(live_info)

                                # value = "102351738,官邸前抗議の首都圏反原発連合と 脱原発を…"
                                # value = "102373563,co1299695,7169359"
                                lives = live_info.split(',')

                                if len(lives) == 3:
                                    # the stream is NOT the official one
                                    live_id, community_id, user_id = lives
                                    self.alert_logger.info(
                                        "received alert, live_id: %s community_id: %s "
                                        "user_id: %s" % (live_id, community_id, user_id))

                                    handler(live_id, community_id, user_id)
                                    self.received_live_count += 1
                    except KeyError:
                        self.logger.debug("received unknown information.")
                    msg = ""
                else:
                    msg += ch
        self.logger.error("encountered unexpected alert recv() end.")

    def handle_live(self, live_id, community_id, user_id):
        # self.logger.debug("*** live started: %s" % live_id)
        if self.recent_lives.count(live_id):
            self.logger.debug(
                "skipped duplicate alert, live_id: %s community_id: %s user_id: %s" %
                (live_id, community_id, user_id))
            return

        if 500 < len(self.recent_lives):
            self.recent_lives.pop(0)
        self.recent_lives.append(live_id)
        # self.logger.debug("recent_lives: %s" % self.recent_lives)

        try:
            live = nicolive.NicoLive()
            p = threading.Thread(name="%s,%s" % (community_id, live_id),
                                 target=live.start,
                                 args=(self.mail, self.password, community_id, live_id))
            p.start()
        except Exception, e:
            self.logger.error("failed to start nicolive thread, error: %s" % e)

    def start(self):
        ticket = self.get_ticket()
        communities, host, port, thread = self.get_alert_status(ticket)
        self.listen_alert(host, port, thread, self.handle_live)

# statistics
    def log_statistics(self):
        while True:
            self.logger.info(
                "*** received lives: %s active live threads: %s sum total comments: %s" %
                (self.received_live_count,
                 threading.active_count(), nicolive.NicoLive.sum_total_comment_count))
            time.sleep(10)

    def kick_log_statistics(self):
        t = threading.Thread(target=self.log_statistics)
        t.start()


if __name__ == "__main__":
    nicoalert = NicoAlert()
    nicoalert.go()
