"""Core sprite-sheet slicing engine: detection, chroma keying, manifest + catalog."""
import os
import json
import numpy as np
from PIL import Image, ImageDraw
import cv2

# Anchors the transparent PNG's meaningful colour data. Deep green cushions
# would otherwise pick up a green cast while being measured for keying.
_ALPHA_SENTINEL = np.array([255, 0, 255], dtype=np.uint8)


def remove_background_and_despill(crop, key_color='green'):
    """Clean the background using connected components, border flood-fill, and despill.

    Guarantees internal objects sharing the key colour (cushions, foliage, shirts)
    remain 100% solid, because only background regions touching the crop border —
    plus provably pure-key interior holes — are keyed out.
    """
    h, w = crop.shape[:2]
    if crop.ndim != 3 or h == 0 or w == 0:
        return np.zeros((max(h, 1), max(w, 1), 4), dtype=np.uint8)

    r = crop[:, :, 0].astype(int)
    g = crop[:, :, 1].astype(int)
    b = crop[:, :, 2].astype(int)
    max_rb = np.maximum(r, b)
    diff = g - max_rb

    if key_color == 'green':
        # Pure chroma green background (high purity, low R and B)
        c1 = (g >= 140) & (r <= 35) & (b <= 35) & (diff >= 90)
        # Shadowed / ambient green background along edges
        c2 = (g >= 70) & (r <= 25) & (b <= 25) & (diff >= 50)
        candidate_bg = c1 | c2
    elif key_color == 'white':
        candidate_bg = (r >= 240) & (g >= 240) & (b >= 240)
    elif key_color == 'black':
        candidate_bg = (r <= 15) & (g <= 15) & (b <= 15)
    else:
        c1 = (g >= 140) & (r <= 35) & (b <= 35) & (diff >= 90)
        c2 = (g >= 70) & (r <= 25) & (b <= 25) & (diff >= 50)
        candidate_bg = c1 | c2

    # Connected components separate exterior background from internal same-colour objects
    num_labels, labels = cv2.connectedComponents(candidate_bg.astype(np.uint8))
    border_mask = np.zeros((h, w), dtype=bool)
    border_mask[0, :] = True
    border_mask[-1, :] = True
    border_mask[:, 0] = True
    border_mask[:, -1] = True

    bg_labels = set(np.unique(labels[border_mask & candidate_bg]).tolist())
    bg_labels.discard(0)

    # Interior holes count as background only when they are provably pure key colour
    if num_labels > 1:
        counts = np.bincount(labels.ravel(), minlength=num_labels)
        for lbl in range(1, num_labels):
            if lbl in bg_labels or counts[lbl] <= 10:
                continue
            ys, xs = np.where(labels == lbl)
            if key_color == 'green':
                if (np.mean(g[ys, xs]) >= 150 and np.mean(diff[ys, xs]) >= 100
                        and np.mean(r[ys, xs]) <= 30):
                    bg_labels.add(lbl)
            elif key_color == 'white':
                if np.mean(crop[ys, xs]) > 240:
                    bg_labels.add(lbl)

    final_bg = np.isin(labels, np.fromiter(bg_labels, dtype=labels.dtype,
                                           count=len(bg_labels))) if bg_labels \
        else np.zeros((h, w), dtype=bool)

    # Morphological rings around the background, used for anti-aliasing and despill
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    bg_u8 = final_bg.astype(np.uint8)
    dilated_bg_1 = cv2.dilate(bg_u8, kernel, iterations=1)
    dilated_bg_2 = cv2.dilate(bg_u8, kernel, iterations=2)

    edge_zone_1 = (dilated_bg_1 == 1) & (~final_bg)
    edge_zone_2 = (dilated_bg_2 == 1) & (dilated_bg_1 == 0)

    alpha = np.full((h, w), 255, dtype=np.uint8)
    alpha[final_bg] = 0
    cleaned = crop.copy().astype(np.float32)
    # Fill keyed-out pixels with a sentinel so transparent areas never stay neon green
    cleaned[final_bg] = _ALPHA_SENTINEL

    if key_color == 'green':
        # Vectorised despill: G is clamped down to max(R, B) on the edge rings
        ys, xs = np.where(edge_zone_1)
        if ys.size:
            r_val = r[ys, xs].astype(np.float32)
            g_val = g[ys, xs].astype(np.float32)
            b_val = b[ys, xs].astype(np.float32)
            m_rb = np.maximum(r_val, b_val)
            d_val = g_val - m_rb
            hit = d_val > 10
            cleaned[ys[hit], xs[hit], 1] = m_rb[hit] + 2.0

            g_hit = g_val[hit]
            a_hit = np.full(g_hit.shape, 255, dtype=np.uint8)
            a_hit[g_hit > 140] = 0
            mid = (g_hit > 70) & (g_hit <= 140)
            a_hit[mid] = ((140.0 - g_hit[mid]) / 70.0 * 255.0).astype(np.uint8)
            alpha[ys[hit], xs[hit]] = a_hit

        ys2, xs2 = np.where(edge_zone_2)
        if ys2.size:
            r_val = r[ys2, xs2].astype(np.float32)
            g_val = g[ys2, xs2].astype(np.float32)
            b_val = b[ys2, xs2].astype(np.float32)
            m_rb = np.maximum(r_val, b_val)
            hit = (g_val - m_rb > 25) & (g_val > 110)
            cleaned[ys2[hit], xs2[hit], 1] = m_rb[hit] + 5.0

    rgba = np.dstack([np.clip(cleaned, 0, 255).astype(np.uint8), alpha])

    # Trim empty transparent edges
    non_empty = np.where(alpha > 0)
    if len(non_empty[0]) > 0:
        ymin, ymax = non_empty[0].min(), non_empty[0].max() + 1
        xmin, xmax = non_empty[1].min(), non_empty[1].max() + 1
        rgba = rgba[ymin:ymax, xmin:xmax]

    return rgba


