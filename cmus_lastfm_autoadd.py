#!/usr/bin/env python2.6
# -*- coding: utf-8 -*-

# written by Johannes Weißl, GPLv3

from __future__ import print_function

# ---------------------------------------------------------------------------
# configuration, can't use command line options because of cmus'
# status_display_program handling

# only consider tracks which are in the library when cmus starts
ONLY_TRACKS_IN_LIBRARY = True

# can be 'queue' or 'playlist'
ADD_TO = 'queue'

# percentage of similar artists to choose epsilon-greedy from
# (e.g. almost always choose an artist from the first third of the similar
# artists, just in 10% of all cases choose one from the other 2/3)
MOST_SIMILAR = 0.33
EPSILON = 0.1

# probability to not consider similar artists at all, but to choose
# completely randomly
JUMPOUT_EPSILON = 0.0

# enable debug output
DEBUG = False
# ---------------------------------------------------------------------------

import sys
import os
import os.path
import mmap
import struct
import random
import subprocess
import urllib
import urllib2
import re

def die(msg):
    print('%s: %s' % (sys.argv[0],msg), file=sys.stderr)
    exit(1)

def warn(msg):
    print('%s: %s' % (sys.argv[0],msg), file=sys.stderr)

def debug(msg):
    if DEBUG:
        print('DEBUG: %s' % (msg,), file=sys.stderr)
    
def list2dict(lst):
    return dict((lst[i],lst[i+1]) for i in xrange(0,len(lst),2))

def xml_entitiy_decode(text):
    entitydefs = {
        'quot': '"',
        'amp' : '&',
        'apos': "'",
        'lt'  : '<',
        'gt'  : '>'
    }
    def fixup(m):
        return entitydefs[m.group(1)]
    return re.sub('&('+'|'.join(entitydefs.keys())+');', fixup, text)

def xml_entitiy_encode(text):
    def fixup(m):
        return '%'+hex(ord(m.group(0)))[2:]
    return re.sub('["&\'<>]', fixup, text)

def detach():
    try:
        pid = os.fork()
        if pid != 0:
            os._exit(0)
    except:
        pass

class LastFM(object):
    def __init__(self):
        self.root_url = 'http://ws.audioscrobbler.com/2.0/'
    def get_similar(self, artist):
        q_artist = urllib.quote_plus(xml_entitiy_encode(artist).encode('utf-8'), '')
        try:
            f = urllib2.urlopen(self.root_url+'artist/'+q_artist+'/similar.txt')
            d = f.read()
        except urllib2.HTTPError as e:
            raise Exception(str(e))
        tuples = [tuple(x.split(',',2)) for x in d.rstrip('\n').split('\n')]
        return [(a,b,xml_entitiy_decode(unicode(c, 'utf-8'))) for (a,b,c) in tuples]

class CMus(object):
    def __init__(self, confdir=None):
        if not confdir:
            rel_confdir = '.cmus'
            confdir = os.path.expandvars('${CMUS_HOME}/'+rel_confdir)
            if not os.path.isabs(confdir):
                confdir = os.path.expanduser('~/'+rel_confdir)
        self.confdir = os.path.abspath(confdir)
        self.cachepath = self.confdir + '/cache'
        self.libpath = self.confdir + '/lib.pl'
        self.remotecmd = ['cmus-remote']
        self.libfiles = set()
        self.artists = {}
        self.cache = {}
    def is_running(self):
        try:
            subprocess.check_call(self.remotecmd + ['-C'])
        except OSError:
            return False
        except subprocess.CalledProcessError:
            return False
        return True
    def addfile(self, filename, target='queue'):
        opt = '-P' if target == 'playlist' else '-q'
        subprocess.Popen(self.remotecmd + [opt, filename])
    def read_lib(self):
        try:
            f = open(self.libpath)
            self.libfiles = set(line.rstrip('\n') for line in f)
        except IOError as e:
            errno, strerror = e
            warn('could not open %s: %s' % (self.libpath, strerror))
    def read_cache(self,restrict_to_lib=False):
        struct_long = struct.Struct('l')
        def align(size):
            return (size + struct_long.size - 1) & ~(struct_long.size - 1)
        try:
            f = open(self.cachepath, 'rb')
        except IOError as e:
            errno, strerror = e
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
    cmus.read_cache(restrict_to_lib=ONLY_TRACKS_IN_LIBRARY)

    if not cmus.artists:
        die('no artists in library / cache')

    lastfm = LastFM()
    
    artist_name = unicode(cur_track['artist'], 'utf-8')
    try:
        all_similar_artists = lastfm.get_similar(artist_name)
    except Exception as e:
        die('cannot fetch similar artists to "'+artist_name+'": '+str(e))

    debug('searching for similar artists to "%s"' % (artist_name,))

    similar_artists = [a[2] for a in all_similar_artists if a[2] in cmus.artists]
    debug('you have %d from %d similar artists' % (len(similar_artists),len(all_similar_artists)))
    if random.random() < JUMPOUT_EPSILON or not similar_artists:
        if not similar_artists:
            warn('no similar artist found, choosing completely randomly')
        else:
            debug('hah! %s%% probability, doing a jump out of similar artists' % (str(100*JUMPOUT_EPSILON),))
        similar_artists = cmus.artists.keys()
        random.shuffle(similar_artists)
    else:
        n_most_similar = int(len(similar_artists) * MOST_SIMILAR)
        most_similar_artists = similar_artists[:n_most_similar]
        lesser_similar_artists = similar_artists[n_most_similar:]
        random.shuffle(most_similar_artists)
        random.shuffle(lesser_similar_artists)
        if random.random() < EPSILON:
            similar_artists = lesser_similar_artists + most_similar_artists
            debug('choosing from the %s%% (= %d) lesser similar artists' % (str(100*(1-MOST_SIMILAR)),len(lesser_similar_artists)))
        else:
            similar_artists = most_similar_artists + lesser_similar_artists
            debug('choosing from the %s%% (= %d) most similar artists' % (str(100*MOST_SIMILAR),len(most_similar_artists)))

    next_track = None
    for similar_artist in similar_artists:
        if cmus.artists[similar_artist]:
            files = cmus.artists[similar_artist].values()
            random.shuffle(files)
            for f in files:
                if os.path.exists(f):
                    next_track = f
                    break
                else:
                    debug('path "%s" does not exist, continuing...' % (f,))
            if next_track:
                break

    if next_track:
        cmus.addfile(next_track,target=ADD_TO)
        debug("add file \"%s\" to %s\n" % (next_track,ADD_TO))
    else:
        die('no existing track found to add')

    return 0

if __name__ == '__main__':
    sys.exit(main())
