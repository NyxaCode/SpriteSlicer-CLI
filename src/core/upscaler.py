"""Real-ESRGAN (NCNN / Vulkan) upscaler with a safe Lanczos fallback."""
import os
import sys
import subprocess
from PIL import Image

EXE_NAME = 'realesrgan-ncnn-vulkan.exe' if os.name == 'nt' else 'realesrgan-ncnn-vulkan'
FALLBACK_MODEL = 'realesrgan-x4plus-anime'


def get_realesrgan_bin_dir():
    """Locate the bundled realesrgan binary directory, or None if absent."""
    if getattr(sys, 'frozen', False):
        candidates = [os.path.join(getattr(sys, '_MEIPASS', ''), 'bin', 'realesrgan')]
    else:
        here = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.abspath(os.path.join(here, '..', '..'))
        candidates = [os.path.join(project_root, 'bin', 'realesrgan')]

    for path in candidates:
        if path and os.path.exists(os.path.join(path, EXE_NAME)):
            return path
    return None


def has_gpu_upscaler():
    """True when the bundled Real-ESRGAN binary is actually available."""
    return get_realesrgan_bin_dir() is not None


def get_available_models():
    """Model names (without extension) found in the bundled models/ folder."""
    bin_dir = get_realesrgan_bin_dir()
    if not bin_dir:
        return [FALLBACK_MODEL]
    models_dir = os.path.join(bin_dir, 'models')
    if not os.path.isdir(models_dir):
        return [FALLBACK_MODEL]
    names = sorted(
        os.path.splitext(f)[0] for f in os.listdir(models_dir) if f.endswith('.param')
    )
    return names or [FALLBACK_MODEL]


def _report(cb, current, total, message):
    """Invoke the progress callback without letting a UI bug kill the pipeline."""
    if not cb:
        return
    try:
        cb(current, total, message)
    except Exception:
        pass


def upscale_image(input_path, output_path, scale=2, model_name=FALLBACK_MODEL,
                  progress_callback=None):
    """Upscale an image, preferring the NCNN GPU binary and falling back to Lanczos."""
    bin_dir = get_realesrgan_bin_dir()
    exe_path = os.path.join(bin_dir, EXE_NAME) if bin_dir else None

    if exe_path:
        _report(progress_callback, 0, 100,
                f'Running Real-ESRGAN GPU upscaler ({scale}x, {model_name})...')

        cmd = [exe_path, '-i', input_path, '-o', output_path,
               '-s', str(scale), '-n', model_name]

        try:
            process = subprocess.Popen(
                cmd,
                cwd=bin_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                errors='replace',
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
            )

            # Real-ESRGAN prints progress as "12.34%" lines mixed with noise.
            for line in process.stdout or []:
                line = line.strip()
                if '%' not in line:
                    continue
                token = line.split('%')[0].split()[-1] if line else ''
                try:
                    pct = float(token)
                except (ValueError, IndexError):
                    continue
                pct = max(0.0, min(100.0, pct))
                _report(progress_callback, int(pct), 100, f'Upscaling: {pct:.1f}%')

            process.wait()

            if process.returncode == 0 and os.path.exists(output_path):
                _report(progress_callback, 100, 100,
                        'Upscaling complete (NCNN GPU)')
                return output_path
        except Exception as exc:
            print(f'Warning: Real-ESRGAN failed ({exc}). Falling back to Lanczos.')
    else:
        print('Note: bundled Real-ESRGAN binary not found; using Lanczos fallback.')

    # Fallback: high-quality Lanczos resampling via Pillow
    _report(progress_callback, 50, 100, f'Running Lanczos upscale fallback ({scale}x)...')

    with Image.open(input_path) as im:
        new_w = max(1, int(im.width * scale))
        new_h = max(1, int(im.height * scale))
        upscaled = im.resize((new_w, new_h), Image.Resampling.LANCZOS)
        upscaled.save(output_path)

    _report(progress_callback, 100, 100, 'Upscaling complete (Lanczos fallback)')
    return output_path
