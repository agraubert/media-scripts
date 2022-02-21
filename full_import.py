"""
Plex TV Import Automation
Title detection and automatic transcoding

Author: Aaron Graubert 2022

------

This script is designed to start by grabbing one or more anonymous files freshly
ripped from a DVD/BluRay, automatically detect their titles, rename the files
appropriately, generate appropriate handbrake encoding arguments, and then either
transcode the files or dump a batch script for future transcoding.

Each input MKV file goes through the following stages
1) Files are renamed temporarily so as not to conflict with fresh rips
2) FFMPEG is used to cut out the bottom half of the frame of minutes 2-4 of the video
3) That cut is uploaded to Google Cloud Storage
4) Google Cloud VideoIntelligence is used to detect text present in the cut
5) Any text detected with high enough confidence is cross-referenced with a user-provided list of expected episode titles
6) If no match is found, the script repeats steps 2-5 for several different time slices within the first 10 minutes.
    If no match is found after checking all of the first 10 minutes, the script prompts the user to manually provide the information
7) If a match is found, the match is used to assign season and episode numbers to the file
8) The file is renamed to reflect it's detected name
9) Handbrake is invoked, or handbrake arguments are written to file
"""

import asyncio
import tvlib
import random
import os
from datetime import datetime
import tempfile
from contextlib import asynccontextmanager
import transcode_and_import as xcode
from google.cloud import storage, videointelligence
from concurrent.futures import ThreadPoolExecutor
from numpy import median
import aiofiles
import argparse
import json
import pandas as pd
import traceback
import sys

def getblob(gs_path):
    if gs_path.startswith('gs://'):
        gs_path = gs_path[5:]
    bucket, *path = gs_path.split('/')
    path = '/'.join(path)
    blob = storage.Client().bucket(bucket).blob(path)
    blob.chunk_size = 104857600 # ~100mb
    return blob

TIMESTAMP_FORMAT = '%Y-%m-%d-%H-%M-%S'

async def run_cmd(cmd, check=True):
    proc = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await proc.communicate()
    if check and proc.returncode != 0:
        print(stderr, file=sys.stderr)
        raise ValueError("Command '{}' failed with status {}".format(cmd, proc.returncode))
    return proc.returncode, stdout, stderr

class Taskmaster(object):
    """
    Tracks and manages tasks
    """

    def __init__(self, stagger_start=30, **throttles):
        self.throttles = {k:v for k,v in throttles.items()} # stage: limit task throttles
        self.tasks = {}
        self.stagger = stagger_start
        self.lock = asyncio.Lock()
        self.pool = None

    def __enter__(self):
        self.pool = ThreadPoolExecutor()
        self.pool.__enter__()
        return self

    def __exit__(self, *args):
        self.pool.__exit__(*args)
        self.pool = None

    async def dispatch(self, func, *args):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self.pool, func, *args)

    async def initialize(self):
        if self.stagger is not None:
            await asyncio.sleep(random.randint(0, self.stagger))
        async with self.lock:
            self.tasks[len(self.tasks)] = None
            return len(self.tasks) - 1 # taskID

    async def log(self, taskid, text):
        print('[{}] {}'.format(taskid, text.strip()))

    async def update_status(self, taskid, status):
        async with self.lock:
            self.tasks[taskid] = status
        await self.log(taskid, "Status update: {}".format(status))

    @asynccontextmanager
    async def throttle(self, limit):
        if limit in self.throttles:
            if isinstance(self.throttles[limit], int):
                self.throttles[limit] = asyncio.BoundedSemaphore(self.throttles[limit])
            async with self.throttles[limit]:
                yield
        else:
            yield

    async def prompt(self, taskid, *args, context=None):
        # Prompt the user for input to the various arguments
        print("Task", taskid, "requires user input")
        print("The following inputs are needed:", args)
        filename = 'mov_import.user_conf.t{}.r{}.json'.format(taskid, os.urandom(2).hex())
        print("Further context in", filename)
        conf_dict = {
            'ready_to_import': False,
            'context': context,
            'README': "Edit the following keys: {}; When finished, set 'ready_to_import' to true.".format(','.join(args)),
        }
        for arg in args:
            conf_dict[arg] = None
        async with aiofiles.open(filename, 'w') as w:
            await w.write(json.dumps(conf_dict, indent=2))
        while not conf_dict['ready_to_import']:
            await asyncio.sleep(5)
            try:
                async with aiofiles.open(filename, 'r') as r:
                    conf_dict = json.loads(await r.read())
            except json.JSONDecodeError:
                pass
        os.remove(filename)
        return tuple(conf_dict[arg] for arg in args)

