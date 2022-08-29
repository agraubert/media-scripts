from .common import AbstractProfile
import subprocess
import sys
import os

class TVProfile(AbstractProfile):
	@staticmethod
	def configure_subparser(parser):
		parser.add_argument(
			'episodes',
			help='tsv file containing "season", "episode", and "title" columns. Used for title detection'
		)

		parser.add_argument(
			'gs_path',
			help="gs:// bucket path to use as a staging directory for text detection"
		)

		parser.add_argument(
			'-s', '--subset',
			help="Subset of episodes in EPList selector format",
			default=None
		)

		parser.add_argument(
			'-c', '--confidence',
			help="Confidence threshold for title detection. Default: 0.9",
			type=float,
			default=0.9
		)

		parser.add_argument(
			'-p', '--project',
			help="User project for VideoIntelligence API. Default: None",
			default=None
		)

		parser.add_argument(
			'--ffmpeg',
			help='Path to ffmpeg executable. Default assume ffmpeg on PATH',
			default='ffmpeg'
		)

	def __init__(self, args):
		super().__init__(args)
		self.episodes = args.episodes
		self.subset = args.subset
		self.confidence = args.confidence
		self.ffmpeg = args.ffmpeg
		self.gs_path = args.gs_path
		self.project = args.project

	def _import(self):
		os.mkdir(os.path.join(self.tempdir), 'profile_staging')
		for f in self.input:
			os.link(
				f,
				os.path.join(
					self.tempdir,
					'profile_staging',
					'title_{}{}.mkv'.format(
						os.path.basename(f),
						os.urandom(2).hex()
					)
				)
			)
		subprocess.check_call(
			[
				sys.executable,
				os.path.join(
					os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
					'full_import.py'
				),
				self.name,
				os.path.join(self.tempdir, 'profile_staging'),
				os.path.join(self.output, 'TV', self.name),
				self.transcode_preset,
				self.episodes,
				self.gs_path,
				'-c',
				self.confidence,
				'-f',
				self.ffmpeg,
				'-b',
				self.handbrakecli,
				'-m',
				'-p',
				self.project,
			]
		)