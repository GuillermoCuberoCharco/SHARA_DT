/**
 * eyes/drawFace.js
 *
 * Port of draw.py to Canvas 2D API.
 *
 * Coordinate space: 1024 x 600 px
 * (Robot uses sc_width=600, sc_height=1024 -> numpy shape (600,1024) -> 1024w x 600h)
 *
 * Key fix vs previous version: all eye drawing (iris, pupil, eyelid fills AND
 * eyelid bezier lines) happens inside a single save/clip/restore block clipped
 * to the eye ellipse. Only the outer contour stroke is drawn after restore so
 * it sits cleanly on top with no bleeding into adjacent frames.
 */

export const EYE_COORDINATE_WIDTH = 1024;
export const EYE_COORDINATE_HEIGHT = 600;
export const EYE_COORDINATE_ASPECT_RATIO = EYE_COORDINATE_WIDTH / EYE_COORDINATE_HEIGHT;

const EYE_OUTLINE_BASE_WIDTH = 14;
const EYELID_BASE_WIDTH = EYE_OUTLINE_BASE_WIDTH * (2 / 3);

function bezier(ctx, pts, transform, color, lineWidth) {
    const { scale, offsetX, offsetY } = transform;

    ctx.beginPath();
    ctx.moveTo(offsetX + pts[0][0] * scale, offsetY + pts[0][1] * scale);
    ctx.quadraticCurveTo(
        offsetX + pts[1][0] * scale,
        offsetY + pts[1][1] * scale,
        offsetX + pts[2][0] * scale,
        offsetY + pts[2][1] * scale,
    );
    ctx.strokeStyle = color;
    ctx.lineWidth = lineWidth * scale;
    ctx.lineJoin = 'round';
    ctx.lineCap = 'round';
    ctx.stroke();
}

function drawEye(ctx, eye, transform) {
    const { scale, offsetX, offsetY } = transform;
    const cx = offsetX + eye.center[0] * scale;
    const cy = offsetY + eye.center[1] * scale;
    const rx = (eye.width / 2) * scale;
    const ry = (eye.height / 2) * scale;
    const pad = Math.max(rx, ry) + 10;

    const topPts = eye.eyelid_top.map(([dx, dy]) => [cx + dx * scale, cy + dy * scale]);
    const botPts = eye.eyelid_bottom.map(([dx, dy]) => [cx + dx * scale, cy + dy * scale]);

    const pupilX = cx + eye.pupil.offset[0] * scale;
    const pupilY = cy + eye.pupil.offset[1] * scale;
    const irisX = pupilX + eye.iris.offset[0] * scale;
    const irisY = pupilY + eye.iris.offset[1] * scale;
    const irisRx = (eye.iris.width / 2) * scale;
    const irisRy = (eye.iris.height / 2) * scale;
    const pupilRx = (eye.pupil.width / 2) * scale;
    const pupilRy = (eye.pupil.height / 2) * scale;
    const [r, g, b] = eye.iris.color;
    const eyeOutlineWidth = EYE_OUTLINE_BASE_WIDTH * scale;
    const eyelidLineWidth = EYELID_BASE_WIDTH * scale;

    ctx.save();
    ctx.beginPath();
    ctx.ellipse(cx, cy, rx, ry, 0, 0, Math.PI * 2);
    ctx.clip();

    ctx.fillStyle = '#ffffff';
    ctx.fillRect(cx - rx - 5, cy - ry - 5, (rx + 5) * 2, (ry + 5) * 2);

    ctx.beginPath();
    ctx.ellipse(irisX, irisY, irisRx, irisRy, 0, 0, Math.PI * 2);
    ctx.fillStyle = `rgb(${r},${g},${b})`;
    ctx.fill();

    ctx.beginPath();
    ctx.ellipse(pupilX, pupilY, pupilRx, pupilRy, 0, 0, Math.PI * 2);
    ctx.fillStyle = '#000000';
    ctx.fill();

    ctx.fillStyle = '#ffffff';
    ctx.beginPath();
    ctx.moveTo(topPts[0][0], topPts[0][1]);
    ctx.quadraticCurveTo(topPts[1][0], topPts[1][1], topPts[2][0], topPts[2][1]);
    ctx.lineTo(cx + pad, cy - pad);
    ctx.lineTo(cx - pad, cy - pad);
    ctx.closePath();
    ctx.fill();

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
    ctx.lineWidth = eyeOutlineWidth;
    ctx.stroke();
    ctx.restore();

    ctx.beginPath();
    ctx.moveTo(botPts[0][0], botPts[0][1]);
    ctx.quadraticCurveTo(botPts[1][0], botPts[1][1], botPts[2][0], botPts[2][1]);
    ctx.lineTo(cx + pad, cy + pad);
    ctx.lineTo(cx - pad, cy + pad);
    ctx.closePath();
    ctx.fill();

    ctx.strokeStyle = '#000000';
    ctx.lineWidth = eyelidLineWidth;
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

function drawBlush(ctx, face, transform) {
    const { scale, offsetX, offsetY } = transform;
    const le = face.eyes.left;
    const re = face.eyes.right;
    const rx = (le.width / 2) * scale;
    const ry = (le.height / 2) * scale;

    const lcx = offsetX + (le.center[0] / 2) * scale;
    const rcx = offsetX + (re.center[0] + le.center[0] / 2) * scale;
    const bcy = offsetY + (le.center[1] + EYE_COORDINATE_HEIGHT / 3) * scale;

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

export function drawFace(ctx, canvasW, canvasH, faceData) {
    const scale = Math.min(
        canvasW / EYE_COORDINATE_WIDTH,
        canvasH / EYE_COORDINATE_HEIGHT,
    );
    const renderW = EYE_COORDINATE_WIDTH * scale;
    const renderH = EYE_COORDINATE_HEIGHT * scale;
    const transform = {
        scale,
        offsetX: (canvasW - renderW) / 2,
        offsetY: (canvasH - renderH) / 2,
    };

    ctx.fillStyle = '#ffffff';
    ctx.fillRect(0, 0, canvasW, canvasH);

    bezier(ctx, faceData.eyebrows.left, transform, '#000000', EYELID_BASE_WIDTH);
    bezier(ctx, faceData.eyebrows.right, transform, '#000000', EYELID_BASE_WIDTH);

    drawEye(ctx, faceData.eyes.left, transform);
    drawEye(ctx, faceData.eyes.right, transform);

    if (faceData.blush) drawBlush(ctx, faceData, transform);
}
