#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import ConfigParser
import logging
import logging.config
import threading
import time
import re
from datetime import datetime as dt
from datetime import timedelta
import gzip
import tweepy

import nicoapi

# tweet threasholds
OPEN_ROOM_TWEET_THREASHOLD = 2
ACTIVE_TWEET_INITIAL_THREASHOLD = 100
ACTIVE_TWEET_INCREMENT_VALUE = 100

# tweet frequency
TWEET_COUNT_THREASHOLD_UPPER = 30
TWEET_COUNT_THREASHOLD_LOWER = 10

TWEET_FREQUENCY_MODE_NORMAL = 1
TWEET_FREQUENCY_MODE_ACTIVE_ONLY = 2

# twitter, misc
TWEET_RATE_WATCHING_MINUTES = 60
DEFAULT_CREDENTIAL_KEY = "all"

# retry values
RETRY_INTERVAL_GET_STREAM_INFO = 3
RETRY_INTERVAL_LISTEN_LIVE = 3

MAX_RETRY_COUNT_GET_STREAM_INFO = 5
MAX_RETRY_COUNT_LISTEN_LIVE = 5
# retrying for 30 min for the case like comingsoon, full, block_now_count_overflow
MAX_RETRY_COUNT_LISTEN_LIVE_LONG = 30 * 60 / RETRY_INTERVAL_LISTEN_LIVE

# subthread intervals,
# global is for all lives and class-wide one, local is for a live and instance-wide one
GLOBAL_MANAGING_THREAD_INTERVAL = 10
LOCAL_MANAGING_THREAD_INTERVAL = 10

# constants, file path
NICOCOMMENT_CONFIG = os.path.dirname(os.path.abspath(__file__)) + '/nicocomment.config'
NICOCOMMENT_CONFIG_SAMPLE = NICOCOMMENT_CONFIG + '.sample'
LIVE_LOG_BASE_DIR = os.path.dirname(os.path.abspath(__file__)) + '/log/live'

# constants, service url
LIVE_URL = "http://live.nicovideo.jp/watch/lv"

LIVE_STATUS_TYPE_UNKNOWN = 0
LIVE_STATUS_TYPE_STARTED = 1
LIVE_STATUS_TYPE_FINISHED = 2

# misc settings
ENABLE_CONFIG_CACHE = False

# some debug definitions
DEBUG_LOG_COMMENT_TO_APP_LOG = False
DEBUG_LOG_COMMENT_TO_STDOUT = False
DEBUG_FORCE_USER_TWEET_AND_EXIT = False
DEBUG_SKIP_STREAM_INFO = False


class NicoLive(object):
# class variables
    instances_lock = threading.Lock()
    twitter_status_update_lock = threading.Lock()

    instances = set()
    global_managing_thread = None

    config = None

    comment_count = 0

    last_tweeted_credential_key = None
    last_tweeted_status = None
    tweets = []
    tweets_rate = 0
    tweet_frequency_mode = TWEET_FREQUENCY_MODE_NORMAL

