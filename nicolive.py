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
import gzip
import tweepy

from nicoerror import UnexpectedStatusError

SOCKET_TIMEOUT = 60 * 30

NICOCOMMENT_CONFIG = os.path.dirname(os.path.abspath(__file__)) + '/nicocomment.config'
LIVE_LOG_DIR = os.path.dirname(os.path.abspath(__file__)) + '/log/live'

LOGIN_URL = "https://secure.nicovideo.jp/secure/login?site=niconico"
GET_STREAM_INFO_URL = "http://live.nicovideo.jp/api/getstreaminfo/lv"
GET_PLAYER_STATUS_URL = "http://watch.live.nicovideo.jp/api/getplayerstatus?v=lv"
# DEBUG_LOG_COMMENT = True
DEBUG_LOG_COMMENT = False

LIVE_TYPE_UNKNOWN = 0
LIVE_TYPE_OFFICIAL = 1
LIVE_TYPE_USER = 2

LIVE_URL = "http://live.nicovideo.jp/watch/lv"

COMMENT_SERVER_HOST_NUMBER_FIRST = 101
COMMENT_SERVER_HOST_NUMBER_LAST = 104
COMMENT_SERVER_PORT_FIRST = 2805
COMMENT_SERVER_PORT_LAST = 2814


class NicoLive(object):
# class variables
    logger = logging.getLogger()
    lock = threading.Lock()
    cookie_container = None
    sum_total_comment_count = 0

    last_status_update_user_id = None
    last_status_update_status = None

# object life cycle
    def __init__(self):
        self.logger = logging.getLogger()
        self.log_file_obj = None

        self.comment_count = 0
        self.last_comment = ""

        (self.force_debug_tweet, self.live_logging, self.monitoring_user_ids) = self.get_config()
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

        # self.logger.debug("*** nicolive __init__, %s" % threading.current_thread().ident)

    def __del__(self):
        # self.logger.debug("*** nicolive __del__, %s" % threading.current_thread().ident)
        pass

# config
    def get_config(self):
        config = ConfigParser.ConfigParser()
        config.read(NICOCOMMENT_CONFIG)

        if config.get("nicolive", "force_debug_tweet").lower() == "true":
            force_debug_tweet = True
        else:
            force_debug_tweet = False

        if config.get("nicolive", "live_logging").lower() == "true":
            live_logging = True
        else:
            live_logging = False

        try:
            monitoring_user_ids = config.get("nicolive", "monitoring_user_ids").split(',')
        except ConfigParser.NoOptionError, unused_error:
            monitoring_user_ids = None

        return force_debug_tweet, live_logging, monitoring_user_ids

    def get_twitter_credentials(self, user_id):
        config = ConfigParser.ConfigParser()
        config.read(NICOCOMMENT_CONFIG)
        section = user_id

        header_text = config.get(section, "header_text")
        consumer_key = config.get(section, "consumer_key")
        consumer_secret = config.get(section, "consumer_secret")
        access_key = config.get(section, "access_key")
        access_secret = config.get(section, "access_secret")

        return header_text, consumer_key, consumer_secret, access_key, access_secret

# twitter
    def update_twitter_status(self, live_id, user_id, comment):
        self.logger.debug("entering to critical section: update_twitter_status")

        with NicoLive.lock:
            self.logger.debug("entered to critical section: update_twitter_status")

            status = "[%s]\n%s\n%s%s".encode('UTF-8') % (
                self.header_text[user_id], comment.encode('UTF-8'), LIVE_URL, live_id)

            if (user_id == NicoLive.last_status_update_user_id and
                    status == NicoLive.last_status_update_status):
                self.logger.debug(
                    "skipped duplicate tweet, user_id: %s status: [%s]" % (user_id, status))
            else:
                auth = tweepy.OAuthHandler(
                    self.consumer_key[user_id], self.consumer_secret[user_id])
                auth.set_access_token(self.access_key[user_id], self.access_secret[user_id])
                try:
                    tweepy.API(auth).update_status(status)
                except tweepy.error.TweepError, error:
                    # ("%s" % error) is unicode type; it's defined as TweepError.__str__ in
                    # tweepy/error.py. so we need to convert it to str type here.
                    # see http://bit.ly/jm5Zpc for details about string type conversion.
                    error_str = ("%s" % error).encode('UTF-8')
                    self.logger.error(
                        "error in post, user_id: %s status: [%s] error_response: %s" %
                        (user_id, status, error_str))

            NicoLive.last_status_update_user_id = user_id
            NicoLive.last_status_update_status = status

            self.logger.debug("exiting from critical section: update_twitter_status")

        self.logger.debug("exited from critical section: update_twitter_status")

