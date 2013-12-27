# -*- coding: utf-8 -*-

class NicoAPIError(Exception):
    def __init__(self, status='', code='', info=''):
        self.status = status
        self.code = code
        self.info = info

    def __str__(self):
        status = 'n/a' if self.status == '' else self.status
        code = 'n/a' if self.code == '' else self.code
        info = 'n/a' if self.info == '' else self.info
        return u'nico error, status:[%s] code:[%s] info:[%s]' % (status, code, info)


class NicoAPIInitializeLiveError(NicoAPIError):
    pass