async def detect_title(taskmaster, taskid, constants, tempdir, staging_path):
    # Cycle through 120 second clips. Roughly ordered by how often the title shows up in that segment
    for offset in [4, 2, 6, 0, 8]:
        await taskmaster.log(taskid, 'Attempting title detection in minutes {} - {}'.format(offset, offset+2))
        season, episode, title = await _detect_title(taskmaster, taskid, constants, tempdir, staging_path, start_offset=60*offset, encode_duration=120)
        if episode is None:
            await taskmaster.log(taskid, 'No title detected. Checking next segment')
        else:
            await taskmaster.log(taskid, "Title detected in minute {}".format(offset))
            return season, episode, title
    await taskmaster.log(taskid, 'Title detection failed. Awaiting manual input')
    return await taskmaster.prompt(taskid, 'SEASON', 'EPISODE', 'TITLE', context=staging_path)


async def _detect_title(taskmaster, taskid, constants, tempdir, staging_path, start_offset=0, encode_duration=None):
    encode_path = os.path.join(tempdir, 'title.{}.{}.m4v'.format(start_offset, encode_duration if encode_duration is not None else 'all'))
    async with taskmaster.throttle('ffmpeg'):
        await taskmaster.log(taskid, "Starting ffmpeg copy")
        await ffmpeg_copy(
            constants['ffmpeg-path'],
            staging_path,
            encode_path,
            start_offset,
            encode_duration
        )
    gs_path = os.path.join(constants['gsutil-path'], 'ocr_{}'.format(os.urandom(4).hex()), os.path.basename(encode_path))
    async with taskmaster.throttle('gcloud'):
        await taskmaster.log(taskid, "Starting upload {} -> {}".format(encode_path, gs_path))
        # await taskmaster.dispatch(
        #     gsutil_upload,
        #     encode_path,
        #     gs_path
        # )
        await run_cmd(
            'gsutil -o GSUtil:parallel_composite_upload_threshold=150M mv {} {}'.format(
                encode_path,
                gs_path
            )
        )
    try:
        await taskmaster.log(taskid, "Starting OCR Text recognition")
        text = await taskmaster.dispatch(
            gcloud_annotate,
            gs_path,
            constants['confidence'],
            constants['user-project']
        )
    finally:
        await taskmaster.dispatch(gsutil_rm, gs_path)
    await taskmaster.log(taskid, "Attempting to match detected text with episode titles")
    return select_episode(constants['episodes'], text)

def gcloud_annotate(gs_path, confidence_threshold=0.9, user_project=None):
    # start operation
    # Poll every 30 + 2**i + randint(0, 10) up to max of 300s, then every 300s afterwards
    # limit text results to those where the median segment confidence is >= threshold
    # return text

    # Could use the async client in future
    client = videointelligence.VideoIntelligenceServiceClient()
    operation = client.annotate_video(
        request={
            'features': [videointelligence.Feature.TEXT_DETECTION],
            'input_uri': gs_path
        }
    )

    i = -1
    while not operation.done():
        i += 1
        try:
            result = operation.result(timeout=min(300, 30 + (2**i) + random.randint(0, 10)))
        except:
            continue
        return [
            annotation.text
            for annotation in result.annotation_results[0].text_annotations
            if median([
                segment.confidence
                for segment in annotation.segments
            ]) >= confidence_threshold
        ]

def gsutil_rm(gs_path):
    getblob(gs_path).delete()

def select_episode(allowed_episodes, detected_text):
    common_titles = {t.lower().strip() for s,e,t in allowed_episodes} & {t.lower().strip() for t in detected_text}
    if len(common_titles) == 1:
        ep_dict = {t.lower().strip():(s,e,t) for s,e,t in allowed_episodes}
        return ep_dict[common_titles.pop()]
    return None, None, None

