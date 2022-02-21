import argparse
import os

if __name__ == '__main__':
    parser = argparse.ArgumentParser('title-renamer')
    parser.add_argument('import_dir', help="import directory to scan for title_txx.mkv")
    parser.add_argument('prefix', help='prefix to rename titles: title_{prefix}txx.mkv')
    args = parser.parse_args()

    for f in os.listdir(args.import_dir):
        if f.startswith('title_t') and f.endswith('.mkv'):
            os.rename(
                os.path.join(args.import_dir, f),
                os.path.join(
                    args.import_dir,
                    'title_{}{}'.format(
                        args.prefix,
                        f[6:]
                    )
                )
            )
