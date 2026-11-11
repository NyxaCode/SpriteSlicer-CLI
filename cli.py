#!/usr/bin/env python3
"""SpriteSlicer CLI — standalone command-line sprite sheet slicer.

Entry points:
  cli.py                       -> interactive menu (no arguments)
  cli.py -i sheet.png          -> single file
  cli.py -d ./sheets/          -> batch folder
  cli.py --help                -> full option reference
"""
import os
import sys
import time
import argparse
import shutil
import tempfile

# Make `src` importable when run as a plain script from any working directory
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from src.core.slicer import slice_spritesheet
from src.core.upscaler import upscale_image, has_gpu_upscaler, get_available_models

VERSION = '1.0.0'
IMAGE_EXTS = ('.png', '.jpg', '.jpeg', '.webp', '.bmp')
KEY_CHOICES = ['green', 'white', 'black']
DEFAULT_MODEL = 'realesrgan-x4plus-anime'


# --------------------------------------------------------------------------
# Terminal helpers
# --------------------------------------------------------------------------
def _enable_unicode():
    """Use UTF-8 on Windows consoles so box drawing / symbols never raise."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding='utf-8', errors='replace')
        except (AttributeError, ValueError):
            pass


_enable_unicode()

USE_COLOR = sys.stdout.isatty() and os.environ.get('NO_COLOR') is None


def _c(text, code):
    if not USE_COLOR:
        return text
    return f'\033[{code}m{text}\033[0m'


def info(msg):
    print(msg, flush=True)


def ok(msg):
    print(_c('  [OK] ', '32') + msg, flush=True)


def warn(msg):
    print(_c('  [!]  ', '33') + msg, flush=True)


def error(msg):
    print(_c('  [X]  ', '31') + msg, file=sys.stderr, flush=True)


def progress(current, total, message):
    """Single-line progress bar that always terminates with a newline."""
    total = max(1, total)
    pct = min(100.0, current / total * 100)
    filled = int(30 * current // total)
    bar = '=' * filled + '-' * (30 - filled)
    if USE_COLOR:
        bar = _c(bar, '36')
    sys.stdout.write(f'\r  [{bar}] {pct:5.1f}% | {message[:60]:<60}')
    sys.stdout.flush()
    if current >= total:
        sys.stdout.write('\n')
        sys.stdout.flush()


# --------------------------------------------------------------------------
# Core pipeline
# --------------------------------------------------------------------------
def default_output_dir(input_path):
    """`<dir>/<name>_extracted` next to the source sheet."""
    base = os.path.splitext(os.path.basename(input_path))[0]
    return os.path.join(os.path.dirname(os.path.abspath(input_path)) or '.',
                        f'{base}_extracted')


def run_pipeline(input_path, output_dir, scale=1, model=DEFAULT_MODEL,
                 min_area=80, padding=2, key_color='green', remove_bg=True,
                 mode='auto', grid_cols=None, grid_rows=None, quiet=False):
    """Upscale (optional) then slice one sheet. Returns a result dict."""
    if not os.path.isfile(input_path):
        error(f'Input file not found: {input_path}')
        return None

    if not input_path.lower().endswith(IMAGE_EXTS):
        warn(f'Unexpected extension; attempting anyway: {os.path.basename(input_path)}')

    output_dir = output_dir or default_output_dir(input_path)
    os.makedirs(output_dir, exist_ok=True)

    started = time.time()
    current_input = input_path
    temp_dir = None

    try:
        # Step 1 — optional GPU upscale
        if scale > 1:
            engine = 'NCNN GPU' if has_gpu_upscaler() else 'Lanczos fallback'
            info(f'[1/2] Upscaling {scale}x with {model} ({engine})...')
            temp_dir = tempfile.mkdtemp(prefix='sss_upscale_')
            upscaled_path = os.path.join(temp_dir, 'upscaled.png')
            upscale_image(current_input, upscaled_path, scale=scale,
                          model_name=model,
                          progress_callback=None if quiet else progress)
            if not os.path.exists(upscaled_path):
                error('Upscaling produced no output; aborting.')
                return None
            current_input = upscaled_path
        elif not quiet:
            info('[1/2] Skipping upscaling (scale = 1x)')

        # Step 2 — detect, key, and export
        if not quiet:
            if mode == 'grid':
                info(f'[2/2] Slicing grid {grid_cols or 4}x{grid_rows or 4} '
                     f'(key={key_color}, bg removal={remove_bg})...')
            else:
                info(f'[2/2] Slicing sprites (key={key_color}, '
                     f'bg removal={remove_bg})...')

        # Detection thresholds must scale with the upscaled pixel count,
        # otherwise a 4x upscale would under-detect tiny sprites.
        result = slice_spritesheet(
            current_input,
            output_dir,
            min_area=int(min_area * (scale ** 2)),
            padding=int(padding * scale),
            key_color=key_color,
            remove_bg=remove_bg,
            progress_callback=None if quiet else progress,
            mode=mode,
            grid_cols=grid_cols,
            grid_rows=grid_rows,
        )
        result['elapsed'] = time.time() - started
        result['input'] = input_path
        return result

    except Exception as exc:
        error(f'Failed to process "{os.path.basename(input_path)}": {exc}')
        return None

    finally:
        # Always release the temp upscaled sheet, even on failure
        if temp_dir and os.path.isdir(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)


def report_single(result):
    if not result:
        return 1
    info('')
    ok(f'Extracted {result["total"]} sprites across {result["rows"]} rows '
       f'in {result["elapsed"]:.2f}s')
    info(f'  Folder   : {result["out_dir"]}')
    info(f'  Manifest : {result["manifest_path"]}')
    info(f'  Catalog  : {result["catalog_path"]}')
    return 0


def collect_images(folder, recursive=False):
    """Every supported image directly inside `folder` (or below it), sorted."""
    found = []
    if recursive:
        for root, _dirs, files in os.walk(folder):
            for f in files:
                if f.lower().endswith(IMAGE_EXTS):
                    found.append(os.path.join(root, f))
    else:
        try:
            entries = os.listdir(folder)
        except OSError as exc:
            error(f'Cannot read folder: {exc}')
            return []
        for f in entries:
            full = os.path.join(folder, f)
            if os.path.isfile(full) and f.lower().endswith(IMAGE_EXTS):
                found.append(full)
    return sorted(found)


def run_batch(folder, output_dir, recursive=False, **kwargs):
    """Process every image in a folder, one output sub-folder each.

    `recursive` is a batch-only concern; it is deliberately not forwarded
    to run_pipeline(), which takes the pipeline keyword arguments.
    """
    if not os.path.isdir(folder):
        error(f'Input folder not found: {folder}')
        return 1

    images = collect_images(folder, recursive=recursive)
    if not images:
        error(f'No supported images found in: {folder}')
        return 1

    total = len(images)
    info(f'Batch mode: {total} image(s) found in "{folder}"')

    succeeded, failed, total_sprites = 0, 0, 0
    started = time.time()

    for idx, img in enumerate(images, 1):
        name = os.path.basename(img)
        base = os.path.splitext(name)[0]
        out = os.path.join(output_dir, base)
        info('')
        info(f'--- [{idx}/{total}] {name} ---')
        result = run_pipeline(img, out, quiet=True, **kwargs)
        if result:
            succeeded += 1
            total_sprites += result['total']
            ok(f'{result["total"]} sprites -> {result["out_dir"]}')
        else:
            failed += 1

    info('')
    info('=' * 62)
    ok(f'Batch finished in {time.time() - started:.2f}s')
    info(f'  Succeeded : {succeeded}/{total}')
    if failed:
        warn(f'Failed    : {failed}/{total}')
    info(f'  Sprites   : {total_sprites}')
    info(f'  Output    : {output_dir}')
    info('=' * 62)
    return 0 if failed == 0 else 1


# --------------------------------------------------------------------------
# Interactive menu (used when the CLI is started with no arguments)
# --------------------------------------------------------------------------
def ask(prompt, default=''):
    try:
        answer = input(f'  {prompt}' + (f' [{default}]' if default else '') + ': ')
    except (EOFError, KeyboardInterrupt):
        print()
        raise SystemExit(0)
    # Strip residual CR/LF: pasted or piped input can carry them on Windows
    answer = answer.replace('\r', '').replace('\n', '').strip()
    return answer or default


def ask_int(prompt, default, lo=None, hi=None):
    """Prompt for an integer, re-asking instead of crashing on bad input."""
    while True:
        raw = ask(prompt, str(default))
        try:
            value = int(raw)
        except ValueError:
            warn(f'"{raw}" is not a number - please try again.')
            continue
        if lo is not None and value < lo:
            warn(f'Value must be >= {lo}.')
            continue
        if hi is not None and value > hi:
            warn(f'Value must be <= {hi}.')
            continue
        return value


def ask_bool(prompt, default=True):
    raw = ask(f'{prompt} (y/n)', 'y' if default else 'n').strip().lower()
    return raw in ('y', 'yes', '1', 'true', 'ya')


def interactive_menu():
    while True:
        print()
        print('=' * 62)
        print('        SPRITESLICER CLI  v' + VERSION + '  — interactive menu')
        print('=' * 62)
        engine = 'Real-ESRGAN / NCNN Vulkan' if has_gpu_upscaler() else 'Lanczos (no GPU binary)'
        print(f'  Upscaler engine : {engine}')
        print()
        print('  [1] Single image')
        print('  [2] Batch folder')
        print('  [3] Show info / available models')
        print('  [0] Exit')
        print('-' * 62)

        choice = ask('Choose [1/2/3/0]', '0')
        if not choice or choice == '0':
            info('Bye!')
            return 0
        if choice == '3':
            print()
            info(f'  Version        : {VERSION}')
            info(f'  Python         : {sys.version.split()[0]}')
            info(f'  GPU binary     : {"yes" if has_gpu_upscaler() else "no (Lanczos fallback)"}')
            info(f'  Models         : {", ".join(get_available_models())}')
            info(f'  Key colours    : {", ".join(KEY_CHOICES)}')
            ask('Press Enter to continue')
            continue
        if choice not in ('1', '2'):
            warn('Invalid choice.')
            continue

        batch = choice == '2'
        print()
        source = ask('Path to image' if not batch else 'Path to folder').strip('"').strip("'")
        if not os.path.exists(source):
            error(f'Path not found: {source}')
            continue

        print()
        remove_bg = ask_bool('Remove background (chroma key)', True)
        key_color = 'green'
        if remove_bg:
            info(f'  Key colours: {", ".join(KEY_CHOICES)}')
            key_color = ask('Key colour', 'green').lower()
            if key_color not in KEY_CHOICES:
                warn(f'Unknown key "{key_color}", using green.')
                key_color = 'green'

        mode = 'auto'
        grid_cols = grid_rows = None
        if ask_bool('Uniform grid slicing instead of auto-detect', False):
            mode = 'grid'
            grid_cols = ask_int('Grid columns', 4, lo=1)
            grid_rows = ask_int('Grid rows', 4, lo=1)

        use_upscale = ask_bool('Upscale with Real-ESRGAN', False)
        scale = 1
        model = DEFAULT_MODEL
        if use_upscale:
            scale = ask_int('Scale factor (2/3/4)', 2, lo=1, hi=4)
            info(f'  Available models: {", ".join(get_available_models())}')
            model = ask('Model', DEFAULT_MODEL)

        min_area = ask_int('Minimum sprite area (px)', 80, lo=0)
        padding = ask_int('Padding around sprites (px)', 2, lo=0)

        print()
        out_dir = ask('Output folder (blank = auto)').strip('"').strip("'")
        if not out_dir:
            out_dir = os.path.join(os.path.abspath(source), 'batch_output') if batch \
                else default_output_dir(source)

        print('-' * 62)
        kwargs = dict(scale=scale, model=model, min_area=min_area, padding=padding,
                      key_color=key_color, remove_bg=remove_bg, mode=mode,
                      grid_cols=grid_cols, grid_rows=grid_rows)

        if batch:
            run_batch(source, out_dir, **kwargs)
        else:
            result = run_pipeline(source, out_dir, **kwargs)
            report_single(result)

        try:
            ask('Press Enter to return to the menu')
        except (EOFError, KeyboardInterrupt):
            return 0


# --------------------------------------------------------------------------
# Argument parsing
# --------------------------------------------------------------------------
def build_parser():
    p = argparse.ArgumentParser(
        prog='spriteslicer',
        description='SpriteSlicer CLI - slice sprite sheets into transparent PNGs '
                    'with chroma keying and optional GPU upscaling.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''examples:
  spriteslicer -i sheet.png
  spriteslicer -i sheet.png -o out -k white
  spriteslicer -i sheet.png -s 4 -m realesrgan-x4plus-anime
  spriteslicer -d ./sheets -o ./out --recursive
  spriteslicer -i sheet.png --grid 4 4
  spriteslicer -i sheet.png --no-bg --quiet
''')

    src = p.add_argument_group('input / output')
    src.add_argument('-i', '--input', help='path to one sprite sheet image')
    src.add_argument('-d', '--input-dir', help='path to a folder of sprite sheets (batch)')
    src.add_argument('-o', '--output', help='output folder (default: <name>_extracted)')
    src.add_argument('-r', '--recursive', action='store_true',
                     help='with --input-dir, also scan sub-folders')

    key = p.add_argument_group('background keying')
    key.add_argument('-k', '--key-color', choices=KEY_CHOICES, default='green',
                     help='background colour to remove (default: green)')
    key.add_argument('--no-bg', action='store_true',
                     help='keep the background, only crop sprites')

    det = p.add_argument_group('detection')
    det.add_argument('--min-area', type=int, default=80,
                     help='minimum sprite area in pixels (default: 80)')
    det.add_argument('--padding', type=int, default=2,
                     help='margin around each sprite crop (default: 2)')
    det.add_argument('--grid', nargs=2, type=int, metavar=('COLS', 'ROWS'),
                     help='slice a uniform COLSxROWS grid instead of auto-detect')

    up = p.add_argument_group('upscaling')
    up.add_argument('-s', '--scale', type=int, choices=[1, 2, 3, 4], default=1,
                    help='upscale factor before slicing (default: 1)')
    up.add_argument('-m', '--model', default=DEFAULT_MODEL,
                    help=f'Real-ESRGAN model (default: {DEFAULT_MODEL})')

    misc = p.add_argument_group('misc')
    misc.add_argument('--list-models', action='store_true',
                      help='print available upscaler models and exit')
    misc.add_argument('--quiet', action='store_true', help='suppress progress output')
    misc.add_argument('--no-color', action='store_true', help='disable coloured output')
    misc.add_argument('--version', action='version', version=f'SpriteSlicer CLI {VERSION}')

    return p


def main(argv=None):
    global USE_COLOR

    parser = build_parser()
    args = parser.parse_args(argv)

    if args.no_color:
        USE_COLOR = False

    if args.list_models:
        info('Available models:')
        for name in get_available_models():
            info(f'  - {name}')
        if not has_gpu_upscaler():
            warn('Real-ESRGAN binary not found; upscaling falls back to Lanczos.')
        return 0

    if args.input and args.input_dir:
        parser.error('use either --input or --input-dir, not both')

    # No source given -> interactive menu
    if not args.input and not args.input_dir:
        return interactive_menu()

    if args.input and not args.input_dir and args.scale > 1 and not args.quiet:
        if not has_gpu_upscaler():
            warn('Bundled Real-ESRGAN binary missing; will use Lanczos fallback.')
        elif args.model not in get_available_models():
            warn(f'Model "{args.model}" not found; using {DEFAULT_MODEL} instead.')
            args.model = DEFAULT_MODEL

    mode = 'auto'
    grid_cols = grid_rows = None
    if args.grid:
        grid_cols, grid_rows = args.grid
        if grid_cols < 1 or grid_rows < 1:
            parser.error('--grid values must be >= 1')
        mode = 'grid'

    kwargs = dict(
        scale=args.scale,
        model=args.model,
        min_area=args.min_area,
        padding=args.padding,
        key_color=args.key_color,
        remove_bg=not args.no_bg,
        mode=mode,
        grid_cols=grid_cols,
        grid_rows=grid_rows,
    )

    if args.input_dir:
        out = args.output or os.path.join(os.path.abspath(args.input_dir), 'batch_output')
        return run_batch(args.input_dir, out, recursive=args.recursive, **kwargs)

    result = run_pipeline(args.input, args.output, quiet=args.quiet, **kwargs)
    return 0 if report_single(result) == 0 else 1


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print('\nCancelled.')
        sys.exit(130)
