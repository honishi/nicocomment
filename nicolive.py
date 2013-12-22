#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import ConfigParser
import logging
import logging.config
import urllib2
import socket
import threading
from lxml import etree
import time
import re
import cookielib
from datetime import datetime as dt
from datetime import timedelta
import gzip
import tweepy

from nicoerror import UnexpectedStatusError

OPEN_ROOM_TWEET_THREASHOLD = 1
ACTIVE_LOGGING_THREASHOLD = 20
ACTIVE_TWEET_THREASHOLD = 100

RETRY_INTERVAL_GET_COOKIE_CONTAINER = 1
RETRY_INTERVAL_GET_STREAM_INFO = 2
RETRY_INTERVAL_GET_PLAYER_STATUS = 3
RETRY_INTERVAL_OPEN_COMMENT_SERVER_SOCKET = 1

MAX_RETRY_COUNT_GET_COOKIE_CONTAINER = 5
MAX_RETRY_COUNT_GET_STREAM_INFO = 5
MAX_RETRY_COUNT_GET_PLAYER_STATUS = 5
# block_now_count_overflow case, retrying for 30 min
MAX_RETRY_COUNT_GET_PLAYER_STATUS_BNCO = 30 * 60 / RETRY_INTERVAL_GET_PLAYER_STATUS
MAX_RETRY_COUNT_OPEN_COMMENT_SERVER_SOCKET = 5

ACTIVE_CALCULATION_INTERVAL = 10
SOCKET_TIMEOUT = 60 * 30

NICOCOMMENT_CONFIG = os.path.dirname(os.path.abspath(__file__)) + '/nicocomment.config'
LIVE_LOG_BASE_DIR = os.path.dirname(os.path.abspath(__file__)) + '/log/live'

LOGIN_URL = "https://secure.nicovideo.jp/secure/login?site=niconico"
GET_STREAM_INFO_URL = "http://live.nicovideo.jp/api/getstreaminfo/lv"
GET_PLAYER_STATUS_URL = "http://watch.live.nicovideo.jp/api/getplayerstatus?v=lv"

LIVE_TYPE_UNKNOWN = 0
LIVE_TYPE_OFFICIAL = 1
LIVE_TYPE_USER = 2

LIVE_STATUS_TYPE_UNKNOWN = 0
LIVE_STATUS_TYPE_STARTED = 1
LIVE_STATUS_TYPE_FINISHED = 2

LIVE_URL = "http://live.nicovideo.jp/watch/lv"

COMMENT_SERVER_HOST_NUMBER_FIRST = 101
COMMENT_SERVER_HOST_NUMBER_LAST = 104
COMMENT_SERVER_PORT_OFFICIAL_FIRST = 2815
COMMENT_SERVER_PORT_OFFICIAL_LAST = 2817
COMMENT_SERVER_PORT_USER_FIRST = 2805
COMMENT_SERVER_PORT_USER_LAST = 2814

CREDENTIAL_KEY_ALL = "all"

# DEBUG_DUMMY_COMMENT_AND_EXIT = True
DEBUG_DUMMY_COMMENT_AND_EXIT = False
# DEBUG_LOG_COMMENT_TO_APP_LOG = True
DEBUG_LOG_COMMENT_TO_APP_LOG = False


class NicoLive(object):
# class variables
    lock = threading.Lock()
    cookie_container = None
    sum_total_comment_count = 0
    all_opened_thread_ids = []

    last_tweeted_credential_key = None
    last_tweeted_status = None

    lives_active = {}
    lives_info = {}

