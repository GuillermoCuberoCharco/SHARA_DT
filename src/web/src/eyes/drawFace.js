/**
 * eyes/drawFace.js
 *
 * Port of Proactive-Shara-Robot-main/services/eyes/draw.py to Canvas 2D API.
 *
 * Original uses OpenCV + NumPy with bitmask operations for eyelids.
 * Here we use canvas clip() + fill-over-white, which produces identical results.
 *
 * Coordinate space: 1920 × 1080 (matching the JSON data).
 * All coordinates are scaled to the canvas element's actual pixel size.
 */

// Original coordinate space (matches face JSON data)
const SRC_W = 1920;
const SRC_H = 1080;

// ── Low-level helpers ─────────────────────────────────────────────────────────

/**
 * Draws a quadratic Bézier through 3 control points [P0, P1, P2].
 * Equivalent to Python's draw_bezier() via make_bezier().
 */
function drawBezierCurve(ctx, pts, sx, sy, color, lineWidth) {
    ctx.beginPath();
    ctx.moveTo(pts[0][0] * sx, pts[0][1] * sy);
    ctx.quadraticCurveTo(
        pts[1][0] * sx, pts[1][1] * sy,
        pts[2][0] * sx, pts[2][1] * sy,
    );
    ctx.strokeStyle = color;
    ctx.lineWidth = lineWidth * Math.min(sx, sy);
    ctx.lineJoin = 'round';
    ctx.lineCap = 'round';
    ctx.stroke();
}

/**
 * Defines the ellipse path for clipping — does NOT stroke or fill.
 */
function ellipsePath(ctx, cx, cy, rx, ry) {
    ctx.beginPath();
    ctx.ellipse(cx, cy, rx, ry, 0, 0, Math.PI * 2);
}

// ── Eye renderer ─────────────────────────────────────────────────────────────

function drawEye(ctx, eye, sx, sy) {
    const cx = eye.center[0] * sx;
    const cy = eye.center[1] * sy;
    const rx = (eye.width / 2) * sx;
    const ry = (eye.height / 2) * sy;

    // Absolute eyelid bezier points (in canvas pixels)
    const topPts = eye.eyelid_top.map(([dx, dy]) => [
        (eye.center[0] + dx) * sx,
        (eye.center[1] + dy) * sy,
    ]);
    const botPts = eye.eyelid_bottom.map(([dx, dy]) => [
        (eye.center[0] + dx) * sx,
        (eye.center[1] + dy) * sy,
    ]);

    // Iris & pupil centers
    const pupilX = (eye.center[0] + eye.pupil.offset[0]) * sx;
    const pupilY = (eye.center[1] + eye.pupil.offset[1]) * sy;
    const irisX = (eye.center[0] + eye.pupil.offset[0] + eye.iris.offset[0]) * sx;
    const irisY = (eye.center[1] + eye.pupil.offset[1] + eye.iris.offset[1]) * sy;
    const irisRx = (eye.iris.width / 2) * sx;
    const irisRy = (eye.iris.height / 2) * sy;
    const pupilRx = (eye.pupil.width / 2) * sx;
    const pupilRy = (eye.pupil.height / 2) * sy;

    // ── Step 1: white fill inside eye ellipse ────────────────────────────────
    ctx.save();
    ellipsePath(ctx, cx, cy, rx, ry);
    ctx.fillStyle = '#ffffff';
    ctx.fill();

    // ── Step 2: iris ─────────────────────────────────────────────────────────
    ctx.clip(); // clip subsequent draws to eye ellipse
    const [r, g, b] = eye.iris.color;
    ctx.beginPath();
    ctx.ellipse(irisX, irisY, irisRx, irisRy, 0, 0, Math.PI * 2);
    ctx.fillStyle = `rgb(${r},${g},${b})`;
    ctx.fill();

    // ── Step 3: pupil ────────────────────────────────────────────────────────
    ctx.beginPath();
    ctx.ellipse(pupilX, pupilY, pupilRx, pupilRy, 0, 0, Math.PI * 2);
    ctx.fillStyle = '#000000';
    ctx.fill();

    ctx.restore();

    // ── Step 4: paint eyelid areas white (clip to eye ellipse) ───────────────
    ctx.save();
    ellipsePath(ctx, cx, cy, rx, ry);
    ctx.clip();
    ctx.fillStyle = '#ffffff';

    // Area ABOVE eyelid_top: polygon from far-top-left → far-top-right → right bezier end → bezier curve → left bezier end → close
    const pad = Math.max(rx, ry) + 10;
    ctx.beginPath();
    ctx.moveTo(topPts[0][0], topPts[0][1]);
    ctx.quadraticCurveTo(topPts[1][0], topPts[1][1], topPts[2][0], topPts[2][1]);
    ctx.lineTo(cx + pad, cy - pad);
    ctx.lineTo(cx - pad, cy - pad);
    ctx.closePath();
    ctx.fill();

    // Area BELOW eyelid_bottom
    ctx.beginPath();
    ctx.moveTo(botPts[0][0], botPts[0][1]);
    ctx.quadraticCurveTo(botPts[1][0], botPts[1][1], botPts[2][0], botPts[2][1]);
    ctx.lineTo(cx + pad, cy + pad);
    ctx.lineTo(cx - pad, cy + pad);
    ctx.closePath();
    ctx.fill();

    ctx.restore();

    // ── Step 5: eye contour (always on top) ──────────────────────────────────
    ctx.beginPath();
    ctx.ellipse(cx, cy, rx, ry, 0, 0, Math.PI * 2);
    ctx.strokeStyle = '#000000';
    ctx.lineWidth = 7 * Math.min(sx, sy);
    ctx.stroke();

    // ── Step 6: eyelid bezier lines ──────────────────────────────────────────
    drawBezierCurve(ctx, topPts.map(([x, y]) => [x / sx, y / sy]), sx, sy, '#000000', 7);
    drawBezierCurve(ctx, botPts.map(([x, y]) => [x / sx, y / sy]), sx, sy, '#000000', 7);
}