def _foreground_mask(arr, key_color):
    """Boolean mask of pixels that are NOT the key background."""
    if key_color == 'green':
        bg = (arr[:, :, 1] >= 200) & (arr[:, :, 0] <= 60) & (arr[:, :, 2] <= 60)
    elif key_color == 'white':
        bg = (arr[:, :, 0] >= 240) & (arr[:, :, 1] >= 240) & (arr[:, :, 2] >= 240)
    elif key_color == 'black':
        bg = (arr[:, :, 0] <= 15) & (arr[:, :, 1] <= 15) & (arr[:, :, 2] <= 15)
    else:
        bg = (arr[:, :, 1] >= 200) & (arr[:, :, 0] <= 60) & (arr[:, :, 2] <= 60)
    return (~bg)


def _freeform_boxes(fg_mask, min_area):
    """Connected-component boxes for free-form detection."""
    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(fg_mask, connectivity=8)
    boxes = []
    for i in range(1, num_labels):
        area = int(stats[i, cv2.CC_STAT_AREA])
        if area >= min_area:
            boxes.append((
                int(stats[i, cv2.CC_STAT_TOP]),
                int(stats[i, cv2.CC_STAT_LEFT]),
                int(stats[i, cv2.CC_STAT_WIDTH]),
                int(stats[i, cv2.CC_STAT_HEIGHT]),
                area,
            ))
    return boxes


def _grid_boxes(fg_mask, H, W, cols, rows, min_area):
    """Evenly sliced dense boxes; empty cells are skipped."""
    cols = max(1, int(cols))
    rows = max(1, int(rows))
    cell_w = W / cols
    cell_h = H / rows
    boxes = []
    for row in range(rows):
        for col in range(cols):
            x1 = int(round(col * cell_w))
            y1 = int(round(row * cell_h))
            x2 = int(round((col + 1) * cell_w))
            y2 = int(round((row + 1) * cell_h))
            cell = fg_mask[y1:y2, x1:x2]
            area = int(cell.sum())
            if area < min_area:
                continue
            ys, xs = np.where(cell)
            if ys.size == 0:
                continue
            boxes.append((
                y1 + int(ys.min()),
                x1 + int(xs.min()),
                int(xs.max() - xs.min() + 1),
                int(ys.max() - ys.min() + 1),
                area,
            ))
    return boxes


def _cluster_rows(boxes):
    """Group boxes into horizontal rows by vertical overlap, then sort left-to-right."""
    boxes.sort(key=lambda b: (b[0], b[1]))
    rows = []
    for b in boxes:
        y, _x, _w, h, _area = b
        placed = False
        for row in rows:
            r_y1 = min(item[0] for item in row)
            r_y2 = max(item[0] + item[3] for item in row)
            # Overlap test: a box joins a row when its span intersects the row span
            if not (y + h <= r_y1 or y >= r_y2):
                row.append(b)
                placed = True
                break
        if not placed:
            rows.append([b])

    for row in rows:
        row.sort(key=lambda item: item[1])
    rows.sort(key=lambda row: min(item[0] for item in row))
    return rows


