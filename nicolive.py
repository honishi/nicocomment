#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import sys
import ConfigParser
import logging
import logging.config
import datetime
import urllib2
import socket
from threading import Thread
from threading import Timer
from lxml import etree
import time
import re
import unicodedata
import cookielib
import tweepy

from nicoerror import UnexpectedStatusError

COOKIE_CONTAINER_INITILIZATION_SLEEP_TIME = 3
SOCKET_TIMEOUT = 60 * 30

COOKIE_CONTAINER_NOT_INITIALIZED = 0
COOKIE_CONTAINER_INITIALIZING = 1
COOKIE_CONTAINER_INITIALIZED = 2

NICOCOMMENT_CONFIG = os.path.dirname(os.path.abspath(__file__)) + '/nicocomment.config'

LOGIN_URL = "https://secure.nicovideo.jp/secure/login?site=niconico"
GET_STREAM_INFO_URL = "http://live.nicovideo.jp/api/getstreaminfo/lv"
GET_PLAYER_STATUS_URL = "http://watch.live.nicovideo.jp/api/getplayerstatus?v=lv"
# DEBUG_LOG_COMMENT = True
DEBUG_LOG_COMMENT = False

LIVE_URL = "http://live.nicovideo.jp/watch/lv"

COMMENT_SERVER_HOST_NUMBER_FIRST = 101
COMMENT_SERVER_HOST_NUMBER_LAST = 104
COMMENT_SERVER_PORT_FIRST = 2805
COMMENT_SERVER_PORT_LAST = 2814


class NicoLive(object):
# class variables
    logger = None
    cookie_container_status = COOKIE_CONTAINER_NOT_INITIALIZED
    cookie_container = None
    total_comment_count = 0
    last_comment = ""

# object life cycle
    def __init__(self, mail, password, community_id, live_id):
        self.logger = logging.getLogger()
        self.mail = mail
        self.password = password
        self.community_id = community_id
        self.live_id = live_id
        self.comment_count = 0

        (self.force_debug_tweet, self.monitoring_user_ids) = self.get_config()
        # self.logger.debug("monitoring_user_ids: %s" % self.monitoring_user_ids)

        self.header_text = {}
        self.consumer_key = {}
        self.consumer_secret = {}
        self.access_key = {}
        self.access_secret = {}
        for user_id in self.monitoring_user_ids:
            (self.header_text[user_id],
             self.consumer_key[user_id], self.consumer_secret[user_id],
             self.access_key[user_id], self.access_secret[user_id]) = (
                self.get_twitter_credentials(user_id))
            """
            self.logger.debug("user_id: " + user_id)
            self.logger.debug("header_text: " + self.header_text[user_id])
            self.logger.debug(
                "consumer_key: %s consumer_secret: ***" % self.consumer_key[user_id])
            self.logger.debug(
                "access_key: %s access_secret: ***" % self.access_key[user_id])
            """

    def __del__(self):
        pass

# config
    def get_config(self):
        config = ConfigParser.ConfigParser()
        config.read(NICOCOMMENT_CONFIG)

        if config.get("nicolive", "force_debug_tweet").lower() == "true":
            force_debug_tweet = True
        else:
            force_debug_tweet = False

        try:
            monitoring_user_ids = config.get("nicolive", "monitoring_user_ids").split(',')
        except ConfigParser.NoOptionError, unused_error:
            monitoring_user_ids = None

        return force_debug_tweet, monitoring_user_ids

    def get_twitter_credentials(self, user_id):
        config = ConfigParser.ConfigParser()
        config.read(NICOCOMMENT_CONFIG)
        section = "twitter-" + user_id

        header_text = config.get(section, "header_text")
        consumer_key = config.get(section, "consumer_key")
        consumer_secret = config.get(section, "consumer_secret")
        access_key = config.get(section, "access_key")
        access_secret = config.get(section, "access_secret")

        return header_text, consumer_key, consumer_secret, access_key, access_secret

