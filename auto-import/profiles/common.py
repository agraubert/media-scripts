import abc
from contextlib import ExitStack
import tempfile
import re
import os
import numpy as np
from ..cdrom import CDRom

countn_p = re.compile(r'count:(\d+)')
name_p = re.compile(r'name:(\w+)')


class AbstractProfile(abc.ABC):
	def __init__(self, args):
		self.input = args.input
		self.name = args.name
		self.mkv_extraction_mode = args.extraction_mode.lower() if args.extraction_mode is not None else None
		if self.mkv_extraction_mode is not None:
			if self.mkv_extraction_mode.startswith('count:'):
				match = countn_p.match(self.mkv_extraction_mode)
				if not match:
					raise ValueError("count:n extraction mode invalid format")
				self.mkv_extraction_mode = ('count', int(match.group(1)))
			elif self.mkv_extraction_mode.startswith('name:'):
				match = name_p.match(self.mkv_extraction_mode)
				if not match:
					raise ValueError('name:title extraction mode invalid format')
				self.mkv_extraction_mode = ('name', *match.group(1).split(','))
			elif self.mkv_extraction_mode in {'1gb', 'median', 'all'}:
				# Convert to tuple for compatibility with other modes
				self.mkv_extraction_mode = (self.mkv_extraction_mode,)
			else:
				raise ValueError('Invalid extraction mode')
		self.mediadir = args.mediadir
		self.preset = args.preset
		self.makemkvcon = args.makemkvcon
		self.handbrakecli = args.handbrakecli
		self.tempdir_base = args.tempdir
		self.tempdir = None
		self.stack = None

	@abc.abstractstaticmethod
	def configure_subparser(parser):
		"""
		Given a parser object, add required options for this profile
		"""
		pass

	def import_media(self):
		"""
		Sets up staging directories and allows profile to configure other resources
		If extraction mode is set, then this will rip media from makemkv before running _import()
		"""
		with self:
			if self.mkv_extraction_mode is not None:
				self.rip_mkv()
			self._import()

	def __enter__(self):
		"""
		Sets up temporary directory and exit stack
		Classes overriding this method should call this method first before running their own code
		"""
		self.stack = ExitStack()
		self.stack.__enter__()
		self.tempdir = self.stack.enter_context(tempfile.TemporaryDirectory(dir=self.tempdir_base))
	
	def __exit__(self, exc_type, exc_val, exc_tb):
		"""
		Cleans up temporary resources.
		Classes overriding this method should call this method **AFTER** running their own code
		"""
		self.stack.__exit__(exc_type, exc_val, exc_tb)
		self.stack = None
		self.tempdir = None
		
	@abc.abstractmethod
	def _import(self):
		"""
		Override this method.
		This is where the profile should actually import media
		"""

	def rip_mkv(self):
		"""
		Uses makemkvcon to rip media from current inputs and create a new list of inputs
		"""
		if not os.path.isdir(os.path.join(self.tempdir, 'raw_mkv')):
			os.mkdir(os.path.join(self.tempdir, 'raw_mkv'))
		inputs = []
		for device in self.input:
			cdr = CDRom(device, self.makemkvcon)
			if self.mkv_extraction_mode[0] == 'all':
				titles = cdr.titles
			elif self.mkv_extraction_mode[0] == 'median':
				thresh = np.median([title.length.total_seconds() for title in cdr.titles])
				titles = [title for title in cdr.titles if title.length.total_seconds() > thresh]
			elif self.mkv_extraction_mode[0] == '1gb':
				raise NotImplementedError("Currently our makemkv binding cannot determine title size")
			elif self.mkv_extraction_mode[0] == 'count':
				titles = sorted(cdr.titles, key=lambda t:t.length.total_seconds(), reverse=True)[:self.mkv_extraction_mode[1]]
			elif self.mkv_extraction_mode[0] == 'name':
				raise NotImplementedError("Currently our makemkv binding cannot determine title name")
			
			inputs+= [
				cdr.extract_file(title.id, os.path.join(self.tempdir, 'raw_mkv'))
				for title in titles
			]
		self.input = inputs