# magic methods
    def __init__(self, mail, password, community_id, live_id):
        self.log_file_obj = None

        self.mail = mail
        self.password = password
        self.community_id = community_id
        self.live_id = live_id

        self.community_name = ""
        self.live_name = ""
        self.live_start_time = None
        self.opened_live_threads = []
        self.thread_local_vars = threading.local()
        self.live_status = LIVE_TYPE_UNKNOWN

        self.comments = []
        self.should_recalculate_active = True
        self.logged_active = False
        self.active_tweet_target = ACTIVE_TWEET_THREASHOLD

        config = ConfigParser.ConfigParser()
        config.read(NICOCOMMENT_CONFIG)

        self.force_debug_tweet, self.live_logging = self.get_basic_config(config)
        """
        logging.debug("force_debug_tweet: %s live_logging: %s" %
                      (self.force_debug_tweet, self.live_logging))
        """

        self.consumer_key = {}
        self.consumer_secret = {}
        self.access_key = {}
        self.access_secret = {}

        self.target_users = []
        self.header_text = {}
        for (user, header_text, consumer_key, consumer_secret, access_key,
                access_secret) in self.get_user_config(config):
            self.target_users.append(user)
            self.header_text[self.target_users[-1]] = header_text
            self.consumer_key[self.target_users[-1]] = consumer_key
            self.consumer_secret[self.target_users[-1]] = consumer_secret
            self.access_key[self.target_users[-1]] = access_key
            self.access_secret[self.target_users[-1]] = access_secret
            """
            logging.debug("user: %s" % self.target_users[-1])
            logging.debug("header_text: %s" % self.header_text[self.target_users[-1]])
            logging.debug("consumer_key: %s consumer_secret: xxxxx" %
                          self.consumer_key[self.target_users[-1]])
            logging.debug("access_key: %s access_secret: xxxxx" %
                          self.access_key[self.target_users[-1]])
            """

        self.target_communities = []
        for (community, consumer_key, consumer_secret, access_key,
                access_secret) in self.get_community_config(config):
            self.target_communities.append(community)
            self.consumer_key[self.target_communities[-1]] = consumer_key
            self.consumer_secret[self.target_communities[-1]] = consumer_secret
            self.access_key[self.target_communities[-1]] = access_key
            self.access_secret[self.target_communities[-1]] = access_secret
            """
            logging.debug("community: %s" % self.target_communities[-1])
            logging.debug("consumer_key: %s consumer_secret: xxxxx" %
                          self.consumer_key[self.target_communities[-1]])
            logging.debug("access_key: %s access_secret: xxxxx" %
                          self.access_key[self.target_communities[-1]])
            """

        self.log_filename = (LIVE_LOG_BASE_DIR + "." + dt.now().strftime('%Y%m%d') + '/' +
                             self.live_id[len(self.live_id)-3:] + '/' + self.live_id + '.log')

    def __del__(self):
        pass

    # utility
    def get_basic_config(self, config):
        section = "nicolive"

        force_debug_tweet = self.get_bool_for_option(config, section, "force_debug_tweet")
        live_logging = self.get_bool_for_option(config, section, "live_logging")

        return force_debug_tweet, live_logging

    def get_user_config(self, config):
        result = []

        for section in config.sections():
            matched = re.match(r'user-(.+)', section)
            if matched:
                user = matched.group(1)
                header_text = config.get(section, "header_text")
                result.append(
                    (user, header_text) + self.get_twitter_credentials(config, section))

        return result

    def get_community_config(self, config):
        result = []

        for section in config.sections():
            matched = re.match(r'community-(.+)', section)
            if matched:
                community = matched.group(1)
                result.append(
                    (community,) + self.get_twitter_credentials(config, section))

        return result

    # utility, again
    def get_bool_for_option(self, config, section, option):
        if config.has_option(section, option):
            option = config.getboolean(section, option)
        else:
            option = False

        return option

    def get_twitter_credentials(self, config, section):
        consumer_key = config.get(section, "consumer_key")
        consumer_secret = config.get(section, "consumer_secret")
        access_key = config.get(section, "access_key")
        access_secret = config.get(section, "access_secret")

        return consumer_key, consumer_secret, access_key, access_secret

