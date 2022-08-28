# Automatic Media Ingestion

## Media Profiles

When ingesting media, the user must specify a profile. The profile determines the set of tasks and may expose several profile-specific options

### Movie Profile

This profile is for extracting a movie from a DVD or BluRay disc

Options:

- mediadir: The destination media folder. Media will be saved in $MediaDir/Movies
- title: The output title name
- device: The makemkvcon device ID to read from
- transcode-preset: The handbrake transcoding preset name. For a custom UI preset, this should be in presetPath:presetName format
- [makemkvcon]: (optional) command/executable name for makemkvcon
- [handbrake]: (optional) command/executable name for handbrakeCLI

#### makemkv

This phase opens the current disk and extracts the largest title into $MediaDir/Movies/$MediaName/$MediaName.mkv

#### handbrake

This phase transcodes the extracted mkv file into $MediaDir/Movies/$MediaName/$MediaName.mp4

### TV Profile

This profile is for extracting several episodes from a DVD or BluRay disc

Options:

- mediadir: The destination media folder. Media will be saved in $MediaDir/TV/
- show: The name of the Show
- ~~season: The season number. Episodes will be saved in $MediaDir/TV/$Show/Season $Season/~~
- device: The makemkvcon device ID to read from
- transcode-preset: The handbrake transcoding preset name. For a custom UI preset, this should be in presetPath:presetName format
- episodes: A TSV file containing 'season', 'episode', and 'title' columns. Used to filter names for title detection
- [extraction-mode]: The mode for selecting titles to extract from the disc
    - 1GB (default): Select all titles greater than 1GB
	- Count:n : Select the n largest titles
	- Median: Select all titles greater than the median title size
	- Name:title1,title2... : Select the named titles
- [subset]: An EPList (S:E...) selector to limit title detection to a range of episodes from the full episodes TSV
- [makemkvcon]: (optional) command/executable name for makemkvcon
- [ffmpeg]: (optional) command/executable name for ffmpeg
- [handbrake]: (optional) command/executable name for handbrakeCLI
- [confidence]: (optional) Title detection confidence threshold

#### makemkv

This phase extracts titles from the raw disk (based on the given extraction mode).
Titles are saved in $WorkDir/{hex}.mkv

#### Title detection

This phase uses ffmpeg to clip the bottom half of frames in 2 minute chunks from the first 10 minutes of each title.
The chunks are then uploaded to Google Cloud and passed through the VideoIntelligence API to detect text present in the video.
Text is then downloaded and the video chunks deleted. Text is cross-referenced with the provided list of title names and if a 
match is found, it is used to infer the season number, episode number, and title.

Chunks are tried one at a time in this order: Minutes 4-6, 2-4, 6-8, 0-2, and 8-10. If no match is found after attempting each of those chunks,
the program will prompt the user to manually specify the season number, episode number, and title.

#### Copy

After tile detection, the original raw MKV files are copied to
$MediaDir/TV/$Show/Season $Season/$Show - S${Season}E${Episode} - $Title/$Show - S${Season}E${Episode} - $Title.mkv

#### Handbrake

Handbrake is used to transcode a lower quality MP4 container. The media is saved to 
$MediaDir/TV/$Show/Season $Season/$Show - S${Season}E${Episode} - $Title/$Show - S${Season}E${Episode} - $Title.mp4