# live log
    def log_file_path_for_live_id(self, live_id):
        sub_directory = live_id[len(live_id)-4:]
        return LIVE_LOG_DIR + '/' + sub_directory + '/' + live_id + '.log'

    def prepare_live_log_directory(self, live_id):
        log_file_path = self.log_file_path_for_live_id(live_id)
        directory = os.path.dirname(log_file_path)
        try:
            os.makedirs(directory)
        except OSError:
            # already existed
            pass
        else:
            self.logger.debug("directory %s created." % directory)

    def open_live_log_file(self, live_id):
        log_path = self.log_file_path_for_live_id(live_id)
        if not os.path.exists(log_path):
            self.prepare_live_log_directory(live_id)

        file_obj = open(log_path, 'a')
        self.logger.debug("opened live log file: %s" % log_path)

        return file_obj

    def log_live(self, message):
        self.log_file_obj.write(message + "\n")
        self.log_file_obj.flush()

    def gzip_live_log_file(self, live_id):
        log_path = self.log_file_path_for_live_id(live_id)
        gzipped_log_path = log_path + '.gz'

        if not os.path.exists(log_path):
            self.logger.debug("gzip requested log file not found, log file: %s" % log_path)
            return

        if os.path.exists(gzipped_log_path):
            self.logger.debug("gzipped log file already exists, "
                              "gzipped log file: %s" % gzipped_log_path)
            return

        self.logger.debug("gzipping live log file: %s", log_path)

        log_file = open(log_path, 'rb')
        gzipped_log_file = gzip.open(gzipped_log_path, 'wb')
        gzipped_log_file.writelines(log_file)
        gzipped_log_file.close()
        log_file.close()

        os.remove(log_path)
        self.logger.debug("gzipped live log file: %s", gzipped_log_path)