# public methods, main
    def start_listening_live(self):
        self.live_start_time = dt.now()

        retry_count = 0
        while True:
            try:
                (self.community_name, self.live_name) = self.get_stream_info(self.live_id)
                #logging.debug("*** stream info, community name: %s live name: %s" %
                #              (self.community_name, self.live_name))
                break
            except Exception, e:
                logging.warning("could not get stream info: %s" % e)

                if retry_count < MAX_RETRY_COUNT_GET_STREAM_INFO:
                    logging.debug("retrying to open getstreaminfo, "
                                  "retry count: %d" % retry_count)
                else:
                    logging.error("gave up retrying to open getstreaminfo, so quit, "
                                  "retry count: %d" % retry_count)
                    self.community_name = "n/a"
                    self.live_name = "n/a"
                    break
                time.sleep(RETRY_INTERVAL_GET_STREAM_INFO)
                retry_count += 1

        for community_id in self.target_communities:
            if self.community_id == community_id:
                status = self.create_start_live_status()
                self.update_twitter_status(community_id, status)

        (room_label, host, port, thread) = (None, None, None, None)
        retry_count = 0
        max_retry_count = 0
        retry_interval = 0

        while True:
            cookie_container = NicoLive.get_cookie_container(self.mail, self.password)
            try:
                (room_label, host, port, thread) = self.get_player_status(
                    cookie_container, self.live_id)
                break
            except UnexpectedStatusError, e:
                # possible error code list: http://looooooooop.blog35.fc2.com/blog-entry-1159.html
                if e.code == "require_community_member":
                    logging.debug("live is 'require_community_member', so skip.")
                    # "error: %s" % e
                    break
                elif e.code in ["notfound", "deletedbyuser", "deletedbyvisor",
                                "violated", "usertimeshift", "closed", "noauth"]:
                    logging.debug("caught regular error in getplayerstatus, so quit, "
                                  "error: %s" % e)
                    break
                else:
                    max_retry_count = MAX_RETRY_COUNT_GET_PLAYER_STATUS
                    if e.code in ["comingsoon", "block_now_count_overflow"]:
                        logging.debug("live is '%s', so retry, error: %s" % (e.code, e))
                        if e.code == "block_now_count_overflow":
                            max_retry_count = MAX_RETRY_COUNT_GET_PLAYER_STATUS_BNCO
                        retry_interval = RETRY_INTERVAL_GET_PLAYER_STATUS
                    else:
                        # possible case of session expiration, so clearing container and retry
                        logging.warning(
                            "caught irregular error in getplayerstatus, error: %s" % e)
                        NicoLive.cookie_container = None
                        retry_interval = 0
            except Exception, e:
                logging.warning("possible network error when opening getplayerstatus, "
                                "error: %s" % e)
                max_retry_count = MAX_RETRY_COUNT_GET_PLAYER_STATUS
                retry_interval = RETRY_INTERVAL_GET_PLAYER_STATUS

            if retry_count < max_retry_count:
                logging.debug("retrying to open getplayerstatus, "
                              "retry count: %d" % retry_count)
            else:
                logging.error("gave up retrying to open getplayerstatus, so quit, "
                              "retry count: %d" % retry_count)
                break

            time.sleep(retry_interval)
            retry_count += 1

        if (room_label is not None and
                host is not None and port is not None and thread is not None):

            NicoLive.lives_active[self.live_id] = 0
            NicoLive.lives_info[self.live_id] = (
                self.community_id, self.live_id, self.community_name,
                self.live_name, self.live_start_time)

            live_type = self.get_live_type_with_host(host)
            distance_from_arena = self.get_distance_from_arena(live_type, room_label)

            self.comment_servers = self.get_comment_servers(
                live_type, distance_from_arena, host, port, thread)

            if self.live_logging:
                self.log_file_obj = self.open_live_log_file()

            self.live_status = LIVE_STATUS_TYPE_STARTED
            self.start_active_calculation_thread()
            for unused_i in xrange(distance_from_arena+1):
                self.add_live_thread()

            for live_thread in self.opened_live_threads:
                live_thread.join()
            self.live_status = LIVE_STATUS_TYPE_FINISHED

            # logging.debug("finished all sub threads")
            if self.live_logging:
                self.log_file_obj.close()
                self.gzip_live_log_file()

            NicoLive.lives_active.pop(self.live_id)
            NicoLive.lives_info.pop(self.live_id)

    def open_comment_server(self, room_position, host, port, thread):
        self.thread_local_vars.room_position = room_position
        self.thread_local_vars.comment_count = 0
        self.thread_local_vars.tweeted_open_room = False
        # self.thread_local_vars.last_comment = ""

        if self.live_logging and DEBUG_DUMMY_COMMENT_AND_EXIT:
            self.log_live("dummy comment...")
            return

        if thread in NicoLive.all_opened_thread_ids:
            logging.warning("live thread is already opened, so skip.")
            return

        logging.debug("*** opened live thread, server: %s, %s, %s" % (host, port, thread))
        NicoLive.all_opened_thread_ids.append(thread)

        sock = self.open_comment_server_socket(host, port, thread)

        if sock:
            message = ""
            while True:
                try:
                    recved = sock.recv(1024)
                except socket.timeout, unused_e:
                    logging.debug("detected timeout at socket recv().")
                    break
                should_close_connection = False

                for character in recved:
                    if character == chr(0):
                        # logging.debug("xml: %s" % message)
                        if self.live_logging:
                            self.log_live(message)

                        if DEBUG_LOG_COMMENT_TO_APP_LOG:
                            logging.debug(message)

                        should_close_connection = self.parse_thread_stream(message)
                        message = ""
                    else:
                        message += character
                if recved == '' or should_close_connection:
                    # logging.debug("break")
                    break
            sock.close()

        logging.debug("*** closed live thread, server: %s, %s, %s comments: %s" %
                      (host, port, thread, self.thread_local_vars.comment_count))
        NicoLive.all_opened_thread_ids.remove(thread)

