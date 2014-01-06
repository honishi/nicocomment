# -*- coding: utf-8 -*-

import logging
import urllib
import urllib2
import socket
import cookielib
import time
import re
from datetime import datetime as dt
from datetime import timedelta
import threading
from lxml import etree

from nicoapi.error import *

# enum values
LIVE_TYPE_UNKNOWN = 0
LIVE_TYPE_OFFICIAL = 1
LIVE_TYPE_USER = 2

# constants, urls
ANTENNA_URL = 'https://secure.nicovideo.jp/secure/login?site=nicolive_antenna'
GET_ALERT_STATUS_URL = 'http://live.nicovideo.jp/api/getalertstatus'
GET_STREAM_INFO_URL = "http://live.nicovideo.jp/api/getstreaminfo/lv"
LOGIN_URL = "https://secure.nicovideo.jp/secure/login?site=niconico"
GET_PLAYER_STATUS_URL = "http://watch.live.nicovideo.jp/api/getplayerstatus?v=lv"

# retry values
RETRY_INTERVAL_GET_COOKIE_CONTAINER = 1
RETRY_INTERVAL_OPEN_COMMENT_SERVER_SOCKET = 1

MAX_RETRY_COUNT_GET_COOKIE_CONTAINER = 5
MAX_RETRY_COUNT_OPEN_COMMENT_SERVER_SOCKET = 5

# constants, alert
MAX_RECENT_LIVES_COUNT = 10000

# constants, socket
DEFAULT_SOCKET_TIMEOUT_ALERT = 60
DEFAULT_SOCKET_TIMEOUT_LIVE = 60 * 30

# comment server magic numbers
COMMENT_SERVER_HOST_NUMBER_FIRST = 101
COMMENT_SERVER_HOST_NUMBER_LAST = 104
COMMENT_SERVER_PORT_OFFICIAL_FIRST = 2815
COMMENT_SERVER_PORT_OFFICIAL_LAST = 2817
COMMENT_SERVER_PORT_USER_FIRST = 2805
COMMENT_SERVER_PORT_USER_LAST = 2814


class NicoAPI(object):
    # cookie
    cookie_container_lock = threading.Lock()
    cookie_container = None

    # live
    all_opened_thread_ids = []

# magic methods
    def __init__(self, mail, password):
        self.mail = mail
        self.password = password

        # alert
        self.alert_socket = None
        self.should_close_alert_socket = False
        self.recent_lives = []

        # live
        self.community_id = None
        self.live_id = None
        self.chat_handler = None
        self.raw_handler = None
        self.comment_servers = []
        self.opened_live_threads = None
        self.thread_local_vars = threading.local()

        # logging.debug('nicoapi initialized.')

    def __del__(self):
        pass

