import argparse
import re
from .profiles.tv import TVProfile

def regex_type(pattern, groups):

	def parser(arg):
		match = pattern.match(arg)
		if match is not None:
			return [*(match.group(group+1) for group in range(groups))]
		raise ValueError("Invalid format. Expected {}".format(pattern))
	
	return parser

profiles = {
	'tv': TVProfile
}

if __name__ == '__main__':
	parser = argparse.ArgumentParser(
		description="Automated media import script. Select a import profile for detailed help"
	)
	subparsers = parser.add_subparsers(dest='profile', required=True)

	parent = argparse.ArgumentParser(add_help=False)

	parent.add_argument(
		'input',
		help='Input media file(s)',
		nargs="+"
	)

	parent.add_argument(
		'name',
		help='Movie/Show name'
	)

	parent.add_argument(
		'mediadir',
		help="Destination root media folder. Output media will usually be stored in a subdirectory from this folder based on the selected import profile"
	)

	parent.add_argument(
		'transcode-preset',
		help="Path to, and name of, a handbrake prset json file. Should be in filepath:presetName format",
		type=regex_type(re.compile('(.+):(.+)'), 2)
	)

	

	parent.add_argument(
		'-e', '--extraction-mode',
		help='If this is set, the "input" filepath(s) are interpreted as paths to optical media devices.'
		' MakeMKV will be used to extract the actual input files from these devices. If this flag is set'
		' you must provide one of the following heuristics:\n'
		' count:n : (default) Extract the longest n titles from the device\n'
		' 1gb : Extract all titles larger than 1GB\n'
		' median : Extract all titles larger than the median title size\n'
		' name:title1,title2,title3... : Extract the comma separated titles by name\n'
		' all : Extract all titles (not recommended)'
	)

	parent.add_argument(
		'-t', '--tempdir',
		help='Path where importer should stage temporary files. Default: system default temp location',
		default=None
	)

	parent.add_argument(
		'--makemkvcon',
		help='Path to makemkvcon executable. By default, "makemkvcon" is assumed to be on PATH',
		default='makemkvcon'
	)

	parent.add_argument(
		'--handbrakecli',
		help='Path to handbrakecli executable. By default, "handbrakecli" is assumed to be on PATH',
		default='handbrakecli'
	)

	for name, profile in profiles.items():
		profile.configure_subparser(subparsers.add_parser(name, parents=[parent]))

	

	args = parser.parse_args()
	profiles[args.profile](args).import_media()