# private methods, niconico api
    @classmethod
    def get_cookie_container(cls, mail, password):
        # logging.debug("entering to critical section: get_cookie_container")

        with cls.lock:
            # logging.debug("entered to critical section: get_cookie_container")
            if cls.cookie_container is None:
                retry_count = 0
                while True:
                    try:
                        cookiejar = cookielib.CookieJar()
                        opener = urllib2.build_opener(urllib2.HTTPCookieProcessor(cookiejar))
                        opener.open(LOGIN_URL, "mail=%s&password=%s" % (mail, password))
                        cls.cookie_container = opener
                    except Exception, e:
                        logging.warning(
                            "possible network error when initializing cookie container, "
                            "error: %s" % e)
                        if retry_count < MAX_RETRY_COUNT_GET_COOKIE_CONTAINER:
                            logging.debug(
                                "retrying cookie container initialization, retry count: %d" %
                                retry_count)
                            time.sleep(RETRY_INTERVAL_GET_COOKIE_CONTAINER)
                        else:
                            logging.error(
                                "gave up retrying cookie container initialization, "
                                "retry count: %d" % retry_count)
                            break   # = return None
                    else:
                        logging.debug("opened cookie container")
                        break
                    retry_count += 1

            # logging.debug("exiting from critical section: get_cookie_container")
        # logging.debug("exited from critical section: get_cookie_container")

        return cls.cookie_container

    def get_stream_info(self, live_id):
        res = urllib2.urlopen(GET_STREAM_INFO_URL + live_id)
        xml = res.read()
        element = etree.fromstring(xml)
        # logging.debug(etree.tostring(element))

        status = element.xpath("//getstreaminfo")[0].attrib["status"]
        # status = "fail"
        if status == "ok":
            community_name = element.xpath("//getstreaminfo/communityinfo/name")[0].text
            live_name = element.xpath("//getstreaminfo/streaminfo/title")[0].text
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

        element = etree.fromstring(res.read())
        # logging.debug(etree.tostring(element))
        status = element.xpath("//getplayerstatus")[0].attrib["status"]
        if status != 'ok':
            code = element.xpath("//getplayerstatus/error/code")[0].text
            raise UnexpectedStatusError(status, code)

        room_label = element.xpath("//getplayerstatus/user/room_label")[0].text

        host = element.xpath("//getplayerstatus/ms/addr")[0].text
        port = int(element.xpath("//getplayerstatus/ms/port")[0].text)
        thread = int(element.xpath("//getplayerstatus/ms/thread")[0].text)

        logging.debug("*** getplayerstatus, room_label: %s host: %s port: %s thread: %s" %
                      (room_label, host, port, thread))
        return room_label, host, port, thread