async def ffmpeg_copy(ffmpeg, input_path, output_path, start_offset=0, encode_duration=None):
    """
    Make a quick copy of a MKV container to M4V, only storing the bottom half of each frame
    """
    return await run_cmd(
        '"{}" -i "{}" -ss {} {} -filter:v "crop=in_w:in_h/2:0:in_h/2" -c:a copy "{}"'.format(
            ffmpeg,
            input_path,
            start_offset,
            '-t {}'.format(encode_duration) if encode_duration is not None else '',
            output_path
        )
    )

async def handbrake(taskmaster, taskid, handbrake_path, encoding_args):
    await taskmaster.log(taskid, "Waiting to begin transcoding")
    async with taskmaster.throttle('handbrake'):
        await taskmaster.log(taskid, "Start transcode")
        dirpath = os.path.dirname(encoding_args['output'])
        if not os.path.isdir(dirpath):
            os.makedirs(dirpath)
        if os.path.isfile(encoding_args['output']):
            await taskmaster.log(taskid, "Output file exists, adjusting to 2ndary output path")
            encoding_args['output'] = os.path.join(dirpath, '_tmp_.{}'.format(os.path.basename(encoding_args['output'])))
        await run_cmd(
            '"{}" --preset-import-file "{}" -Z "{}" -i "{}" -o "{}"'.format(
                handbrake_path,
                encoding_args['preset'][0],
                encoding_args['preset'][1],
                encoding_args['input'],
                encoding_args['output']
            )
        )
        await taskmaster.log(taskid, "Finished transcode")
    return tvlib.parse_filename(encoding_args['output'])

async def run_main(taskmaster, constants, filepaths):
    return await asyncio.gather(*(import_file(taskmaster, constants, filepath) for filepath in filepaths))

async def import_file(taskmaster, constants, filepath):
    taskid = await taskmaster.initialize()
    await taskmaster.update_status(taskid, 'Starting')
    start_dir = os.path.dirname(filepath)
    basename = os.path.basename(filepath)
    staging_path = os.path.join(
        start_dir,
        'import_inprogress.{}.{}'.format(datetime.now().strftime(TIMESTAMP_FORMAT), basename)
    )
    try:

        os.rename(filepath, staging_path)
        with tempfile.TemporaryDirectory() as tempdir:
            await taskmaster.update_status(taskid, 'Title Detection')
            season, episode, title = await detect_title(taskmaster, taskid, constants, tempdir, staging_path)
        await taskmaster.log(taskid, "Detected {} --> S{}E{} - {}".format(basename, season, episode, title))
        epinfo = tvlib.EpInfo(
            constants['show-name'],
            season,
            episode,
            title,
            staging_path,
            os.path.basename(staging_path),
            'mkv'
        )
        encoding_args = xcode.handbrake_args(
            [epinfo],
            constants['preset-standard'],
            constants['output-dir'],
            constants['preset-hq'],
            constants['hq-multipart'],
            constants['manual-hq']
        )[0]
        if constants['title-mode']:
            await taskmaster.update_status(taskid, 'Finish')
            encoding_args['input'] = os.path.join(
                start_dir,
                's{}e{} {}.mkv'.format(epinfo.season, epinfo.episode, epinfo.title)
            )
            os.rename(staging_path, encoding_args['input'])
            return encoding_args
        await taskmaster.update_status(taskid, 'Transcoding')
        epinfo = await handbrake(taskmaster, taskid, constants['handbrake-path'], encoding_args)
        await taskmaster.update_status(taskid, 'Finish')
        os.rename(staging_path, os.path.join(
            start_dir,
            'import_complete.{}.{}'.format(datetime.now().strftime(TIMESTAMP_FORMAT), basename)
        ))
        return epinfo
    except:
        await taskmaster.update_status(taskid, "Failed")
        traceback.print_exc()
        os.rename(staging_path, filepath)
        raise