# main
    @classmethod
    def get_cookie_container(cls, mail, password):
        # cls.logger.debug("entering to critical section: get_cookie_container")

        with cls.lock:
            # cls.logger.debug("entered to critical section: get_cookie_container")
            if cls.cookie_container is None:
                retry_count = 0
                while True:
                    try:
                        cookiejar = cookielib.CookieJar()
                        opener = urllib2.build_opener(urllib2.HTTPCookieProcessor(cookiejar))
                        opener.open(LOGIN_URL, "mail=%s&password=%s" % (mail, password))
                        cls.cookie_container = opener
                    except Exception, e:
                        cls.logger.warning(
                            "possible network error when initializing cookie container, "
                            "error: %s" % e)
                        if retry_count < 5:
                            cls.logger.debug(
                                "retrying cookie container initialization, retry count: %d" %
                                retry_count)
                            time.sleep(1)
                        else:
                            cls.logger.error(
                                "gave up retrying cookie container initialization, "
                                "retry count: %d" % retry_count)
                            break   # = return None
                    else:
                        cls.logger.debug("opened cookie container")
                        break
                    retry_count += 1

            # cls.logger.debug("exiting from critical section: get_cookie_container")
        # cls.logger.debug("exited from critical section: get_cookie_container")

        return cls.cookie_container

    def get_stream_info(self, live_id):
        res = urllib2.urlopen(GET_STREAM_INFO_URL + live_id)
        xml = res.read()
        element = etree.fromstring(xml)
        # self.logger.debug(etree.tostring(element))

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
        # TODO: integrate retry logic here with start() method below. here, we should raise
        # some exception rather than UnexpectedStatusError. and it should be handled in start().
        retry_count = 0
        while True:
            try:
                res = cookie_container.open(GET_PLAYER_STATUS_URL + live_id)
                break
            except Exception, e:
                self.logger.warning("possible network error when opening api getplayerstatus, "
                                    "error: %s" % e)
                if retry_count < 5:
                    self.logger.debug("retrying to open api getplayerstatus, "
                                      "retry count: %d" % retry_count)
                    time.sleep(2)
                else:
                    self.logger.error("gave up retrying to open api getplayerstatus, so quit, "
                                      "retry count: %d" % retry_count)
                    return
                retry_count += 1

        element = etree.fromstring(res.read())
        # self.logger.debug(etree.tostring(element))
        status = element.xpath("//getplayerstatus")[0].attrib["status"]
        if status != 'ok':
            code = element.xpath("//getplayerstatus/error/code")[0].text
            raise UnexpectedStatusError(status, code)

        room_label = element.xpath("//getplayerstatus/user/room_label")[0].text

        host = element.xpath("//getplayerstatus/ms/addr")[0].text
        port = int(element.xpath("//getplayerstatus/ms/port")[0].text)
        thread = int(element.xpath("//getplayerstatus/ms/thread")[0].text)

        self.logger.debug("*** getplayerstatus, room_label: %s host: %s port: %s thread: %s" %
                          (room_label, host, port, thread))
        return room_label, host, port, thread

    # comment server
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
                if port == COMMENT_SERVER_PORT_FIRST:
                    port = COMMENT_SERVER_PORT_LAST
                else:
                    port -= 1
            else:
                host_number -= 1
        elif live_type == LIVE_TYPE_USER:
            if port == COMMENT_SERVER_PORT_FIRST:
                port = COMMENT_SERVER_PORT_LAST
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
                if port == COMMENT_SERVER_PORT_LAST:
                    port = COMMENT_SERVER_PORT_FIRST
                else:
                    port += 1
            else:
                host_number += 1
        elif live_type == LIVE_TYPE_USER:
            if port == COMMENT_SERVER_PORT_LAST:
                port = COMMENT_SERVER_PORT_FIRST
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

        for i in xrange(distance):
            (host_number, port, thread) = self.previous_comment_server(
                live_type, host_number, port, thread)

        return (host_prefix + str(host_number) + host_surfix, port, thread)

    def calculate_distance_from_arena(self, live_type, room_label):
        distance = -1

        matched_room = re.match('c(?:o|h)\d+', room_label)
        if matched_room:
            # arena
            # self.logger.debug("no need to adjust the room")
            distance = 0
        else:
            if live_type == LIVE_TYPE_OFFICIAL:
                # TODO: temporary implementation
                self.logger.warning("official live but could not get the seat in arena, "
                                    "this is not supported right now, so skip.")
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
                    self.logger.warning("could not parse room label: %s" % room_label)

        return distance

    def get_comment_servers(self, room_label, host, port, thread):
        """
        self.logger.debug(
            "provided comment server, room_label: %s host: %s port: %s thread: %s" %
            (room_label, host, port, thread))
        """
        comment_servers = []

        live_type = LIVE_TYPE_UNKNOWN
        if re.match(r'^o', host):
            # self.logger.error(u'detected official live')
            live_type = LIVE_TYPE_OFFICIAL
        else:
            # self.logger.debug(u'detected user/channel live')
            live_type = LIVE_TYPE_USER

        distance_from_arena = self.calculate_distance_from_arena(live_type, room_label)
        if distance_from_arena < 0:
            return comment_servers

        (host, port, thread) = self.get_arena_comment_server(
            live_type, distance_from_arena, host, port, thread)

        (host_prefix, host_number, host_surfix) = self.split_host(host)
        for i in xrange(4):
            comment_servers.append(
                (host_prefix + str(host_number) + host_surfix, port, thread))
            (host_number, port, thread) = self.next_comment_server(
                live_type, host_number, port, thread)

        return comment_servers