# private methods, open comment server
    def add_live_thread(self):
        # room_position 0: arena, 1: stand_a, 2: ...
        target_room_position = len(self.opened_live_threads)
        if not target_room_position < len(self.comment_servers):
            logging.warning("could not add live thread, opened: %d comment servers: %d" %
                            (target_room_position, len(self.comment_servers)))
            return

        (host, port, thread) = self.comment_servers[target_room_position]
        live_thread = threading.Thread(
            name="%s,%s,%s" % (self.community_id, self.live_id, thread),
            target=self.open_comment_server,
            args=(target_room_position, host, port, thread))

        self.opened_live_threads.append(live_thread)
        live_thread.start()

# private methods, comment server
    def split_host(self, host):
        matched_host = re.match(r'((?:o|)msg)(\d+)(\..+)', host)
        if not matched_host:
            return (None, None, None)

        host_prefix = matched_host.group(1)
        host_number = int(matched_host.group(2))
        host_surfix = matched_host.group(3)

        return (host_prefix, host_number, host_surfix)

    def previous_comment_server(self, live_type, host_number, port, thread):
        if live_type == LIVE_TYPE_OFFICIAL:
            if host_number == COMMENT_SERVER_HOST_NUMBER_FIRST:
                host_number = COMMENT_SERVER_HOST_NUMBER_LAST
                if port == COMMENT_SERVER_PORT_OFFICIAL_FIRST:
                    port = COMMENT_SERVER_PORT_OFFICIAL_LAST
                else:
                    port -= 1
            else:
                host_number -= 1
        elif live_type == LIVE_TYPE_USER:
            if port == COMMENT_SERVER_PORT_USER_FIRST:
                port = COMMENT_SERVER_PORT_USER_LAST
                if host_number == COMMENT_SERVER_HOST_NUMBER_FIRST:
                    host_number = COMMENT_SERVER_HOST_NUMBER_LAST
                else:
                    host_number -= 1
            else:
                port -= 1
        thread -= 1

        return (host_number, port, thread)

    def next_comment_server(self, live_type, host_number, port, thread):
        if live_type == LIVE_TYPE_OFFICIAL:
            if host_number == COMMENT_SERVER_HOST_NUMBER_LAST:
                host_number = COMMENT_SERVER_HOST_NUMBER_FIRST
                if port == COMMENT_SERVER_PORT_OFFICIAL_LAST:
                    port = COMMENT_SERVER_PORT_OFFICIAL_FIRST
                else:
                    port += 1
            else:
                host_number += 1
        elif live_type == LIVE_TYPE_USER:
            if port == COMMENT_SERVER_PORT_USER_LAST:
                port = COMMENT_SERVER_PORT_USER_FIRST
                if host_number == COMMENT_SERVER_HOST_NUMBER_LAST:
                    host_number = COMMENT_SERVER_HOST_NUMBER_FIRST
                else:
                    host_number += 1
            else:
                port += 1
        thread += 1

        return (host_number, port, thread)

    def get_arena_comment_server(
            self, live_type, distance, provided_host, provided_port, provided_thread):
        host = provided_host
        port = provided_port
        thread = provided_thread

        (host_prefix, host_number, host_surfix) = self.split_host(host)
        if host_prefix is None or host_number is None or host_surfix is None:
            return (host, port, thread)

        for unused_i in xrange(distance):
            (host_number, port, thread) = self.previous_comment_server(
                live_type, host_number, port, thread)

        return (host_prefix + str(host_number) + host_surfix, port, thread)

    def get_distance_from_arena(self, live_type, room_label):
        distance = -1

        matched_room = re.match('c(?:o|h)\d+', room_label)
        if matched_room:
            # arena
            # logging.debug("no need to adjust the room")
            distance = 0
        else:
            if live_type == LIVE_TYPE_OFFICIAL:
                # TODO: temporary implementation
                logging.warning("official live but could not parse the room label properly. "
                                "this is expected, cause it's still not implemented.")
                pass
            elif live_type == LIVE_TYPE_USER:
                matched_room = re.match(u'立ち見(\w)列', room_label)
                if matched_room:
                    # stand A, B, C. host, port, thread should be adjusted
                    stand_type = matched_room.group(1)
                    if stand_type == "A":
                        distance = 1
                    elif stand_type == "B":
                        distance = 2
                    elif stand_type == "C":
                        distance = 3
                if distance == -1:
                    logging.warning("could not parse room label: %s" % room_label)

        return distance

    def get_live_type_with_host(self, host):
        live_type = LIVE_TYPE_UNKNOWN

        if re.match(r'^o', host):
            # logging.error(u'detected official live')
            live_type = LIVE_TYPE_OFFICIAL
        else:
            # logging.debug(u'detected user/channel live')
            live_type = LIVE_TYPE_USER

        return live_type

    def get_comment_servers(self, live_type, distance_from_arena, host, port, thread):
        """
        logging.debug(
            "provided comment server, live_type: %d distance_from_arena: %d "
            "host: %s port: %s thread: %s" %
            (live_type, distance_from_arena, host, port, thread))
        """
        comment_servers = []

        room_count = 0
        if distance_from_arena < 0:
            # could not calculate distance from arena,
            # so use host, port and thread with no change
            room_count = 1
        else:
            (host, port, thread) = self.get_arena_comment_server(
                live_type, distance_from_arena, host, port, thread)
            # arena + stand a + stand b + stand c
            room_count = 4

        (host_prefix, host_number, host_surfix) = self.split_host(host)
        for unused_i in xrange(room_count):
            comment_servers.append(
                (host_prefix + str(host_number) + host_surfix, port, thread))
            (host_number, port, thread) = self.next_comment_server(
                live_type, host_number, port, thread)

        return comment_servers

    def open_comment_server_socket(self, host, port, thread):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(SOCKET_TIMEOUT)

        retry_count = 0
        while True:
            try:
                sock.connect((host, port))
            except Exception, e:
                # possible case like connection time out
                logging.warning(
                    "possible network error when connecting to comment server, error: %s" % e)
                if retry_count < MAX_RETRY_COUNT_OPEN_COMMENT_SERVER_SOCKET:
                    logging.debug(
                        "retrying to connect to comment server, retry count: %d" % retry_count)
                    time.sleep(RETRY_INTERVAL_OPEN_COMMENT_SERVER_SOCKET)
                else:
                    logging.error(
                        "gave up retrying to connect to comment server so quit, "
                        "retry count: %d" % retry_count)
                    return None
            else:
                break
            retry_count += 1

        sock.sendall(('<thread thread="%s" version="20061206" res_form="-1"/>'
                      + chr(0)) % thread)

        return sock

