import argparse
import re
import os
import shutil
from itertools import groupby
from collections import namedtuple
from tqdm import tqdm

episode_pattern = re.compile(r'(.*) \(S(\d+), E(\d+), E\d+\) - (.*) \(1\) & \(2\)\.(m4v|mp4)')

EpInfo = namedtuple(
    'EpInfo',
    [
        'show',
        'season',
        'episode',
        'title',
        'path'
    ]
)


def extract_match(episode):
    match = episode_pattern.match(episode)
    if not match:
        return match
    return EpInfo(
        match.group(1),
        int(match.group(2)),
        int(match.group(3)),
        match.group(4),
        episode
    )


def main(src, dest):
    print("Scanning for dual episodes in", src)
    valid = [*filter(
        bool,
        [
            extract_match(ep)
            for ep in os.listdir(src)
        ]
    )]
    print("Detected", len(valid), "dual episodes with valid filenames")
    for show, grp in groupby(valid, key=lambda ep:ep.show):
        grp = list(grp)
        print("Processing", len(grp), "episodes of", show)
        dest_show = os.path.join(dest, show)
        if not os.path.isdir(dest_show):
            os.makedirs(dest_show)
        valid = sorted(valid, key=lambda ep: (ep.season, ep.episode))
        for season, eps in groupby(grp, key=lambda ep:ep.season):
            print("Migrating Season", season)
            dest_season = os.path.join(dest_show, 'Season {}'.format(season))
            if not os.path.isdir(dest_season):
                os.mkdir(dest_season)
            eps = list(eps)
            for ep in tqdm(eps):
                shutil.move(
                    os.path.join(src, ep.path),
                    os.path.join(
                        dest_season,
                        "{} - S{}E{} - {}.m4v".format(show, ep.season, ep.episode, ep.title)
                    )
                )
    print("PLEX metadata to manually validate:")
    for ep in valid:
        print(ep.show, "Season", ep.season, "Episode", ep.episode, "-", ep.title)
    print("All done!")

if __name__ == '__main__':
    parser = argparse.ArgumentParser("Dual Episode Collection")
    parser.add_argument(
        'source',
        help="Source path of unorganized TV episodes"
    )
    parser.add_argument(
        'destination',
        help="Destination path. This should be the root where different shows are stored."
    )

    args = parser.parse_args()
    main(args.source, args.destination)