# twitter
    def update_twitter_status(self, user_id, comment):
        try:
            self.last_status_update_user_id
            self.last_status_update_comment
        except AttributeError:
            self.last_status_update_user_id = None
            self.last_status_update_comment = None

        auth = tweepy.OAuthHandler(self.consumer_key[user_id], self.consumer_secret[user_id])
        auth.set_access_token(self.access_key[user_id], self.access_secret[user_id])
        status = "[%s]\n%s\n%s%s".encode('UTF-8') % (
            self.header_text[user_id], comment.encode('UTF-8'), LIVE_URL, self.live_id)

        if (user_id == self.last_status_update_user_id and
                comment == self.last_status_update_comment):
            # duplicated tweet. skip
            pass
        else:
            try:
                tweepy.API(auth).update_status(status)
            except tweepy.error.TweepError, error:
                self.logger.debug("error in post, user_id: %s comment: %s error_response: %s" %
                                  (user_id, comment, error))

        self.last_status_update_user_id = user_id
        self.last_status_update_comment = comment

# main
    @classmethod
    def get_cookie_container(cls, mail, password):
        if cls.cookie_container is None:
            cls.cookie_container_status = COOKIE_CONTAINER_INITIALIZING

            cookiejar = cookielib.CookieJar()
            opener = urllib2.build_opener(
                urllib2.HTTPCookieProcessor(cookiejar))
            # self.logger.debug("finished setting up cookie library.")

            opener.open(LOGIN_URL, "mail=%s&password=%s" % (mail, password))
            # self.logger.debug("finished login.")

            cls.cookie_container = opener
            cls.cookie_container_status = COOKIE_CONTAINER_INITIALIZED
            print "cookie container opened"

        return cls.cookie_container

    def get_stream_info(self, live_id):
        res = urllib2.urlopen(GET_STREAM_INFO_URL + live_id)
        xml = res.read()
        res_data = etree.fromstring(xml)
        # self.logger.debug(etree.tostring(res_data))

        status = res_data.xpath("//getstreaminfo")[0].attrib["status"]
        # status = "fail"
        if status == "ok":
            community_name = res_data.xpath("//getstreaminfo/communityinfo/name")[0].text
            live_name = res_data.xpath("//getstreaminfo/streaminfo/title")[0].text
            # set "n/a", when no value provided; like <title/>
            if community_name is None:
                community_name = "n/a"
            if live_name is None:
                live_name = "n/a"
        else:
            raise UnexpectedStatusError(status)

        return community_name, live_name

    def get_player_status(self, cookie_container, live_id):
        res = cookie_container.open(GET_PLAYER_STATUS_URL + live_id)

        res_data = etree.fromstring(res.read())
        # self.logger.debug(etree.tostring(res_data))
        status = res_data.xpath("//getplayerstatus")[0].attrib["status"]
        if status != 'ok':
            code = res_data.xpath("//getplayerstatus/error/code")[0].text
            raise UnexpectedStatusError(status, code)

        room_label = res_data.xpath("//getplayerstatus/user/room_label")[0].text

        host = res_data.xpath("//getplayerstatus/ms/addr")[0].text
        port = int(res_data.xpath("//getplayerstatus/ms/port")[0].text)
        thread = int(res_data.xpath("//getplayerstatus/ms/thread")[0].text)

        self.logger.debug("*** getplayerstatus, live_id: %s room_label: %s "
                          "host: %s port: %s thread: %s" %
                          (live_id, room_label, host, port, thread))
        return room_label, host, port, thread

    def split_host(self, host):
        matched_host = re.match('(msg)(\d+)(\..+)', host)
        if not matched_host:
            return (None, None, None)

        host_prefix = matched_host.group(1)
        host_number = int(matched_host.group(2))
        host_surfix = matched_host.group(3)

        return (host_prefix, host_number, host_surfix)

    def get_arena_comment_server(self, stand_type, arena_host, arena_port, arena_thread):
        host = arena_host
        port = arena_port
        thread = arena_thread

        decrement_count = 0
        if stand_type == "A":
            decrement_count = 1
        elif stand_type == "B":
            decrement_count = 2
        elif stand_type == "C":
            decrement_count = 3

        (host_prefix, host_number, host_surfix) = self.split_host(host)
        if host_prefix is None or host_number is None or host_surfix is None:
            return (host, port, thread)

        for i in xrange(decrement_count):
            if port == COMMENT_SERVER_PORT_FIRST:
                port = COMMENT_SERVER_PORT_LAST
                if host_number == COMMENT_SERVER_HOST_NUMBER_FIRST:
                    host_number = COMMENT_SERVER_HOST_NUMBER_LAST
                else:
                    host_number -= 1
            else:
                port -= 1
            thread -= 1

        return (host_prefix + str(host_number) + host_surfix, port, thread)

    def get_comment_servers(self, room_label, host, port, thread):
        self.logger.debug("original server, room_label: %s host: %s port: %s thread: %s" %
                          (room_label, host, port, thread))
        comment_servers = []

        matched_room = re.match('co\d+', room_label)
        if matched_room:
            # arena
            self.logger.debug("no need to adjust the room")
            pass
        else:
            matched_room = re.match('立ち見(\w)列', room_label)
            if matched_room:
                # stand A, B, C. host, port, thread should be adjusted
                stand_type = matched_room.group(1)
                (host, port, thread) = self.get_arena_comment_server(
                    stand_type, host, port, thread)
                self.logger.debug("adjusted arena server, host: %s port: %s thread: %s" %
                                  (host, port, thread))
            else:
                # channel live? not supported for now
                self.logger.debug("live is not user live, so skip")
                return comment_servers

        (host_prefix, host_number, host_surfix) = self.split_host(host)
        if host_prefix is None or host_number is None or host_surfix is None:
            return comment_servers

        for i in xrange(4):
            comment_servers.append((host_prefix + str(host_number) + host_surfix, port, thread))
            if port == COMMENT_SERVER_PORT_LAST:
                port = COMMENT_SERVER_PORT_FIRST
                if host_number == COMMENT_SERVER_HOST_NUMBER_LAST:
                    host_number = COMMENT_SERVER_HOST_NUMBER_FIRST
                else:
                    host_number += 1
            else:
                port += 1
            thread += 1

        return comment_servers

    def connect_to_server(self, host, port, thread):
        # main loop
        # self.schedule_stream_stat_timer()
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(SOCKET_TIMEOUT)
        sock.connect((host, port))
        sock.sendall(('<thread thread="%s" version="20061206" res_form="-1"/>'
                      + chr(0)) % thread)

        self.logger.debug("*** opened live thread, lv: %s server: %s,%s,%s" %
                          (self.live_id, host, port, thread))
        message = ""
        while True:
            try:
                recved = sock.recv(1024)
            except socket.timeout, e:
                self.logger.debug("detected timeout at socket recv().")
                break
            should_close_connection = False

            for character in recved:
                if character == chr(0):
                    # self.logger.debug("live_id: %s server: %s,%s,%s xml: %s" %
                    #                   (self.live_id, host, port, thread, message))
                    # wrap message using dummy "elements" tag to avoid parse error
                    message = "<elements>" + message + "</elements>"

                    try:
                        res_data = etree.fromstring(message)
                    except etree.XMLSyntaxError, e:
                        self.logger.debug("nicolive xml parse error: %s" % e)
                        self.logger.debug("xml: %s" % message)

                    try:
                        thread_elem = res_data.xpath("//elements/thread")
                        if 0 < len(thread_elem):
                            # self.logger.debug("live_id: %s server: %s,%s,%s xml: %s" %
                            #                   (self.live_id, host, port, thread, message))
                            result_code = thread_elem[0].attrib.get('resultcode')
                            if result_code == "1":
                                # no comments will be provided from this thread
                                should_close_connection = True
                                break

                        chats = res_data.xpath("//elements/chat")
                        if 1 < len(chats):
                            # self.logger.debug("xml: %s" % message)
                            pass

                        for chat in chats:
                            # self.logger.debug(etree.tostring(chat))
                            user_id = chat.attrib.get('user_id')
                            comment = chat.text
                            """
                            self.logger.debug(
                                "live_id: %s server: %s,%s,%s user_id: %s comment: %s" %
                                (self.live_id, host, port, thread, user_id, comment))
                            """
                            if comment == NicoLive.last_comment:
                                continue
                            NicoLive.last_comment = comment
                            NicoLive.total_comment_count += 1
                            self.comment_count += 1

                            for monitoring_user_id in self.monitoring_user_ids:
                                if self.force_debug_tweet:
                                    user_id = monitoring_user_id
                                if user_id == monitoring_user_id:
                                    self.update_twitter_status(user_id, comment)
                                if self.force_debug_tweet:
                                    should_close_connection = True
                                    break

                            if comment == "/disconnect":
                                # self.logger.debug("disconnect break")
                                should_close_connection = True
                                break
                    except KeyError:
                        self.logger.debug("received unrecognized data.")
                    message = ""
                else:
                    message += character
            if recved == '' or should_close_connection:
                # self.logger.debug("break")
                break
        # self.logger.debug("%s, (socket closed.)" % self.live_id)
        self.logger.debug("*** closed live thread, lv: %s server: %s,%s,%s comments: %s" %
                          (self.live_id, host, port, thread, self.comment_count))

