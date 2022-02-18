import tvlib
import os
import argparse
import subprocess
import re
import json

NEVER_TITLEIZE = {
    'a', 'an', 'the', 'for', 'and', 'nor', 'but', 'or', 'yet',
    'so', 'at', 'around', 'by', 'after', 'along', 'from', 'of', 'on', 'to',
    'with', 'in'
}

informal_pattern = re.compile(r'[sS](\d+)[eE](\d+) (.+)\.mkv$') # show name excluded, must be provided on CLI
number_pattern = re.compile(r'\d+')
multipart_pattern = re.compile(r'Part \d+$')

# Rundown:
# 1) User provides show name, import dir, handbrake preset, and output base TV folder
#   * Allow specifying HQ and standard presets. If HQ is specified, then allow customizing hq usage
#   * --(no)-hq-multipart: whether or not to auto use hq preset on multipart episodes
#   * --manual-hq: Season:episode,episode... list of episodes to apply HQ preset
#   * --retitle "informal name" "formal name"
# 2) Script auto detects informal episodes
# 3) Script runs handbrakecli for each episode: informal --[handbrake preset]--> formal path

def parse_preset(path):
    with open(path) as r:
        preset = json.load(r)
    if 'PresetList' not in preset or len(preset['PresetList']) != 1:
        raise TypeError("Preset file '{}' in unexpected format".format(path))
    return (path, preset['PresetList'][0]['PresetName'])

def titleize(title):
    """
    Title case episode names except for the words in NEVER_TITLEIZE
    (mostly articles and prepositions)
    Also: The first word is always title
    """
    first, *remainder = title.split(' ')
    return '{} {}'.format(
        first.title(),
        ' '.join(word.title() if word.lower() not in NEVER_TITLEIZE else word for word in remainder)
    ).strip()

def initial_epinfo(show_name, filepath):
    match = informal_pattern.search(filepath)
    if match is None:
        raise ValueError("File {} did not match expected pattern".format(filepath))
    return tvlib.EpInfo(
        show_name,
        int(match.group(1)),
        int(match.group(2)),
        match.group(3),
        filepath,
        os.path.basename(filepath),
        'mkv'
    )

def load_raw_episodes(import_dir, show_name, retitle=None, add_parts=True):
    """
    Imports mkv files from the import_dir.
    If retitle is not none, it must be a dictionary of informal title -> manual title
    If add_parts is true, then reformat titles from foo 1 -> Foo Part 1 if:
    * The episode title is more than 1 word
    * The last word is a number
    * There are multiple episodes with the same title prefix but with different end numbers
    """
    files = [
        os.path.join(import_dir, filename)
        for filename in os.listdir(import_dir)
    ]

    proper_files = [
        filename for filename in files if informal_pattern.search(filename) is not None
    ]

    if len(proper_files) < len(files):
        print("Warning: The following files were found in the import directory but did not have a valid filename:")
        print('\n'.join(filename for filename in files if filename not in proper_files))

    proper_files = [initial_epinfo(show_name, filename) for filename in proper_files]
    initial = {ep.title:ep for ep in proper_files}
    assignments = {} # filename -> epinfo (title will be corrected, filename/path will be current)

    # Now automatically titleize each remaining episode
    for ep in initial.values():
        if ep.filename not in assignments:
            assignments[ep.filename] = tvlib.update_epinfo(ep, title=titleize(ep.title))

    # Now add parts
    if add_parts:
        # title base -> [list of part epinfos]
        multiparts = {}
        for episode in assignments.values():
            *prefix, partnum = episode.title.split(' ')
            prefix = ' '.join(prefix)
            if number_pattern.match(partnum) is not None and 'part' not in prefix.lower().split(' '):
                if prefix in multiparts:
                    multiparts[prefix].append(episode)
                else:
                    multiparts[prefix] = [episode]
        for prefix, parts in multiparts.items():
            # Make sure it's not a 1-parter
            if len(parts) > 1:
                for episode in parts:
                    *_, partnum = episode.title.split(' ')
                    assignments[episode.filename] = tvlib.update_epinfo(episode, title="{} Part {}".format(prefix, partnum))

    # Finally, overwrite changes with any manual retitles
    if retitle is not None:
        for current, desired in retitle.items():
            if current in initial:
                episode = initial[current]
                assignments[episode.filename] = tvlib.update_epinfo(episode, title=desired)
            else:
                print("Warning: Attempting to set manual title of '{}' -> '{}' but no episode was found with that name".format(current, desired))

    print("Title assignments")
    for episode in assignments.values():
        print(episode.filename, '->', episode.title)

    return sorted(assignments.values(), key=lambda ep:(ep.season, ep.episode))