# public methods
    # alert
    def listen_alert(self, alert_handler):
        ticket = self.get_ticket()
        logging.debug('ticket: %s' % ticket)

        communities, host, port, thread = self.get_alert_status(ticket)
        logging.debug('communities: %s' % communities)
        logging.debug('host: %s port: %s thread: %s' % (host, port, thread))

        self.open_alert_server(host, port, thread, alert_handler)

    # stream info
    def get_stream_info(self, live_id):
        response = urllib2.urlopen(GET_STREAM_INFO_URL + live_id).read()
        # logging.debug('response: %s' % response)
        """
        <getstreaminfo status="ok">
            <request_id>lv163956337</request_id>
            <streaminfo>
                <title>Saints Row Ⅳ</title>
                <description>宇宙人がやってｋぅる</description>
                <provider_type>community</provider_type>
                <default_community>co1755128</default_community>
            </streaminfo>
            <communityinfo>
                <name>マーガリンの溶ける頃に</name>
                <thumbnail>
                    http://icon.nimg.jp/community/s/175/co1755128.jpg?1385794582
                </thumbnail>
            </communityinfo>
            <adsense>
                <item>
                    <name>&gt;&gt;ニコ生クルーズで他の番組を探す</name>
                    <url>http://live.nicovideo.jp/cruise</url>
                </item>
            </adsense>
        </getstreaminfo>
        """

        root_element = etree.fromstring(response)
        stream_info_elements = root_element.xpath("//getstreaminfo")

        if stream_info_elements:
            stream_info_element = stream_info_elements[0]
            status = stream_info_element.attrib['status']
            if status != 'ok':
                code = stream_info_element.xpath("//error/code")[0].text
                raise NicoAPIError(status, code, response)

            community_name = stream_info_element.xpath("//communityinfo/name")[0].text
            live_name = stream_info_element.xpath("//streaminfo/title")[0].text
            # set "n/a", when no value provided; like <title/>
            if community_name is None:
                community_name = "n/a"
            if live_name is None:
                live_name = "n/a"
        else:
            raise NicoAPIError(info=response)

        return self.convert_to_unicode(community_name), self.convert_to_unicode(live_name)

    def listen_live(self, community_id, live_id, chat_handler=None, raw_handler=None):
        self.community_id = community_id    # used only for logging, so can be specified as ''
        self.live_id = live_id
        self.chat_handler = chat_handler
        self.raw_handler = raw_handler

        room_label, host, port, thread = self.get_player_status(self.live_id)
        logging.debug("*** getplayerstatus, room_label: %-9s host: %s port: %s thread: %s" %
                      (room_label, host, port, thread))

        if room_label and host and port and thread:
            live_type = self.get_live_type_with_host(host)
            distance_from_arena = self.get_distance_from_arena(live_type, room_label)

            self.comment_servers = self.get_comment_servers(
                live_type, distance_from_arena, host, port, thread)

            self.opened_live_threads = []
            for unused_i in xrange(distance_from_arena+1):
                self.add_live_thread()

            for live_thread in self.opened_live_threads:
                live_thread.join()

        # set None to release strong reference to nicolive object
        self.chat_handler = None
        self.raw_handler = None

# private methods, core utility
    @classmethod
    def reset_cookie_container(cls):
        cls.cookie_container = None

    @classmethod
    def get_cookie_container(cls, mail, password):
        # logging.debug("entering to critical section: get_cookie_container")

        with cls.cookie_container_lock:
            # logging.debug("entered to critical section: get_cookie_container")
            if cls.cookie_container is None:
                retry_count = 0
                while True:
                    try:
                        cookiejar = cookielib.CookieJar()
                        opener = urllib2.build_opener(urllib2.HTTPCookieProcessor(cookiejar))
                        opener.open(LOGIN_URL, 'mail=%s&password=%s' % (mail, password))
                        cls.cookie_container = opener
                    except Exception, e:
                        logging.warning(
                            "possible network error when initializing cookie container, "
                            "error: %s" % e)
                        if retry_count < MAX_RETRY_COUNT_GET_COOKIE_CONTAINER:
                            logging.debug(
                                "retrying cookie container initialization, retry count: %d/%d" %
                                (retry_count, MAX_RETRY_COUNT_GET_COOKIE_CONTAINER))
                            time.sleep(RETRY_INTERVAL_GET_COOKIE_CONTAINER)
                        else:
                            logging.error(
                                "gave up retrying cookie container initialization, "
                                "retry count: %d/%d" %
                                (retry_count, MAX_RETRY_COUNT_GET_COOKIE_CONTAINER))
                            break   # = return None
                    else:
                        logging.debug("opened cookie container")
                        break
                    retry_count += 1

            # logging.debug("exiting from critical section: get_cookie_container")
        # logging.debug("exited from critical section: get_cookie_container")

        return cls.cookie_container