# private methods, stream parser
    def notify_opening_room(self, room_position):
        if 0 < room_position:
            room_name = u"立ち見"
            if room_position == 1:
                room_name += u"A"
            elif room_position == 2:
                room_name += u"B"
            elif room_position == 3:
                room_name += u"C"
            else:
                room_name += u"X"
            status = self.create_stand_room_status(room_name)

            if CREDENTIAL_KEY_ALL in self.target_communities:
                self.update_twitter_status(CREDENTIAL_KEY_ALL, status)

            if self.community_id in self.target_communities:
                self.update_twitter_status(self.community_id, status)

    def parse_chat_element(self, chat):
        # logging.debug(etree.tostring(chat))
        user_id = chat.attrib.get('user_id')
        premium = chat.attrib.get('premium')
        if premium is None:
            premium = "0"
        comment = chat.text

        return user_id, premium, comment

    def check_user_id(self, user_id, comment):
        tweeted = False

        target_user_ids = self.target_users
        if self.force_debug_tweet:
            target_user_ids = [user_id]

        for monitoring_user_id in target_user_ids:
            if user_id == monitoring_user_id:
                status = self.create_monitored_comment_status(user_id, comment)
                self.update_twitter_status(user_id, status)
                # uncomment this to simulate duplicate tweet
                # self.update_twitter_status(user_id, status)
                tweeted = True

        return tweeted

    def check_ifseetno(self, comment):
        if len(self.opened_live_threads) == 4:
            # logging.debug("detected ifseetno, but already opened max live threads")
            pass
        elif (self.thread_local_vars.room_position + 1 == len(self.opened_live_threads) and
                re.match(r'/hb ifseetno', comment)):
            logging.debug("detected ifseetno in current last room, so open new thread")
            self.add_live_thread()

    def check_disconnect(self, premium, comment):
        should_close_connection = False

        if premium in ['2', '3'] and comment == "/disconnect":
            # see the references below for details of the conbination of premium
            # attribute value and disconnect command:
            # - http://www.yukun.info/blog/2008/08/python-if-for-in.html
            # - https://twitter.com/Hemus_/status/6766945512
            # logging.debug("detected command: %s w/ premium: %s" %
            #                   (comment, premium))
            # logging.debug("disconnect, xml: %s" % message)
            should_close_connection = True

        return should_close_connection

    def parse_thread_stream(self, message):
        should_close_connection = False
        # wrap message using dummy "elements" tag to avoid parse error
        message = "<elements>" + message + "</elements>"

        try:
            element = etree.fromstring(message)
        except etree.XMLSyntaxError, e:
            logging.warning("nicolive xml parse error: %s" % e)
            logging.debug("xml: %s" % message)

        try:
            thread_element = element.xpath("//elements/thread")
            if 0 < len(thread_element):
                result_code = thread_element[0].attrib.get('resultcode')
                if result_code == "1":
                    # logging.debug("thread xml: %s" % message)
                    # no comments will be provided from this thread
                    should_close_connection = True
                else:
                    # successfully opened thread
                    pass
            else:
                chats = element.xpath("//elements/chat")
                if 1 < len(chats):
                    # logging.debug("chat xml: %s" % message)
                    pass
                for chat in chats:
                    user_id, premium, comment = self.parse_chat_element(chat)

                    # if comment == self.thread_local_vars.last_comment:
                    #     continue
                    # self.thread_local_vars.last_comment = comment

                    self.thread_local_vars.comment_count += 1
                    NicoLive.sum_total_comment_count += 1
                    self.comments.append((dt.now(), premium, user_id, comment))
                    self.should_recalculate_active = True

                    if (not self.thread_local_vars.tweeted_open_room and
                            OPEN_ROOM_TWEET_THREASHOLD <= self.thread_local_vars.room_position and
                            not re.match(r'^/', comment)):
                        self.thread_local_vars.tweeted_open_room = True
                        self.notify_opening_room(self.thread_local_vars.room_position)

                    tweeted = self.check_user_id(user_id, comment)
                    if tweeted and self.force_debug_tweet:
                        should_close_connection = True
                        break

                    self.check_ifseetno(comment)

                    should_close_connection = self.check_disconnect(premium, comment)
                    if should_close_connection:
                        break
        except KeyError:
            logging.debug("received unrecognized data.")

        return should_close_connection