# public method
    def start(self):
        try:
            (community_name, live_name) = self.get_stream_info(self.live_id)
        except Exception, e:
            self.logger.debug("could not get stream info: %s" % e)
        else:
            pass

        if NicoLive.cookie_container_status == COOKIE_CONTAINER_INITIALIZING:
            time.sleep(COOKIE_CONTAINER_INITILIZATION_SLEEP_TIME)
        cookie_container = self.get_cookie_container(self.mail, self.password)

        (room_label, host, port, thread) = (None, None, None, None)
        try:
            (room_label, host, port, thread) = self.get_player_status(
                cookie_container, self.live_id)
        except UnexpectedStatusError, e:
            if e.code in ["notfound", "require_community_member"]:
                self.logger.debug("caught 'expected' error, so quit: %s" % e)
                # exit
            else:
                self.logger.debug("caught 'unexpected' error, so try to clear session: %s" % e)
                # TODO: improve logic
                # possible case of session expiration, so try again
                NicoLive.cookie_container = None
                try:
                    cookie_container = self.get_cookie_container(self.mail, self.password)
                    (room_label, host, port, thread) = self.get_player_status(
                        cookie_container, self.live_id)
                except UnexpectedStatusError, e:
                    self.logger.debug("again: could not get player status: %s" % e)

        if (room_label is not None and
                host is not None and port is not None and thread is not None):
            comment_servers = self.get_comment_servers(room_label, host, port, thread)
            self.logger.debug("comment servers: %s" % comment_servers)

            for (host, port, thread) in comment_servers:
                t = Thread(target=self.connect_to_server, args=(host, port, thread))
                t.start()


