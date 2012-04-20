# -*- coding: utf-8 -*-
import codecs
import datetime
import glob
import hashlib
import os
import sys

from doit.tools import timeout
import feedparser
import peewee


class Feed(peewee.Model):
    name = peewee.CharField()
    url = peewee.CharField(max_length = 200)
    last_status = peewee.CharField()
    etag = peewee.CharField(max_length = 200)
    last_modified = peewee.DateTimeField()

class Entry(peewee.Model):
    date = peewee.DateTimeField()
    feed = peewee.ForeignKeyField(Feed)
    content = peewee.TextField(max_length = 20000)
    link = peewee.CharField(max_length = 200)
    title = peewee.CharField(max_length = 200)
    guid = peewee.CharField(max_length = 200)

Feed.create_table(fail_silently=True)
Entry.create_table(fail_silently=True)

def task_load_feeds():
    "Read the feeds file, add it to the database."
    feeds = []
    feed = name = None
    for line in codecs.open('feeds', 'r', 'utf-8'):
        line = line.strip()
        if line.startswith("#"):
            continue
        elif line.startswith(u'http'):
            feed = line
        elif line:
            name = line
        if feed and name:
            feeds.append([feed, name])
            feed = name = None

    def add_feed(name, url):
        f = Feed.create(
            name=name,
            url=url,
            etag='caca',
            last_modified=datetime.datetime(1970,1,1),
            )
        f.save()

    def update_feed_url(feed, url):
        feed.url = url
        feed.save()
        
    for feed, name in feeds:
        f = Feed.select().where(name=name)
        if not list(f):
            yield {
                'name': name.encode('utf8'),
                'actions': ((add_feed,(name, feed)),),
                'file_dep': ['feeds'],
                }
        elif list(f)[0].url != feed:
            yield {
                'name': (u'updating_'+name).encode('utf8'),
                'actions': ((update_feed_url,(list(f)[0], feed)),),
                }
            

def task_update_feeds():
    """Download feed contents, add entries to the database."""
    def update_feed(feed):    
        modified = feed.last_modified.timetuple()
        etag = feed.etag
        parsed = feedparser.parse(feed.url,
            etag=etag,
            modified=modified
        )
        try:
            feed.last_status = str(parsed.status)
        except:  # Probably a timeout
            # TODO: log failure
            return
        if parsed.feed.get('title'):
            print parsed.feed.title
        else:
            print feed.url
        feed.etag = parsed.get('etag', 'caca')
        modified = tuple(parsed.get('date_parsed', (1970,1,1)))[:6]
        print "==========>", modified
        modified = datetime.datetime(*modified)
        feed.last_modified = modified
        feed.save()
        # No point in adding items from missinfg feeds
        if parsed.status > 400:
            # TODO log failure
            return
        for entry_data in parsed.entries:
            print "========================================="
            date = entry_data.get('published_parsed', None)
            if date is None:
                date = entry_data.get('updated_parsed', None)
            if date is None:
                print "Can't parse date from:"
                print entry_data
                return False
            print "DATE:===>", date
            date = datetime.datetime(*(date[:6]))
            title = "%s: %s" %(feed.name, entry_data.get('title', 'Sin título'))
            content = entry_data.get('content', None)
            if content:
                content = content[0].value
            if not content:
                content = entry_data.get('description', None)
            if not content:
                content = entry_data.get('summary', 'Sin contenido')
            guid = str(entry_data.get('guid', entry_data.link))
            link = entry_data.link
            print repr([date, title])
            e = list(Entry.select().where(guid=guid))
            print repr(dict(
                    date = date,
                    title = title,
                    content = content,
                    guid=guid,
                    feed=feed,
                    link=link,
                ))
            if not e:
                entry = Entry.create(
                    date = date,
                    title = title,
                    content = content,
                    guid=guid,
                    feed=feed,
                    link=link,
                )
            else:
                entry = e[0]
                entry.date = date
                entry.title = title
                entry.content = content
                entry.link = link
            entry.save()
    for feed in Feed.select():
        yield {
            'name': str(feed.id),
            'actions': [(update_feed,(feed,))],
            'uptodate': [timeout(datetime.timedelta(minutes=20))],
            }

def task_generate_posts():
    """Generate post files for the blog entries."""
    def gen_id(entry):
        h = hashlib.md5()
        h.update(entry.feed.name.encode('utf8'))
        h.update(entry.guid)
        return h.hexdigest()

    def generate_post(entry):
        unique_id = gen_id(entry)
        meta_path = os.path.join('posts',unique_id+'.meta')
        post_path = os.path.join('posts',unique_id+'.txt')
        with codecs.open(meta_path, 'wb+', 'utf8') as fd:
            fd.write(u'%s\n' % entry.title.replace('\n', ' '))
            fd.write(u'%s\n' % unique_id)
            fd.write(u'%s\n' % entry.date.strftime('%Y/%m/%d %H:%M'))
            fd.write(u'\n')
            fd.write(u'%s\n' % entry.link)
        with codecs.open(post_path, 'wb+', 'utf8') as fd:
            fd.write(u'.. raw:: html\n\n')
            content = entry.content
            if not content:
                content = u'Sin contenido'
            for line in content.splitlines():
                fd.write(u'    %s\n' % line)

    for entry in Entry.select().order_by(('date', 'desc')):
        yield {
            'name': gen_id(entry),
            'actions': [(generate_post, (entry,))],
            }