# private methods, calcurating active
    def start_active_calculation_thread(self):
        calculation_thread = threading.Thread(
            name="%s,%s,active" % (self.community_id, self.live_id),
            target=self.calculate_active)
        calculation_thread.start()

    def calculate_active(self):
        while True:
            if self.live_status == LIVE_STATUS_TYPE_FINISHED:
                break

            if self.should_recalculate_active:
                active_calcuration_duration = 60 * 10
                unique_users = []
                current_datetime = dt.now()

                for index in xrange(len(self.comments)-1, -1, -1):
                    (comment_datetime, premium, user_id, comment) = self.comments[index]

                    # premium 0: non-paid user, 1: paid user
                    if not premium in ["0", "1"]:
                        continue

                    if (current_datetime - comment_datetime >
                            timedelta(seconds=active_calcuration_duration)):
                        break

                    if not unique_users.count(user_id):
                        unique_users.append(user_id)

                active = len(unique_users)
                NicoLive.lives_active[self.live_id] = active
                self.should_recalculate_active = False

                if ACTIVE_LOGGING_THREASHOLD < active and not self.logged_active:
                    status = self.create_active_live_status(ACTIVE_LOGGING_THREASHOLD)
                    logging.info(status)
                    self.logged_active = True

                if self.active_tweet_target < active:
                    status = self.create_active_live_status(self.active_tweet_target)
                    logging.info(status)
                    self.active_tweet_target += ACTIVE_TWEET_THREASHOLD

                    if CREDENTIAL_KEY_ALL in self.target_communities:
                        self.update_twitter_status(CREDENTIAL_KEY_ALL, status)
                    if self.community_id in self.target_communities:
                        self.update_twitter_status(self.community_id, status)

            time.sleep(ACTIVE_CALCULATION_INTERVAL)