def slice_spritesheet(image_path, out_dir, min_area=80, padding=2, key_color='green',
                      remove_bg=True, progress_callback=None, mode='auto',
                      grid_cols=None, grid_rows=None):
    """Slice a sprite sheet into isolated transparent PNGs and export manifest + catalog.

    mode='auto'  -> free-form connected-component detection (default)
    mode='grid'  -> uniform grid using grid_cols x grid_rows
    """
    os.makedirs(out_dir, exist_ok=True)

    with Image.open(image_path) as im:
        arr = np.array(im.convert('RGB'))
    H, W = arr.shape[:2]

    fg_mask = _foreground_mask(arr, key_color)
    fg_u8 = fg_mask.astype(np.uint8)

    if mode == 'grid':
        cols = grid_cols or 4
        rows_n = grid_rows or 4
        boxes = _grid_boxes(fg_u8, H, W, cols, rows_n, min_area)
    else:
        boxes = _freeform_boxes(fg_u8, min_area)

    rows = _cluster_rows(boxes)

    sprites_dir = os.path.join(out_dir, 'sprites')
    os.makedirs(sprites_dir, exist_ok=True)

    manifest = []
    total_sprites = sum(len(r) for r in rows)
    current_idx = 0

    for row_idx, row in enumerate(rows):
        row_folder = os.path.join(sprites_dir, f'row_{row_idx + 1:02d}')
        os.makedirs(row_folder, exist_ok=True)

        for col_idx, item in enumerate(row):
            y, x, w, h, _area = item
            current_idx += 1
            if progress_callback:
                progress_callback(current_idx, total_sprites,
                                  f'Processing sprite {current_idx}/{total_sprites}')

            x1 = max(0, x - padding)
            y1 = max(0, y - padding)
            x2 = min(W, x + w + padding)
            y2 = min(H, y + h + padding)

            crop = arr[y1:y2, x1:x2]
            if remove_bg:
                rgba = remove_background_and_despill(crop, key_color=key_color)
            else:
                rgba = np.dstack([
                    crop,
                    np.full((crop.shape[0], crop.shape[1]), 255, dtype=np.uint8),
                ])

            # Guard against zero-size crops so the slice is always valid
            if rgba.size == 0:
                rgba = np.zeros((1, 1, 4), dtype=np.uint8)

            fname = f'sprite_r{row_idx + 1:02d}_c{col_idx + 1:02d}.png'
            fpath = os.path.join(row_folder, fname)
            rel_path = f'sprites/row_{row_idx + 1:02d}/{fname}'

            Image.fromarray(np.ascontiguousarray(rgba)).save(fpath)

            manifest.append({
                'id': current_idx,
                'row': row_idx + 1,
                'col': col_idx + 1,
                'filename': fname,
                'rel_path': rel_path,
                'width': int(rgba.shape[1]),
                'height': int(rgba.shape[0]),
                'bbox': [int(x), int(y), int(w), int(h)],
            })

    manifest_path = os.path.join(out_dir, 'manifest.json')
    with open(manifest_path, 'w', encoding='utf-8') as f:
        json.dump(manifest, f, indent=2)

    catalog_path = generate_catalog_preview(out_dir, manifest, rows)

    return {
        'total': total_sprites,
        'rows': len(rows),
        'manifest_path': manifest_path,
        'catalog_path': catalog_path,
        'out_dir': out_dir,
    }


def generate_catalog_preview(out_dir, manifest, rows=None):
    """Render a checkerboard contact sheet of every extracted sprite."""
    preview_w = 1600
    min_h = 400
    if rows is None:
        rows = []
        for m in manifest:
            while len(rows) < m['row']:
                rows.append([])
            rows[m['row'] - 1].append(m)

    # Group manifest by row once, so height estimation is O(n) and order-safe
    by_row = {}
    for m in manifest:
        by_row.setdefault(m['row'], []).append(m)

    # Estimate height first so the canvas is sized correctly (no clipping)
    pad = 25
    row_gap = 25
    label_h = 20
    est = pad
    for row_idx in range(len(rows)):
        items = by_row.get(row_idx + 1, [])
        if not items:
            continue
        max_h = max(m['height'] for m in items)
        # Account for the row wrapping onto several visual lines
        acc_w = 0
        lines = 1
        for m in items:
            if acc_w + m['width'] + 10 > preview_w - pad * 2:
                lines += 1
                acc_w = 0
            acc_w += m['width'] + 10
        est += label_h + max_h * lines + row_gap
    preview_h = max(min_h, est + 40)

    sq = 16
    cb = np.zeros((preview_h, preview_w, 3), dtype=np.uint8)
    yy, xx = np.mgrid[0:preview_h, 0:preview_w]
    checker = (((xx // sq) + (yy // sq)) % 2) == 0
    cb[checker] = (24, 28, 36)
    cb[~checker] = (34, 38, 48)

    catalog_img = Image.fromarray(cb)
    draw = ImageDraw.Draw(catalog_img)

    cur_y = 20
    for row_idx in range(len(rows)):
        row_items = by_row.get(row_idx + 1, [])
        if not row_items:
            continue

        draw.text((25, cur_y), f'ROW {row_idx + 1:02d} ({len(row_items)} SPRITES)',
                  fill=(240, 200, 80))
        cur_y += label_h

        max_h = max(m['height'] for m in row_items)
        cur_x = pad

        for item in row_items:
            sp_path = os.path.join(out_dir, item['rel_path'])
            if not os.path.exists(sp_path):
                continue
            with Image.open(sp_path) as sp_raw:
                sp = sp_raw.copy()
            if cur_x + sp.width > preview_w - pad:
                cur_x = pad
                cur_y += max_h + 10
            catalog_img.paste(sp, (cur_x, cur_y), sp)
            cur_x += sp.width + 10

        cur_y += max_h + row_gap

    catalog_img = catalog_img.crop((0, 0, preview_w, min(preview_h, cur_y + 40)))
    catalog_path = os.path.join(out_dir, 'catalog_preview.png')
    catalog_img.save(catalog_path)
    return catalog_path