# public method
    def open_comment_server(self, live_id, host, port, thread):
        if self.live_logging:
            self.log_file_obj = self.open_live_log_file(live_id)

        # main loop
        # self.schedule_stream_stat_timer()
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(SOCKET_TIMEOUT)

        retry_count = 0
        while True:
            try:
                sock.connect((host, port))
            except Exception, e:
                # possible case like connection time out
                self.logger.warning(
                    "possible network error when connecting to comment server, error: %s" % e)
                if retry_count < 5:
                    self.logger.debug(
                        "retrying to connect to comment server, retry count: %d" % retry_count)
                    time.sleep(1)
                else:
                    self.logger.error(
                        "gave up retrying to connect to comment server so quit, "
                        "retry count: %d" % retry_count)
                    return
            else:
                break
            retry_count += 1

        sock.sendall(('<thread thread="%s" version="20061206" res_form="-1"/>'
                      + chr(0)) % thread)
        self.logger.debug("*** opened live thread, server: %s,%s,%s" % (host, port, thread))
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
                    if self.live_logging:
                        self.log_live(message)

                    # self.logger.debug("server: %s,%s,%s xml: %s" %
                    #                   (host, port, thread, message))
                    # wrap message using dummy "elements" tag to avoid parse error
                    message = "<elements>" + message + "</elements>"

                    try:
                        element = etree.fromstring(message)
                    except etree.XMLSyntaxError, e:
                        self.logger.warning("nicolive xml parse error: %s" % e)
                        self.logger.debug("xml: %s" % message)

                    try:
                        thread_element = element.xpath("//elements/thread")
                        if 0 < len(thread_element):
                            # self.logger.debug("server: %s,%s,%s xml: %s" %
                            #                   (host, port, thread, message))
                            result_code = thread_element[0].attrib.get('resultcode')
                            if result_code == "1":
                                # no comments will be provided from this thread
                                should_close_connection = True
                                break
                        else:
                            chats = element.xpath("//elements/chat")
                            if 1 < len(chats):
                                # self.logger.debug("xml: %s" % message)
                                pass
                            for chat in chats:
                                # self.logger.debug(etree.tostring(chat))
                                user_id = chat.attrib.get('user_id')
                                premium = chat.attrib.get('premium')
                                if premium is None:
                                    premium = "0"
                                comment = chat.text
                                """
                                self.logger.debug(
                                    "server: %s,%s,%s user_id: %s comment: %s" %
                                    (host, port, thread, user_id, comment))
                                """
                                if comment == self.last_comment:
                                    continue
                                self.last_comment = comment
                                self.comment_count += 1

                                NicoLive.sum_total_comment_count += 1

                                for monitoring_user_id in self.monitoring_user_ids:
                                    if self.force_debug_tweet:
                                        user_id = monitoring_user_id
                                    if user_id == monitoring_user_id:
                                        self.update_twitter_status(live_id, user_id, comment)
                                        # uncomment this to simulate duplicate tweet
                                        # self.update_twitter_status(live_id, user_id, comment)
                                    if self.force_debug_tweet:
                                        should_close_connection = True
                                        break

                                if premium in ['2', '3'] and comment == "/disconnect":
                                    # see the references below for details of the conbination of
                                    # premium attribute value and disconnect command:
                                    # - http://www.yukun.info/blog/2008/08/python-if-for-in.html
                                    # - https://twitter.com/Hemus_/status/6766945512
                                    # self.logger.debug(
                                    #     "detected command: %s w/ premium: %s" %
                                    #     (comment, premium))
                                    # self.logger.debug("disconnect, xml: %s" % message)
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
        # self.logger.debug("%s, (socket closed.)" % live_id)
        self.logger.debug("*** closed live thread, server: %s,%s,%s comments: %s" %
                          (host, port, thread, self.comment_count))

        if self.live_logging:
            self.log_file_obj.close()

    def start(self, mail, password, community_id, live_id):
        """
        try:
            (community_name, live_name) = self.get_stream_info(live_id)
            self.logger.debug(
                "*** stream info, community name: %s live name: %s" %
                (community_name, live_name))
        except Exception, e:
            self.logger.debug("could not get stream info: %s" % e)
        """

        (room_label, host, port, thread) = (None, None, None, None)
        retry_count = 0
        while True:
            cookie_container = NicoLive.get_cookie_container(mail, password)
            try:
                (room_label, host, port, thread) = self.get_player_status(
                    cookie_container, live_id)
                break
            except UnexpectedStatusError, e:
                # possible error code list: http://looooooooop.blog35.fc2.com/blog-entry-1159.html
                if e.code == "require_community_member":
                    self.logger.debug("live is 'require_community_member', so skip, "
                                      "error: %s" % e)
                    break
                elif e.code in ["notfound", "deletedbyuser", "deletedbyvisor",
                                "violated", "usertimeshift", "closed", "noauth"]:
                    self.logger.debug("caught regular error in get_player_status(), so quit, "
                                      "error: %s" % e)
                    break
                else:
                    if e.code == "comingsoon":
                        self.logger.debug("live is 'comingsoon', so retry, error: %s" % e)
                        time.sleep(3)
                    else:
                        # possible case of session expiration, so clearing container and retry
                        self.logger.warning(
                            "caught irregular error in get_player_status(), error: %s" % e)
                        NicoLive.cookie_container = None

                    if retry_count < 5:
                        self.logger.debug(
                            "retrying get_player_status(), retry count: %s" % retry_count)
                    else:
                        self.logger.error(
                            "gave up retrying get_player_status(), so quit, retry count: %s" %
                            retry_count)
                        break
            retry_count += 1

        if (room_label is not None and
                host is not None and port is not None and thread is not None):
            comment_servers = self.get_comment_servers(room_label, host, port, thread)
            # self.logger.debug("comment servers: %s" % comment_servers)

            ts = []
            for (host, port, thread) in comment_servers:
                nicolive = NicoLive()
                t = threading.Thread(name="%s,%s,%s" % (community_id, live_id, thread),
                                     target=nicolive.open_comment_server,
                                     args=(live_id, host, port, thread))
                ts.append(t)
                t.start()

            for t in ts:
                t.join()

            # self.logger.debug("finished all sub threads")
            if self.live_logging:
                self.gzip_live_log_file(live_id)


