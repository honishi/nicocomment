#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import yappi

if __name__ == "__main__":
    if len(os.sys.argv) != 2:
        print('usage: {0} stats_file'.format(os.sys.argv[0]))
        os.sys.exit()

    stats = yappi.YFuncStats(os.sys.argv[1])

    # stats.sort("totaltime").print_all()
    stats.sort("totaltime").debug_print()