def handbrake_args(episodes, standard_preset, destination, hq_preset=None, hq_multipart=True, manual_hq=None):
    """
    Assigns handbrake arguments for each episode
    """
    return [
        {
            'input': ep.filepath,
            'output': os.path.join(destination, tvlib.canonical_filepath(tvlib.update_epinfo(ep, ext='m4v'))),
            'preset': hq_preset if (
                hq_preset is not None
                and (
                    (hq_multipart and multipart_pattern.search(ep.title) is not None) or
                    (manual_hq is not None and ep in manual_hq)
                )
            ) else standard_preset
        }
        for ep in episodes
    ]

def dump_batch_script(handbrake_path, args, dest_script):
    for arg in args:
        outdir = os.path.dirname(arg['output'])
        if not os.path.isdir(outdir):
            os.makedirs(outdir)
    with open(dest_script, 'w') as w:
        w.write('\r\n'.join(
            '"{}" --preset-import-file "{}" -Z "{}" -i "{}" -o "{}"'.format(
                handbrake_path,
                arg['preset'][0],
                arg['preset'][1],
                arg['input'],
                arg['output']
            )
            for arg in args
        ))

if __name__ == "__main__":
    parser = argparse.ArgumentParser('plex-transcode-and-import')
    parser.add_argument(
        'show_name',
        help="Fully formatted name of the show to import"
    )
    parser.add_argument(
        'import_dir',
        help="Directory to load .mkv files from. Filesnames must be in [season][episode] [title] format"
    )
    parser.add_argument(
        'handbrake',
        help="Path to handbrake executable"
    )
    parser.add_argument(
        'preset',
        help="Path to standard quality preset",
        type=parse_preset
    )
    parser.add_argument(
        'output',
        help="Output path. This should be the base directory for Plex TV. Show/season directories will be made as needed"
    )
    parser.add_argument(
        'script',
        help="Output script path"
    )
    parser.add_argument(
        '-m', '--no-hq-multipart',
        action='store_false',
        dest='hq_multipart',
        help="Disable automatic HQ multipart. By default, multipart episodes are transcoded using the HQ preset"
    )
    parser.add_argument(
        '-e', '--hq-episodes',
        help="List of episodes to apply the HQ preset to. Must be in S:E,... EPList selector format",
        default=None
    )
    parser.add_argument(
        '-q', '--hq-preset',
        help="Path to HQ preset. Will be used on multipart and manual episodes",
        default=None,
        type=parse_preset
    )
    parser.add_argument(
        '-r', '--retitle',
        action='append',
        help="Takes two arguments. 1st arg is episode title as exists on disk, 2nd is desired episode title. This option may be provided multiple times",
        nargs=2,
        default=None
    )
    parser.add_argument(
        '-p', '--no-parts',
        action='store_false',
        dest='add_parts',
        help="Disable automatic 'Part' titling. By default, episodes with a multi-word name ending in a number will be retitled as '...Part n'"
    )
    args = parser.parse_args()
    manual_hq = None
    if args.hq_episodes:
        if not args.hq_preset:
            raise ValueError("No HQ preset provided")
        manual_hq = tvlib.EPList(args.hq_episodes)

    episodes = load_raw_episodes(args.import_dir, args.show_name, args.retitle, args.add_parts)
    print("Found", len(episodes), "episodes to enqueue")

    dump_batch_script(
        args.handbrake,
        handbrake_args(episodes, args.preset, args.output, args.hq_preset, args.hq_multipart, manual_hq),
        args.script
    )
    print("Script written to", args.script)
