import subprocess
from collections import namedtuple
from datetime import timedelta
import re
import tempfile
import os
import shutil

title_len_p = re.compile(r'Title #\d+ was added \(\d+ cell\(s\), (\d+):(\d+):(\d+)\)')
total_titles_p = re.compile(r'Total \d+ titles$')
title_id_p = re.compile(r'Title\s+(\w+)')

Title = namedtuple('Title', [
	'id',
	'length', # timedelta format
	'tracks' # unused. Will be parsed in future
])
class CDRom(object):

	def __init__(self, device, makemkvcon='makemkvcon'):
		self.dev = device
		self.makemkvcon = makemkvcon
		self.__titles = None
	
	@property
	def titles(self):
		if self.__titles is None:
			proc = subprocess.run(
				[
					self.makemkvcon,
					'info',
					'dev:{}'.format(self.device)
				],
				stdout=subprocess.PIPE,
				check=True
			)
			self.__titles = []
			title_lengths = []
			phase = 'titlelen'
			for line in proc.stdout.decode().split('\n'):
				if phase == 'titlelen':
					if title_len_p.match(line.strip()):
						match = title_len_p.match(line.strip())
						title_lengths.append(timedelta(
							hours=int(match.group(1)),
							minutes=int(match.group(2)),
							seconds=int(match.group(3))
						))
					if total_titles_p.match(line.strip()):
						phase = 'title_start'
				elif phase == 'title_start':
					match = title_id_p.match(line.strip())
					if match is not None:
						phase = 'tracks'
						self.__titles.append(
							Title(
								id=match.group(1),
								length=title_lengths.pop(0),
								tracks=[]
							)
						)
				elif phase == 'tracks':
					if len(line.strip()):
						self.__titles[-1].tracks.append(line.strip())
					else:
						phase = 'title_start'
		return self.__titles


	def extract_file(self, title, dest):
		"""
		Extract the given title id and move the output mkv file to dest
		if dest is a directory then the output file will retain its original
		filename, which is often garbage.
		Returns the full filepath (including filename) of the output file
		"""
		with tempfile.TemporaryDirectory() as tempdir:
			subprocess.check_call(
				[
					self.makemkvcon, 
					'mkv',
					'dev:{}'.format(self.device),
					title,
					tempdir
				],
			)
			filename = os.listdir(tempdir)
			# FIXME: Make sure shutil.move returns in the correct format
			return shutil.move(os.path.join(tempdir, filename), dest)