# private methods, alert
    def get_ticket(self):
        ticket = None

        parameter = {'mail': self.mail, 'password': self.password}
        response = urllib2.urlopen(ANTENNA_URL, urllib.urlencode(parameter)).read()
        # logging.debug('response: %s' % response)
        """
        <?xml version="1.0" encoding="utf-8"?>
        <nicovideo_user_response status="ok">
            <ticket>nicolive_antenna_2229597313331299071345166149</ticket>
        </nicovideo_user_response>
        """

        """
        memo; lxml.tree object conversion...
            etree.fromstring(<str>) --> <etree._Element object>
            <etree._Element object>.xpath() --> <list>
            <list>[x] --> <etree._Element object>
        """

        root_element = etree.fromstring(response)
        response_elements = root_element.xpath('//nicovideo_user_response')

        if response_elements:
            response_element = response_elements[0]
            status = response_element.attrib['status']
            if status != 'ok':
                raise NicoAPIError(status, info=response)
            ticket = response_element.xpath('//ticket')[0].text
        else:
            raise NicoAPIError(info=response)

        return self.convert_to_unicode(ticket)

    def get_alert_status(self, ticket):
        communities = []
        host, port, thread = None, None, None

        parameter = {'ticket': ticket}
        response = urllib2.urlopen(GET_ALERT_STATUS_URL, urllib.urlencode(parameter)).read()
        # logging.debug('response: %s' % response)
        """
        <?xml version='1.0' encoding='utf-8'?>
        <getalertstatus status="ok" time="1388066052">
            <user_id>22295xxx</user_id>
            ...
            <is_premium>1</is_premium>
            <communities>
                <community_id>co313394</community_id>
                ...
            </communities>
            <ms>
                <addr>twr02.live.nicovideo.jp</addr>
                <port>2531</port>
                <thread>1000000013</thread>
            </ms>
        </getalertstatus>
        """

        root_element = etree.fromstring(response)
        alert_status_elements = root_element.xpath('//getalertstatus')

        if alert_status_elements:
            alert_status_element = alert_status_elements[0]
            status = alert_status_element.attrib['status']
            if status != 'ok':
                raise NicoAPIError(status, info=response)

            for community_id in alert_status_element.xpath('//communities/community_id'):
                communities.append(community_id.text)

            host = alert_status_element.xpath('//ms/addr')[0].text
            port = int(alert_status_element.xpath('//ms/port')[0].text)
            thread = int(alert_status_element.xpath('//ms/thread')[0].text)
        else:
            raise NicoAPIError(info=response)

        return communities, host, port, thread

    def open_alert_server(self, host, port, thread, alert_handler):
        self.alert_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.alert_socket.settimeout(DEFAULT_SOCKET_TIMEOUT_ALERT)

        self.alert_socket.connect((host, port))
        self.alert_socket.sendall(
            '<thread thread="%d" version="20061206" res_form="-1"/>' % thread + chr(0))

        self.should_close_alert_socket = False
        message = ''

        while True:
            try:
                recved = self.alert_socket.recv(1024)
                for char in recved:
                    if char == chr(0):
                        self.parse_alert_stream(alert_handler, message)
                        message = ''
                    else:
                        message += char
            except socket.timeout, e:
                if self.should_close_alert_socket:
                    break
                logging.warning('unexpected timeout at alert socket.recv(), %s' % e)
                time.sleep(1)
            except Exception, e:
                logging.error('unexpected error at alert socket.recv(), %s' % e)
                raise

        self.alert_socket.close()

    def close_alert_server(self):
        self.should_close_alert_socket = True
        # simulate socket shutdown to set timeout to very short interval
        self.alert_socket.settimeout(0.1)

    def parse_alert_stream(self, alert_handler, message):
        root_element = etree.fromstring(message)

        try:
            thread_elements = root_element.xpath('//thread')
            if thread_elements:
                logging.info('started receiving live information.')

            chat_elements = root_element.xpath('//chat')
            if chat_elements:
                for chat_element in chat_elements:
                    # logging.debug(etree.tostring(chat))
                    lives = chat_element.text.split(',')

                    if len(lives) == 3:
                        live_id, community_id, user_id = lives
                        if self.is_duplicate_live(live_id):
                            logging.debug('skipped duplicate live, '
                                          'live_id: %s community_id: %s user_id: %s' %
                                          (live_id, community_id, user_id))
                        elif community_id == 'official':
                            logging.debug('skipped official live, '
                                          'live_id: %s community_id: %s user_id: %s' %
                                          (live_id, community_id, user_id))
                        else:
                            alert_handler(live_id, community_id, user_id)
        except Exception, e:
            logging.debug('failed to parse alert stream, error: %s' % e)

    def is_duplicate_live(self, live_id):
        is_duplicate = False

        if self.recent_lives.count(live_id):
            is_duplicate = True

        if MAX_RECENT_LIVES_COUNT < len(self.recent_lives):
            self.recent_lives.pop(0)
        self.recent_lives.append(live_id)

        return is_duplicate

