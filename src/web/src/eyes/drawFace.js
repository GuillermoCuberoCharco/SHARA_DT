/**
 * eyes/drawFace.js
 *
 * Port of draw.py to Canvas 2D API.
 *
 * Coordinate space: 1024 × 600 px
 * (Robot uses sc_width=600, sc_height=1024 → numpy shape (600,1024) → 1024w × 600h)
 *
 * Key fix vs previous version: all eye drawing (iris, pupil, eyelid fills AND
 * eyelid bezier lines) happens inside a single save/clip/restore block clipped
 * to the eye ellipse. Only the outer contour stroke is drawn after restore so
 * it sits cleanly on top with no bleeding into adjacent frames.
 */

const SRC_W = 1024;
const SRC_H = 600;

// ── Bézier helper ─────────────────────────────────────────────────────────────

function bezier(ctx, pts, sx, sy, color, lineWidth) {
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

// ── Eye ───────────────────────────────────────────────────────────────────────

function drawEye(ctx, eye, sx, sy) {
    const cx = eye.center[0] * sx;
    const cy = eye.center[1] * sy;
    const rx = (eye.width / 2) * sx;
    const ry = (eye.height / 2) * sy;
    const pad = Math.max(rx, ry) + 10;

    // Absolute pixel coords of eyelid bezier control points
    const topPts = eye.eyelid_top.map(([dx, dy]) => [cx + dx * sx, cy + dy * sy]);
    const botPts = eye.eyelid_bottom.map(([dx, dy]) => [cx + dx * sx, cy + dy * sy]);

    const pupilX = cx + eye.pupil.offset[0] * sx;
    const pupilY = cy + eye.pupil.offset[1] * sy;
    const irisX = pupilX + eye.iris.offset[0] * sx;
    const irisY = pupilY + eye.iris.offset[1] * sy;
    const irisRx = (eye.iris.width / 2) * sx;
    const irisRy = (eye.iris.height / 2) * sy;
    const pupilRx = (eye.pupil.width / 2) * sx;
    const pupilRy = (eye.pupil.height / 2) * sy;
    const [r, g, b] = eye.iris.color;

    // ── Everything inside eye ellipse clip ───────────────────────────────────
    ctx.save();
    ctx.beginPath();
    ctx.ellipse(cx, cy, rx, ry, 0, 0, Math.PI * 2);
    ctx.clip();

    // White base
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(cx - rx - 5, cy - ry - 5, (rx + 5) * 2, (ry + 5) * 2);

    // Iris
    ctx.beginPath();
    ctx.ellipse(irisX, irisY, irisRx, irisRy, 0, 0, Math.PI * 2);
    ctx.fillStyle = `rgb(${r},${g},${b})`;
    ctx.fill();

    // Pupil
    ctx.beginPath();
    ctx.ellipse(pupilX, pupilY, pupilRx, pupilRy, 0, 0, Math.PI * 2);
    ctx.fillStyle = '#000000';
    ctx.fill();

    // Eyelid top — white fill above the bezier curve
    ctx.fillStyle = '#ffffff';
    ctx.beginPath();
    ctx.moveTo(topPts[0][0], topPts[0][1]);
    ctx.quadraticCurveTo(topPts[1][0], topPts[1][1], topPts[2][0], topPts[2][1]);
    ctx.lineTo(cx + pad, cy - pad);
    ctx.lineTo(cx - pad, cy - pad);
    ctx.closePath();
    ctx.fill();

    // ── Eye contour — clipped to area above bottom eyelid ────────────────────
    ctx.save();
    ctx.beginPath();
    ctx.moveTo(botPts[0][0], botPts[0][1]);
    ctx.quadraticCurveTo(botPts[1][0], botPts[1][1], botPts[2][0], botPts[2][1]);
    ctx.lineTo(cx + pad, cy - pad);
    ctx.lineTo(cx - pad, cy - pad);
    ctx.closePath();
    ctx.clip();
    ctx.beginPath();
    ctx.ellipse(cx, cy, rx, ry, 0, 0, Math.PI * 2);
    ctx.strokeStyle = '#000000';
    ctx.lineWidth = 7 * Math.min(sx, sy);
    ctx.stroke();
    ctx.restore();

    // Eyelid bottom — white fill below the bezier curve
    ctx.beginPath();
    ctx.moveTo(botPts[0][0], botPts[0][1]);
    ctx.quadraticCurveTo(botPts[1][0], botPts[1][1], botPts[2][0], botPts[2][1]);
    ctx.lineTo(cx + pad, cy + pad);
    ctx.lineTo(cx - pad, cy + pad);
    ctx.closePath();
    ctx.fill();

    // Eyelid lines (drawn inside clip — no bleeding outside eye)
    const lw = 7 * Math.min(sx, sy);
    ctx.strokeStyle = '#000000';
    ctx.lineWidth = lw;
    ctx.lineJoin = 'round';
    ctx.lineCap = 'round';

    ctx.beginPath();
    ctx.moveTo(topPts[0][0], topPts[0][1]);
    ctx.quadraticCurveTo(topPts[1][0], topPts[1][1], topPts[2][0], topPts[2][1]);
    ctx.stroke();

    ctx.beginPath();
    ctx.moveTo(botPts[0][0], botPts[0][1]);
    ctx.quadraticCurveTo(botPts[1][0], botPts[1][1], botPts[2][0], botPts[2][1]);
    ctx.stroke();

    ctx.restore();
}

// ── Blush ─────────────────────────────────────────────────────────────────────

function drawBlush(ctx, face, sx, sy) {
    const le = face.eyes.left;
    const re = face.eyes.right;
    const rx = (le.width / 2) * sx;
    const ry = (le.height / 2) * sy;

    const lcx = (le.center[0] / 2) * sx;
    const rcx = (re.center[0] + le.center[0] / 2) * sx;
    const bcy = (le.center[1] * sy) + (SRC_H / 3) * sy;

    ctx.globalAlpha = 0.45;
    ctx.fillStyle = 'rgb(246,195,255)';

    ctx.beginPath();
    ctx.ellipse(lcx, bcy, rx, ry / 2, 0, 0, Math.PI * 2);
    ctx.fill();

    ctx.beginPath();
    ctx.ellipse(rcx, bcy, rx, ry / 2, 0, 0, Math.PI * 2);
    ctx.fill();

    ctx.globalAlpha = 1.0;
}

// ── Public API ────────────────────────────────────────────────────────────────

export function drawFace(ctx, canvasW, canvasH, faceData) {
    const sx = canvasW / SRC_W;
    const sy = canvasH / SRC_H;

    // Clear to white
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(0, 0, canvasW, canvasH);

    // Eyebrows
    bezier(ctx, faceData.eyebrows.left, sx, sy, '#000000', 5);
    bezier(ctx, faceData.eyebrows.right, sx, sy, '#000000', 5);

    // Eyes
    drawEye(ctx, faceData.eyes.left, sx, sy);
    drawEye(ctx, faceData.eyes.right, sx, sy);

    // Blush (optional)
    if (faceData.blush) drawBlush(ctx, faceData, sx, sy);
}