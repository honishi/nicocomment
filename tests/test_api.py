#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import logging
import re
import threading
import time
from datetime import datetime as dt
from datetime import timedelta
import pytest

import nicoapi

TEST_CONFIG = os.path.dirname(os.path.abspath(__file__)) + '/test.config'


class TestNicoAPI(object):
# pytest methods, object injection
    def pytest_funcarg__api(self):
        mail = os.environ.get('NICOAPI_MAIL', '')
        password = os.environ.get('NICOAPI_PASSWORD', '')

        return nicoapi.NicoAPI(mail, password)

# test methods, main
    def test_main(self, api):
        # ticket
        ticket = api.get_ticket()
        logging.info(ticket)

        assert re.match(r'nicolive_antenna_\d+', ticket)

        # alert server
        communities, host, port, thread = api.get_alert_status(ticket)
        logging.info('communities: %s' % communities)
        logging.info('host: %s port: %s thread: %s' % (host, port, thread))

        assert 0 < len(communities)
        assert re.match(r'.+\.live\.nicovideo\.jp', host)
        assert 0 < port and 0 < thread

        # alert
        self.last_received_live_id = None

        alert_thread = threading.Thread(
            target=api.open_alert_server,
            args=(host, port, thread, self.handle_alert))
        alert_thread.start()

        self.prepare_to_wait_async_callback()
        callback_call_count = self.wait_async_callback(20, 1)
        api.close_alert_server()

        assert 0 < callback_call_count

        # stream info
        community_name, live_name = api.get_stream_info(self.last_received_live_id)
        logging.info('community_name: %s live_name: %s' % (community_name, live_name))

        assert len(community_name) and len(live_name)

        # TODO: live

    def handle_alert(self, live_id, community_id, user_id):
        logging.info('live alert received, live_id: %s community_id: %s user_id: %s' %
                     (live_id, community_id, user_id))

        if (re.match(r'\d+', live_id) and
                re.match(r'c(?:o|h)\d+', community_id) and
                re.match(r'\d+', user_id)):
            self.receive_async_callback()

        self.last_received_live_id = live_id

# private methods, async test utility
    def prepare_to_wait_async_callback(self):
        self.async_callback_call_count = 0

    def receive_async_callback(self):
        self.async_callback_call_count += 1

    def wait_async_callback(self, wait_duration, required_callback_count=1):
        test_start_time = dt.now()
        test_duration = timedelta(seconds=wait_duration)

        while True:
            if (dt.now() - test_start_time > test_duration or
                    required_callback_count <= self.async_callback_call_count):
                break
            time.sleep(0.1)

        return self.async_callback_call_count

    @pytest.mark.parametrize(("input", "expected"), [
        ((u"co12345", "msg103.live.nicovideo.jp", 2808, 1314071859),    # input
         [("msg103.live.nicovideo.jp", 2808, 1314071859),               # expected
          ("msg103.live.nicovideo.jp", 2809, 1314071860),
          ("msg103.live.nicovideo.jp", 2810, 1314071861),
          ("msg103.live.nicovideo.jp", 2811, 1314071862)]),
        ((u"立ち見A列", "msg103.live.nicovideo.jp", 2808, 1314071859),
         [("msg103.live.nicovideo.jp", 2807, 1314071858),
          ("msg103.live.nicovideo.jp", 2808, 1314071859),
          ("msg103.live.nicovideo.jp", 2809, 1314071860),
          ("msg103.live.nicovideo.jp", 2810, 1314071861)]),
        ((u"立ち見A列", "msg103.live.nicovideo.jp", 2805, 1314071859),
         [("msg102.live.nicovideo.jp", 2814, 1314071858),
          ("msg103.live.nicovideo.jp", 2805, 1314071859),
          ("msg103.live.nicovideo.jp", 2806, 1314071860),
          ("msg103.live.nicovideo.jp", 2807, 1314071861)]),
        ((u"立ち見A列", "msg101.live.nicovideo.jp", 2805, 1314071859),
         [("msg104.live.nicovideo.jp", 2814, 1314071858),
          ("msg101.live.nicovideo.jp", 2805, 1314071859),
          ("msg101.live.nicovideo.jp", 2806, 1314071860),
          ("msg101.live.nicovideo.jp", 2807, 1314071861)]),
        ((u"立ち見B列", "msg101.live.nicovideo.jp", 2805, 1314071859),
         [("msg104.live.nicovideo.jp", 2813, 1314071857),
          ("msg104.live.nicovideo.jp", 2814, 1314071858),
          ("msg101.live.nicovideo.jp", 2805, 1314071859),
          ("msg101.live.nicovideo.jp", 2806, 1314071860)]),
        ((u"立ち見C列", "msg101.live.nicovideo.jp", 2805, 1314071859),
         [("msg104.live.nicovideo.jp", 2812, 1314071856),
          ("msg104.live.nicovideo.jp", 2813, 1314071857),
          ("msg104.live.nicovideo.jp", 2814, 1314071858),
          ("msg101.live.nicovideo.jp", 2805, 1314071859)]),
        ((u"立ち見Z列", "msg101.live.nicovideo.jp", 2805, 1314071859),
         [("msg101.live.nicovideo.jp", 2805, 1314071859)]),
        ((u"xxx", "msg101.live.nicovideo.jp", 2805, 1314071859),
         [("msg101.live.nicovideo.jp", 2805, 1314071859)]),
        ((u"ch12345", "omsg101.live.nicovideo.jp", 2815, 1314071859),
         [("omsg101.live.nicovideo.jp", 2815, 1314071859),
          ("omsg102.live.nicovideo.jp", 2815, 1314071860),
          ("omsg103.live.nicovideo.jp", 2815, 1314071861),
          ("omsg104.live.nicovideo.jp", 2815, 1314071862)]),
        ((u"ch12345", "omsg104.live.nicovideo.jp", 2815, 1314071859),
         [("omsg104.live.nicovideo.jp", 2815, 1314071859),
          ("omsg101.live.nicovideo.jp", 2816, 1314071860),
          ("omsg102.live.nicovideo.jp", 2816, 1314071861),
          ("omsg103.live.nicovideo.jp", 2816, 1314071862)]),
        ((u"ch12345", "omsg103.live.nicovideo.jp", 2817, 1314071859),
         [("omsg103.live.nicovideo.jp", 2817, 1314071859),
          ("omsg104.live.nicovideo.jp", 2817, 1314071860),
          ("omsg101.live.nicovideo.jp", 2815, 1314071861),
          ("omsg102.live.nicovideo.jp", 2815, 1314071862)]),
        ((u"xxx", "omsg103.live.nicovideo.jp", 2815, 1314071859),
         [("omsg103.live.nicovideo.jp", 2815, 1314071859)]),
        ]
    )
    def test_comment_servers(self, api, input, expected):
        room_label, host, port, thread = input

        live_type = api.get_live_type_with_host(host)
        distance_from_arena = api.get_distance_from_arena(live_type, room_label)
        comment_servers = api.get_comment_servers(
            live_type, distance_from_arena, host, port, thread)

        assert cmp(comment_servers, expected) == 0

    """
    def test_tweet(self):
        nl = NicoLive("example@example.com", "password", "12345", "67890")
        nl.update_twitter_status("784552", u"日本語")
        nl.update_twitter_status("784552", u"日本語")
        nl.update_twitter_status("784552", u"abc")
        nl.update_twitter_status("784552", u"日本語")
    """


if __name__ == '__main__':
    pass