# private methods, live
    def get_player_status(self, live_id):
        cookie_container = NicoAPI.get_cookie_container(self.mail, self.password)
        response = cookie_container.open(GET_PLAYER_STATUS_URL + live_id).read()
        # logging.debug('response: %s' % response)
        """
        <getplayerstatus status="ok" time="1388153590">
            <stream>
                <id>lv163973121</id>
                <title>xxx</title>
                <description>xxx</description>
                <provider_type>community</provider_type>
                <default_community>co1061242</default_community>
                <internati onal="onal">... </internati>
            </stream>
            <user>
                <user_id>xxx</user_id>
                <nickname>xxx</nickname>
                <is_premium>xxx</is_premium>
                <room_label>co1061242</room_label>
                <room_seetno>0</room_seetno>
                ...
            </user>
            <rtmp is_fms="1" rtmpt_port="80">...</rtmp>
            <ms>
                <addr> msg101.live.nicovideo.jp </addr>
                <port> 2806 </port>
                <thread> 1320508715 </thread>
            </ms>
            <tid_list>...</tid_list>
        </getplayerstatus>
        """
        root_element = etree.fromstring(response)
        player_status_elements = root_element.xpath("//getplayerstatus")

        if player_status_elements:
            player_status_element = player_status_elements[0]
            status = player_status_element.attrib['status']

            if status != 'ok':
                code = player_status_element.xpath("//error/code")[0].text
                raise NicoAPIInitializeLiveError(status, code, response)

            room_label = player_status_element.xpath("//user/room_label")[0].text
            host = player_status_element.xpath("//ms/addr")[0].text
            port = int(player_status_element.xpath("//ms/port")[0].text)
            thread = int(player_status_element.xpath("//ms/thread")[0].text)
        else:
            raise NicoAPIError()

        return room_label, host, port, thread

    def add_live_thread(self):
        # room_position 0: arena, 1: stand_a, 2: ...
        target_room_position = len(self.opened_live_threads)
        if not target_room_position < len(self.comment_servers):
            logging.warning("could not add live thread, opened: %d comment servers: %d" %
                            (target_room_position, len(self.comment_servers)))
            return

        host, port, thread = self.comment_servers[target_room_position]
        live_thread = threading.Thread(
            name="%s,%s,%s/%d" % (self.community_id, self.live_id, thread, target_room_position),
            target=self.open_comment_server,
            args=(target_room_position, host, port, thread))

        self.opened_live_threads.append(live_thread)

        try:
            live_thread.start()
        except Exception, e:
            logging.error("could not start thread, error: %s" % e)

# private methods, calculate comment server
    def get_live_type_with_host(self, host):
        live_type = LIVE_TYPE_UNKNOWN

        if re.match(r'^o', host):
            live_type = LIVE_TYPE_OFFICIAL
        else:
            live_type = LIVE_TYPE_USER

        return live_type

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
            host, port, thread = self.get_arena_comment_server(
                live_type, distance_from_arena, host, port, thread)
            # arena + stand a + stand b + stand c
            room_count = 4

        host_prefix, host_number, host_surfix = self.split_host(host)
        for unused_i in xrange(room_count):
            comment_servers.append(
                (host_prefix + str(host_number) + host_surfix, port, thread))
            host_number, port, thread = self.next_comment_server(
                live_type, host_number, port, thread)

        return comment_servers

    # utility
    def split_host(self, host):
        matched_host = re.match(r'((?:o|)msg)(\d+)(\..+)', host)
        if not matched_host:
            return (None, None, None)

        host_prefix = matched_host.group(1)
        host_number = int(matched_host.group(2))
        host_surfix = matched_host.group(3)

        return host_prefix, host_number, host_surfix

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

