#!/usr/bin/env python
from __future__ import print_function
import os
import sys
import time
import getopt
import requests


def main():

    options = get_arguments()

    print('Watching for JSON files in %s' % options.watch_folder)

    while True:

        time.sleep(options.update_interval)

        files = [ file for file in os.listdir(options.watch_folder) if file.endswith('.json') ]

        send_files(options, files)


def send_files(options, files):
    for file in files:
        fullpath = os.path.join(options.watch_folder, file)
        try:
            res = requests.post(options.url + '/' + options.user_name, readfile(fullpath))
        except Exception as e:
            print(red('Got network error while sending files. Skipping update.'))
            print(e)
            return

        if res.status_code == 200:
            os.remove(fullpath)
            print('Sent %s' % file)
        else:
            print(red('Request failed %d ' % res.status_code) + ('[%s] %s: %s' % (bold(url), file, res.reason)))

def readfile(filename):
    with open(filename, 'r') as file:
        content = file.read()
    return content

def usage():
    print("watch_portal_folder.py - watches a folder for JSON files and sends them to and external URL.")
    print("")
    print(bold("Usage:") + " watch_portal_folder.py [options] ")
    print("")
    print(bold("Options:"))
    print("    -w, --watch     - folder to watch")
    print("    -u, --url       - URL to send the JSON files to")
    print("    -i, --interval  - folder check interval (in seconds) (default: 5)")
    print("        --username  - user name to append to the URL (default: system)")
    print("        --help      - display this message")

def get_arguments():
    options = dotdict({})
    options.user_name       = 'system'
    options.watch_folder    = './buffer'
    options.url             = 'http://localhost:3000'
    options.update_interval = 5

    optli, arg = getopt.getopt(sys.argv[1:], 'w:u:i:h', ['watch=', 'url=', 'interval=', 'username=', 'help'])

    if len(optli) == 0 :
        usage()
        exit('Error: No arguments given')

    for option, value in optli:
        if option in ('-w', '--watch'):
            if str(value) == '':
                exit('Error: --watch folder not provided\n')
            else:
                options.watch_folder = str(value)
        if option in ('-u', '--url'):
            if str(value) == '':
                exit('Error: --url not provided\n')
            else:
                options.url = str(value)
        if option in ('--username'):
            if str(value) == '':
                exit('Error: --username not provided\n')
            else:
                options.user_name = str(value)
        if option in ('-i', '--interval'):
            if int(value) == '':
                exit('Error: --interval not provided\n')
            else:
                options.update_interval = int(value)
        if option in ('-h', '--help'):
            usage()
            exit()

    return options

def bold(text):
    return '\x1b[1m%s\x1b[21m' % text

def red(text):
    return '\x1b[31m%s\x1b[39m' % text

def exit(message):
    sys.exit(red(message))

class dotdict(dict):
    __getattr__ = dict.get
    __setattr__ = dict.__setitem__
    __delattr__ = dict.__delitem__

if __name__ == '__main__':
  main()