# private methods, twitter
    # user-related
    def create_monitored_comment_status(self, user_id, comment):
        status = u"【%s】\n%s\n%s%s\n(%s)".encode('UTF-8') % (
            self.header_text[user_id], comment.encode('UTF-8'),
            LIVE_URL, self.live_id, self.community_name)
        return status

    # community-related
    def create_start_live_status(self):
        status = u"【放送開始】%s（%s）%s%s" % (
            self.live_name, self.community_name, LIVE_URL, self.live_id)
        return status

    def create_active_live_status(self, active):
        status = u"【アクティブ%d+/開始%d分】%s（%s）%s%s" % (
            active, self.elapsed_minutes(),
            self.live_name, self.community_name,
            LIVE_URL, self.live_id)
        # self.live_start_time.strftime('%Y/%m/%d %H:%M')
        return status

    def create_stand_room_status(self, room_name):
        status = u"【%sオープン/開始%d分】%s（%s）%s%s" % (
            room_name, self.elapsed_minutes(),
            self.live_name, self.community_name,
            LIVE_URL, self.live_id)
        return status

    def elapsed_minutes(self):
        return (dt.now() - self.live_start_time).seconds / 60

    # main
    def update_twitter_status(self, credential_key, status):
        logging.debug("entering to critical section: update_twitter_status")

        with NicoLive.lock:
            logging.debug("entered to critical section: update_twitter_status")

            if (credential_key == NicoLive.last_tweeted_credential_key and
                    status == NicoLive.last_tweeted_status):
                logging.debug("skipped duplicate tweet, credential_key: %s status: [%s]" %
                              (credential_key, status))
            else:
                auth = tweepy.OAuthHandler(self.consumer_key[credential_key],
                                           self.consumer_secret[credential_key])
                auth.set_access_token(self.access_key[credential_key],
                                      self.access_secret[credential_key])
                try:
                    tweepy.API(auth).update_status(status)
                except tweepy.error.TweepError, error:
                    # ("%s" % error) is unicode type; it's defined as TweepError.__str__ in
                    # tweepy/error.py. so we need to convert it to str type here.
                    # see http://bit.ly/jm5Zpc for details about string type conversion.
                    error_str = ("%s" % error).encode('UTF-8')
                    logging.error(
                        "error in post, credential_key: %s status: [%s] error_response: %s" %
                        (credential_key, status, error_str))

            NicoLive.last_tweeted_credential_key = credential_key
            NicoLive.last_tweeted_status = status
            # logging.debug("exiting from critical section: update_twitter_status")

        logging.debug("exited from critical section: update_twitter_status")

# private methods, live log
    def open_live_log_file(self):
        if not os.path.exists(self.log_filename):
            directory = os.path.dirname(self.log_filename)
            try:
                os.makedirs(directory)
            except OSError:
                # already existed
                pass
            else:
                logging.debug("directory %s created." % directory)

        file_obj = open(self.log_filename, 'a')
        logging.debug("opened live log file: %s" % self.log_filename)

        return file_obj

    def log_live(self, message):
        self.log_file_obj.write(message + "\n")
        self.log_file_obj.flush()

    def gzip_live_log_file(self):
        gzipped_log_filename = self.log_filename + '.gz'

        if not os.path.exists(self.log_filename):
            logging.debug("gzip requested log file not found, log file: %s" % self.log_filename)
            return

        if os.path.exists(gzipped_log_filename):
            logging.debug("gzipped log file already exists, "
                          "gzipped log file: %s" % gzipped_log_filename)
            return

        logging.debug("gzipping live log file: %s", self.log_filename)

        log_file = open(self.log_filename, 'rb')
        gzipped_log_file = gzip.open(gzipped_log_filename, 'wb')
        gzipped_log_file.writelines(log_file)
        gzipped_log_file.close()
        log_file.close()
        os.remove(self.log_filename)

        logging.debug("gzipped live log file: %s", gzipped_log_filename)


if __name__ == "__main__":
    logging.config.fileConfig(NICOCOMMENT_CONFIG)

    nicolive = NicoLive(os.sys.argv[1], os.sys.argv[2], None, os.sys.argv[3])
    nicolive.start_listening_live()