if __name__ == "__main__":
    logging.config.fileConfig(NICOCOMMENT_CONFIG)

    # """
    nicolive = NicoLive(sys.argv[1], sys.argv[2], 0, sys.argv[3])
    nicolive.start()
    # """

    """
    nicolive = NicoLive("mail", "pass", 0, 123)
    nicolive.update_twitter_status("784552", u"日本語")
    nicolive.update_twitter_status("784552", u"日本語")
    nicolive.update_twitter_status("784552", u"abc")
    nicolive.update_twitter_status("784552", u"日本語")
    """

    """
    nicolive = NicoLive("mail", "pass", 0, 123)
    nicolive.get_comment_servers("co12345", "msg103.live.nicovideo.jp", 2808, 1314071859)
    nicolive.get_comment_servers("立ち見A列", "msg103.live.nicovideo.jp", 2808, 1314071859)
    nicolive.get_comment_servers("立ち見A列", "msg103.live.nicovideo.jp", 2805, 1314071859)
    nicolive.get_comment_servers("立ち見A列", "msg101.live.nicovideo.jp", 2805, 1314071859)
    nicolive.get_comment_servers("立ち見B列", "msg101.live.nicovideo.jp", 2805, 1314071859)
    nicolive.get_comment_servers("立ち見C列", "msg101.live.nicovideo.jp", 2805, 1314071859)
    nicolive.get_comment_servers("立ち見Z列", "msg101.live.nicovideo.jp", 2805, 1314071859)
    """
