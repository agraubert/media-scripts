import re
import os
from collections import namedtuple
from shutil import move

plex_tv_pattern = re.compile(r'(.+) - S(\d+)E(\d+) - (.+)\.(mp4|m4v)')
eplist_selector_pattern = re.compile(r'^(\d+):(\d+|\*)(,((\d+):)?(\d+|\*))*$')

EpInfo = namedtuple(
    'EpInfo',
    [
        'show',
        'season',
        'episode',
        'title',
        'filepath',
        'filename',
        'ext'
    ]
)

def update_epinfo(obj, **kwargs):
    info = {
        'show': obj.show,
        'season': obj.season,
        'episode': obj.episode,
        'title': obj.title,
        'filepath': obj.filepath,
        'filename': obj.filename,
        'ext': obj.ext,
    }
    info.update(kwargs)
    return EpInfo(**info)

def parse_filename(filepath, pattern=plex_tv_pattern):
    match = pattern.match(os.path.basename(filepath))
    return EpInfo(
        match.group(1),
        int(match.group(2)),
        int(match.group(3)),
        match.group(4),
        filepath,
        os.path.basename(filepath),
        match.group(5)
    )

def canonical_filename(epinfo):
    return '{} - S{}E{} - {}.{}'.format(
        epinfo.show,
        epinfo.season,
        epinfo.episode,
        epinfo.title,
        epinfo.ext
    )

def canonical_filepath(epinfo):
    return os.path.join(
        epinfo.show,
        'Season {}'.format(epinfo.season),
        canonical_filename(epinfo)
    )

def canonicalize(epinfo, dest='', move=True):
    """
    Move the given epinfo object to the given destination folder.
    """
    new = update_epinfo(
        epinfo,
        filepath=os.path.join(dest, canonical_filepath(epinfo)),
        filename=canonical_filename(epinfo)
    )
    if move:
        os.makedirs(os.path.dirname(new.filepath), exist_ok=True)
        shutil.move(epinfo.filepath, new.filepath)
    return new

class EPList(object):
    def __init__(self, selector=None):
        """
        Compiles an episode list (season:episode,episode,season:episode,season:episode)
        into a EPList object
        """
        if selector is None:
            selector = ""
        if len(selector) and eplist_selector_pattern.match(selector) is None:
            raise ValueError("Selector '{}' not in valid format".format(selector))
        self.episodes = []
        last_season = None
        for episode in selector.split(','):
            if ':' in episode:
                last_season, ep = episode.split(':')
            else:
                if last_season is None:
                    raise ValueError("No season defined on selector")
                ep = episode
            last_season = int(last_season)
            ep = int(ep) if ep != '*' else None
            self.episodes.append((last_season, ep))

    @property
    def wildcard_seasons(self):
        """
        Returns seasons for which a wildcard was set
        """
        return {s for s,e in self.episodes if e is None}


    def __contains__(self, episode):
        """
        Checks if the given object is contained in this EPList
        """
        if isinstance(episode, str):
            episode = EPList(episode)
        if isinstance(episode, EPList):
            if len(episode) != 1:
                raise ValueError("Use & to compare EPLists")
            return episode.episodes[0] in self.episodes or episode.episodes[0][0] in self.wildcard_seasons
        if isinstance(episode, EpInfo):
            return (episode.season, episode.episode) in self.episodes or episode.season in self.wildcard_seasons

    def __and__(self, other):
        """
        Intersects two EPLists
        """
        if not isinstance(other, EPList):
            raise TypeError("Can only compare two EPLists")
        new = EPList("")
        new.episodes = [ep for ep in self.episodes if ep in other.episodes]
        return new

    def __len__(self):
        return len(self.episodes)
