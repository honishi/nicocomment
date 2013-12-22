#!/usr/bin/env python
# -*- coding: utf-8 -*-

from nicolive import *
import pytest


class TestNicoLive(object):
    def check_comment_servers(self, room_label, host, port, thread, expected_comment_servers):
        nl = NicoLive("example@example.com", "password", "12345", "67890")

        live_type = nl.get_live_type_with_host(host)
        distance_from_arena = nl.get_distance_from_arena(live_type, room_label)
        comment_servers = nl.get_comment_servers(
            live_type, distance_from_arena, host, port, thread)

        print comment_servers
        assert cmp(comment_servers, expected_comment_servers) == 0

    def test_comment_servers(self):
        # user
        self.check_comment_servers(
            u"co12345", "msg103.live.nicovideo.jp", 2808, 1314071859,
            [("msg103.live.nicovideo.jp", 2808, 1314071859),
             ("msg103.live.nicovideo.jp", 2809, 1314071860),
             ("msg103.live.nicovideo.jp", 2810, 1314071861),
             ("msg103.live.nicovideo.jp", 2811, 1314071862)])

        self.check_comment_servers(
            u"立ち見A列", "msg103.live.nicovideo.jp", 2808, 1314071859,
            [("msg103.live.nicovideo.jp", 2807, 1314071858),
             ("msg103.live.nicovideo.jp", 2808, 1314071859),
             ("msg103.live.nicovideo.jp", 2809, 1314071860),
             ("msg103.live.nicovideo.jp", 2810, 1314071861)])

        self.check_comment_servers(
            u"立ち見A列", "msg103.live.nicovideo.jp", 2805, 1314071859,
            [("msg102.live.nicovideo.jp", 2814, 1314071858),
             ("msg103.live.nicovideo.jp", 2805, 1314071859),
             ("msg103.live.nicovideo.jp", 2806, 1314071860),
             ("msg103.live.nicovideo.jp", 2807, 1314071861)])

        self.check_comment_servers(
            u"立ち見A列", "msg101.live.nicovideo.jp", 2805, 1314071859,
            [("msg104.live.nicovideo.jp", 2814, 1314071858),
             ("msg101.live.nicovideo.jp", 2805, 1314071859),
             ("msg101.live.nicovideo.jp", 2806, 1314071860),
             ("msg101.live.nicovideo.jp", 2807, 1314071861)])

        self.check_comment_servers(
            u"立ち見B列", "msg101.live.nicovideo.jp", 2805, 1314071859,
            [("msg104.live.nicovideo.jp", 2813, 1314071857),
             ("msg104.live.nicovideo.jp", 2814, 1314071858),
             ("msg101.live.nicovideo.jp", 2805, 1314071859),
             ("msg101.live.nicovideo.jp", 2806, 1314071860)])

        self.check_comment_servers(
            u"立ち見C列", "msg101.live.nicovideo.jp", 2805, 1314071859,
            [("msg104.live.nicovideo.jp", 2812, 1314071856),
             ("msg104.live.nicovideo.jp", 2813, 1314071857),
             ("msg104.live.nicovideo.jp", 2814, 1314071858),
             ("msg101.live.nicovideo.jp", 2805, 1314071859)])

        self.check_comment_servers(
            u"立ち見Z列", "msg101.live.nicovideo.jp", 2805, 1314071859,
            [("msg101.live.nicovideo.jp", 2805, 1314071859)])

        self.check_comment_servers(
            u"xxx", "msg101.live.nicovideo.jp", 2805, 1314071859,
            [("msg101.live.nicovideo.jp", 2805, 1314071859)])

        # official
        self.check_comment_servers(
            u"ch12345", "omsg101.live.nicovideo.jp", 2815, 1314071859,
            [("omsg101.live.nicovideo.jp", 2815, 1314071859),
             ("omsg102.live.nicovideo.jp", 2815, 1314071860),
             ("omsg103.live.nicovideo.jp", 2815, 1314071861),
             ("omsg104.live.nicovideo.jp", 2815, 1314071862)])

        self.check_comment_servers(
            u"ch12345", "omsg104.live.nicovideo.jp", 2815, 1314071859,
            [("omsg104.live.nicovideo.jp", 2815, 1314071859),
             ("omsg101.live.nicovideo.jp", 2816, 1314071860),
             ("omsg102.live.nicovideo.jp", 2816, 1314071861),
             ("omsg103.live.nicovideo.jp", 2816, 1314071862)])

        self.check_comment_servers(
            u"ch12345", "omsg103.live.nicovideo.jp", 2817, 1314071859,
            [("omsg103.live.nicovideo.jp", 2817, 1314071859),
             ("omsg104.live.nicovideo.jp", 2817, 1314071860),
             ("omsg101.live.nicovideo.jp", 2815, 1314071861),
             ("omsg102.live.nicovideo.jp", 2815, 1314071862)])

        self.check_comment_servers(
            u"xxx", "omsg103.live.nicovideo.jp", 2815, 1314071859,
            [("omsg103.live.nicovideo.jp", 2815, 1314071859)])

    """
    def test_tweet(self):
        nl = NicoLive("example@example.com", "password", "12345", "67890")
        nl.update_twitter_status("784552", u"日本語")
        nl.update_twitter_status("784552", u"日本語")
        nl.update_twitter_status("784552", u"abc")
        nl.update_twitter_status("784552", u"日本語")
    """


if __name__ == '__main__':
    pytest.main()
