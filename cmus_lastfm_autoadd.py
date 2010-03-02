#!/usr/bin/env python2.6
# -*- coding: utf-8 -*-

# written by Johannes Weißl, GPLv3

import sys
import os
import os.path
import mmap
import struct
import random
import subprocess
import lastfm

if 'Api' not in dir(lastfm):
    exit('You need python-lastfm from http://code.google.com/p/python-lastfm/')

def die(msg):
    print('%s: %s' % (sys.argv[0],msg))
    exit(1)

def warn(msg):
    print('%s: %s' % (sys.argv[0],msg))

def list2dict(lst):
    return dict((lst[i],lst[i+1]) for i in xrange(0,len(lst),2))

def detach():
    try:
        pid = os.fork()
        if pid != 0:
            os._exit(0)
    except:
        pass

class CMus(object):
    def __init__(self, confdir='~/.cmus'):
        self.confdir = os.path.expanduser(confdir)
        self.cachepath = self.confdir + '/cache'
        self.libpath = self.confdir + '/lib.pl'
        self.remotecmd = 'cmus-remote'
        self.libfiles = set()
        self.artists = {}
        self.cache = {}
    def is_running(self):
        try:
            subprocess.check_call([self.remotecmd, '-C'])
        except OSError:
            return False
        except subprocess.CalledProcessError:
            return False
        return True
    def addfile(self, filename, target='playlist'):
        subprocess.Popen([self.remotecmd, '-P', filename])
    def read_lib(self):
        try:
            f = open(self.libpath)
            self.libfiles = set(line.rstrip('\n') for line in f)
        except IOError, (errno, strerror):
            warn('could not open %s: %s' % (self.libpath, strerror))
    def read_cache(self,restrict_to_lib=False):
        struct_long = struct.Struct('l')
        def align(size):
            return (size + struct_long.size - 1) & ~(struct_long.size - 1)
        try:
            f = open(self.cachepath, 'rb')
        except IOError, (errno, strerror):
            warn('could not open %s: %s' % (self.cachepath, strerror))
            return
        try:
            buf = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
            buf_size = buf.size()
            if buf_size < 8 or buf[:4] != 'CTC\x02':
                warn('cache signature is not valid')
                return
            offset = 8
            s = struct.Struct('Iil')
            while offset < buf_size:
                e_size, duration, mtime = s.unpack_from(buf, offset)
                strings = buf[offset+s.size:offset+e_size].split('\x00')[:-1]
                filename = strings[0]
                if not restrict_to_lib or filename in self.libfiles:
                    keys = list2dict([unicode(x, 'utf-8') for x in strings[1:]])
                    #self.cache[filename] = {
                    #        'duration': duration,
                    #        'mtime': mtime,
                    #        'keys': keys
                    #}
                    if 'artist' in keys:
                        if keys['artist'] not in self.artists:
                            self.artists[keys['artist']] = {}
                        if 'title' in keys:
                            self.artists[keys['artist']][keys['title']] = filename
                offset += align(e_size)
        except:
            warn('cache is not valid')
        finally:
            buf.close()
            f.close()

def main(argv=None):
    if not argv:
        argv = sys.argv

    if len(argv) < 2 or len(argv) % 2 != 1:
        print('Usage: %s key value [key value]...\n\none key should be \"artist\"')
        exit(1)
    
    cur_track = list2dict(argv[1:])
    if 'artist' not in cur_track:
        die('no artist given')
    
    cmus = CMus()
    
    if not cmus.is_running():
        die('cmus not running or cmus-remote not working')

    detach()

    cmus.read_lib()
    cmus.read_cache(restrict_to_lib=True)

    if not cmus.artists:
        die('no artists in library / cache')

    api = lastfm.Api('23caa86333d2cb2055fa82129802780a')
    
    artist_name = unicode(cur_track['artist'], 'utf-8')
    try:
        artist = api.get_artist(artist_name)
    except lastfm.error.InvalidParametersError:
        die('could not find artist \"artist_name\" on last.fm')

    similar_artists = [a for a in artist.similar if a.name in cmus.artists]
    if not similar_artists:
        warn('no similar artist found, choosing completely randomly')
        next_artist = random.choice(cmus.artists.keys())
    else:
        next_artist = random.choice(similar_artists[:10]).name
    
    next_track = random.choice(cmus.artists[next_artist].values())
    cmus.addfile(next_track)

    return 0

if __name__ == '__main__':
    sys.exit(main())