# private methods, comment server socket
    def open_comment_server(self, room_position, host, port, thread):
        self.thread_local_vars.room_position = room_position
        self.thread_local_vars.comment_count = 0
        self.thread_local_vars.tweeted_open_room = False

        if thread in NicoAPI.all_opened_thread_ids:
            logging.warning("live thread is already opened, so skip.")
            return

        logging.debug("*** opened live thread, server: %s, %s, %s" % (host, port, thread))
        NicoAPI.all_opened_thread_ids.append(thread)

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
                        # logging.debug(message)

                        should_close_connection = self.parse_live_stream(message)
                        message = ""
                    else:
                        message += character
                if recved == '' or should_close_connection:
                    # logging.debug("break")
                    break
            sock.close()

        logging.debug("*** closed live thread, server: %s, %s, %s comments: %s" %
                      (host, port, thread, self.thread_local_vars.comment_count))
        NicoAPI.all_opened_thread_ids.remove(thread)

    def open_comment_server_socket(self, host, port, thread):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(DEFAULT_SOCKET_TIMEOUT_LIVE)

        retry_count = 0
        while True:
            try:
                sock.connect((host, port))
                sock.sendall(
                    '<thread thread="%s" version="20061206" res_form="-1"/>' % thread + chr(0))
                break
            except Exception, e:
                # possible case like connection time out
                logging.warning(
                    "possible network error when connecting to comment server, error: %s" % e)
                if retry_count < MAX_RETRY_COUNT_OPEN_COMMENT_SERVER_SOCKET:
                    logging.debug(
                        "retrying to connect to comment server, retry count: %d/%d" %
                        (retry_count, MAX_RETRY_COUNT_OPEN_COMMENT_SERVER_SOCKET))
                    time.sleep(RETRY_INTERVAL_OPEN_COMMENT_SERVER_SOCKET)
                else:
                    logging.error(
                        "gave up retrying to connect to comment server, retry count: %d/%d" %
                        (retry_count, MAX_RETRY_COUNT_OPEN_COMMENT_SERVER_SOCKET))
                    return None
            retry_count += 1

        return sock

    def parse_live_stream(self, message):
        should_close_connection = False

        if self.raw_handler:
            self.raw_handler(message)

        # wrap message using dummy "elements" tag to avoid parse error
        message = "<elements>" + message + "</elements>"

        try:
            root_element = etree.fromstring(message)
        except etree.XMLSyntaxError, e:
            logging.warning("nicolive xml parse error: %s" % e)
            logging.debug("xml: %s" % message)

        try:
            thread_elements = root_element.xpath("//elements/thread")
            if 0 < len(thread_elements):
                result_code = thread_elements[0].attrib['resultcode']
                if result_code == "1":
                    # logging.debug("thread xml: %s" % message)
                    # no comments will be provided from this thread
                    should_close_connection = True
                else:
                    # successfully opened thread
                    pass
            else:
                chat_elements = root_element.xpath("//elements/chat")
                if 1 < len(chat_elements):
                    # logging.debug("chat xml: %s" % message)
                    pass
                for chat_element in chat_elements:
                    self.thread_local_vars.comment_count += 1

                    user_id, premium, comment = self.parse_chat_element(chat_element)
                    self.check_ifseetno(comment)
                    should_close_connection = self.check_disconnect(premium, comment)

                    if self.chat_handler:
                        self.chat_handler(
                            self.thread_local_vars.room_position, user_id, premium, comment)

                    if should_close_connection:
                        break
        except KeyError:
            logging.debug("received unrecognized data.")

        return should_close_connection

    def parse_chat_element(self, chat):
        # logging.debug(etree.tostring(chat))
        user_id = chat.attrib.get('user_id')
        premium = chat.attrib.get('premium')
        if premium is None:
            premium = "0"
        comment = chat.text

        return user_id, premium, self.convert_to_unicode(comment)

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

# private methods, utility
    def convert_to_unicode(self, s):
        if isinstance(s, str):
            return unicode(s, 'utf8')
        return s


if __name__ == "__main__":
    pass
