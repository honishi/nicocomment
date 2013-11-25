#!/usr/bin/env python
# -*- coding: utf-8 -*-


class NicoAuthorizationError(Exception):
    pass


class UnexpectedStatusError(Exception):
    def __init__(self, status, code=""):
        self.status = status
        self.code = code

    def __str__(self):
        return ('unexpected status "%s", code "%s" found.' %
                (self.status, self.code))
