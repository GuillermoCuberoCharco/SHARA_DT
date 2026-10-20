const toFiniteNumber = (value) => {
    const number = Number(value);
    return Number.isFinite(number) ? number : null;
};

const firstValue = (value) => {
    if (Array.isArray(value) || ArrayBuffer.isView(value)) {
        return value[0];
    }
    return value;
};

export const getFaceObservation = (face) => {
    if (!face?.topLeft || !face?.bottomRight) {
        return null;
    }

    const left = toFiniteNumber(face.topLeft[0]);
    const top = toFiniteNumber(face.topLeft[1]);
    const right = toFiniteNumber(face.bottomRight[0]);
    const bottom = toFiniteNumber(face.bottomRight[1]);
    const probability = toFiniteNumber(firstValue(face.probability));

    if ([left, top, right, bottom].some((value) => value === null)) {
        return null;
    }

    return {
        left,
        top,
        right,
        bottom,
        width: right - left,
        height: bottom - top,
        probability,
    };
};

export const getIntersectionOverUnion = (first, second) => {
    if (!first || !second) {
        return 0;
    }

    const intersectionWidth = Math.max(
        0,
        Math.min(first.right, second.right) - Math.max(first.left, second.left),
    );
    const intersectionHeight = Math.max(
        0,
        Math.min(first.bottom, second.bottom) - Math.max(first.top, second.top),
    );
    const intersectionArea = intersectionWidth * intersectionHeight;
    const firstArea = Math.max(0, first.width) * Math.max(0, first.height);
    const secondArea = Math.max(0, second.width) * Math.max(0, second.height);
    const unionArea = firstArea + secondArea - intersectionArea;

    return unionArea > 0 ? intersectionArea / unionArea : 0;
};

export const validateFaceObservation = (observation, video, settings) => {
    const videoWidth = Number(video?.videoWidth) || 0;
    const videoHeight = Number(video?.videoHeight) || 0;

    if (!observation || videoWidth <= 0 || videoHeight <= 0) {
        return { valid: false, reason: 'invalid_geometry' };
    }

    if (
        observation.probability === null
        || observation.probability < settings.minProbability
    ) {
        return { valid: false, reason: 'low_probability' };
    }

    const minFaceSize = Math.max(
        settings.minFaceSizePx,
        Math.min(videoWidth, videoHeight) * settings.minFaceSizeRatio,
    );

    if (observation.width < minFaceSize || observation.height < minFaceSize) {
        return { valid: false, reason: 'face_too_small' };
    }

    if (
        observation.left < 0
        || observation.top < 0
        || observation.right > videoWidth
        || observation.bottom > videoHeight
    ) {
        return { valid: false, reason: 'outside_frame' };
    }

    const aspectRatio = observation.width / observation.height;
    if (
        aspectRatio < settings.minAspectRatio
        || aspectRatio > settings.maxAspectRatio
    ) {
        return { valid: false, reason: 'invalid_aspect_ratio' };
    }

    return { valid: true, reason: null, minFaceSize };
};
