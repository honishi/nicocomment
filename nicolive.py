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
        auth = tweepy.OAuthHandler(self.consumer_key[user_id], self.consumer_secret[user_id])
        auth.set_access_token(self.access_key[user_id], self.access_secret[user_id])
        status = "[%s]\n%s\n%s%s".encode('UTF-8') % (self.header_text[user_id],
                                       comment.encode('UTF-8'),
                                       LIVE_URL,
                                       self.live_id)
        try:
            tweepy.API(auth).update_status(status)
        except tweepy.error.TweepError, error:
            print u'error in post.'
            print error

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
            print "opened"

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

        host = res_data.xpath("//getplayerstatus/ms/addr")[0].text
        port = int(res_data.xpath("//getplayerstatus/ms/port")[0].text)
        thread = res_data.xpath("//getplayerstatus/ms/thread")[0].text
        # self.logger.debug("host: %s port: %s thread: %s" % (host, port, thread))

        return host, port, thread

    def connect_to_server(self, host, port, thread):
        # main loop
        # self.schedule_stream_stat_timer()
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(SOCKET_TIMEOUT)
        sock.connect((host, port))
        sock.sendall(('<thread thread="%s" version="20061206" res_form="-1"/>'
                      + chr(0)) % thread)

        self.logger.debug("*** started receiving live, lv" + self.live_id)
        message = ""
        while True:
            try:
                recved = sock.recv(1024)
            except socket.timeout, e:
                self.logger.debug("detected timeout at socket recv().")
                break
            disconnected = False

            for character in recved:
                if character == chr(0):
                    # wrap message using dummy "chats" tag to avoid parse error
                    message = "<chats>" + message + "</chats>"
                    # self.logger.debug("xml: %s" % message)

                    try:
                        # res_data = xml.fromstring(message)
                        res_data = etree.fromstring(message)
                    except etree.XMLSyntaxError, e:
                        self.logger.debug("nicolive xml parse error: %s" % e)
                        self.logger.debug("xml: %s" % message)

                    try:
                        chats = res_data.xpath("//chats/chat")
                        if 1 < len(chats):
                            # self.logger.debug("xml: %s" % message)
                            pass

                        for chat in chats:
                            # self.logger.debug(etree.tostring(chat))
                            user_id = chat.attrib.get('user_id')
                            comment = chat.text
                            self.logger.debug("live_id: %s user_id: %s comment: %s" %
                                              (self.live_id, user_id, comment))
                            # thread_id = res_data.xpath("//chat/@thread")[0]
                            thread_id = res_data.xpath("//chats/chat/@thread")[0]
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
                                    disconnected = True
                                    break

                            if comment == "/disconnect":
                                # print "disconnect break"
                                disconnected = True
                                break
                    except KeyError:
                        self.logger.debug("received unrecognized data.")
                    message = ""
                else:
                    message += character
            if recved == '' or disconnected:
                # print "break"
                break
        # self.logger.debug("%s, (socket closed.)" % self.live_id)
        self.logger.debug("*** finished live, lv%s comments: %s" % (self.live_id, self.comment_count))

    def open_comment_server(self):
        try:
            (community_name, live_name) = self.get_stream_info(self.live_id)
        except Exception, e:
            self.logger.debug("could not get stream info: %s" % e)
        else:
            pass

        if NicoLive.cookie_container_status == COOKIE_CONTAINER_INITIALIZING:
            time.sleep(3)
        cookie_container = self.get_cookie_container(self.mail, self.password)

        (host, port, thread) = (None, None, None)
        try:
            (host, port, thread) = self.get_player_status(cookie_container, self.live_id)
        except UnexpectedStatusError, e:
            self.logger.debug("could not get player status: %s" % e)
            if e.code not in ["notfound", "require_community_member"]:
                NicoLive.cookie_container = None
                try:
                    cookie_container = self.get_cookie_container(self.mail, self.password)
                    (host, port, thread) = self.get_player_status(cookie_container, self.live_id)
                except UnexpectedStatusError, e:
                    self.logger.debug("again: could not get player status: %s" % e)

        if host is not None and port is not None and thread is not None:
            self.connect_to_server(host, port, thread)


if __name__ == "__main__":
    logging.config.fileConfig(NICOCOMMENT_CONFIG)

    nicolive = NicoLive(sys.argv[1], sys.argv[2], 0, sys.argv[3])
    nicolive.open_comment_server()
