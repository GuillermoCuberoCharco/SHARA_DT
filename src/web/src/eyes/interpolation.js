/**
 * eyes/interpolation.js
 *
 * Port of Proactive-Shara-Robot-main/services/eyes/interpolation.py
 * Generates intermediate face states between two face JSON objects.
 *
 * All logic is identical to the Python original — same math, same structure.
 */

// ── Helpers ──────────────────────────────────────────────────────────────────

function interpolatePoints(a, b, steps) {
    if (a[0] === b[0] && a[1] === b[1]) return Array(steps).fill(a);

    const vec = [b[0] - a[0], b[1] - a[1]];
    const mod = Math.sqrt(vec[0] ** 2 + vec[1] ** 2);
    const unit = [vec[0] / mod, vec[1] / mod];
    const stepMod = mod / (steps + 1);
    const disp = [unit[0] * stepMod, unit[1] * stepMod];

    const result = [];
    for (let i = 1; i <= steps; i++) {
        result.push([
            Math.round(a[0] + disp[0] * i),
            Math.round(a[1] + disp[1] * i),
        ]);
    }
    return result;
}

// ── Face dict ↔ flat list ─────────────────────────────────────────────────────

function dictfaceToList(d) {
    const e = d.eyes;
    const b = d.eyebrows;
    return [
        // eyebrows: 6 points
        ...b.left,
        ...b.right,
        // left eye
        e.left.center,
        [e.left.width, e.left.height],
        e.left.pupil.offset,
        [e.left.pupil.width, e.left.pupil.height],
        e.left.iris.offset,
        [e.left.iris.width, e.left.iris.height],
        ...e.left.eyelid_top,
        ...e.left.eyelid_bottom,
        // right eye
        e.right.center,
        [e.right.width, e.right.height],
        e.right.pupil.offset,
        [e.right.pupil.width, e.right.pupil.height],
        e.right.iris.offset,
        [e.right.iris.width, e.right.iris.height],
        ...e.right.eyelid_top,
        ...e.right.eyelid_bottom,
    ];
}

function listToFaces(lists, steps, baseDict) {
    // Deep clone utility
    const clone = (obj) => JSON.parse(JSON.stringify(obj));
    const results = [];

    for (let i = 0; i < steps; i++) {
        const f = clone(baseDict);
        const b = f.eyebrows;
        const e = f.eyes;

        // eyebrows
        b.left = [lists[0][i], lists[1][i], lists[2][i]];
        b.right = [lists[3][i], lists[4][i], lists[5][i]];

        // left eye
        e.left.center = lists[6][i];
        e.left.width = lists[7][i][0];
        e.left.height = lists[7][i][1];
        e.left.pupil.offset = lists[8][i];
        e.left.pupil.width = lists[9][i][0];
        e.left.pupil.height = lists[9][i][1];
        e.left.iris.offset = lists[10][i];
        e.left.iris.width = lists[11][i][0];
        e.left.iris.height = lists[11][i][1];
        e.left.eyelid_top = [lists[12][i], lists[13][i], lists[14][i]];
        e.left.eyelid_bottom = [lists[15][i], lists[16][i], lists[17][i]];

        // right eye
        e.right.center = lists[18][i];
        e.right.width = lists[19][i][0];
        e.right.height = lists[19][i][1];
        e.right.pupil.offset = lists[20][i];
        e.right.pupil.width = lists[21][i][0];
        e.right.pupil.height = lists[21][i][1];
        e.right.iris.offset = lists[22][i];
        e.right.iris.width = lists[23][i][0];
        e.right.iris.height = lists[23][i][1];
        e.right.eyelid_top = [lists[24][i], lists[25][i], lists[26][i]];
        e.right.eyelid_bottom = [lists[27][i], lists[28][i], lists[29][i]];

        results.push(f);
    }
    return results;
}

// ── Public API ────────────────────────────────────────────────────────────────

/**
 * Returns `steps` intermediate face objects between origin and target.
 * Identical semantics to Python's get_in_between_faces().
 *
 * @param {object} origin  - source face JSON
 * @param {object} target  - target face JSON
 * @param {number} steps   - number of intermediate frames (default 6)
 * @returns {object[]}
 */
export function getInBetweenFaces(origin, target, steps = 6) {
    const originList = dictfaceToList(origin);
    const targetList = dictfaceToList(target);

    const interpolated = originList.map((a, idx) =>
        interpolatePoints(a, targetList[idx], steps)
    );

    return listToFaces(interpolated, steps, target);
}