if __name__ == '__main__':
    parser = argparse.ArgumentParser('automated-import')
    parser.add_argument(
        'show_name',
        help="Fully formatted name of the show to import"
    )
    parser.add_argument(
        'import_path',
        help="Import directory for raw mkv files"
    )
    parser.add_argument(
        'output',
        help="Output directory"
    )
    parser.add_argument(
        'preset',
        help="Path to standard quality preset",
        type=xcode.parse_preset
    )
    parser.add_argument(
        'episodes_tsv',
        help="TSV file containing list of episodes. Must have 'season', 'episode', and 'title' columns"
    )
    parser.add_argument(
        'gs_path',
        help="gs:// bucket path to use as a staging directory for text detection"
    )
    parser.add_argument(
        '-c', '--confidence',
        help='Title detection confidence threshold. Must be float < 1. Default: 0.9',
        type=float,
        default=0.9
    )
    parser.add_argument(
        '-e', '--hq-episodes',
        help="List of episodes to apply the HQ preset to. Must be in S:E,... EPList selector format",
        default=None
    )
    parser.add_argument(
        '-f', '--ffmpeg',
        help='Path to ffmpeg. Default: Assumed to be on PATH',
        default='ffmpeg'
    )
    parser.add_argument(
        '-b', '--handbrake',
        help='Path to handbrake. Default: Assumed to be on PATH',
        default='handbrake'
    )
    parser.add_argument(
        '-m', '--no-hq-multipart',
        action='store_false',
        dest='hq_multipart',
        help="Disable automatic HQ multipart. By default, multipart episodes are transcoded using the HQ preset"
    )
    parser.add_argument(
        '-q', '--hq-preset',
        help="Path to HQ preset. Will be used on multipart and manual episodes",
        default=None,
        type=xcode.parse_preset
    )
    parser.add_argument(
        '-p', '--project',
        help="User project for VideoIntelligence API. Default: None",
        default=None
    )
    parser.add_argument(
        '--gcloud-limit',
        type=int,
        help="Limit for concurrent gcloud upload tasks. This does not effect concurrent OCR tasks. Default: 3",
        default=3
    )
    parser.add_argument(
        '--ffmpeg-limit',
        type=int,
        help="Limit for concurrent ffmpeg tasks. Default: 2",
        default=2
    )
    parser.add_argument(
        '--handbrake-limit',
        type=int,
        help="Limit for concurrent handbrake tasks. Do not increase this limit unless you are very confident in what you are doing. Default: 1",
        default=1
    )
    parser.add_argument(
        '-t', '--title-only',
        action='store_true',
        help="If provided, this will run in title detection only mode. It will run through OCR but skip the final handbrake step, and instead write handbrake arguments to a batch script."
    )
    args = parser.parse_args()

    if args.confidence > 1 or args.confidence < 0:
        raise ValueError("Confidence must be a float in [0, 1]")

    constants = {
        'confidence': args.confidence,
        'episodes': [
            (int(row['Season']), int(row['Episode']), row['Title'])
            for row in
            pd.read_csv(args.episodes_tsv, sep='\t')[['Season', 'Episode', 'Title']].dropna().to_dict('rows')
        ],
        'ffmpeg-path': args.ffmpeg,
        'gsutil-path': args.gs_path,
        'handbrake-path': args.handbrake,
        'hq-multipart': args.hq_multipart,
        'manual-hq': tvlib.EPList(args.hq_episodes) if args.hq_episodes is not None else None,
        'output-dir': args.output,
        'preset-hq': args.hq_preset,
        'preset-standard': args.preset,
        'show-name': args.show_name,
        'user-project': args.project,
        'title-mode': args.title_only,
    }

    source_files = [
        os.path.join(args.import_path, filename)
        for filename in os.listdir(args.import_path)
        if filename.endswith('.mkv') and filename.startswith('title')
    ]

    print("Importing", len(source_files), "files")
    print(source_files)

    with Taskmaster(handbrake=args.handbrake_limit, ffmpeg=args.ffmpeg_limit, gcloud=args.gcloud_limit) as tm:
        output = asyncio.run(run_main(tm, constants, source_files))
    if args.title_only:
        print("Encoding arguments written to import.bat")
        xcode.dump_batch_script(
            args.handbrake,
            output,
            'import.bat'
        )