if __name__ == "__main__":
    logging.config.fileConfig(NICOCOMMENT_CONFIG)

    # """
    nicolive = NicoLive()
    nicolive.start(os.sys.argv[1], os.sys.argv[2], 0, os.sys.argv[3])
    # """

    """
    nicolive = NicoLive()
    nicolive.update_twitter_status(0, "784552", u"日本語")
    nicolive.update_twitter_status(0, "784552", u"日本語")
    nicolive.update_twitter_status(0, "784552", u"abc")
    nicolive.update_twitter_status(0, "784552", u"日本語")
    """

    """
    nicolive = NicoLive()
    # user
    comment_servers = nicolive.get_comment_servers(
        u"co12345", "msg103.live.nicovideo.jp", 2808, 1314071859)
    logging.debug(comment_servers)

    comment_servers = nicolive.get_comment_servers(
        u"立ち見A列", "msg103.live.nicovideo.jp", 2808, 1314071859)
    logging.debug(comment_servers)

    comment_servers = nicolive.get_comment_servers(
        u"立ち見A列", "msg103.live.nicovideo.jp", 2805, 1314071859)
    logging.debug(comment_servers)

    comment_servers = nicolive.get_comment_servers(
        u"立ち見A列", "msg101.live.nicovideo.jp", 2805, 1314071859)
    logging.debug(comment_servers)

    comment_servers = nicolive.get_comment_servers(
        u"立ち見B列", "msg101.live.nicovideo.jp", 2805, 1314071859)
    logging.debug(comment_servers)

    comment_servers = nicolive.get_comment_servers(
        u"立ち見C列", "msg101.live.nicovideo.jp", 2805, 1314071859)
    logging.debug(comment_servers)

    comment_servers = nicolive.get_comment_servers(
        u"立ち見Z列", "msg101.live.nicovideo.jp", 2805, 1314071859)
    logging.debug(comment_servers)

    comment_servers = nicolive.get_comment_servers(
        u"xxx", "msg101.live.nicovideo.jp", 2805, 1314071859)
    logging.debug(comment_servers)

    # official
    servers = nicolive.get_comment_servers(
        u"ch12345", "omsg101.live.nicovideo.jp", 2805, 1314071859)
    logging.debug(servers)

    servers = nicolive.get_comment_servers(
        u"ch12345", "omsg104.live.nicovideo.jp", 2808, 1314071859)
    logging.debug(servers)

    servers = nicolive.get_comment_servers(
        u"ch12345", "omsg103.live.nicovideo.jp", 2814, 1314071859)
    logging.debug(servers)

    servers = nicolive.get_comment_servers(
        u"xxx", "omsg103.live.nicovideo.jp", 2814, 1314071859)
    logging.debug(servers)
    """
