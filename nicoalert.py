#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import ConfigParser
import logging
import logging.config
import datetime
import urllib
import urllib2
import socket
#from multiprocessing import Process
import threading
from threading import Thread
from threading import Timer
from lxml import etree

# from nicoerror import UnexpectedStatusError
import nicoerror
# import nicolive

NICOCOMMENT_CONFIG = os.path.dirname(os.path.abspath(__file__)) + '/nicocomment.config'

ANTENNA_URL = 'https://secure.nicovideo.jp/secure/login?site=nicolive_antenna'
GET_ALERT_STATUS_URL = 'http://live.nicovideo.jp/api/getalertstatus'

class NicoAlert(object):
# object lifecycle
    def __init__(self):
        self.logger = logging.getLogger()                     

        (self.mail, self.password) = self.get_config()
        self.logger.debug("mail: %s password: %s" % (self.mail, self.password))
        self.logger.debug("nicoalert initialized.")

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
        sock.connect((host, port))
        sock.sendall(('<thread thread="%s" version="20061206" res_form="-1"/>'
                      + chr(0)) % thread)

        # schedule log timer
        self.log_statistics()

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
                            self.logger.debug("started receiving live information.")

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
                                    # self.logger.debug(
                                    #    "stream_id: %s community_id: %s user_id: %s" %
                                    #    (stream_id, community_id, user_id))

                                    handler(live_id, community_id, user_id)

                    except KeyError:
                        self.logger.debug("received unknown information.")
                    msg = ""
                else:
                    msg += ch

    def handle_live(self, live_id, community_id, user_id):
        self.logger.debug("*** live started: %s" % live_id)
        '''
        live = nicolive.NicoLive(self.mail, self.password, community_id, live_id)
        p = Thread(target=live.open_comment_server, args=())
        p.start()
        '''

    def start(self):
        ticket = self.get_ticket()
        communities, host, port, thread = self.get_alert_status(ticket)
        self.listen_alert(host, port, thread, self.handle_live)

    def log_statistics(self):
        self.logger.debug(
            "active live thread: %s, total comment count: %s" %
            (9999, 9999))
        # (threading.active_count(), nicolive.NicoLive.total_comment_count))

        t = Timer(10, self.log_statistics)
        t.start()


if __name__ == "__main__":
    nicoalert = NicoAlert()
    nicoalert.go()