// ── Blush ─────────────────────────────────────────────────────────────────────

function drawBlush(ctx, face, sx, sy) {
    const leftEye = face.eyes.left;
    const rightEye = face.eyes.right;
    const eyeRx = (leftEye.width / 2) * sx;
    const eyeRy = (leftEye.height / 2) * sy;

    const blushRx = eyeRx;
    const blushRy = (eyeRy / 2);

    const lcx = leftEye.center[0] * sx / 2;
    const rcx = (rightEye.center[0] * sx + lcx);
    const bcy = (leftEye.center[1] * sy) + (SRC_W / 3) * sy;

    ctx.globalAlpha = 0.45;
    ctx.fillStyle = 'rgb(246, 195, 255)';

    ctx.beginPath();
    ctx.ellipse(lcx, bcy, blushRx, blushRy, 0, 0, Math.PI * 2);
    ctx.fill();

    ctx.beginPath();
    ctx.ellipse(rcx, bcy, blushRx, blushRy, 0, 0, Math.PI * 2);
    ctx.fill();

    ctx.globalAlpha = 1.0;
}

// ── Public API ────────────────────────────────────────────────────────────────

/**
 * Renders a face JSON object onto a canvas element.
 * The canvas element must already be sized (canvas.width / canvas.height set).
 *
 * @param {CanvasRenderingContext2D} ctx
 * @param {number}  canvasW  - canvas.width in pixels
 * @param {number}  canvasH  - canvas.height in pixels
 * @param {object}  faceData - parsed face JSON
 */
export function drawFace(ctx, canvasW, canvasH, faceData) {
    const sx = canvasW / SRC_W;
    const sy = canvasH / SRC_H;

    // White background
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(0, 0, canvasW, canvasH);

    // Eyebrows
    const eyebrowWidth = 5;
    drawBezierCurve(ctx, faceData.eyebrows.left, sx, sy, '#000000', eyebrowWidth);
    drawBezierCurve(ctx, faceData.eyebrows.right, sx, sy, '#000000', eyebrowWidth);

    // Eyes
    drawEye(ctx, faceData.eyes.left, sx, sy);
    drawEye(ctx, faceData.eyes.right, sx, sy);

    // Optional blush
    if (faceData.blush) {
        drawBlush(ctx, faceData, sx, sy);
    }
}