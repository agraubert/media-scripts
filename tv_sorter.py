import argparse
import re
import os
import shutil
from itertools import groupby
from collections import namedtuple
from tqdm import tqdm

episode_pattern = re.compile(r'.* \(S(\d+), E(\d+)\) - (.+\.(mp4|m4v))')

EpInfo = namedtuple(
    'EpInfo',
    [
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
        int(match.group(1)),
        int(match.group(2)),
        match.group(3),
        episode
    )


def main(src, dest, show):
    print("Detecting episodes of", show, "in", src)
    episodes = [
        ep for ep in os.listdir(src)
        if ep.startswith(show)
    ]
    valid = [*filter(
        bool,
        [
            extract_match(ep)
            for ep in episodes
        ]
    )]
    print("Detected", len(episodes), "episodes of", show)
    print(len(valid), "had valid filenames and will be moved")
    dest_show = os.path.join(dest, show)
    if not os.path.isdir(dest_show):
        os.makedirs(dest_show)
    valid = sorted(valid, key=lambda ep: (ep.season, ep.episode))
    for season, eps in groupby(valid, key=lambda ep:ep.season):
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
                    "{} - S{}E{} - {}".format(show, ep.season, ep.episode, ep.title)
                )
            )
    if len(valid) < len(episodes):
        print("The following episodes must be handled manually:")
        valid_paths = {ep.path for ep in valid}
        print("\n".join([episode for episode in episodes if episode not in valid_paths]))
    print("All done!")

if __name__ == '__main__':
    parser = argparse.ArgumentParser("TV Sorter")
    parser.add_argument(
        'source',
        help="Source path of unorganized TV episodes"
    )
    parser.add_argument(
        'destination',
        help="Destination path. This should be the root where different shows are stored."
    )
    parser.add_argument(
        'show',
        help='Show title. This must be the prefix of all desired files in the source directory'
    )

    args = parser.parse_args()
    main(args.source, args.destination, args.show)