# magic methods
    def __init__(self, mail, password, community_id, live_id, user_id):
        self.mail = mail
        self.password = password
        self.community_id = community_id
        self.live_id = live_id
        self.user_id = user_id

        self.api = nicoapi.NicoAPI(self.mail, self.password)

        self.log_file_obj = None

        self.community_name = "n/a"
        self.live_name = "n/a"
        self.live_start_time = dt.fromtimestamp(0)

        self.live_status = LIVE_STATUS_TYPE_UNKNOWN

        self.comments = []
        self.active = 0
        self.should_recalculate_active = True

        self.active_tweet_target = ACTIVE_TWEET_INITIAL_THREASHOLD
        self.open_room_tweeted = {}

        if ENABLE_CONFIG_CACHE and NicoLive.config:
            config = NicoLive.config
        else:
            config_file = NICOCOMMENT_CONFIG
            if not os.path.exists(config_file):
                config_file = NICOCOMMENT_CONFIG_SAMPLE

            config = ConfigParser.ConfigParser()
            config.read(config_file)
            NicoLive.config = config

        (self.live_logging, self.mute_user_ids, self.mute_community_ids, self.mute_live_names,
            self.mute_descriptions) = self.get_basic_config(config)
        """
        logging.debug("live_logging: %s mute_user_ids: %s mute_community_ids: %s "
                      "mute_live_names: %s mute_descriptions: %s" %
                      (self.live_logging, self.mute_user_ids, self.mute_community_ids,
                       self.mute_live_names, self.mute_descriptions))
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
        # logging.debug("__del__")

    # utility
    def get_basic_config(self, config):
        section = "nicolive"

        live_logging = self.get_bool_for_option(config, section, "live_logging")

        mute_user_ids = self.get_mutes(config, section, "mute_user_ids")
        mute_community_ids = self.get_mutes(config, section, "mute_community_ids")
        mute_live_names = self.get_mutes(config, section, "mute_titles")
        mute_descriptions = self.get_mutes(config, section, "mute_descriptions")

        return live_logging, mute_user_ids, mute_community_ids, mute_live_names, mute_descriptions

    def get_mutes(self, config, section, mute_option):
        value = []

        if config.has_option(section, mute_option):
            value = unicode(config.get(section, mute_option), 'utf8').split(',')

        return value

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
        # we have to use lock here to serialize access to 'instances' var.
        # with that, we can iterate instances safely in calculate_active_ranking method.
        with NicoLive.instances_lock:
            NicoLive.instances.add(self)

        if not NicoLive.global_managing_thread:
            NicoLive.start_global_managing_thread()

        # don't call these method below with thread(async),
        # names of community and live are required in the following steps.
        if not DEBUG_SKIP_STREAM_INFO:
            self.get_live_basic_info(self.set_live_basic_info)
            if self.should_mute_live():
                logging.info("this live will be muted.")

        self.live_status = LIVE_STATUS_TYPE_STARTED
        self.start_local_managing_thread()

        if self.live_logging:
            self.log_file_obj = self.open_live_log_file()

        for room_position in xrange(4):
            self.open_room_tweeted[room_position] = False

        retry_count = 0
        max_retry_count = MAX_RETRY_COUNT_LISTEN_LIVE

        while True:
            try:
                self.api.listen_live(self.community_id, self.live_id,
                                     self.handle_chat, self.handle_raw)
                break
            except nicoapi.NicoAPIInitializeLiveError, e:
                # possible error code list: http://looooooooop.blog35.fc2.com/blog-entry-1159.html
                if (e.status == 'fail' and e.code in [
                        'require_community_member', 'notfound', 'deletedbyuser',
                        'deletedbyvisor', 'violated', 'usertimeshift', 'closed', 'noauth']):
                    logging.debug("live is '%s', so skip.", e.code)
                    break
                else:
                    if (e.status == 'fail' and e.code in [
                            'comingsoon', 'full', 'block_now_count_overflow']):
                        logging.debug("live is '%s', so retry, error: %s" % (e.code, e))
                        max_retry_count = MAX_RETRY_COUNT_LISTEN_LIVE_LONG
                    else:
                        # possible case of session expiration, so clearing container and retry
                        logging.warning("unexpected error when opening live, error: %s" % e)
                        self.api.reset_cookie_container()
            except Exception, e:
                logging.warning("possible network error when opening live, error: %s" % e)

            if retry_count < max_retry_count:
                logging.debug("retrying to open live, retry count: %d/%d" %
                              (retry_count, max_retry_count))
            else:
                logging.error("gave up retrying to open live, retry count: %d/%d" %
                              (retry_count, max_retry_count))
                break

            time.sleep(RETRY_INTERVAL_LISTEN_LIVE)
            retry_count += 1

        self.live_status = LIVE_STATUS_TYPE_FINISHED

        # logging.debug("finished all sub threads")
        if self.live_logging:
            self.log_file_obj.close()
            self.gzip_live_log_file()

        with NicoLive.instances_lock:
            NicoLive.instances.remove(self)

# private methods, live handler
    def handle_raw(self, raw):
        if self.live_logging:
            self.log_live(raw)

    def handle_chat(self, room_position, user_id, premium, comment):
        log = ('room_position: %d user_id: %s premium: %s comment: %s' %
               (room_position, user_id, premium, comment))
        if DEBUG_LOG_COMMENT_TO_APP_LOG:
            logging.debug(log)
        if DEBUG_LOG_COMMENT_TO_STDOUT:
            print log

        self.check_opening_room(room_position, premium)
        self.check_user_id(user_id, comment)

        self.comments.append((dt.now(), premium, user_id))
        self.should_recalculate_active = True

    # examines stream contents
    def check_opening_room(self, room_position, premium):
        if room_position == 0 or self.open_room_tweeted[room_position]:
            return

        # assume the comment from 0(ippan), 1(premium), 7(bsp) as a sign of opening room
        if not premium in ['0', '1', '7']:
            return

        if 0 < room_position:
            self.open_room_tweeted[room_position] = True

            if self.should_mute_live():
                logging.info("skipped 'open room' tweets.")
                self.open_room_tweeted[room_position] = True
            else:
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

                if (DEFAULT_CREDENTIAL_KEY in self.target_communities and
                        1 < room_position and
                        NicoLive.tweet_frequency_mode == TWEET_FREQUENCY_MODE_NORMAL):
                    self.update_twitter_status(DEFAULT_CREDENTIAL_KEY, status)

                if self.community_id in self.target_communities:
                    self.update_twitter_status(self.community_id, status)

    def check_user_id(self, user_id, comment):
        if DEBUG_FORCE_USER_TWEET_AND_EXIT:
            user_id = self.target_users[0]
            status = self.create_monitored_comment_status(user_id, comment)
            self.update_twitter_status(user_id, status)
            os.sys.exit()
        else:
            for monitoring_user_id in self.target_users:
                if user_id == monitoring_user_id:
                    status = self.create_monitored_comment_status(user_id, comment)
                    self.update_twitter_status(user_id, status)

# private methods, live utility
    def should_mute_live(self):
        if self.user_id in self.mute_user_ids:
            logging.info("this live should be muted by user_id: %s" % self.user_id)
            return True

        if self.community_id in self.mute_community_ids:
            logging.info("this live should be muted by community_id: %s" % self.community_id)
            return True

        for mute_live_name in self.mute_live_names:
            if re.search(mute_live_name, self.live_name):
                logging.info("this live should be muted by live_name: %s" % self.live_name)
                return True

        for mute_description in self.mute_descriptions:
            if re.search(mute_description, self.description):
                logging.info("this live should be muted by description: %s" % self.description)
                return True

        return False

# private methods, live information
    def get_live_basic_info(self, callback):
        live_start_time = dt.now()

        retry_count = 0
        while True:
            try:
                community_name, live_name, description = self.api.get_stream_info(self.live_id)
                if False:
                    logging.debug(
                        "*** stream info, community name: %s live name: %s description: %s" %
                        (community_name, live_name, description))
                break
            except Exception, e:
                if retry_count < MAX_RETRY_COUNT_GET_STREAM_INFO:
                    logging.debug("retrying to open getstreaminfo, retry count: %d/%d" %
                                  (retry_count, MAX_RETRY_COUNT_GET_STREAM_INFO))
                else:
                    logging.error("gave up retrying to open getstreaminfo, so quit, "
                                  "retry count: %d/%d" %
                                  (retry_count, MAX_RETRY_COUNT_GET_STREAM_INFO))
                    logging.error("could not get stream info: %s" % e)
                    community_name = "n/a"
                    live_name = "n/a"
                    description = "n/a"
                    break
                time.sleep(RETRY_INTERVAL_GET_STREAM_INFO)
                retry_count += 1

        callback(live_start_time, community_name, live_name, description)

    def set_live_basic_info(self, live_start_time, community_name, live_name, description):
        self.live_start_time = live_start_time
        self.community_name = community_name
        self.live_name = live_name
        self.description = description

        for community_id in self.target_communities:
            if self.community_id == community_id:
                status = self.create_start_live_status()
                self.update_twitter_status(community_id, status)

# private methods, global managing thread
    @classmethod
    def start_global_managing_thread(cls):
        if cls.global_managing_thread:
            return

        cls.global_managing_thread = threading.Thread(
            name="NicoLive.global",
            target=cls.execute_global_managing_thread)
        cls.global_managing_thread.start()

    @classmethod
    def execute_global_managing_thread(cls):
        while True:
            with NicoLive.instances_lock:
                if len(NicoLive.instances) == 0:
                    NicoLive.global_managing_thread = None
                    break

            cls.calculate_tweet_rate()
            cls.adjust_tweet_frequency_mode()

            if True:
                logging.debug("started creating ranking")
                ranking = cls.calculate_active_ranking()
                logging.debug("finished creating ranking")

                index = 0
                for (active, community_id, live_id, community_name, live_name,
                        live_start_time) in ranking:
                    if 0 < active:
                        logging.info("rank #%2d(%3d): [%-9s,%-9s] %s (%s)(%s)" % (
                            index+1, active,
                            community_id, live_id, live_name, community_name,
                            live_start_time.strftime('%Y/%m/%d %H:%M')))
                        index += 1
                    if 20 < index:
                        break

            if cls.tweet_frequency_mode == TWEET_FREQUENCY_MODE_NORMAL:
                tmode = "normal"
            elif cls.tweet_frequency_mode == TWEET_FREQUENCY_MODE_ACTIVE_ONLY:
                tmode = "active_only"

            logging.info("live instances: %-5d threads: %-5d "
                         "tweets rate: %-3d/%-2dmin tweet mode: %s" %
                         (len(cls.instances), threading.active_count(),
                          cls.tweets_rate, TWEET_RATE_WATCHING_MINUTES, tmode))

            time.sleep(GLOBAL_MANAGING_THREAD_INTERVAL)

    @classmethod
    def calculate_tweet_rate(cls):
        current_datetime = dt.now()
        tweets_to_be_deleted = []

        for tweet in cls.tweets:
            tweet_datetime, status = tweet
            if current_datetime - tweet_datetime > timedelta(minutes=TWEET_RATE_WATCHING_MINUTES):
                tweets_to_be_deleted.append(tweet)

        for tweet in tweets_to_be_deleted:
            cls.tweets.remove(tweet)

        cls.tweets_rate = len(cls.tweets)

    @classmethod
    def adjust_tweet_frequency_mode(cls):
        if cls.tweet_frequency_mode == TWEET_FREQUENCY_MODE_NORMAL:
            if TWEET_COUNT_THREASHOLD_UPPER < cls.tweets_rate:
                cls.tweet_frequency_mode = TWEET_FREQUENCY_MODE_ACTIVE_ONLY
                logging.info("detected tweet rate high, "
                             "so changed mode to TWEET_FREQUENCY_MODE_ACTIVE_ONLY")
        elif cls.tweet_frequency_mode == TWEET_FREQUENCY_MODE_ACTIVE_ONLY:
            if cls.tweets_rate < TWEET_COUNT_THREASHOLD_LOWER:
                cls.tweet_frequency_mode = TWEET_FREQUENCY_MODE_NORMAL
                logging.info("detected tweet rate low, "
                             "so changed mode to TWEET_FREQUENCY_MODE_NORMAL")

    @classmethod
    def calculate_active_ranking(cls):
        ranking = []

        # to avoid RuntimeError 'Set changed size during iteration',
        # we should make a copy of 'instances' with explicit lock.
        with cls.instances_lock:
            lives = cls.instances.copy()

        for live in lives:
            ranking.append((live.active, live.community_id, live.live_id,
                            live.community_name, live.live_name, live.live_start_time))

        return sorted(ranking, key=lambda x: x[0], reverse=True)

# private methods, local managing thread
    def start_local_managing_thread(self):
        local_managing_thread = threading.Thread(
            name="%s,%s,local" % (self.community_id, self.live_id),
            target=self.execute_local_managing_thread)
        local_managing_thread.start()

    def execute_local_managing_thread(self):
        while True:
            if self.live_status == LIVE_STATUS_TYPE_FINISHED:
                break
            self.calculate_active()
            time.sleep(LOCAL_MANAGING_THREAD_INTERVAL)

    def calculate_active(self):
        if not self.should_recalculate_active:
            return

        active_calcuration_duration = 60 * 10
        unique_users = []
        current_datetime = dt.now()

        for index in xrange(len(self.comments)-1, -1, -1):
            (comment_datetime, premium, user_id) = self.comments[index]

            # premium 0: non-paid user, 1: paid user
            if not premium in ["0", "1"]:
                continue

            if (current_datetime - comment_datetime >
                    timedelta(seconds=active_calcuration_duration)):
                break

            if not user_id in unique_users:
                unique_users.append(user_id)

        self.active = len(unique_users)
        self.should_recalculate_active = False
        # logging.info("active: %d" % self.active)

        if self.active_tweet_target < self.active:
            status = self.create_active_live_status(self.active_tweet_target)
            self.active_tweet_target += ACTIVE_TWEET_INCREMENT_VALUE

            if self.should_mute_live():
                logging.info("skipped 'active' tweets.")
            else:
                if DEFAULT_CREDENTIAL_KEY in self.target_communities:
                    self.update_twitter_status(DEFAULT_CREDENTIAL_KEY, status)
                if self.community_id in self.target_communities:
                    self.update_twitter_status(self.community_id, status)

# private methods, twitter
    # user-related
    def create_monitored_comment_status(self, user_id, comment):
        comment = re.sub(ur'/press show \w+ ', '', comment)

        status = u"【%s】\n%s\n%s%s\n(%s)" % (
            unicode(self.header_text[user_id], 'utf8'), comment,
            LIVE_URL, self.live_id, self.community_name)
        return status

    # community-related
    def create_start_live_status(self):
        status = u"【放送開始】%s（%s）%s%s #%s" % (
            self.live_name, self.community_name, LIVE_URL, self.live_id, self.community_id)
        return status

    def create_active_live_status(self, active):
        status = u"【アクティブ%d+/開始%d分】%s（%s）%s%s #%s" % (
            active, self.elapsed_minutes(),
            self.live_name, self.community_name,
            LIVE_URL, self.live_id, self.community_id)
        return status

    def create_stand_room_status(self, room_name):
        status = u"【%sオープン/開始%d分】%s（%s）%s%s #%s" % (
            room_name, self.elapsed_minutes(),
            self.live_name, self.community_name,
            LIVE_URL, self.live_id, self.community_id)
        return status

    def elapsed_minutes(self):
        return (dt.now() - self.live_start_time).seconds / 60

    # main
    def update_twitter_status(self, credential_key, status):
        logging.debug("entering to critical section: update_twitter_status")

        with NicoLive.twitter_status_update_lock:
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
                    logging.info("status successfully updated, credential_key: %s status: %s" %
                                 (credential_key, status))

                    if credential_key == DEFAULT_CREDENTIAL_KEY:
                        NicoLive.tweets.append((dt.now(), status))
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
                # logging.debug("directory %s created." % directory)
            except OSError:
                # already existed
                pass

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

    nicolive = NicoLive(os.sys.argv[1], os.sys.argv[2], None, os.sys.argv[3], None)
    nicolive.start_listening_live()
